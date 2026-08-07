import json
import os
import signal
from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

from src.config import load_config
from src.models import TranscriptionJobMessage
from src.status_writer import StatusWriter
from src.worker import Clients, install_sigterm_handler, run_job

JOBS_TABLE = "heediq-jobs"
SOURCES_TABLE = "heediq-sources"
AUDIO_BUCKET = "heediq-audio"


@pytest.fixture
def aws_clients(worker_env):
    with mock_aws():
        dynamodb = boto3.client("dynamodb", region_name="eu-west-1")
        # Matches the real deployed schemas (heediq-infra foundation-stack.ts): jobs is keyed
        # by sourceId alone (no jobId sort key); sources is a composite orgId+sourceId key.
        dynamodb.create_table(
            TableName=JOBS_TABLE,
            KeySchema=[{"AttributeName": "sourceId", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "sourceId", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        dynamodb.put_item(
            TableName=JOBS_TABLE,
            Item={"sourceId": {"S": "rec-1"}, "jobId": {"S": "job-1"}, "status": {"S": "queued"}},
        )
        dynamodb.create_table(
            TableName=SOURCES_TABLE,
            KeySchema=[
                {"AttributeName": "orgId", "KeyType": "HASH"},
                {"AttributeName": "sourceId", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "orgId", "AttributeType": "S"},
                {"AttributeName": "sourceId", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        dynamodb.put_item(TableName=SOURCES_TABLE, Item={"orgId": {"S": "org-1"}, "sourceId": {"S": "rec-1"}})

        s3 = boto3.client("s3", region_name="eu-west-1")
        s3.create_bucket(Bucket=AUDIO_BUCKET, CreateBucketConfiguration={"LocationConstraint": "eu-west-1"})
        s3.put_object(Bucket=AUDIO_BUCKET, Key="key.wav", Body=b"fake-audio")

        sqs = boto3.client("sqs", region_name="eu-west-1")
        sqs.create_queue(QueueName="heediq-transcription")
        sqs.create_queue(QueueName="heediq-summarization")

        clients = Clients.__new__(Clients)
        clients.dynamodb = dynamodb
        clients.s3 = s3
        clients.sqs = sqs
        yield clients


def _summarization_queue_url(sqs_client) -> str:
    return sqs_client.get_queue_url(QueueName="heediq-summarization")["QueueUrl"]


@patch("src.worker.Transcriber")
def test_run_job_writes_status_progression_and_enqueues_summarization(mock_transcriber_cls, aws_clients):
    mock_transcriber_cls.return_value.transcribe.return_value = "hello world"
    config = load_config()
    job = TranscriptionJobMessage.from_json(config.sqs_message_body)
    status_writer = StatusWriter(aws_clients.dynamodb, config.jobs_table)

    run_job(job, config, aws_clients, status_writer)

    item = aws_clients.dynamodb.get_item(TableName=JOBS_TABLE, Key={"sourceId": {"S": "rec-1"}})["Item"]
    assert item["status"]["S"] == "summarizing"

    source = aws_clients.dynamodb.get_item(
        TableName=SOURCES_TABLE, Key={"orgId": {"S": "org-1"}, "sourceId": {"S": "rec-1"}}
    )["Item"]
    assert source["transcript"]["S"] == "hello world"

    queue_url = _summarization_queue_url(aws_clients.sqs)
    received = aws_clients.sqs.receive_message(QueueUrl=queue_url)["Messages"][0]
    body = json.loads(received["Body"])
    assert body["sourceType"] == "text"
    assert body["contentRef"] == "rec-1"


@patch("src.worker.Diarizer")
@patch("src.worker.Transcriber")
def test_run_job_runs_diarization_when_diarize_is_enabled(mock_transcriber_cls, mock_diarizer_cls, aws_clients, monkeypatch):
    monkeypatch.setenv("DIARIZE", "true")
    mock_transcriber_cls.return_value.transcribe.return_value = "hello world"
    config = load_config()
    job = TranscriptionJobMessage.from_json(config.sqs_message_body)
    status_writer = StatusWriter(aws_clients.dynamodb, config.jobs_table)

    run_job(job, config, aws_clients, status_writer)

    mock_diarizer_cls.return_value.diarize.assert_called_once()


@patch("src.worker.Transcriber")
def test_run_job_skips_diarization_when_diarize_is_disabled(mock_transcriber_cls, aws_clients):
    mock_transcriber_cls.return_value.transcribe.return_value = "hello world"
    config = load_config()
    job = TranscriptionJobMessage.from_json(config.sqs_message_body)
    status_writer = StatusWriter(aws_clients.dynamodb, config.jobs_table)

    with patch("src.worker.Diarizer") as mock_diarizer_cls:
        run_job(job, config, aws_clients, status_writer)
        mock_diarizer_cls.assert_not_called()


def test_sigterm_handler_writes_retrying_status_and_requeues_job(aws_clients):
    config = load_config()
    job = TranscriptionJobMessage.from_json(config.sqs_message_body)
    status_writer = StatusWriter(aws_clients.dynamodb, config.jobs_table)
    original_handler = signal.getsignal(signal.SIGTERM)

    install_sigterm_handler(job, config, status_writer, aws_clients.sqs)
    try:
        with pytest.raises(SystemExit):
            os.kill(os.getpid(), signal.SIGTERM)
    finally:
        signal.signal(signal.SIGTERM, original_handler)

    item = aws_clients.dynamodb.get_item(TableName=JOBS_TABLE, Key={"sourceId": {"S": "rec-1"}})["Item"]
    assert item["status"]["S"] == "retrying"

    queue_url = aws_clients.sqs.get_queue_url(QueueName="heediq-transcription")["QueueUrl"]
    received = aws_clients.sqs.receive_message(QueueUrl=queue_url, MessageAttributeNames=["All"])["Messages"][0]
    # D-157: tier is carried in the body for the dispatcher to route on — no SQS attribute.
    assert "MessageAttributes" not in received
    assert json.loads(received["Body"])["tier"] == "free"
