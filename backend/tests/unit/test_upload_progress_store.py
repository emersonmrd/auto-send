import pytest

from src.infrastructure.upload_progress_store import UploadProgressStore


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


def test_entries_idle_longer_than_ttl_are_dropped_on_next_write(clock: FakeClock):
    store = UploadProgressStore(ttl_seconds=1800, max_items=10, clock=clock)
    store["old"] = {"percent": 10}
    clock.now += 1801

    store["new"] = {"percent": 0}

    assert "old" not in store
    assert list(store) == ["new"]


def test_reading_an_entry_keeps_it_alive(clock: FakeClock):
    # O callback de progresso faz store[id]["percent"] = ...; um upload longo não pode expirar no meio.
    store = UploadProgressStore(ttl_seconds=1800, max_items=10, clock=clock)
    store["upload"] = {"percent": 0}
    for _ in range(3):
        clock.now += 1000
        store["upload"]["percent"] += 10

    store["other"] = {"percent": 0}

    assert store["upload"]["percent"] == 30


def test_above_the_limit_the_least_recently_used_entries_leave(clock: FakeClock):
    store = UploadProgressStore(ttl_seconds=1800, max_items=3, clock=clock)
    for key in ("a", "b", "c"):
        store[key] = {}
        clock.now += 1
    store["a"]  # "a" volta a ser o mais recente

    store["d"] = {}

    assert list(store) == ["c", "a", "d"]
    assert len(store) == 3


def test_membership_check_does_not_refresh_an_entry(clock: FakeClock):
    store = UploadProgressStore(ttl_seconds=1800, max_items=10, clock=clock)
    store["old"] = {}
    clock.now += 1000
    assert "old" in store
    clock.now += 900

    store["new"] = {}

    assert "old" not in store


def test_missing_entry_raises_key_error_and_get_returns_default(clock: FakeClock):
    store = UploadProgressStore(ttl_seconds=1800, max_items=10, clock=clock)

    with pytest.raises(KeyError):
        store["missing"]
    assert store.get("missing", {}) == {}


def test_delete_removes_the_entry(clock: FakeClock):
    store = UploadProgressStore(ttl_seconds=1800, max_items=10, clock=clock)
    store["a"] = {}

    del store["a"]

    assert len(store) == 0


@pytest.mark.parametrize("ttl, limit", [(0, 10), (1800, 0)])
def test_rejects_non_positive_limits(ttl: int, limit: int):
    with pytest.raises(ValueError):
        UploadProgressStore(ttl_seconds=ttl, max_items=limit)


def test_api_progress_tracker_is_bounded():
    # Regressão da #38: o dicionário da rota crescia uma entrada por tracking_id, sem limite.
    from src.presentation import main

    main.upload_progress_tracker.clear()
    try:
        for n in range(main.UPLOAD_PROGRESS_MAX_ITEMS + 5):
            main.update_progress(f"tracking-{n}")

        assert len(main.upload_progress_tracker) == main.UPLOAD_PROGRESS_MAX_ITEMS
        assert "tracking-0" not in main.upload_progress_tracker
    finally:
        main.upload_progress_tracker.clear()
