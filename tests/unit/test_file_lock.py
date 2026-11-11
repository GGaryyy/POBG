"""The cross-process data lock (src/scrapers/common.py: file_lock), held through the OS."""
import subprocess
import sys

import pytest

from src.scrapers.common import LockBusy, file_lock

pytestmark = pytest.mark.unit

TRY_IN_CHILD = ("import sys\nfrom src.scrapers.common import LockBusy, file_lock\n"
                "try:\n    with file_lock(sys.argv[1]):\n        print('got')\n"
                "except LockBusy:\n    print('busy')\n")


def in_other_process(lock) -> str:
    out = subprocess.run([sys.executable, "-c", TRY_IN_CHILD, str(lock)], capture_output=True, text=True,
                         timeout=60, check=True)
    return out.stdout.strip()


def test_lock_is_held_inside_and_free_afterwards(tmp_path):
    lock = tmp_path / "data" / ".update.lock"
    with file_lock(lock):
        assert lock.read_text(encoding="utf-8").split()[0].isdigit()
        assert in_other_process(lock) == "busy"
    assert in_other_process(lock) == "got"


def test_second_holder_in_the_same_process_is_refused(tmp_path):
    lock = tmp_path / ".update.lock"
    with file_lock(lock):
        with pytest.raises(LockBusy, match=".update.lock is held by another process"):
            with file_lock(lock):
                pytest.fail("must not enter")
    with file_lock(lock):          # and free again afterwards
        pass


def test_lock_is_released_when_the_body_raises(tmp_path):
    lock = tmp_path / ".update.lock"
    with pytest.raises(RuntimeError):
        with file_lock(lock):
            raise RuntimeError("boom")
    assert in_other_process(lock) == "got"


def test_lock_file_left_behind_by_a_dead_process_does_not_block(tmp_path):
    lock = tmp_path / ".update.lock"
    lock.write_text("4242 crashed long ago\n", encoding="utf-8")       # a file, but nobody holds a lock on it
    with file_lock(lock):
        assert lock.read_text(encoding="utf-8").split()[0] != "4242"


def test_a_holder_that_runs_long_keeps_its_lock(tmp_path):
    # the old age-based takeover let a third writer in; an OS lock has no age
    import os
    import time
    lock = tmp_path / ".update.lock"
    with file_lock(lock):
        old = time.time() - 24 * 3600
        os.utime(lock, (old, old))
        assert in_other_process(lock) == "busy"
