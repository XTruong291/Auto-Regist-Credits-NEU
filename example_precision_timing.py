"""
Example: High-precision burst registration with sub-5ms timing.
Demonstrates RequestEngine + PrecisionScheduler integration.
"""

import asyncio
import time
import httpx
from datetime import datetime, timedelta
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from worker.engine import RequestEngine
from worker.scheduler import PrecisionScheduler
from worker.timer import HighPrecisionTimer


async def example_burst_registration():
    """
    Example: Register courses with precise burst timing.
    """
    print("=" * 70)
    print("HIGH-PRECISION BURST REGISTRATION EXAMPLE")
    print("=" * 70)
    print()

    # Setup
    async with httpx.AsyncClient(
        limits=httpx.Limits(max_connections=200, max_keepalive_connections=100),
        http2=True,
        timeout=httpx.Timeout(3.0),
    ) as client:
        engine = RequestEngine(
            client=client,
            max_concurrent=120,
            num_bursts=4,
            burst_delay_ms=150,
        )

        # Target: 5 seconds from now
        target_timestamp = time.time() + 5.0
        target_datetime = datetime.fromtimestamp(target_timestamp)

        print(f"Current time:  {datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}")
        print(f"Target time:   {target_datetime.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}")
        print(f"Wait duration: 5.000 seconds")
        print()

        # Pre-login phase (optional, before target time)
        print("Phase 1: Pre-login (perform before target time)")
        print("-" * 70)
        # In production, login here to establish session
        print("  [Pre-login would occur here: 2-3 seconds before target]")
        print()

        # Warm-up: Send lightweight request (optional)
        print("Phase 2: Warm-up (establish DNS/TCP/TLS)")
        print("-" * 70)
        print("  [Sending lightweight request to warm up connection...]")
        # This would be replaced with actual warm-up in production
        await asyncio.sleep(0.1)
        print("  ✓ Connection warm-up complete")
        print()

        # Main burst phase
        print("Phase 3: Precision wait and burst registration")
        print("-" * 70)
        
        # Wait until target with sub-5ms precision
        start_perf = time.perf_counter()
        print(f"  Waiting until {target_timestamp:.3f}...")
        
        await PrecisionScheduler.wait_until(target_timestamp)
        
        elapsed_perf = (time.perf_counter() - start_perf) * 1000.0
        print(f"  ✓ Target reached in {elapsed_perf:.2f}ms")
        print()

        # Mock burst registration
        print("Phase 4: Fire burst requests")
        print("-" * 70)
        
        course_ids = ["CS101", "MATH201", "ENG101"]
        results = {}
        
        for course_id in course_ids:
            payload = {
                "course_id": course_id,
                "action": "register",
            }
            
            # In production, this would call the RequestEngine
            # For this example, we simulate success
            results[course_id] = True
            print(f"  ✓ Registered {course_id}")
        
        print()
        print("=" * 70)
        print("RESULTS")
        print("=" * 70)
        print(f"Timing accuracy: {elapsed_perf:.2f}ms (target: <5ms)")
        print(f"Courses registered: {sum(1 for v in results.values() if v)}/{len(results)}")
        print()


async def example_multi_burst_timing():
    """
    Example: Execute multiple bursts with precise intervals.
    """
    print("=" * 70)
    print("MULTI-BURST TIMING EXAMPLE")
    print("=" * 70)
    print()

    num_bursts = 5
    burst_interval_ms = 200
    target_timestamp = time.time() + 2.0

    print(f"Bursts: {num_bursts}")
    print(f"Interval: {burst_interval_ms}ms")
    print(f"Total duration: {num_bursts * burst_interval_ms}ms")
    print()

    timings = []
    errors = []

    for i in range(num_bursts):
        burst_target = target_timestamp + (i * burst_interval_ms / 1000.0)
        
        start_perf = time.perf_counter()
        await PrecisionScheduler.wait_until(burst_target)
        elapsed = (time.perf_counter() - start_perf) * 1000.0
        
        expected_wait = (burst_target - time.time()) * 1000.0 + elapsed
        error = elapsed - (burst_interval_ms if i > 0 else burst_interval_ms)
        
        timings.append(elapsed)
        if i > 0:
            errors.append(error)
        
        status = "✓" if abs(error) < 5.0 if i > 0 else ""
        print(f"  Burst {i+1}: {elapsed:7.2f}ms {status}")

    if errors:
        print()
        print(f"Inter-burst interval consistency:")
        print(f"  Mean error: {sum(errors)/len(errors):+.2f}ms")
        print(f"  Max error:  {max(errors, key=abs):+.2f}ms")


async def example_offset_parameter():
    """
    Example: Using offset_ms parameter.
    """
    print("=" * 70)
    print("OFFSET PARAMETER EXAMPLE")
    print("=" * 70)
    print()

    base_target = time.time() + 2.0
    offsets = [-100, -50, 0, 50, 100]

    print(f"Base target: {base_target:.3f}")
    print(f"Testing offsets: {offsets}ms")
    print()

    for offset_ms in offsets:
        start_perf = time.perf_counter()
        await PrecisionScheduler.wait_until(base_target, offset_ms=offset_ms)
        elapsed = (time.perf_counter() - start_perf) * 1000.0
        
        expected = (base_target - time.time()) * 1000.0 + offset_ms
        error = elapsed - expected
        
        actual_offset = offset_ms if offset_ms != 0 else ""
        print(f"  offset {offset_ms:+4d}ms: {elapsed:7.2f}ms (error: {error:+.2f}ms)")


async def main():
    """Run all examples."""
    try:
        await example_burst_registration()
        print()
        
        await example_multi_burst_timing()
        print()
        
        await example_offset_parameter()
        print()
        
        print("=" * 70)
        print("✓ ALL EXAMPLES COMPLETED")
        print("=" * 70)
        
    except KeyboardInterrupt:
        print("\nInterrupted")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
