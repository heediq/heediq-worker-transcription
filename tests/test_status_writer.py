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


def test_write_does_not_log_pii(dynamodb_client, caplog):
    writer = StatusWriter(dynamodb_client, JOBS_TABLE)

    with caplog.at_level("INFO"):
        writer.write("job-1", "transcribing")

    assert "job-1" in caplog.text
    assert "transcribing" in caplog.text
