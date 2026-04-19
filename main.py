#!/usr/bin/env python3
"""
Transcript API — transcribe any TikTok or Instagram video to text.

POST /transcribe   { "url": "https://tiktok.com/..." }
GET  /health       → { "status": "ok" }

Auth: pass X-API-Key header (set API_KEY env var, or use dev key "dev" locally)

Deploy on Hostinger VPS:
    pip3 install fastapi uvicorn yt-dlp faster-whisper
    API_KEY=yourkey uvicorn main:app --host 0.0.0.0 --port 8000
"""

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException, Security
from fastapi.security.api_key import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ── Config ────────────────────────────────────────────────────────────────────

API_KEY       = os.environ.get("API_KEY", "dev")   # override in prod
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "base.en")  # tiny.en for speed, medium.en for quality

SUPPORTED_PLATFORMS = ["tiktok.com", "instagram.com", "instagr.am", "vm.tiktok"]

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Transcript API",
    description="Transcribe any TikTok or Instagram video to text. Paste a URL, get a transcript.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


# ── Models ────────────────────────────────────────────────────────────────────

class TranscribeRequest(BaseModel):
    url: str

    class Config:
        json_schema_extra = {
            "example": {"url": "https://www.tiktok.com/@user/video/123456789"}
        }


class TranscribeResponse(BaseModel):
    url: str
    platform: str
    transcript: str
    word_count: int
    method: str   # "yt-dlp" or "playwright"


# ── Auth ──────────────────────────────────────────────────────────────────────

def require_api_key(key: str = Security(api_key_header)):
    if key != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid or missing API key. Pass X-API-Key header.")
    return key


# ── Platform detection ────────────────────────────────────────────────────────

def detect_platform(url: str) -> str:
    url_lower = url.lower()
    if "tiktok.com" in url_lower or "vm.tiktok" in url_lower:
        return "tiktok"
    if "instagram.com" in url_lower or "instagr.am" in url_lower:
        return "instagram"
    return "unknown"


# ── Download: yt-dlp (primary, no browser needed) ────────────────────────────

def download_with_ytdlp(url: str, dest: Path) -> bool:
    """Try yt-dlp first — works on most public TikTok/Instagram from VPS IPs."""
    if not shutil.which("yt-dlp"):
        return False
    try:
        result = subprocess.run(
            [
                "yt-dlp",
                "--quiet",
                "--no-warnings",
                "--format", "mp4/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best",
                "--output", str(dest),
                url,
            ],
            capture_output=True, text=True, timeout=120,
        )
        return dest.exists() and dest.stat().st_size > 100_000
    except Exception:
        return False


# ── Transcription ─────────────────────────────────────────────────────────────

def transcribe_video(video_path: Path) -> str:
    """
    Transcribe with faster-whisper (CPU, no GPU needed on VPS).
    Falls back to openai-whisper if faster-whisper not installed.
    """
    # Option 1: faster-whisper (recommended for server — fast CPU inference)
    try:
        from faster_whisper import WhisperModel
        model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
        segments, _ = model.transcribe(str(video_path), language="en")
        return " ".join(seg.text.strip() for seg in segments).strip()
    except ImportError:
        pass

    # Option 2: openai-whisper (fallback)
    try:
        import whisper
        model = whisper.load_model(WHISPER_MODEL)
        result = model.transcribe(str(video_path), language="en")
        return result["text"].strip()
    except ImportError:
        raise RuntimeError(
            "No Whisper variant installed. Run: pip3 install faster-whisper"
        )


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    """Health check — use this for RapidAPI uptime monitoring."""
    return {"status": "ok", "version": "1.0.0"}


@app.post("/transcribe", response_model=TranscribeResponse)
def transcribe(request: TranscribeRequest, _: str = Security(require_api_key)):
    """
    Transcribe a TikTok or Instagram video to plain text.

    - Supports: TikTok (tiktok.com, vm.tiktok), Instagram (Reels, Posts)
    - Returns: full transcript, word count, detected platform
    - Processing time: ~10-30s depending on video length
    """
    url = request.url.strip()
    platform = detect_platform(url)

    if platform == "unknown":
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported URL. Supported platforms: TikTok, Instagram. Got: {url}"
        )

    with tempfile.TemporaryDirectory() as tmp:
        video_path = Path(tmp) / "video.mp4"
        method = "yt-dlp"

        # Primary: yt-dlp (fast, no browser needed)
        downloaded = download_with_ytdlp(url, video_path)

        if not downloaded:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Could not download video. The video may be private, deleted, "
                    "or region-restricted. Make sure the URL is a public video."
                )
            )

        # Transcribe
        try:
            transcript = transcribe_video(video_path)
        except RuntimeError as e:
            raise HTTPException(status_code=500, detail=str(e))

        if not transcript:
            raise HTTPException(
                status_code=422,
                detail="Transcription produced no output. Video may have no speech."
            )

    return TranscribeResponse(
        url=url,
        platform=platform,
        transcript=transcript,
        word_count=len(transcript.split()),
        method=method,
    )
