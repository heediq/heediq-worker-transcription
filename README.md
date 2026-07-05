# heediq-worker-transcription

## Purpose

Python ECS worker that transcribes one audio Source per container invocation. EventBridge Pipes is the SQS consumer — it launches a `RunTask` for each message and injects the job payload as the `SQS_MESSAGE_BODY` container-override env var (`<$.body>` dynamic path). There is no SQS receive/poll loop inside this process: one `RunTask` = one job (D-066).

Two separate images are built from this repo — one per tier — each with its model weights baked in at build time (D-062). The infra resolves which image to pull per environment from an SSM parameter (`/heediq/transcription/{free,paid}-image-tag`) managed by CI's promotion step, not by CDK.

## Key Files

- `src/config.py` — `Config` frozen dataclass + `load_config()`; all config arrives as env vars at launch (D-038)
- `src/models.py` — `TranscriptionJobMessage` and `SummarizationJobMessage` frozen dataclasses mirroring `@heediq/shared`'s camelCase wire shapes (hand-maintained, no shared package across the language boundary)
- `src/worker.py` — entrypoint: SIGTERM handler, `run_job()` pipeline, `write_transcript()` to DynamoDB
- `src/transcriber.py` — `faster-whisper` `WhisperModel` wrapper (model baked into image, no runtime download)
- `src/diarizer.py` — `pyannote.audio` `Pipeline` wrapper (paid tier only; gated HuggingFace model, D-059/D-062)
- `src/status_writer.py` — DynamoDB `update_item` for job status stages (fan-out to client via DDB Streams → Status Pusher Lambda → WebSocket, D-061)
- `src/logger.py` — `create_logger(service)` structured JSON logger, hand-mirroring `@heediq/shared`'s `logger.ts` shape and PII denylist since this worker can't import the TS package (D-085); correlates by `source_id`
- `src/sqs_client.py` — SQS sends: enqueue to `heediq-summarization` on completion (D-065); re-enqueue to `heediq-transcription` on SIGTERM with `tier` attribute preserved (D-066)
- `Dockerfile.free` — base `nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04`; bakes `whisper small` weights; `WHISPER_MODEL=small DIARIZE=false`
- `Dockerfile.paid` — same base; bakes `whisper large-v3` + pyannote speaker-diarization-3.1 via BuildKit secret mount (`--mount=type=secret,id=hf_token`); `WHISPER_MODEL=large-v3 DIARIZE=true`
- `scripts/promote-transcription-worker.sh` — SSM put-parameter + register-task-definition + pipes update-pipe per tier; called by all three deploy jobs

## Data Flow

```
EventBridge Pipe (heediq-infra TranscriptionStack)
  └─ RunTask with SQS_MESSAGE_BODY container override
       │
       ▼
main() in worker.py
  1. parse TranscriptionJobMessage from SQS_MESSAGE_BODY
  2. install SIGTERM handler (Spot interruption re-enqueue, D-066)
  3. every stage logs a structured JSON line via logger.py, correlated by source_id (D-085)
  4. run_job():
       starting   → DynamoDB status write
       S3 download audio to /tmp (read-only grant on task role)
       transcribing → WhisperModel.transcribe()
       diarizing  → Diarizer.diarize()  [paid tier only; output not yet merged — MVP gap]
       write transcript to heediq-sources[sourceId].transcript
       summarizing → enqueue SummarizationJobMessage to heediq-summarization
  5. on SIGTERM before or during step 4:
       retrying   → DynamoDB status write
       re-enqueue TranscriptionJobMessage to heediq-transcription with tier attribute
       sys.exit(0)
```

## Contracts

### TranscriptionJobMessage (wire: camelCase JSON)
```
jobId        string   — job UUID (primary key in heediq-jobs)
sourceId     string   — Source UUID (primary key in heediq-sources)
orgId        string   — org UUID
audioS3Key   string   — S3 object key in heediq-audio-uploads-{accountId}
model        string   — 'small' | 'large-v3'
tier         string   — 'free' | 'paid'
```

### SummarizationJobMessage enqueued on completion (wire: camelCase JSON)
```
jobId        string   — same job UUID
sourceId     string   — same Source UUID
orgId        string   — same org UUID
sourceType   'text'   — transcript is written to DynamoDB, not S3 (no S3 write grant on task role)
contentRef   string   — sourceId; heediq-worker-summarization reads transcript back from
                        heediq-sources[sourceId].transcript
tier         string   — 'free' | 'paid' forwarded from TranscriptionJobMessage; summarization
                        worker uses it to select the Claude model (D-067)
```

### Environment variables (injected by TranscriptionStack at RunTask time, D-038)
| Variable | Source |
|---|---|
| `AWS_DEFAULT_REGION` | hardcoded `eu-west-1` in stack |
| `JOBS_TABLE_NAME` | `heediq-jobs` |
| `SOURCES_TABLE_NAME` | `heediq-sources` |
| `AUDIO_BUCKET_NAME` | `heediq-audio-uploads-{accountId}` (bucket name is account-ID-suffixed for S3 global-uniqueness, not env-suffixed — account IS the environment per D-037) |
| `TRANSCRIPTION_QUEUE_URL` | SQS queue URL (for SIGTERM re-enqueue, D-066) |
| `SUMMARIZATION_QUEUE_URL` | SQS queue URL (enqueue after completion, D-065) |
| `SQS_MESSAGE_BODY` | raw SQS message body, set by Pipe's `<$.body>` container override |
| `WHISPER_MODEL` | baked into image: `small` (free) or `large-v3` (paid) |
| `DIARIZE` | baked into image: `false` (free) or `true` (paid) |

### IAM task role grants (from TranscriptionStack)
- S3 **read** on `heediq-audio-uploads-{accountId}` — no write grant (transcript goes to DynamoDB, not S3)
- DynamoDB **write-only** on `heediq-jobs` and `heediq-sources` (the worker only ever `update_item`s status/transcript; it never reads either table)
- SQS `sqs:SendMessage` on `heediq-summarization` (completion enqueue, D-065)
- SQS `sqs:SendMessage` on `heediq-transcription` (SIGTERM re-enqueue, D-066)

## Dependencies

- **Upstream:** heediq-infra `TranscriptionStack` (EventBridge Pipes, ECS task defs, IAM grants) + heediq-api Source job enqueue (must set `tier` SQS message attribute or the Pipe filter silently drops the job)
- **Downstream:** `heediq-worker-summarization` reads `transcript` from `heediq-sources` by `sourceId` — `sourceType: 'text', contentRef: sourceId` in the enqueued message is the contract

## Testing

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q          # 11 tests, ~3s
mypy src           # strict, ignore_missing_imports for boto3/faster_whisper/pyannote
```

AWS services (DynamoDB, SQS, S3) are mocked with `moto`. Transcriber and Diarizer are patched in worker tests — no GPU/model weights needed locally. The SIGTERM test fires a real OS signal and asserts on re-enqueue behavior.

CI runs both on every PR (`ci.yml`) and as the first job of every deploy (`deploy.yml`) on Python 3.11.

## Gotchas & Constraints

- **pyannote/speaker-diarization-3.1 is a gated HuggingFace model.** Building `Dockerfile.paid` requires an `HF_TOKEN` GitHub secret (added via Settings → Secrets). The token is never persisted in an image layer — it's injected via `--mount=type=secret,id=hf_token` (BuildKit) and read only during the `Pipeline.from_pretrained()` call baked into the image at build time.
- **SSM parameters must be seeded before the first infra deploy.** TranscriptionStack resolves image tags from `/heediq/transcription/{free,paid}-image-tag` via a CloudFormation dynamic reference. These parameters must exist in each workload account before the first `cdk deploy TranscriptionStack`. `heediq-infra/scripts/setup.sh` section 3 seeds them automatically (idempotent — skips if already set). If seeding manually: `aws ssm put-parameter --name /heediq/transcription/free-image-tag --value free --type String`. After CI's first promote run, CI owns the value and `setup.sh` will no longer overwrite it.
- **`logger.py` bypasses stdlib `logging` entirely (D-085)** — it `print()`s JSON directly to stdout (info) / stderr (warn, error), matching the ECS `awslogs` driver's line-based capture. Tests must use pytest's `capsys` fixture to assert on log output, not `caplog` (which only captures stdlib `logging` records).
- **Local Python version mismatch.** Dev machines may only have Python 3.9 (macOS system default). `pyproject.toml` declares `requires-python = ">=3.11"` matching the Dockerfiles and CI; use `actions/setup-python@v5` with `python-version: '3.11'` in CI. Local 3.9 works for running tests but is not the target runtime.
