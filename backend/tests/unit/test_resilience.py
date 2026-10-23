import asyncio
import pytest
from src.infrastructure.resilience import CircuitBreaker, CircuitState, CircuitBreakerOpenException


class FakeClock:
    def __init__(self, start_time: float = 1000.0):
        self.current_time = start_time

    def time(self) -> float:
        return self.current_time

    def advance(self, seconds: float):
        self.current_time += seconds


@pytest.mark.asyncio
async def test_circuit_breaker_starts_closed():
    clock = FakeClock()
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=30.0, time_func=clock.time)

    assert cb.state == CircuitState.CLOSED
    assert cb.failure_count == 0
    assert await cb.can_execute() is True


@pytest.mark.asyncio
async def test_transition_closed_to_open_after_consecutive_failures():
    clock = FakeClock()
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=30.0, time_func=clock.time)

    # 1st failure
    await cb.record_failure()
    assert cb.state == CircuitState.CLOSED
    assert cb.failure_count == 1

    # 2nd failure
    await cb.record_failure()
    assert cb.state == CircuitState.CLOSED
    assert cb.failure_count == 2

    # 3rd failure reaches threshold
    await cb.record_failure()
    assert cb.state == CircuitState.OPEN
    assert cb.failure_count == 3

    # Calls should now fail fast
    with pytest.raises(CircuitBreakerOpenException) as exc_info:
        await cb.can_execute()
    assert exc_info.value.retry_after == pytest.approx(30.0)


@pytest.mark.asyncio
async def test_fast_fail_while_circuit_is_open():
    clock = FakeClock()
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=20.0, time_func=clock.time)

    await cb.record_failure()
    await cb.record_failure()
    assert cb.state == CircuitState.OPEN

    # In OPEN state, can_execute raises CircuitBreakerOpenException without allowing execution
    with pytest.raises(CircuitBreakerOpenException):
        await cb.can_execute()

    clock.advance(10.0)
    # Still open (10s remaining)
    with pytest.raises(CircuitBreakerOpenException) as exc_info:
        await cb.can_execute()
    assert exc_info.value.retry_after == pytest.approx(10.0)


@pytest.mark.asyncio
async def test_immediate_open_on_explicit_retry_after_rate_limit_429():
    clock = FakeClock()
    cb = CircuitBreaker(failure_threshold=5, recovery_timeout=30.0, time_func=clock.time)

    # Immediate open when retry_after is passed, even on 1st occurrence
    await cb.record_failure(retry_after=45.0)

    assert cb.state == CircuitState.OPEN
    with pytest.raises(CircuitBreakerOpenException) as exc_info:
        await cb.can_execute()
    assert exc_info.value.retry_after == pytest.approx(45.0)


@pytest.mark.asyncio
async def test_transition_open_to_half_open_to_closed_on_success():
    clock = FakeClock()
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=15.0, time_func=clock.time)

    await cb.record_failure()
    await cb.record_failure()
    assert cb.state == CircuitState.OPEN

    # Advance clock past cooldown
    clock.advance(15.1)
    assert cb.state == CircuitState.HALF_OPEN

    # In HALF_OPEN, can_execute is allowed
    assert await cb.can_execute() is True

    # Record success -> resets to CLOSED
    await cb.record_success()
    assert cb.state == CircuitState.CLOSED
    assert cb.failure_count == 0


@pytest.mark.asyncio
async def test_half_open_failure_reopens_circuit():
    clock = FakeClock()
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=15.0, time_func=clock.time)

    await cb.record_failure()
    await cb.record_failure()
    assert cb.state == CircuitState.OPEN

    clock.advance(15.5)
    assert cb.state == CircuitState.HALF_OPEN

    # Trial call fails
    await cb.record_failure()
    assert cb.state == CircuitState.OPEN

    # Must wait another recovery_timeout
    with pytest.raises(CircuitBreakerOpenException):
        await cb.can_execute()


@pytest.mark.asyncio
async def test_execute_helper_wrapper():
    clock = FakeClock()
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=10.0, time_func=clock.time)

    async def successful_call(val: int):
        return val * 2

    res = await cb.execute(successful_call, 5)
    assert res == 10
    assert cb.state == CircuitState.CLOSED

    async def failing_call():
        raise RuntimeError("Service failure")

    with pytest.raises(RuntimeError):
        await cb.execute(failing_call)
    assert cb.failure_count == 1
    assert cb.state == CircuitState.CLOSED

    with pytest.raises(RuntimeError):
        await cb.execute(failing_call)
    assert cb.state == CircuitState.OPEN

    # Now calls fail with CircuitBreakerOpenException
    with pytest.raises(CircuitBreakerOpenException):
        await cb.execute(successful_call, 10)
