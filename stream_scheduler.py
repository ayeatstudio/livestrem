"""Canonical Stream Scheduler.

Architecture:
    StreamScheduler
        -> StreamingEngine
            -> FFmpegWorker

The scheduler owns scheduling/orchestration only.
FFmpeg process lifecycle belongs exclusively to the canonical engine/worker
stack.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from threading import RLock
from typing import Any, Dict, List, Optional

try:
    from .engine import StreamingEngine
    from .models import (
        StreamDestination,
        StreamJob,
        StreamSchedule,
        VideoSource,
        StreamStatus,
        PlatformType,
        SourceType,
    )
except ImportError:
    from engine import StreamingEngine
    from models import (
        StreamDestination,
        StreamJob,
        StreamSchedule,
        VideoSource,
        StreamStatus,
        PlatformType,
        SourceType,
    )


class ScheduleStatus(str, Enum):
    STOPPED = "STOPPED"
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    BLOCKED = "BLOCKED"
    ERROR = "ERROR"


@dataclass
class ScheduleEntry:
    job_id: str
    destination_id: str
    source_path: str
    start_at: Optional[datetime] = None
    enabled: bool = True
    status: ScheduleStatus = ScheduleStatus.STOPPED
    last_error: Optional[str] = None
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class StreamScheduler:
    """High-level scheduling/orchestration facade.

    Responsibilities:
        - Maintain schedule entries.
        - Build canonical StreamJob objects.
        - Register jobs with StreamingEngine.
        - Delegate lifecycle operations to StreamingEngine.

    Non-responsibilities:
        - FFmpeg command construction.
        - subprocess management.
        - RTMP execution.
        - worker/process lifecycle.
    """

    def __init__(
        self,
        root: str | Path = ".",
        engine: Optional[StreamingEngine] = None,
        dry_run: bool = True,
    ):
        self.root = Path(root)
        self.engine = engine or StreamingEngine()
        self.dry_run = bool(dry_run)

        self._entries: Dict[str, ScheduleEntry] = {}
        self._jobs: Dict[str, StreamJob] = {}

        self._lock = RLock()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def add(
        self,
        job_id: str,
        destination_id: str,
        source_path: str | Path,
        start_at: Optional[datetime] = None,
        enabled: bool = True,
    ) -> ScheduleEntry:
        """Register a schedule entry and its canonical StreamJob."""

        if not job_id:
            raise ValueError("job_id is required")

        if not destination_id:
            raise ValueError("destination_id is required")

        source = Path(source_path)

        entry = ScheduleEntry(
            job_id=job_id,
            destination_id=destination_id,
            source_path=str(source),
            start_at=start_at,
            enabled=enabled,
        )

        job = self._build_job(entry)

        with self._lock:
            if job_id in self._entries:
                raise ValueError(f"Job already registered: {job_id}")

            self._entries[job_id] = entry
            self._jobs[job_id] = job

        try:
            self.engine.create_job(job)
        except Exception:
            with self._lock:
                self._entries.pop(job_id, None)
                self._jobs.pop(job_id, None)
            raise

        return entry

    schedule = add
    register = add

    # ------------------------------------------------------------------
    # Job construction
    # ------------------------------------------------------------------

    def _build_job(self, entry: ScheduleEntry) -> StreamJob:
        """Build the canonical StreamJob object.

        Scheduler does not own credentials or real destination settings.
        Therefore the destination created here is intentionally unconfigured.
        A higher-level configuration layer can provide configured jobs when
        actual execution is required.
        """

        source = VideoSource(
            name=Path(entry.source_path).name or entry.job_id,
            source_type=SourceType.LOCAL_FILE,
            file_path=entry.source_path,
            id=f"{entry.job_id}_source",
        )

        destination = StreamDestination(
            platform=PlatformType.YOUTUBE,
            name=entry.destination_id,
            stream_url=None,
            stream_key=None,
            enabled=False,
            id=entry.destination_id,
        )

        schedule = StreamSchedule(
            enabled=entry.enabled,
            start_time=entry.start_at,
            repeat=False,
            timezone="UTC",
        )

        job = StreamJob(
            name=entry.job_id,
            source=source,
            destinations=[destination],
            schedule=schedule,
            id=entry.job_id,
        )

        return job

    def _get_job(self, job_id: str) -> Optional[StreamJob]:
        with self._lock:
            return self._jobs.get(job_id)

    # ------------------------------------------------------------------
    # Removal
    # ------------------------------------------------------------------

    def remove(self, job_id: str) -> bool:
        """Remove a scheduler entry and its engine job."""

        with self._lock:
            entry = self._entries.get(job_id)

        if entry is None:
            return False

        try:
            removed = self.engine.remove_job(job_id)
        except Exception:
            removed = False

        with self._lock:
            self._entries.pop(job_id, None)
            self._jobs.pop(job_id, None)

        return removed or True

    unschedule = remove

    def clear(self) -> None:
        """Remove all registered scheduler jobs."""

        for entry in self.list():
            self.remove(entry.job_id)

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get(self, job_id: str) -> Optional[ScheduleEntry]:
        with self._lock:
            return self._entries.get(job_id)

    def list(self) -> List[ScheduleEntry]:
        with self._lock:
            return list(self._entries.values())

    # ------------------------------------------------------------------
    # Preparation
    # ------------------------------------------------------------------

    def prepare(self, job_id: str) -> Dict[str, Any]:
        """Prepare an already registered job.

        Registration and source-file availability are deliberately separate.
        This allows dry-run and architecture tests without requiring an actual
        media file.
        """

        entry = self.get(job_id)

        if entry is None:
            return {
                "ok": False,
                "job_id": job_id,
                "status": "ERROR",
                "reason": "JOB_NOT_FOUND",
            }

        job = self._get_job(job_id)

        if job is None:
            entry.status = ScheduleStatus.ERROR
            entry.last_error = "ENGINE_JOB_NOT_REGISTERED"
            entry.updated_at = datetime.now(timezone.utc)

            return {
                "ok": False,
                "job_id": job_id,
                "status": "ERROR",
                "reason": "ENGINE_JOB_NOT_REGISTERED",
            }

        entry.status = ScheduleStatus.SCHEDULED
        entry.last_error = None
        entry.updated_at = datetime.now(timezone.utc)

        return {
            "ok": True,
            "job_id": job_id,
            "status": "SCHEDULED",
            "engine_job": job,
        }

    # ------------------------------------------------------------------
    # Scheduling
    # ------------------------------------------------------------------

    @staticmethod
    def _is_due(
        start_at: Optional[datetime],
        now: Optional[datetime] = None,
    ) -> bool:
        if start_at is None:
            return True

        current = now or datetime.now(timezone.utc)

        if start_at.tzinfo is None:
            start_at = start_at.replace(tzinfo=timezone.utc)

        return current >= start_at

    def due(
        self,
        now: Optional[datetime] = None,
    ) -> List[ScheduleEntry]:
        return [
            entry
            for entry in self.list()
            if (
                entry.enabled
                and entry.status
                in (
                    ScheduleStatus.STOPPED,
                    ScheduleStatus.SCHEDULED,
                )
                and self._is_due(entry.start_at, now)
            )
        ]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(
        self,
        job_id: str,
        *,
        execute: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Start a scheduled job through StreamingEngine."""

        entry = self.get(job_id)

        if entry is None:
            return {
                "ok": False,
                "job_id": job_id,
                "status": "ERROR",
                "reason": "JOB_NOT_FOUND",
            }

        prepared = self.prepare(job_id)

        if not prepared["ok"]:
            return prepared

        should_execute = not self.dry_run if execute is None else bool(execute)

        if not should_execute:
            return {
                "ok": True,
                "job_id": job_id,
                "status": "SCHEDULED",
                "mode": "DRY_RUN",
                "reason": "EXECUTION_SKIPPED",
            }

        try:
            if not self.engine.is_running:
                self.engine.start()

            result = self.engine.start_job(job_id)

        except Exception as exc:
            entry.status = ScheduleStatus.ERROR
            entry.last_error = str(exc)
            entry.updated_at = datetime.now(timezone.utc)

            return {
                "ok": False,
                "job_id": job_id,
                "status": "ERROR",
                "reason": str(exc),
            }

        entry.status = ScheduleStatus.RUNNING
        entry.last_error = None
        entry.updated_at = datetime.now(timezone.utc)

        return {
            "ok": True,
            "job_id": job_id,
            "status": "RUNNING",
            "mode": "ENGINE",
            "result": result,
        }

    def stop(self, job_id: str) -> Dict[str, Any]:
        entry = self.get(job_id)

        if entry is None:
            return {
                "ok": False,
                "job_id": job_id,
                "status": "ERROR",
                "reason": "JOB_NOT_FOUND",
            }

        if self.dry_run:
            entry.status = ScheduleStatus.STOPPED
            entry.last_error = None
            entry.updated_at = datetime.now(timezone.utc)

            return {
                "ok": True,
                "job_id": job_id,
                "status": "STOPPED",
                "mode": "DRY_RUN",
                "reason": "EXECUTION_SKIPPED",
            }

        try:
            result = self.engine.stop_job(job_id)

        except Exception as exc:
            entry.last_error = str(exc)
            entry.updated_at = datetime.now(timezone.utc)

            return {
                "ok": False,
                "job_id": job_id,
                "status": entry.status.value,
                "reason": str(exc),
            }

        entry.status = ScheduleStatus.STOPPED
        entry.last_error = None
        entry.updated_at = datetime.now(timezone.utc)

        return {
            "ok": True,
            "job_id": job_id,
            "status": "STOPPED",
            "result": result,
        }

    def pause(self, job_id: str) -> Dict[str, Any]:
        return self._delegate_lifecycle(
            job_id,
            "pause_job",
            ScheduleStatus.PAUSED,
        )

    def resume(self, job_id: str) -> Dict[str, Any]:
        return self._delegate_lifecycle(
            job_id,
            "resume_job",
            ScheduleStatus.RUNNING,
        )

    def restart(self, job_id: str) -> Dict[str, Any]:
        entry = self.get(job_id)

        if entry is None:
            return {
                "ok": False,
                "job_id": job_id,
                "status": "ERROR",
                "reason": "JOB_NOT_FOUND",
            }

        if self.dry_run:
            return {
                "ok": True,
                "job_id": job_id,
                "status": "SCHEDULED",
                "mode": "DRY_RUN",
                "reason": "EXECUTION_SKIPPED",
            }

        try:
            if not self.engine.is_running:
                self.engine.start()

            result = self.engine.restart_job(job_id)

        except Exception as exc:
            entry.status = ScheduleStatus.ERROR
            entry.last_error = str(exc)
            entry.updated_at = datetime.now(timezone.utc)

            return {
                "ok": False,
                "job_id": job_id,
                "status": "ERROR",
                "reason": str(exc),
            }

        entry.status = ScheduleStatus.RUNNING
        entry.last_error = None
        entry.updated_at = datetime.now(timezone.utc)

        return {
            "ok": True,
            "job_id": job_id,
            "status": "RUNNING",
            "result": result,
        }

    def _delegate_lifecycle(
        self,
        job_id: str,
        method: str,
        status: ScheduleStatus,
    ) -> Dict[str, Any]:
        entry = self.get(job_id)

        if entry is None:
            return {
                "ok": False,
                "job_id": job_id,
                "status": "ERROR",
                "reason": "JOB_NOT_FOUND",
            }

        if self.dry_run:
            entry.status = status
            entry.last_error = None
            entry.updated_at = datetime.now(timezone.utc)

            return {
                "ok": True,
                "job_id": job_id,
                "status": status.value,
                "mode": "DRY_RUN",
                "reason": "EXECUTION_SKIPPED",
            }

        fn = getattr(self.engine, method, None)

        if not callable(fn):
            return {
                "ok": False,
                "job_id": job_id,
                "status": entry.status.value,
                "reason": f"ENGINE_METHOD_MISSING:{method}",
            }

        try:
            result = fn(job_id)

        except Exception as exc:
            entry.last_error = str(exc)
            entry.updated_at = datetime.now(timezone.utc)

            return {
                "ok": False,
                "job_id": job_id,
                "status": entry.status.value,
                "reason": str(exc),
            }

        entry.status = status
        entry.last_error = None
        entry.updated_at = datetime.now(timezone.utc)

        return {
            "ok": True,
            "job_id": job_id,
            "status": status.value,
            "result": result,
        }

    # ------------------------------------------------------------------
    # Due jobs
    # ------------------------------------------------------------------

    def start_due(
        self,
        now: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        return [
            self.start(entry.job_id)
            for entry in self.due(now)
        ]

    # ------------------------------------------------------------------
    # Stop all
    # ------------------------------------------------------------------

    def stop_all(self) -> Dict[str, Any]:
        if self.dry_run:
            for entry in self.list():
                entry.status = ScheduleStatus.STOPPED
                entry.last_error = None
                entry.updated_at = datetime.now(timezone.utc)

            return {
                "ok": True,
                "mode": "DRY_RUN",
                "reason": "EXECUTION_SKIPPED",
            }

        try:
            result = self.engine.stop_all()

        except Exception as exc:
            return {
                "ok": False,
                "status": "ERROR",
                "reason": str(exc),
            }

        for entry in self.list():
            entry.status = ScheduleStatus.STOPPED
            entry.last_error = None
            entry.updated_at = datetime.now(timezone.utc)

        return {
            "ok": True,
            "result": result,
        }

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(
        self,
        job_id: Optional[str] = None,
    ) -> Any:
        if job_id is not None:
            entry = self.get(job_id)

            if entry is None:
                return {
                    "ok": False,
                    "job_id": job_id,
                    "reason": "JOB_NOT_FOUND",
                }

            engine_status = None

            fn = getattr(self.engine, "get_status", None)

            if callable(fn):
                try:
                    engine_status = fn(job_id)
                except Exception:
                    engine_status = None

            return {
                "ok": True,
                "job_id": job_id,
                "scheduler_status": entry.status.value,
                "destination_id": entry.destination_id,
                "source_path": entry.source_path,
                "enabled": entry.enabled,
                "start_at": (
                    entry.start_at.isoformat()
                    if entry.start_at
                    else None
                ),
                "last_error": entry.last_error,
                "engine_status": engine_status,
            }

        return {
            entry.job_id: self.status(entry.job_id)
            for entry in self.list()
        }

    def is_running(self, job_id: str) -> bool:
        state = self.status(job_id)

        return (
            isinstance(state, dict)
            and state.get("scheduler_status") == "RUNNING"
        )

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        fn = getattr(self.engine, "shutdown", None)

        if callable(fn):
            fn()


# ----------------------------------------------------------------------
# Safe integration test
# ----------------------------------------------------------------------

def _safe_test() -> int:
    print("=" * 72)
    print("STREAM SCHEDULER v1.0 ENGINE INTEGRATION TEST")
    print("=" * 72)

    scheduler = StreamScheduler(
        root=Path.cwd(),
        dry_run=True,
    )

    source = (
        Path.cwd()
        / "cache"
        / "scheduler_test.mp4"
    )

    entry = scheduler.add(
        job_id="scheduler_test_01",
        destination_id="youtube_01",
        source_path=source,
    )

    print("registered:", scheduler.get("scheduler_test_01") is not None)
    print("engine job:", scheduler._get_job("scheduler_test_01") is not None)
    print("job id:", entry.job_id)
    print("dry_run:", scheduler.dry_run)

    prepared = scheduler.prepare("scheduler_test_01")

    print(
        "prepare:",
        prepared["ok"],
        prepared.get("status"),
    )

    result = scheduler.start("scheduler_test_01")

    print(
        "start:",
        result["ok"],
        result.get("reason"),
    )

    print(
        "scheduler status:",
        scheduler.status("scheduler_test_01")["scheduler_status"],
    )

    print("No real RTMP streaming was started.")
    print("=" * 72)

    return 0


if __name__ == "__main__":
    raise SystemExit(_safe_test())