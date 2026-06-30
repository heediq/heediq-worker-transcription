import json

import boto3
import pytest
from moto import mock_aws

from src.models import SummarizationJobMessage, TranscriptionJobMessage
from src.sqs_client import enqueue_summarization_job, requeue_transcription_job


@pytest.fixture
def sqs_client():
    with mock_aws():
        yield boto3.client("sqs", region_name="eu-west-1")


def _create_queue(sqs_client, name: str) -> str:
    return sqs_client.create_queue(QueueName=name)["QueueUrl"]


def test_enqueue_summarization_job_sends_camel_case_body(sqs_client):
    queue_url = _create_queue(sqs_client, "heediq-summarization")
    message = SummarizationJobMessage(
        job_id="job-1", recording_id="rec-1", org_id="org-1", source_type="text", content_ref="rec-1"
    )

    enqueue_summarization_job(sqs_client, queue_url, message)

    received = sqs_client.receive_message(QueueUrl=queue_url)["Messages"][0]
    body = json.loads(received["Body"])
    assert body == {
        "jobId": "job-1",
        "recordingId": "rec-1",
        "orgId": "org-1",
        "sourceType": "text",
        "contentRef": "rec-1",
    }


def test_requeue_transcription_job_sets_tier_message_attribute(sqs_client):
    # The EventBridge Pipe filter only matches on this attribute (see transcription-stack.ts) —
    # if a requeue ever drops it, the job would silently never be picked up again (D-066).
    queue_url = _create_queue(sqs_client, "heediq-transcription")
    message = TranscriptionJobMessage(
        job_id="job-1",
        recording_id="rec-1",
        org_id="org-1",
        audio_s3_key="key.wav",
        model="large-v3",
        tier="paid",
    )

    requeue_transcription_job(sqs_client, queue_url, message)

    received = sqs_client.receive_message(QueueUrl=queue_url, MessageAttributeNames=["tier"])["Messages"][0]
    assert received["MessageAttributes"]["tier"]["StringValue"] == "paid"
