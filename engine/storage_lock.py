"""Portable, reentrant cross-process locks for local SPPtab files."""
from __future__ import annotations

import errno
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path


_registry_guard = threading.Lock()
_path_locks: dict[str, threading.RLock] = {}
_thread_state = threading.local()


def _identity(path: Path) -> str:
    return os.path.normcase(str(path.expanduser().resolve(strict=False)))


def _thread_lock(identity: str) -> threading.RLock:
    with _registry_guard:
        return _path_locks.setdefault(identity, threading.RLock())


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if not handle:
            return ctypes.get_last_error() == 5  # Access denied means the process exists.
        try:
            return kernel32.WaitForSingleObject(handle, 0) == 0x00000102  # WAIT_TIMEOUT
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except (ProcessLookupError, OSError):
        return False


def _clear_stale_directory_lock(directory: Path) -> bool:
    """Remove a directory lock only when its recorded process has exited."""
    try:
        modified = directory.stat().st_mtime
    except FileNotFoundError:
        return True
    owner = directory / "owner"
    try:
        details = owner.read_text(encoding="ascii").split()
        pid = int(details[0])
    except (OSError, ValueError, IndexError):
        # Allow time for the process that created the directory to write owner.
        if time.time() - modified < 30:
            return False
        pid = 0
    if pid and _pid_alive(pid):
        return False
    try:
        owner.unlink(missing_ok=True)
        directory.rmdir()
        return True
    except OSError:
        return False


def _directory_lock(path: Path, blocking: bool) -> Path:
    directory = path.with_name(path.name + ".d")
    deadline = time.monotonic() + 1800
    while True:
        try:
            directory.mkdir()
            try:
                (directory / "owner").write_text(f"{os.getpid()} {time.time():.6f}\n", encoding="ascii")
            except OSError:
                try:
                    directory.rmdir()
                except OSError:
                    pass
                raise
            return directory
        except FileExistsError:
            if _clear_stale_directory_lock(directory):
                continue
            if not blocking:
                raise TimeoutError("O arquivo está em uso por outra operação.")
            if time.monotonic() >= deadline:
                raise TimeoutError("A operação aguardou demais pelo arquivo em uso. Tente novamente.")
            time.sleep(0.08)


def _acquire_file_lock(handle, blocking: bool) -> bool:
    """Return False when the filesystem cannot provide a usable file lock."""
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            flags = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
            fcntl.flock(handle.fileno(), flags)
        return True
    except OSError as exc:
        if not blocking and exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
            raise TimeoutError("O arquivo está em uso por outra operação.") from exc
        if exc.errno == errno.EDEADLK:
            return False
        raise


def _release_file_lock(handle) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def interprocess_lock(path: Path, blocking: bool = True):
    """Lock a path across threads/processes, including reentrant same-thread calls.

    The atomic directory coordinates every current process. The legacy file
    lock also waits for older SPPtab processes when the filesystem supports it.
    Filesystems reporting EDEADLK can still use the directory lock safely.
    """
    path = Path(path)
    identity = _identity(path)
    local_lock = _thread_lock(identity)
    if not local_lock.acquire(blocking=blocking):
        raise TimeoutError("O arquivo está em uso por outra operação.")
    held = getattr(_thread_state, "held", None)
    if held is None:
        held = {}
        _thread_state.held = held
    depth = held.get(identity, 0)
    if depth:
        held[identity] = depth + 1
        try:
            yield
        finally:
            if depth:
                held[identity] = depth
            else:
                held.pop(identity, None)
            local_lock.release()
        return

    handle = None
    file_locked = False
    directory_locked = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        directory_locked = _directory_lock(path, blocking)
        handle = path.open("a+b")
        file_locked = _acquire_file_lock(handle, blocking)
        if not file_locked:
            handle.close()
            handle = None
        held[identity] = 1
        yield
    finally:
        held.pop(identity, None)
        if file_locked and handle is not None:
            try:
                _release_file_lock(handle)
            except OSError:
                pass
        try:
            if handle is not None:
                handle.close()
        finally:
            if directory_locked is not None:
                owner = directory_locked / "owner"
                try:
                    owner.unlink(missing_ok=True)
                    directory_locked.rmdir()
                except OSError:
                    pass
            local_lock.release()
