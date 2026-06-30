"""Entrypoint. One ECS RunTask = one job (D-066): EventBridge Pipes is the SQS consumer, not
this process — the job payload arrives via the SQS_MESSAGE_BODY container-override env var, set
by the Pipe's `<$.body>` dynamic path reference. There is no SQS receive/poll loop here.
"""
from __future__ import annotations

import logging
import signal
import sys
import tempfile
from pathlib import Path
from types import FrameType
from typing import Any

import boto3

from .config import Config, load_config
from .diarizer import Diarizer
from .models import SummarizationJobMessage, TranscriptionJobMessage
from .sqs_client import enqueue_summarization_job, requeue_transcription_job
from .status_writer import StatusWriter
from .transcriber import Transcriber

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Clients:
    def __init__(self, region: str):
        self.dynamodb = boto3.client("dynamodb", region_name=region)
        self.sqs = boto3.client("sqs", region_name=region)
        self.s3 = boto3.client("s3", region_name=region)


def install_sigterm_handler(
    job: TranscriptionJobMessage,
    config: Config,
    status_writer: StatusWriter,
    sqs_client: Any,
) -> None:
    def handle_sigterm(signum: int, frame: FrameType | None) -> None:
        # Spot interruption (D-066, supersedes D-059's original mechanism): EventBridge Pipes
        # deletes the SQS message as soon as it hands the job to RunTask, before this process
        # even starts — there is no visibility timeout left to expire by the time SIGTERM
        # arrives, so retry must be an explicit re-enqueue.
        logger.warning("SIGTERM received for job %s — re-enqueueing for retry", job.job_id)
        status_writer.write(job.job_id, "retrying")
        requeue_transcription_job(sqs_client, config.transcription_queue_url, job)
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_sigterm)


def run_job(job: TranscriptionJobMessage, config: Config, clients: Clients, status_writer: StatusWriter) -> None:
    status_writer.write(job.job_id, "starting")

    with tempfile.TemporaryDirectory() as tmp_dir:
        audio_path = Path(tmp_dir) / "audio"
        clients.s3.download_file(config.audio_bucket, job.audio_s3_key, str(audio_path))

        status_writer.write(job.job_id, "transcribing")
        transcript = Transcriber(config.whisper_model).transcribe(audio_path)

        if config.diarize:
            status_writer.write(job.job_id, "diarizing")
            Diarizer().diarize(audio_path)
            # MVP: diarization output is not yet merged into the transcript text — tracked as
            # a known gap, not silently dropped (see README Gotchas).

        # No S3 write grant on the task role (only grantRead) — the transcript is written onto
        # the recording row itself. The summarization worker reads it back by recordingId.
        write_transcript(clients.dynamodb, config.recordings_table, job.recording_id, transcript)

        status_writer.write(job.job_id, "summarizing")
        enqueue_summarization_job(
            clients.sqs,
            config.summarization_queue_url,
            SummarizationJobMessage(
                job_id=job.job_id,
                recording_id=job.recording_id,
                org_id=job.org_id,
                source_type="text",
                content_ref=job.recording_id,
            ),
        )


def write_transcript(dynamodb_client: Any, recordings_table: str, recording_id: str, transcript: str) -> None:
    dynamodb_client.update_item(
        TableName=recordings_table,
        Key={"recordingId": {"S": recording_id}},
        UpdateExpression="SET transcript = :t",
        ExpressionAttributeValues={":t": {"S": transcript}},
    )


def main() -> None:
    config = load_config()
    job = TranscriptionJobMessage.from_json(config.sqs_message_body)
    clients = Clients(config.aws_region)
    status_writer = StatusWriter(clients.dynamodb, config.jobs_table)

    install_sigterm_handler(job, config, status_writer, clients.sqs)

    try:
        run_job(job, config, clients, status_writer)
    except Exception:
        logger.exception("job %s failed", job.job_id)
        status_writer.write(job.job_id, "failed")
        raise


if __name__ == "__main__":
    main()
