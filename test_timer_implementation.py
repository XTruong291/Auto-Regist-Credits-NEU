#!/usr/bin/env python3
"""
Integration test: Verify high-precision wait_until implementation.
Run this to validate the complete timer implementation.
"""

import asyncio
import time
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from worker.timer import HighPrecisionTimer, wait_until
from worker.scheduler import PrecisionScheduler


class TimerTest:
    """Comprehensive timer implementation tests."""
    
    def __init__(self):
        self.passed = 0
        self.failed = 0

    def assert_true(self, condition, message):
        """Assert condition is True."""
        if condition:
            self.passed += 1
            print(f"  ✓ {message}")
        else:
            self.failed += 1
            print(f"  ✗ {message}")

    def assert_close(self, actual, expected, tolerance, message):
        """Assert actual is close to expected within tolerance."""
        if abs(actual - expected) <= tolerance:
            self.passed += 1
            print(f"  ✓ {message} (error: {actual-expected:+.2f})")
        else:
            self.failed += 1
            print(f"  ✗ {message} (error: {actual-expected:+.2f}, tolerance: {tolerance})")

    async def test_basic_wait_until(self):
        """Test 1: Basic wait_until functionality."""
        print("\n[Test 1] Basic wait_until()")
        print("-" * 50)
        
        target = time.time() + 0.5
        start = time.perf_counter()
        await wait_until(target)
        elapsed = (time.perf_counter() - start) * 1000
        
        self.assert_close(elapsed, 500, 10, "Wait 500ms with <10ms error")

    async def test_wait_with_offset(self):
        """Test 2: wait_until with offset_ms parameter."""
        print("\n[Test 2] wait_until with offset_ms")
        print("-" * 50)
        
        offsets = [-50, 0, 50]
        
        for offset_ms in offsets:
            target = time.time() + 0.5
            start = time.perf_counter()
            await wait_until(target, offset_ms=offset_ms)
            elapsed = (time.perf_counter() - start) * 1000
            
            expected = 500 + offset_ms
            self.assert_close(elapsed, expected, 15, f"Offset {offset_ms}ms: {expected}ms ±15ms")

    async def test_multiple_sequential_waits(self):
        """Test 3: Multiple sequential waits."""
        print("\n[Test 3] Multiple sequential waits")
        print("-" * 50)
        
        errors = []
        
        for i in range(5):
            target = time.time() + 0.2
            start = time.perf_counter()
            await wait_until(target)
            elapsed = (time.perf_counter() - start) * 1000
            
            error = abs(elapsed - 200)
            errors.append(error)
        
        max_error = max(errors)
        avg_error = sum(errors) / len(errors)
        
        self.assert_close(avg_error, 0, 5, f"Average error across 5 waits: {avg_error:.2f}ms")
        self.assert_true(max_error < 10, f"Max error: {max_error:.2f}ms <10ms")

    async def test_high_precision_timer_class(self):
        """Test 4: HighPrecisionTimer class methods."""
        print("\n[Test 4] HighPrecisionTimer class")
        print("-" * 50)
        
        # Test sleep_ms
        start = time.perf_counter()
        await HighPrecisionTimer.sleep_ms(300)
        elapsed = (time.perf_counter() - start) * 1000
        
        self.assert_close(elapsed, 300, 15, "sleep_ms(300): ±15ms")
        
        # Test get_current_timestamp
        ts = HighPrecisionTimer.get_current_timestamp()
        self.assert_true(ts > 0, "get_current_timestamp() returns valid value")
        
        # Test get_current_perf_time
        perf = HighPrecisionTimer.get_current_perf_time()
        self.assert_true(perf > 0, "get_current_perf_time() returns valid value")

    async def test_precision_scheduler_integration(self):
        """Test 5: PrecisionScheduler integration."""
        print("\n[Test 5] PrecisionScheduler integration")
        print("-" * 50)
        
        target = time.time() + 0.5
        
        async def dummy_coro():
            return "success"
        
        start = time.perf_counter()
        result = await PrecisionScheduler.schedule_at(target, dummy_coro)
        elapsed = (time.perf_counter() - start) * 1000
        
        self.assert_true(result == "success", "Coroutine executed and returned result")
        self.assert_close(elapsed, 500, 15, "schedule_at() timing: 500ms ±15ms")

    async def test_burst_scheduling(self):
        """Test 6: Burst scheduling with intervals."""
        print("\n[Test 6] Burst scheduling")
        print("-" * 50)
        
        target = time.time() + 1.0
        num_bursts = 3
        interval_ms = 200
        
        timings = []
        
        for i in range(num_bursts):
            burst_target = target + (i * interval_ms / 1000.0)
            start = time.perf_counter()
            await wait_until(burst_target)
            elapsed = (time.perf_counter() - start) * 1000
            timings.append(elapsed)
        
        # Check intervals
        if len(timings) >= 2:
            interval = (timings[0] + timings[1]) / 2
            self.assert_close(interval, interval_ms, 20, 
                            f"Burst interval: {interval_ms}ms ±20ms")

    async def test_accuracy_measurement(self):
        """Test 7: Accuracy measurement utility."""
        print("\n[Test 7] Accuracy measurement")
        print("-" * 50)
        
        measurements = [
            (500, 501.2, True, "GOOD"),
            (500, 510.0, False, "POOR"),
            (500, 500.5, True, "EXCELLENT"),
        ]
        
        for target, actual, should_pass, expected_class in measurements:
            result = HighPrecisionTimer.measure_accuracy(target, actual)
            
            self.assert_true(result["passed"] == should_pass, 
                           f"Accuracy measure {target}ms vs {actual}ms: passed={should_pass}")
            self.assert_true(result["classification"] == expected_class,
                           f"Classification: {expected_class}")

    async def test_stress_multiple_concurrent(self):
        """Test 8: Stress test with multiple concurrent waits."""
        print("\n[Test 8] Concurrent waits stress test")
        print("-" * 50)
        
        target = time.time() + 0.3
        
        async def concurrent_wait():
            start = time.perf_counter()
            await wait_until(target)
            return (time.perf_counter() - start) * 1000
        
        # Note: These waits are started concurrently but don't actually overlap
        # due to the synchronous nature of wait_until
        results = await asyncio.gather(*[concurrent_wait() for _ in range(5)])
        
        errors = [abs(r - 300) for r in results]
        max_error = max(errors)
        
        self.assert_true(max_error < 20, f"Max error in concurrent test: {max_error:.2f}ms <20ms")

    async def test_sub_5ms_accuracy(self):
        """Test 9: Verify <5ms accuracy requirement."""
        print("\n[Test 9] <5ms accuracy requirement")
        print("-" * 50)
        
        iterations = 10
        errors = []
        
        for i in range(iterations):
            target = time.time() + 0.25
            start = time.perf_counter()
            await wait_until(target)
            elapsed = (time.perf_counter() - start) * 1000
            
            error = abs(elapsed - 250)
            errors.append(error)
        
        passed_count = sum(1 for e in errors if e < 5)
        
        self.assert_true(passed_count >= iterations * 0.9,
                        f"<5ms accuracy: {passed_count}/{iterations} passed (90%+ required)")
        self.assert_true(max(errors) < 7, f"Max error: {max(errors):.2f}ms <7ms")

    async def run_all_tests(self):
        """Run all tests."""
        print("=" * 70)
        print("HIGH-PRECISION TIMER IMPLEMENTATION TESTS")
        print("=" * 70)
        
        try:
            await self.test_basic_wait_until()
            await self.test_wait_with_offset()
            await self.test_multiple_sequential_waits()
            await self.test_high_precision_timer_class()
            await self.test_precision_scheduler_integration()
            await self.test_burst_scheduling()
            await self.test_accuracy_measurement()
            await self.test_stress_multiple_concurrent()
            await self.test_sub_5ms_accuracy()
            
        except Exception as e:
            print(f"\n✗ Test error: {e}")
            import traceback
            traceback.print_exc()
            self.failed += 1
        
        # Summary
        print("\n" + "=" * 70)
        print(f"RESULTS: {self.passed} passed, {self.failed} failed")
        print("=" * 70)
        
        if self.failed == 0:
            print("✓ ALL TESTS PASSED")
            return 0
        else:
            print(f"✗ {self.failed} TEST(S) FAILED")
            return 1


async def main():
    """Run test suite."""
    tester = TimerTest()
    exit_code = await tester.run_all_tests()
    return exit_code


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
