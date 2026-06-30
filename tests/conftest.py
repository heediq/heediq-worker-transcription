import pytest


@pytest.fixture
def worker_env(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-1")
    monkeypatch.setenv("JOBS_TABLE_NAME", "heediq-jobs")
    monkeypatch.setenv("RECORDINGS_TABLE_NAME", "heediq-recordings")
    monkeypatch.setenv("AUDIO_BUCKET_NAME", "heediq-audio")
    monkeypatch.setenv("TRANSCRIPTION_QUEUE_URL", "https://sqs.eu-west-1.amazonaws.com/123/heediq-transcription")
    monkeypatch.setenv("SUMMARIZATION_QUEUE_URL", "https://sqs.eu-west-1.amazonaws.com/123/heediq-summarization")
    monkeypatch.setenv("WHISPER_MODEL", "small")
    monkeypatch.setenv("DIARIZE", "false")
    monkeypatch.setenv(
        "SQS_MESSAGE_BODY",
        '{"jobId":"job-1","recordingId":"rec-1","orgId":"org-1",'
        '"audioS3Key":"key.wav","model":"small","tier":"free"}',
    )
