from __future__ import annotations

import logging
import os
import tempfile
from typing import Optional

import httpx

from app.config import settings

log = logging.getLogger(__name__)

WHISPER_MODEL = "whisper-large-v3"


def download_twilio_media(media_url: str) -> Optional[str]:
    if not media_url:
        return None
    try:
        auth = None
        if settings.has_twilio:
            auth = (settings.twilio_account_sid, settings.twilio_auth_token)
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            r = client.get(media_url, auth=auth)
            r.raise_for_status()
            ext = ".ogg"
            ct = r.headers.get("content-type", "")
            if "mpeg" in ct or "mp3" in ct:
                ext = ".mp3"
            elif "wav" in ct:
                ext = ".wav"
            elif "ogg" in ct:
                ext = ".ogg"
            elif "amr" in ct:
                ext = ".amr"
            fd, path = tempfile.mkstemp(suffix=ext, prefix="careloop_in_")
            with os.fdopen(fd, "wb") as f:
                f.write(r.content)
            return path
    except Exception as e:
        log.error("download_twilio_media failed: %s", e)
        return None


def transcribe_audio(file_path: str, language: Optional[str] = None) -> Optional[str]:
    if not file_path or not os.path.exists(file_path):
        return None
    if not settings.groq_api_key:
        log.warning("GROQ_API_KEY missing — cannot transcribe")
        return None
    try:
        from groq import Groq

        client = Groq(api_key=settings.groq_api_key)
        with open(file_path, "rb") as f:
            kwargs = {
                "file": (os.path.basename(file_path), f.read()),
                "model": WHISPER_MODEL,
                "response_format": "json",
            }
            if language and language in {"hi", "en", "bn", "ta", "te", "mr"}:
                kwargs["language"] = language
            resp = client.audio.transcriptions.create(**kwargs)
        text = (getattr(resp, "text", None) or "").strip()
        return text or None
    except Exception as e:
        log.error("Groq Whisper transcribe failed: %s", e)
        return None


def transcribe_twilio_media(media_url: str, language: Optional[str] = None) -> Optional[str]:
    path = download_twilio_media(media_url)
    if not path:
        return None
    try:
        return transcribe_audio(path, language=language)
    finally:
        try:
            os.unlink(path)
        except Exception:
            pass
