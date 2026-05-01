from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path
from typing import Optional

from gtts import gTTS

log = logging.getLogger(__name__)

AUDIO_DIR = Path(os.environ.get("CARELOOP_AUDIO_DIR", "/tmp/careloop_audio"))
AUDIO_DIR.mkdir(parents=True, exist_ok=True)


def _lang_code(language: str) -> str:
    if not language:
        return "en"
    if language.startswith("hi"):
        return "hi"
    if language.startswith("bn"):
        return "bn"
    if language.startswith("ta"):
        return "ta"
    if language.startswith("te"):
        return "te"
    if language.startswith("mr"):
        return "mr"
    return "en"


def synthesize_sync(text: str, language: str = "hi") -> Optional[Path]:
    if not text or not text.strip():
        return None
    try:
        out_path = AUDIO_DIR / f"{uuid.uuid4().hex}.mp3"
        tts = gTTS(text=text, lang=_lang_code(language), slow=False)
        tts.save(str(out_path))
        return out_path
    except Exception as e:
        log.error("gTTS synthesis failed: %s", e)
        return None


def public_audio_url(path: Path, base_url: Optional[str] = None) -> str:
    base = (base_url or "").strip()
    if not base:
        base = os.environ.get("CARELOOP_PUBLIC_BASE", "").strip()
    if not base:
        repl = os.environ.get("REPLIT_DEV_DOMAIN", "").strip()
        if repl:
            base = f"https://{repl}"
    if not base:
        return ""
    return f"{base.rstrip('/')}/audio/{path.name}"
