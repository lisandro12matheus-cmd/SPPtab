"""Small cross-process exclusive file lock for local SPPtab metadata."""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def interprocess_lock(path: Path, blocking: bool = True):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    acquired = False
    try:
        if os.name == "nt":
            import msvcrt
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            if blocking:
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            else:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        acquired = True
        yield
    except (OSError, BlockingIOError):
        if not blocking:
            raise TimeoutError("O arquivo está em uso por outra operação.")
        raise
    finally:
        if acquired:
            try:
                if os.name == "nt":
                    import msvcrt
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        handle.close()
