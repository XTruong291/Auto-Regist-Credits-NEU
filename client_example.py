#!/usr/bin/env python3
"""
Example client for the NEU course registration bot API.
"""

import asyncio
from datetime import datetime, timedelta
import json
import sys

import httpx


class RegistrationClient:
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.client = None
        self.neu_token = None

    async def __aenter__(self):
        self.client = httpx.AsyncClient(timeout=10.0)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()

    async def health_check(self) -> bool:
        response = await self.client.get(f"{self.base_url}/health")
        response.raise_for_status()
        data = response.json()
        print(f"Health: {data['status']} (v{data['version']})")
        return True

    async def neu_login(self, neu_username: str, neu_password: str) -> str:
        response = await self.client.post(
            f"{self.base_url}/auth/neu/login",
            json={"neu_username": neu_username, "neu_password": neu_password},
        )
        response.raise_for_status()
        self.neu_token = response.json()["neu_token"]
        return self.neu_token

    def _auth_headers(self) -> dict:
        return {"Authorization": f"Bearer {self.neu_token}"}

    async def submit_job(
        self,
        course_ids: list[str],
        target_timestamp: float,
        regist_type: str = "NKH",
    ) -> str:
        response = await self.client.post(
            f"{self.base_url}/jobs",
            headers=self._auth_headers(),
            json={
                "regist_type": regist_type,
                "course_ids": course_ids,
                "target_timestamp": target_timestamp,
            },
        )
        response.raise_for_status()
        data = response.json()
        print(f"Job submitted: {data['job_id']}")
        return data["job_id"]

    async def get_job_status(self, job_id: str) -> dict:
        response = await self.client.get(f"{self.base_url}/jobs/{job_id}", headers=self._auth_headers())
        response.raise_for_status()
        return response.json()


async def main():
    neu_username = "YOUR_NEU_USERNAME"
    neu_password = "YOUR_NEU_PASSWORD"
    course_ids = ["ABC123"]
    target_time = (datetime.now() + timedelta(seconds=10)).timestamp()

    async with RegistrationClient() as client:
        await client.health_check()
        await client.neu_login(neu_username, neu_password)
        job_id = await client.submit_job(course_ids, target_time)
        status = await client.get_job_status(job_id)
        print(json.dumps(status, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(f"Error: {exc}")
        sys.exit(1)
