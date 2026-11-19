from __future__ import annotations

import threading
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path


class RunReads:
    def __init__(self) -> None:
        self._for_the_run: dict[str, object] = {}
        self._payloads: dict[Path, dict] = {}
        self._walks: dict[Path, list[Path]] = {}
        self._answers: dict[str, object] = {}
        self._files_may_move = False

    def files_may_move(self, moving: bool) -> None:
        if moving or self._files_may_move:
            self.forget_what_moving_files_changes()
        self._files_may_move = moving

    def payload(self, path: Path, read: Callable[[Path], dict]) -> dict:
        if self._files_may_move:
            return read(path)
        if path not in self._payloads:
            self._payloads[path] = read(path)
        return self._payloads[path]

    def wrote(self, path: Path, payload: dict | None) -> None:
        if payload is None or self._files_may_move:
            self.forget(path)
        else:
            self._payloads[path] = payload

    def forget(self, path: Path) -> None:
        self._payloads.pop(path, None)
        self._answers.clear()

    def videos(self, root: Path, walk: Callable[[Path], Iterable[Path]]) -> list[Path]:
        if self._files_may_move:
            return sorted(walk(root))
        if root not in self._walks:
            self._walks[root] = sorted(walk(root))
        return self._walks[root]

    def answer[T](self, key: str, work: Callable[[], T]) -> T:
        if self._files_may_move:
            return work()
        if key not in self._answers:
            self._answers[key] = work()
        return self._answers[key]

    def for_the_run[T](self, key: str, work: Callable[[], T]) -> T:
        if key not in self._for_the_run:
            self._for_the_run[key] = work()
        return self._for_the_run[key]

    def forget_what_moving_files_changes(self) -> None:
        self._payloads.clear()
        self._walks.clear()
        self._answers.clear()


_here = threading.local()


def current() -> RunReads | None:
    return getattr(_here, "reads", None)


@contextmanager
def kept(reads: RunReads | None) -> Iterator[RunReads | None]:
    before = current()
    _here.reads = reads
    try:
        yield reads
    finally:
        _here.reads = before


@contextmanager
def one_look() -> Iterator[RunReads]:
    reads = current()
    if reads is not None:
        yield reads
        return
    with kept(RunReads()) as reads:
        yield reads


def videos_in(root: Path, walk: Callable[[Path], Iterable[Path]]) -> list[Path]:
    reads = current()
    return sorted(walk(root)) if reads is None else reads.videos(root, walk)


def until_files_move[T](key: str, work: Callable[[], T]) -> T:
    reads = current()
    return work() if reads is None else reads.answer(key, work)


def once_per_run[T](key: str, work: Callable[[], T]) -> T:
    reads = current()
    return work() if reads is None else reads.for_the_run(key, work)
