"""faster-whisper wrapper. Model weights are baked into the image at build time (D-062) — no
runtime download, so cold start is just process+model load, not a network fetch.
"""
from __future__ import annotations

from pathlib import Path

from faster_whisper import WhisperModel


class Transcriber:
    def __init__(self, model_name: str):
        self._model = WhisperModel(model_name, device="cuda", compute_type="float16")

    def transcribe(self, audio_path: Path) -> str:
        segments, _ = self._model.transcribe(str(audio_path))
        return " ".join(segment.text.strip() for segment in segments)
