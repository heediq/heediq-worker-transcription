import json

from src.models import SummarizationJobMessage, TranscriptionJobMessage


def test_transcription_job_message_round_trips_through_json():
    msg = TranscriptionJobMessage(
        job_id="job-1",
        recording_id="rec-1",
        org_id="org-1",
        audio_s3_key="orgs/org-1/rec-1/audio.wav",
        model="small",
        tier="free",
    )

    parsed = TranscriptionJobMessage.from_json(msg.to_json())

    assert parsed == msg


def test_transcription_job_message_parses_camel_case_keys_from_heediq_api():
    raw = (
        '{"jobId":"job-1","recordingId":"rec-1","orgId":"org-1",'
        '"audioS3Key":"key.wav","model":"large-v3","tier":"paid"}'
    )

    parsed = TranscriptionJobMessage.from_json(raw)

    assert parsed.job_id == "job-1"
    assert parsed.audio_s3_key == "key.wav"
    assert parsed.model == "large-v3"
    assert parsed.tier == "paid"


def test_summarization_job_message_serializes_to_camel_case_keys():
    msg = SummarizationJobMessage(
        job_id="job-1",
        recording_id="rec-1",
        org_id="org-1",
        source_type="text",
        content_ref="rec-1",
        tier="free",
    )

    body = json.loads(msg.to_json())

    assert body["jobId"] == "job-1"
    assert body["sourceType"] == "text"
    assert body["contentRef"] == "rec-1"
    assert body["tier"] == "free"
