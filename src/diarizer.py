"""pyannote diarization wrapper — paid tier only (D-059, D-062). Runs on the g4dn.xlarge CPU
cores while faster-whisper uses the GPU, so the two can overlap within the same task.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

DEFAULT_MODEL = "pyannote/speaker-diarization-3.1"


class Diarizer:
    def __init__(self, model_name: str = DEFAULT_MODEL):
        # Lazy import — pyannote.audio requires torch/torchaudio pinned to compatible
        # versions baked into the Docker image. Importing at module level breaks CI where
        # torch is installed unpinned and torchaudio.AudioMetaData may not exist.
        from pyannote.audio import Pipeline
        self._pipeline = Pipeline.from_pretrained(model_name)

    def diarize(self, audio_path: Path) -> Any:
        return self._pipeline(str(audio_path))
