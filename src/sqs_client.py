"""SQS sends the worker makes: enqueue to summarization on completion (D-065), and re-enqueue
to the transcription queue itself on Spot interruption (D-066).
"""
from __future__ import annotations

from typing import Any

from .models import SummarizationJobMessage, TranscriptionJobMessage


def enqueue_summarization_job(sqs_client: Any, queue_url: str, message: SummarizationJobMessage) -> None:
    sqs_client.send_message(QueueUrl=queue_url, MessageBody=message.to_json())


def requeue_transcription_job(sqs_client: Any, queue_url: str, message: TranscriptionJobMessage) -> None:
    # No `tier` message attribute — `tier` travels in the body and the dispatcher Lambda routes on
    # it (D-157, replaces the tier-filtered EventBridge Pipes). Same shape as the original enqueue.
    sqs_client.send_message(QueueUrl=queue_url, MessageBody=message.to_json())
