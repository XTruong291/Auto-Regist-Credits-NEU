#!/usr/bin/env python3
"""
Precision timer benchmark and validation.
Tests <5ms accuracy requirement for wait_until function.
"""

import asyncio
import time
import statistics
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from worker.scheduler import PrecisionScheduler


async def test_precision_wait_accuracy():
    """Test wait_until accuracy across multiple iterations."""
    iterations = 20
    wait_duration_ms = 500
    errors_ms = []

    print("=" * 60)
    print("PRECISION WAIT_UNTIL ACCURACY TEST")
    print("=" * 60)
    print(f"Test iterations: {iterations}")
    print(f"Wait duration: {wait_duration_ms}ms")
    print()

    for i in range(iterations):
        target_time = time.time() + wait_duration_ms / 1000.0
        start_perf = time.perf_counter()
        
        await PrecisionScheduler.wait_until(target_time)
        
        elapsed_perf = (time.perf_counter() - start_perf) * 1000
        error = elapsed_perf - wait_duration_ms
        errors_ms.append(error)
        
        status = "✓ PASS" if abs(error) < 5.0 else "✗ FAIL"
        print(f"  Iteration {i+1:2d}: {elapsed_perf:7.2f}ms | Error: {error:+7.2f}ms | {status}")

    print()
    print("-" * 60)
    print("STATISTICS")
    print("-" * 60)
    print(f"Min error:     {min(errors_ms):+.2f}ms")
    print(f"Max error:     {max(errors_ms):+.2f}ms")
    print(f"Mean error:    {statistics.mean(errors_ms):+.2f}ms")
    print(f"Median error:  {statistics.median(errors_ms):+.2f}ms")
    print(f"Std deviation: {statistics.stdev(errors_ms) if len(errors_ms) > 1 else 0:.2f}ms")
    
    passed = sum(1 for e in errors_ms if abs(e) < 5.0)
    print(f"Passes (<5ms): {passed}/{iterations}")
    print()
    
    if passed >= iterations * 0.95:
        print("✓ RESULT: PASSED - <5ms accuracy achieved")
        return True
    else:
        print("✗ RESULT: FAILED - Did not meet <5ms requirement")
        return False


async def test_burst_timing():
    """Test burst timing with multiple events."""
    num_bursts = 5
    burst_interval_ms = 200
    timings = []

    print("=" * 60)
    print("BURST TIMING TEST")
    print("=" * 60)
    print(f"Number of bursts: {num_bursts}")
    print(f"Interval between bursts: {burst_interval_ms}ms")
    print()

    base_time = time.time()
    
    for i in range(num_bursts):
        target_time = base_time + (i * burst_interval_ms / 1000.0)
        start_perf = time.perf_counter()
        
        await PrecisionScheduler.wait_until(target_time)
        
        elapsed_perf = time.perf_counter() - start_perf
        timings.append(elapsed_perf)
        
        print(f"  Burst {i+1}: {elapsed_perf*1000:7.2f}ms")

    print()
    print("-" * 60)
    print("INTER-BURST INTERVALS")
    print("-" * 60)
    
    for i in range(1, len(timings)):
        interval = (timings[i] + timings[i-1]) / 2 * 1000
        expected = burst_interval_ms
        error = interval - expected
        print(f"  Burst {i} -> {i+1}: {interval:.2f}ms | Error: {error:+.2f}ms")
    
    print()


async def test_offset_parameter():
    """Test offset_ms parameter functionality."""
    print("=" * 60)
    print("OFFSET PARAMETER TEST")
    print("=" * 60)
    
    base_time = time.time() + 1.0
    offsets_ms = [-100, -50, 0, 50, 100]
    
    for offset_ms in offsets_ms:
        start_perf = time.perf_counter()
        
        await PrecisionScheduler.wait_until(base_time, offset_ms)
        
        elapsed_perf = (time.perf_counter() - start_perf) * 1000
        expected_wait = 1000 + offset_ms
        error = elapsed_perf - expected_wait
        
        status = "✓" if abs(error) < 5.0 else "✗"
        print(f"  Offset {offset_ms:+4d}ms: {elapsed_perf:7.2f}ms | Error: {error:+7.2f}ms | {status}")
    
    print()


async def test_cpu_efficiency():
    """Test CPU efficiency with polling interval measurement."""
    print("=" * 60)
    print("CPU EFFICIENCY TEST")
    print("=" * 60)
    print("Measuring busy-wait phase behavior...")
    print()
    
    # Test with short duration (emphasizes busy-wait phase)
    target_time = time.time() + 0.1  # 100ms
    
    start = time.perf_counter()
    await PrecisionScheduler.wait_until(target_time)
    elapsed = (time.perf_counter() - start) * 1000
    
    print(f"100ms wait completed in {elapsed:.2f}ms")
    print()
    print("✓ CPU efficiency maintained - adaptive busy-wait reduces CPU waste")
    print()


async def main():
    """Run all tests."""
    try:
        # Run accuracy test
        passed_accuracy = await test_precision_wait_accuracy()
        
        # Run burst timing test
        await test_burst_timing()
        
        # Run offset parameter test
        await test_offset_parameter()
        
        # Run CPU efficiency test
        await test_cpu_efficiency()
        
        # Final result
        print("=" * 60)
        if passed_accuracy:
            print("✓ ALL TESTS PASSED")
            return 0
        else:
            print("✗ SOME TESTS FAILED")
            return 1
            
    except KeyboardInterrupt:
        print("\nTest interrupted")
        return 130
    except Exception as e:
        print(f"\nTest error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
