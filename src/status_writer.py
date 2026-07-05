"""Writes job status stages to heediq-jobs DynamoDB. Status fan-out to the client happens via
DDB Streams -> Status Pusher Lambda -> WebSocket (D-061) — this module only owns the write.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .logger import create_logger
from .models import JobStatus

logger = create_logger("heediq-worker-transcription")


class StatusWriter:
    def __init__(self, dynamodb_client: Any, jobs_table: str):
        self._client = dynamodb_client
        self._jobs_table = jobs_table

    def write(self, job_id: str, status: JobStatus, source_id: str | None = None) -> None:
        # IDs and status only — never log transcript text or audio keys (D-038 PII rule); the
        # logger's own denylist also strips it if ever accidentally passed as metadata.
        logger.info("Job status changed", job_id=job_id, source_id=source_id, status=status)
        self._client.update_item(
            TableName=self._jobs_table,
            Key={"jobId": {"S": job_id}},
            UpdateExpression="SET #status = :status, updatedAt = :updatedAt",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":status": {"S": status},
                ":updatedAt": {"S": datetime.now(timezone.utc).isoformat()},
            },
        )
