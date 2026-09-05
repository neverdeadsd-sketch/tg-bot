"""Background jobs for the local UI.

Generation and scanning both take long enough that the browser cannot wait for
them, so they run on a worker thread and report progress the page can poll.
Only one job runs at a time — the scans are rate limited anyway, and two at
once would race on the same quota.
"""

from __future__ import annotations

import threading
import time
import traceback
from dataclasses import dataclass, field


@dataclass
class Job:
    kind: str
    total: int = 0
    done: int = 0
    state: str = "running"          # running | finished | failed | stopped
    message: str = ""
    lines: list[dict] = field(default_factory=list)
    error: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "total": self.total,
            "done": self.done,
            "state": self.state,
            "message": self.message,
            "lines": self.lines[-400:],
            "error": self.error,
            "elapsed": round((self.finished_at or time.time()) - self.started_at, 1),
        }


class JobRunner:
    """Runs one job at a time and exposes its progress."""

    def __init__(self):
        self._lock = threading.Lock()
        self._job: Job | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    @property
    def busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def snapshot(self) -> dict | None:
        with self._lock:
            return self._job.as_dict() if self._job else None

    def start(self, kind: str, target) -> Job:
        """Run `target(job, should_stop)` on a worker thread."""
        if self.busy:
            raise RuntimeError("another job is already running")
        job = Job(kind=kind)
        self._stop.clear()

        def run():
            try:
                target(job, self._stop.is_set)
                if job.state == "running":
                    job.state = "stopped" if self._stop.is_set() else "finished"
            except Exception as exc:  # surfaced in the UI, not swallowed
                job.state = "failed"
                job.error = f"{type(exc).__name__}: {exc}"
                job.lines.append({"level": "error", "text": job.error})
                traceback.print_exc()
            finally:
                job.finished_at = time.time()

        with self._lock:
            self._job = job
        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()
        return job

    def request_stop(self) -> bool:
        if not self.busy:
            return False
        self._stop.set()
        if self._job:
            self._job.message = "stopping after the current request..."
        return True
