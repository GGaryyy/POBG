"""The cross-process data lock (src/scrapers/common.py: file_lock)."""
import os
import time

import pytest

from src.scrapers.common import LOCK_STALE_SECONDS, LockBusy, file_lock

pytestmark = pytest.mark.unit


def test_lock_file_exists_while_held_and_is_removed_afterwards(tmp_path):
    lock = tmp_path / "data" / ".update.lock"
    with file_lock(lock):
        assert lock.exists() and lock.read_text(encoding="utf-8").split()[0] == str(os.getpid())
    assert not lock.exists()


def test_second_holder_is_refused_and_the_first_keeps_its_lock(tmp_path):
    lock = tmp_path / ".update.lock"
    with file_lock(lock):
        with pytest.raises(LockBusy, match=".update.lock is held by another process"):
            with file_lock(lock):
                pytest.fail("must not enter")
        assert lock.exists()
    assert not lock.exists()


def test_lock_is_released_when_the_body_raises(tmp_path):
    lock = tmp_path / ".update.lock"
    with pytest.raises(RuntimeError):
        with file_lock(lock):
            raise RuntimeError("boom")
    assert not lock.exists()


def test_fresh_foreign_lock_is_respected_and_left_in_place(tmp_path):
    lock = tmp_path / ".update.lock"
    lock.write_text("1 other\n", encoding="utf-8")
    with pytest.raises(LockBusy):
        with file_lock(lock):
            pytest.fail("must not enter")
    assert lock.read_text(encoding="utf-8") == "1 other\n"


def test_stale_lock_is_taken_over(tmp_path):
    lock = tmp_path / ".update.lock"
    lock.write_text("1 crashed\n", encoding="utf-8")
    old = time.time() - LOCK_STALE_SECONDS - 5
    os.utime(lock, (old, old))
    with file_lock(lock):
        assert lock.read_text(encoding="utf-8").split()[0] == str(os.getpid())
    assert not lock.exists()
