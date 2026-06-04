# Course Registration Bot

Async NEU course registration backend with FastAPI, PostgreSQL, Redis and Celery.

## Architecture

```text
FastAPI API
  -> PostgreSQL: NEU accounts, NEU token hash, jobs, job events
  -> Redis: Celery broker/result backend
  -> Celery worker: login NEU, wait for target time, scan slots, register courses
```

There is no separate app account and no internal app session. Users authenticate by NEU credentials first. The API verifies the credentials with NEU, stores the NEU account in PostgreSQL, returns the NEU token, then uses that NEU token for job actions.

## Run With Docker Compose

```bash
docker compose up --build
```

Services:

- `api`: FastAPI on `http://localhost:8000`
- `worker`: Celery worker
- `postgres`: PostgreSQL 16 with persistent `postgres_data`
- `redis`: Redis 7 with persistent `redis_data`

## API Flow

### Health

```http
GET /health
```

### Login With NEU Account

```http
POST /auth/neu/login
Content-Type: application/json

{
  "neu_username": "student_id",
  "neu_password": "password"
}
```

Response:

```json
{
  "neu_token": "token-from-neu",
  "token_type": "Bearer",
  "neu_username": "student_id"
}
```

### Submit Job

```http
POST /jobs
Authorization: Bearer <neu_token>
Content-Type: application/json

{
  "regist_type": "NKH",
  "course_ids": ["ABC123"],
  "target_timestamp": 1893456000.0
}
```

### Get Jobs

```http
GET /jobs
Authorization: Bearer <neu_token>
```

### Get Job Status

```http
GET /jobs/{job_id}
Authorization: Bearer <neu_token>
```

### Get Job Events

```http
GET /jobs/{job_id}/events
Authorization: Bearer <neu_token>
```

This returns worker events such as login, slot scan, slot found, register attempt, result, cancel and timeout.

### Cancel Job

```http
DELETE /jobs/{job_id}
Authorization: Bearer <neu_token>
```

## Data Model

- `neu_accounts`: NEU username/password, latest NEU token hash, login timestamps
- `registration_jobs`: course targets, status, result, cancel flag
- `job_events`: worker event log

NEU passwords are stored as plaintext by project choice. They are not returned by API responses and must not be written to logs.

## Configuration

Docker Compose sets the main environment variables:

- `DATABASE_URL`
- `CELERY_BROKER_URL`
- `CELERY_RESULT_BACKEND`
- `SCAN_INTERVAL_MIN_SECONDS` default `1.0`
- `SCAN_INTERVAL_MAX_SECONDS` default `2.5`
- `JOB_TIMEOUT_SECONDS`

## Tests

```bash
pytest tests.py
```
