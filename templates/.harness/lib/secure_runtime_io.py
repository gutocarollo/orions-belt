#!/usr/bin/env python3
"""No-follow, locked file access for runtime evidence ledgers."""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import os
import stat
from pathlib import Path
from typing import Iterator, TextIO


def _component(value: str) -> str:
    if not value or value in {".", ".."} or Path(value).name != value:
        raise OSError(f"unsafe runtime-ledger path component: {value!r}")
    return value


@contextmanager
def open_locked_text(
    root: Path,
    directories: tuple[str, ...],
    filename: str,
) -> Iterator[tuple[Path, TextIO]]:
    """Open a regular file below ``root`` without following any symlink.

    Every directory is created and reopened relative to the already-open
    parent descriptor. This prevents both pre-existing symlinks and a parent
    swap between validation and the final open.
    """
    resolved_root = root.resolve(strict=True)
    directory_names = tuple(_component(value) for value in directories)
    safe_filename = _component(filename)
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
    file_flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW
    descriptors: list[int] = []
    stream: TextIO | None = None
    try:
        current = os.open(resolved_root, directory_flags)
        descriptors.append(current)
        for name in directory_names:
            try:
                os.mkdir(name, mode=0o700, dir_fd=current)
            except FileExistsError:
                pass
            child = os.open(name, directory_flags, dir_fd=current)
            descriptors.append(child)
            current = child
        file_descriptor = os.open(safe_filename, file_flags, mode=0o600, dir_fd=current)
        metadata = os.fstat(file_descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            os.close(file_descriptor)
            raise OSError(f"runtime-ledger target is not a regular file: {safe_filename}")
        stream = os.fdopen(file_descriptor, "r+", encoding="utf-8")
        fcntl.flock(stream, fcntl.LOCK_EX)
        path = resolved_root.joinpath(*directory_names, safe_filename)
        yield path, stream
    finally:
        if stream is not None:
            stream.close()
        for descriptor in reversed(descriptors):
            os.close(descriptor)
