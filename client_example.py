#!/usr/bin/env python3
"""
Example client for course registration bot API.
"""

import asyncio
import httpx
import json
from datetime import datetime, timedelta
import sys


class RegistrationClient:
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.client = None

    async def __aenter__(self):
        self.client = httpx.AsyncClient(timeout=10.0)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()

    async def health_check(self) -> bool:
        """Check API health."""
        try:
            response = await self.client.get(f"{self.base_url}/health")
            response.raise_for_status()
            data = response.json()
            print(f"Health: {data['status']} (v{data['version']})")
            return True
        except Exception as e:
            print(f"Health check failed: {e}")
            return False

    async def submit_job(
        self,
        username: str,
        password: str,
        course_ids: list[str],
        target_timestamp: float,
    ) -> str:
        """Submit registration job."""
        payload = {
            "username": username,
            "password": password,
            "course_ids": course_ids,
            "target_timestamp": target_timestamp,
        }

        response = await self.client.post(
            f"{self.base_url}/jobs",
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
        print(f"Job submitted: {data['job_id']}")
        return data["job_id"]

    async def get_job_status(self, job_id: str) -> dict:
        """Get job status."""
        response = await self.client.get(f"{self.base_url}/jobs/{job_id}")
        response.raise_for_status()
        return response.json()

    async def poll_job(self, job_id: str, max_wait_seconds: int = 60) -> dict:
        """Poll job until completion or timeout."""
        start_time = asyncio.get_event_loop().time()
        poll_interval = 0.5

        while True:
            try:
                status = await self.get_job_status(job_id)
                print(f"Status: {status['status']}")

                if status["status"] in ("completed", "failed"):
                    return status

                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed > max_wait_seconds:
                    print(f"Timeout after {max_wait_seconds}s")
                    return status

                await asyncio.sleep(poll_interval)

            except Exception as e:
                print(f"Error polling job: {e}")
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed > max_wait_seconds:
                    raise
                await asyncio.sleep(poll_interval)


async def main():
    """Example usage."""
    # Configuration
    username = "YOUR_USERNAME"
    password = "YOUR_PASSWORD"
    course_ids = ["CS101", "MATH201", "ENG101"]

    # Calculate target time (10 seconds from now)
    target_time = (datetime.now() + timedelta(seconds=10)).timestamp()

    print(f"Target timestamp: {target_time}")
    print(f"Target time: {datetime.fromtimestamp(target_time)}")
    print()

    async with RegistrationClient("http://localhost:8000") as client:
        # Check health
        if not await client.health_check():
            print("API is not reachable")
            sys.exit(1)

        print()

        # Submit job
        try:
            job_id = await client.submit_job(
                username=username,
                password=password,
                course_ids=course_ids,
                target_timestamp=target_time,
            )
            print(f"Created at: {datetime.now().isoformat()}")
            print()

            # Poll for status
            result = await client.poll_job(job_id, max_wait_seconds=60)

            print("\nFinal Status:")
            print(json.dumps(result, indent=2))

            # Summary
            if result.get("result"):
                registered = sum(1 for v in result["result"].values() if v)
                total = len(result["result"])
                print(f"\nRegistered: {registered}/{total} courses")

        except Exception as e:
            print(f"Error: {e}")
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
