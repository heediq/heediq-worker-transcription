"""Entrypoint. One ECS RunTask = one job (D-066): the dispatcher Lambda is the SQS consumer, not
this process (D-157) — the job payload arrives via the SQS_MESSAGE_BODY container-override env var
the dispatcher sets from the raw message body. There is no SQS receive/poll loop here.
"""
from __future__ import annotations

import signal
import sys
import tempfile
import traceback
from pathlib import Path
from types import FrameType
from typing import Any

import boto3

from .config import Config, load_config
from .diarizer import Diarizer
from .logger import create_logger
from .models import SummarizationJobMessage, TranscriptionJobMessage
from .sqs_client import enqueue_summarization_job, requeue_transcription_job
from .status_writer import StatusWriter
from .transcriber import Transcriber

logger = create_logger("heediq-worker-transcription")


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
        # Spot interruption (D-066, supersedes D-059's original mechanism): the dispatcher Lambda
        # deletes the SQS message as soon as it hands the job to RunTask, before this process
        # even starts — there is no visibility timeout left to expire by the time SIGTERM
        # arrives, so retry must be an explicit re-enqueue.
        logger.warn("SIGTERM received — re-enqueueing for retry", job_id=job.job_id, source_id=job.source_id)
        status_writer.write(job.job_id, "retrying", job.source_id)
        requeue_transcription_job(sqs_client, config.transcription_queue_url, job)
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_sigterm)


def run_job(job: TranscriptionJobMessage, config: Config, clients: Clients, status_writer: StatusWriter) -> None:
    logger.info("Transcription job started", job_id=job.job_id, source_id=job.source_id, tier=job.tier)
    status_writer.write(job.job_id, "starting", job.source_id)

    with tempfile.TemporaryDirectory() as tmp_dir:
        audio_path = Path(tmp_dir) / "audio"
        clients.s3.download_file(config.audio_bucket, job.audio_s3_key, str(audio_path))

        status_writer.write(job.job_id, "transcribing", job.source_id)
        transcript = Transcriber(config.whisper_model).transcribe(audio_path)

        if config.diarize:
            status_writer.write(job.job_id, "diarizing", job.source_id)
            Diarizer().diarize(audio_path)
            # MVP: diarization output is not yet merged into the transcript text — tracked as
            # a known gap, not silently dropped (see README Gotchas).

        # No S3 write grant on the task role (only grantRead) — the transcript is written onto
        # the source row itself. The summarization worker reads it back by sourceId.
        write_transcript(clients.dynamodb, config.sources_table, job.org_id, job.source_id, transcript)

        status_writer.write(job.job_id, "summarizing", job.source_id)
        enqueue_summarization_job(
            clients.sqs,
            config.summarization_queue_url,
            SummarizationJobMessage(
                job_id=job.job_id,
                source_id=job.source_id,
                org_id=job.org_id,
                source_type="text",
                content_ref=job.source_id,
                tier=job.tier,
            ),
        )


def write_transcript(
    dynamodb_client: Any, sources_table: str, org_id: str, source_id: str, transcript: str
) -> None:
    # heediq-sources' key is composite: pk=orgId, sk=sourceId.
    dynamodb_client.update_item(
        TableName=sources_table,
        Key={"orgId": {"S": org_id}, "sourceId": {"S": source_id}},
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
    except Exception as exc:
        logger.error(
            "Transcription job failed",
            job_id=job.job_id,
            source_id=job.source_id,
            error=str(exc),
            stack=traceback.format_exc(),
        )
        status_writer.write(job.job_id, "failed", job.source_id)
        raise


if __name__ == "__main__":
    main()
