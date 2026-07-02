"""Env-var config (D-038) — everything injected by heediq-infra at task launch, plus the
two values baked into the image at build time (WHISPER_MODEL, DIARIZE) since D-062 splits
tier by image rather than by a runtime env var.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    aws_region: str
    jobs_table: str
    sources_table: str
    audio_bucket: str
    transcription_queue_url: str
    summarization_queue_url: str
    sqs_message_body: str
    whisper_model: str
    diarize: bool


def load_config() -> Config:
    return Config(
        aws_region=os.environ["AWS_DEFAULT_REGION"],
        jobs_table=os.environ["JOBS_TABLE_NAME"],
        sources_table=os.environ["SOURCES_TABLE_NAME"],
        audio_bucket=os.environ["AUDIO_BUCKET_NAME"],
        transcription_queue_url=os.environ["TRANSCRIPTION_QUEUE_URL"],
        summarization_queue_url=os.environ["SUMMARIZATION_QUEUE_URL"],
        sqs_message_body=os.environ["SQS_MESSAGE_BODY"],
        whisper_model=os.environ["WHISPER_MODEL"],
        diarize=os.environ.get("DIARIZE", "false").lower() == "true",
    )
