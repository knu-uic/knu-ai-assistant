"""Blocking process lock using each OS's standard library, no extra package."""
from contextlib import contextmanager
import errno
import os
import time


@contextmanager
def exclusive_file_lock(path):
    with open(path, "a+b") as handle:
        if os.name == "nt":
            import msvcrt

            # Windows byte-range locks require at least one byte. Always lock
            # byte zero, regardless of append mode or another writer's offset.
            if os.fstat(handle.fileno()).st_size == 0:
                handle.write(b"\0")
                handle.flush()
            while True:
                handle.seek(0)
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError as error:
                    if error.errno not in {errno.EACCES, errno.EAGAIN}:
                        raise
                    time.sleep(0.1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
