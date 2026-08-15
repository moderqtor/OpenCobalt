"""Last-intent coalescing for conversation routing writes.

Mirrors ui/src/routingPersist.js so delayed/reordered writes can be proven
without a JavaScript test runner.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any


class PerConversationWriteQueue:
    def __init__(self, write: Callable[[str, Any], Any]) -> None:
        self._write = write
        self._lock = threading.Lock()
        self._pending: dict[str, tuple[int, Any]] = {}
        self._generation: dict[str, int] = {}
        self._tails: dict[str, threading.Thread] = {}
        self._events: dict[str, threading.Event] = {}
        self._results: dict[int, Any] = {}
        self._errors: dict[int, BaseException] = {}
        self._done: dict[int, threading.Event] = {}

    def enqueue(self, conversation_id: str, payload: Any) -> threading.Event:
        with self._lock:
            generation = self._generation.get(conversation_id, 0) + 1
            self._generation[conversation_id] = generation
            self._pending[conversation_id] = (generation, payload)
            done = threading.Event()
            self._done[generation] = done
            previous = self._events.get(conversation_id)
            self._events[conversation_id] = done

        def run() -> None:
            if previous is not None:
                previous.wait(timeout=5)
            with self._lock:
                queued = self._pending.get(conversation_id)
                if queued is None or queued[0] != generation:
                    done.set()
                    return
                self._pending.pop(conversation_id, None)
                to_write = queued[1]
            try:
                result = self._write(conversation_id, to_write)
                self._results[generation] = result
            except BaseException as exc:
                self._errors[generation] = exc
            finally:
                done.set()

        worker = threading.Thread(target=run)
        self._tails[conversation_id] = worker
        worker.start()
        return done


def test_coalesced_queue_delayed_first_write_keeps_last_payload():
    release_first = threading.Event()
    started_first = threading.Event()
    writes: list[tuple[str, str]] = []

    def write(conversation_id: str, payload: str) -> str:
        if payload == "A1":
            started_first.set()
            assert release_first.wait(timeout=5)
        writes.append((conversation_id, payload))
        return payload

    queue = PerConversationWriteQueue(write)
    first = queue.enqueue("conv-a", "A1")
    assert started_first.wait(timeout=5)
    queue.enqueue("conv-a", "A2")
    last = queue.enqueue("conv-a", "A3")
    release_first.set()
    assert first.wait(timeout=5)
    assert last.wait(timeout=5)
    assert writes == [("conv-a", "A1"), ("conv-a", "A3")]


def test_coalesced_queue_does_not_serialize_unrelated_conversations():
    release_a = threading.Event()
    started_a = threading.Event()
    started_b = threading.Event()
    writes: list[str] = []

    def write(conversation_id: str, payload: str) -> str:
        writes.append(f"{conversation_id}:{payload}")
        if conversation_id == "conv-a":
            started_a.set()
            assert release_a.wait(timeout=5)
        else:
            started_b.set()
        return payload

    queue = PerConversationWriteQueue(write)
    queue.enqueue("conv-a", "manual")
    assert started_a.wait(timeout=5)
    queue.enqueue("conv-b", "automatic")
    assert started_b.wait(timeout=5)
    release_a.set()
    assert "conv-b:automatic" in writes
