"""Writes job status stages to heediq-jobs DynamoDB. Status fan-out to the client happens via
DDB Streams -> Status Pusher Lambda -> WebSocket (D-061) — this module only owns the write.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from .models import JobStatus

logger = logging.getLogger(__name__)


class StatusWriter:
    def __init__(self, dynamodb_client: Any, jobs_table: str):
        self._client = dynamodb_client
        self._jobs_table = jobs_table

    def write(self, job_id: str, status: JobStatus) -> None:
        # IDs and status only — never log transcript text or audio keys (D-038 PII rule).
        logger.info("job %s -> %s", job_id, status)
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
