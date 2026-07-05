import json

import boto3
import pytest
from moto import mock_aws

from src.status_writer import StatusWriter

JOBS_TABLE = "heediq-jobs"


@pytest.fixture
def dynamodb_client():
    with mock_aws():
        client = boto3.client("dynamodb", region_name="eu-west-1")
        client.create_table(
            TableName=JOBS_TABLE,
            KeySchema=[{"AttributeName": "jobId", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "jobId", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        client.put_item(TableName=JOBS_TABLE, Item={"jobId": {"S": "job-1"}, "status": {"S": "queued"}})
        yield client


def test_write_updates_status_and_updated_at(dynamodb_client):
    writer = StatusWriter(dynamodb_client, JOBS_TABLE)

    writer.write("job-1", "starting")

    item = dynamodb_client.get_item(TableName=JOBS_TABLE, Key={"jobId": {"S": "job-1"}})["Item"]
    assert item["status"]["S"] == "starting"
    assert "updatedAt" in item


def test_write_logs_structured_json_with_ids_and_status(dynamodb_client, capsys):
    writer = StatusWriter(dynamodb_client, JOBS_TABLE)

    writer.write("job-1", "transcribing", source_id="src-1")

    line = json.loads(capsys.readouterr().out.strip())
    assert line["job_id"] == "job-1"
    assert line["source_id"] == "src-1"
    assert line["status"] == "transcribing"
    assert line["service"] == "heediq-worker-transcription"
