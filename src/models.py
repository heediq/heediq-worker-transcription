"""Manual Python mirror of the SQS message shapes defined in @heediq/shared/src/messages.ts.

There is no shared package across the TS/Python boundary, so this is the single place that
must be kept in sync with heediq-shared whenever TranscriptionJobMessageSchema or
SummarizationJobMessageSchema changes.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

Tier = Literal["free", "paid"]
WhisperModelName = Literal["small", "large-v3"]
SourceType = Literal["audio", "text"]
JobStatus = Literal[
    "queued",
    "starting",
    "transcribing",
    "diarizing",
    "summarizing",
    "done",
    "failed",
    "retrying",
]


@dataclass(frozen=True)
class TranscriptionJobMessage:
    job_id: str
    recording_id: str
    org_id: str
    audio_s3_key: str
    model: WhisperModelName
    tier: Tier

    @staticmethod
    def from_json(raw: str) -> "TranscriptionJobMessage":
        data = json.loads(raw)
        return TranscriptionJobMessage(
            job_id=data["jobId"],
            recording_id=data["recordingId"],
            org_id=data["orgId"],
            audio_s3_key=data["audioS3Key"],
            model=data["model"],
            tier=data["tier"],
        )

    def to_json(self) -> str:
        return json.dumps(
            {
                "jobId": self.job_id,
                "recordingId": self.recording_id,
                "orgId": self.org_id,
                "audioS3Key": self.audio_s3_key,
                "model": self.model,
                "tier": self.tier,
            }
        )


@dataclass(frozen=True)
class SummarizationJobMessage:
    job_id: str
    recording_id: str
    org_id: str
    source_type: SourceType
    content_ref: str

    def to_json(self) -> str:
        return json.dumps(
            {
                "jobId": self.job_id,
                "recordingId": self.recording_id,
                "orgId": self.org_id,
                "sourceType": self.source_type,
                "contentRef": self.content_ref,
            }
        )
