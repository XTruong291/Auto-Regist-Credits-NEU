#!/usr/bin/env python3
"""
Unit tests for the registration engine.
"""

import asyncio
import httpx
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from worker.engine import RequestEngine
from worker.scheduler import PrecisionScheduler
from worker.retry import RetryManager, ErrorClassifier, RetryConfig


@pytest.mark.asyncio
async def test_request_engine_basic():
    """Test basic request engine functionality."""
    client = MagicMock(spec=httpx.AsyncClient)
    engine = RequestEngine(client, max_concurrent=10, num_bursts=2, burst_delay_ms=100)

    # Mock successful response
    mock_response = MagicMock()
    mock_response.status_code = 200
    client.post = AsyncMock(return_value=mock_response)

    result = await engine.register_course(
        "CS101",
        {"course_id": "CS101"},
        "http://example.com/register",
    )

    assert result is True


@pytest.mark.asyncio
async def test_request_engine_failure():
    """Test request engine with failure."""
    client = MagicMock(spec=httpx.AsyncClient)
    engine = RequestEngine(client, max_concurrent=10, num_bursts=2, burst_delay_ms=100)

    # Mock failed response
    mock_response = MagicMock()
    mock_response.status_code = 409
    client.post = AsyncMock(return_value=mock_response)

    result = await engine.register_course(
        "CS101",
        {"course_id": "CS101"},
        "http://example.com/register",
    )

    assert result is False


@pytest.mark.asyncio
async def test_precision_scheduler():
    """Test precision scheduler accuracy."""
    import time

    target_time = time.time() + 0.5
    start = time.time()
    await PrecisionScheduler.wait_until(target_time)
    elapsed = time.time() - start

    # Should be very close to 0.5 seconds (±50ms tolerance)
    assert 0.45 < elapsed < 0.55


@pytest.mark.asyncio
async def test_retry_manager_classification():
    """Test error classification."""
    assert RetryManager.classify_error(200) == ErrorClassifier.SUCCESS
    assert RetryManager.classify_error(401) == ErrorClassifier.LOGIN_FAILED
    assert RetryManager.classify_error(409) == ErrorClassifier.SLOT_FULL
    assert RetryManager.classify_error(429) == ErrorClassifier.RATE_LIMIT
    assert RetryManager.classify_error(500) == ErrorClassifier.SERVER_ERROR


@pytest.mark.asyncio
async def test_retry_manager_should_retry():
    """Test retry decision logic."""
    assert RetryManager.should_retry(ErrorClassifier.SERVER_ERROR) is True
    assert RetryManager.should_retry(ErrorClassifier.NETWORK_ERROR) is True
    assert RetryManager.should_retry(ErrorClassifier.LOGIN_FAILED) is False
    assert RetryManager.should_retry(ErrorClassifier.SLOT_FULL) is False


@pytest.mark.asyncio
async def test_retry_manager_exponential_backoff():
    """Test exponential backoff retry."""
    call_count = 0

    async def failing_coro():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise Exception("Transient error")
        return "success"

    config = RetryConfig(max_retries=3, base_delay_ms=10, max_delay_ms=100)
    result = await RetryManager.execute_with_retry(failing_coro, config)

    assert result == "success"
    assert call_count == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
