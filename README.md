# Course Registration Bot

High-performance async course registration bot for tinchi.neu.edu.vn.

## Tech Stack

- FastAPI + Uvicorn (control plane)
- Python asyncio + httpx.AsyncClient (data plane)
- No browser automation (pure HTTP)

## Architecture

```
backend/
├── app/                    # FastAPI application
│   ├── main.py            # FastAPI app definition + endpoints
│   ├── schemas/           # Pydantic models
│   └── utils/             # Helper utilities
├── worker/                # Async registration worker
│   ├── engine.py          # High-performance request engine
│   ├── session.py         # Session & auth management
│   ├── retry.py           # Retry strategy & error classification
│   ├── scheduler.py       # Precision scheduler
│   └── main.py            # Worker pool orchestration
└── config.py              # Configuration
```

## Installation

```bash
python -m venv venv
venv\Scripts\activate 
pip install -r requirements.txt
```

## Running

```bash
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 --log-level info```

## API Endpoints

### Health Check

```http
GET /health
```

### Submit Registration Job

```http
POST /jobs

{
  "username": "student_id",
  "password": "password",
  "course_ids": ["CS101", "MATH201"],
  "target_timestamp": 1699999999.0
}
```

Response:

```json
{
  "job_id": "uuid-here",
  "status": "pending",
  "created_at": "2024-01-01T12:00:00"
}
```

### Get Job Status

```http
GET /jobs/{job_id}
```

Response:

```json
{
  "job_id": "uuid-here",
  "status": "completed",
  "result": {
    "CS101": true,
    "MATH201": false
  },
  "error": null,
  "created_at": "2024-01-01T12:00:00"
}
```

## Performance Features

- **Burst Registration**: 3-4 bursts of 100-150 concurrent requests
- **Sub-millisecond Timing**: Precision scheduler for exact target time
- **HTTP/2 Support**: Connection reuse via httpx with HTTP/2
- **Async Pool**: 4+ worker instances for horizontal scaling
- **Session Reuse**: Cookie + token caching to avoid re-login
- **Smart Retry**: Error classification for immediate/deferred retries
- **Anti-Block**: Proxy rotation + header randomization

## Configuration

Edit `config.py`:

```python
class WorkerConfig:
    NUM_WORKERS = 4                    # Worker pool size
    MAX_CONNECTIONS = 200              # httpx limit
    MAX_KEEPALIVE_CONNECTIONS = 100    # HTTP keep-alive
    REQUEST_TIMEOUT_SECONDS = 3.0      # Per request timeout
    NUM_BURSTS = 4                     # Burst count
    BURST_DELAY_MS = 150               # Burst delay
    REQUESTS_PER_BURST = 120           # Requests per burst
    SEMAPHORE_LIMIT = 120              # Concurrent semaphore
```

## Key Components

### RequestEngine

- 100-150 concurrent requests via asyncio.Semaphore
- Early success detection with cancellation
- 3-4 bursts with configurable delays
- Hot-path optimized (minimal logging)

### SessionManager

- Login before target time (pre-login)
- Session validation & auto re-login
- Cookie & token caching
- ASP.NET hidden field extraction

### PrecisionScheduler

- Hybrid sleep + busy-wait for <5ms precision
- Supports manual time offset (ms)
- millisecond-accurate burst scheduling

### RetryManager

- Error classification (login failure, slot full, rate limit, server error)
- Exponential backoff retry
- Configurable retry policy per error type

## Example Usage

```python
import asyncio
from datetime import datetime, timedelta
import httpx

async def main():
    # Calculate target time (5 seconds from now)
    target_time = (datetime.now() + timedelta(seconds=5)).timestamp()

    # Submit job
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8000/jobs",
            json={
                "username": "your_id",
                "password": "your_password",
                "course_ids": ["CS101", "MATH201"],
                "target_timestamp": target_time,
            }
        )
        job = response.json()
        print(f"Job ID: {job['job_id']}")

        # Poll for status
        await asyncio.sleep(6)
        status_response = await client.get(f"http://localhost:8000/jobs/{job['job_id']}")
        status = status_response.json()
        print(f"Result: {status['result']}")

asyncio.run(main())
```

## Deployment

### Docker

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY backend/ .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
```

### Environment Variables

See `.env.example` for configuration.

## Logging

Logs include job_id for tracing. Minimal overhead in hot path.

```
[2024-01-01 12:00:00] [worker] [INFO] Job abc-123: Registered CS101
```

## Performance Targets

- Sub-5ms burst timing precision
- 100+ concurrent requests per burst
- <50ms total request latency (network dependent)
- Graceful timeout handling
- Automatic session management
