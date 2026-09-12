"""
Professional Cloud Live Streaming Software
Streaming Engine
Version: 1.0.0
"""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Dict, List, Optional

from models import (
    StreamJob,
    StreamInstance,
    StreamStatus,
)

from workers.ffmpeg_worker import (
    FFmpegConfig,
    FFmpegWorker,
)


class StreamingEngine:
    """
    Central controller for all streaming jobs.

    Responsibilities:
        - Create jobs
        - Start jobs
        - Stop jobs
        - Pause jobs
        - Resume jobs
        - Restart jobs
        - Track running instances
        - Manage multiple FFmpeg workers
        - Provide runtime status
        - Cleanup workers
    """

    def __init__(self) -> None:
        self._jobs: Dict[str, StreamJob] = {}
        self._instances: Dict[str, StreamInstance] = {}
        self._workers: Dict[str, FFmpegWorker] = {}

        self._lock = threading.RLock()

        self._running = False

    # ========================================================
    # ENGINE LIFECYCLE
    # ========================================================

    def start(self) -> None:
        """
        Start the streaming engine.
        """

        with self._lock:
            if self._running:
                return

            self._running = True

    def shutdown(self) -> None:
        """
        Shutdown the engine and stop all streams.
        """

        with self._lock:
            if not self._running:
                return

            self.stop_all()

            self._running = False

    @property
    def is_running(self) -> bool:
        """
        Return whether the engine is running.
        """

        with self._lock:
            return self._running

    # ========================================================
    # JOB MANAGEMENT
    # ========================================================

    def create_job(self, job: StreamJob) -> str:
        """
        Register a new StreamJob.

        Returns:
            Job ID
        """

        with self._lock:
            if job.id in self._jobs:
                raise ValueError(
                    f"Stream job already exists: {job.id}"
                )

            self._jobs[job.id] = job

            return job.id

    def remove_job(self, job_id: str) -> bool:
        """
        Remove a stream job.

        A running job must be stopped first.
        """

        with self._lock:
            job = self._jobs.get(job_id)

            if job is None:
                return False

            if job.status in {
                StreamStatus.STARTING,
                StreamStatus.LIVE,
                StreamStatus.RECONNECTING,
                StreamStatus.PAUSED,
                StreamStatus.STOPPING,
            }:
                raise RuntimeError(
                    "Cannot remove a running stream job. "
                    "Stop it first."
                )

            # Defensive worker cleanup.
            self._cleanup_job_workers(job)

            del self._jobs[job_id]

            return True

    def get_job(
        self,
        job_id: str,
    ) -> Optional[StreamJob]:
        """
        Return a job by ID.
        """

        with self._lock:
            return self._jobs.get(job_id)

    def list_jobs(self) -> List[StreamJob]:
        """
        Return all registered jobs.
        """

        with self._lock:
            return list(self._jobs.values())

    # ========================================================
    # START
    # ========================================================

    def start_job(
        self,
        job_id: str,
    ) -> StreamInstance:
        """
        Start a streaming job.

        One FFmpegWorker is created for every enabled
        destination.

        The authoritative worker list is stored in
        StreamJob.worker_ids.
        """

        with self._lock:

            job = self._jobs.get(job_id)

            if job is None:
                raise KeyError(
                    f"Stream job not found: {job_id}"
                )

            if not self._running:
                raise RuntimeError(
                    "Streaming engine is not running."
                )

            if not job.can_start():
                raise RuntimeError(
                    "Stream job is not correctly configured."
                )

            if job.status in {
                StreamStatus.STARTING,
                StreamStatus.LIVE,
                StreamStatus.RECONNECTING,
                StreamStatus.PAUSED,
                StreamStatus.STOPPING,
            }:
                raise RuntimeError(
                    f"Stream job is already running: {job_id}"
                )

            source_path = job.source.file_path

            if not source_path:
                message = (
                    "Stream source file path is missing."
                )

                job.mark_error(message)

                instance = StreamInstance(
                    job_id=job.id,
                    status=StreamStatus.ERROR,
                    error_message=message,
                )

                self._instances[instance.id] = instance

                return instance

            # Remove stale workers from an older run.
            self._cleanup_job_workers(job)

            job.worker_ids.clear()

            job.status = StreamStatus.STARTING
            job.started_at = datetime.utcnow()
            job.stopped_at = None
            job.error_message = None

            instance = StreamInstance(
                job_id=job.id,
                status=StreamStatus.STARTING,
                started_at=job.started_at,
            )

            self._instances[instance.id] = instance

            started_workers: List[FFmpegWorker] = []

            try:

                for destination in job.enabled_destinations():

                    if not destination.is_configured():
                        continue

                    worker_id = (
                        f"{job.id}:{destination.id}"
                    )

                    output_url = (
                        destination.stream_url.rstrip("/")
                        + "/"
                        + destination.stream_key
                    )

                    worker = FFmpegWorker(
                        worker_id=worker_id,
                        input_source=source_path,
                        output_url=output_url,
                        config=FFmpegConfig(
                            extra_args=(
                                job.video_settings.extra_options
                            )
                        ),
                    )

                    self._workers[worker_id] = worker

                    worker.start()

                    if not worker.is_running:
                        raise RuntimeError(
                            "FFmpeg worker failed to start: "
                            f"{worker_id}"
                        )

                    job.worker_ids.append(worker_id)
                    started_workers.append(worker)

                    # StreamInstance currently exposes one
                    # worker_id. StreamJob.worker_ids contains
                    # the complete worker collection.
                    if instance.worker_id is None:
                        instance.worker_id = worker_id

                    if instance.process_id is None:
                        instance.process_id = (
                            worker.process_id
                        )

                if not started_workers:
                    raise RuntimeError(
                        "No enabled destinations were started."
                    )

                job.mark_started()

                instance.status = StreamStatus.LIVE
                instance.started_at = job.started_at

                return instance

            except Exception as exc:

                message = str(exc)

                # Stop workers that successfully started.
                for worker in started_workers:
                    try:
                        worker.stop()
                    except Exception:
                        pass

                # Remove all workers belonging to this job.
                for worker_id in list(job.worker_ids):
                    self._workers.pop(
                        worker_id,
                        None,
                    )

                job.worker_ids.clear()

                job.mark_error(message)

                instance.status = StreamStatus.ERROR
                instance.error_message = message

                return instance

    # ========================================================
    # STOP
    # ========================================================

    def stop_job(
        self,
        job_id: str,
    ) -> bool:
        """
        Stop all FFmpeg workers belonging to a job.
        """

        with self._lock:

            job = self._jobs.get(job_id)

            if job is None:
                return False

            if job.status in {
                StreamStatus.CREATED,
                StreamStatus.STOPPED,
                StreamStatus.ERROR,
            }:
                # Still perform defensive cleanup.
                self._cleanup_job_workers(job)
                return False

            job.status = StreamStatus.STOPPING

            instance = self._find_instance_by_job(
                job_id
            )

            if instance:
                instance.status = StreamStatus.STOPPING

            worker_ids = list(job.worker_ids)

            stop_errors: List[str] = []

            for worker_id in worker_ids:

                worker = self._workers.get(worker_id)

                if worker is None:
                    continue

                try:
                    worker.stop()

                except Exception as exc:
                    stop_errors.append(str(exc))

            # Always remove workers from registry.
            for worker_id in worker_ids:
                self._workers.pop(
                    worker_id,
                    None,
                )

            job.worker_ids.clear()

            if stop_errors:
                message = (
                    "One or more workers failed to stop: "
                    + "; ".join(stop_errors)
                )

                job.mark_error(message)

                if instance:
                    instance.status = StreamStatus.ERROR
                    instance.error_message = message

                return False

            job.mark_stopped()

            if instance:
                instance.status = StreamStatus.STOPPED

            return True

    # ========================================================
    # PAUSE
    # ========================================================

    def pause_job(
        self,
        job_id: str,
    ) -> bool:
        """
        Pause a streaming job at the engine state level.

        FFmpegWorker currently has no native pause API,
        therefore this does not pretend to pause the
        underlying FFmpeg process.
        """

        with self._lock:

            job = self._jobs.get(job_id)

            if job is None:
                return False

            if job.status not in {
                StreamStatus.LIVE,
                StreamStatus.STARTING,
            }:
                return False

            job.status = StreamStatus.PAUSED

            instance = self._find_instance_by_job(
                job_id
            )

            if instance:
                instance.status = StreamStatus.PAUSED

            return True

    # ========================================================
    # RESUME
    # ========================================================

    def resume_job(
        self,
        job_id: str,
    ) -> bool:
        """
        Resume a paused streaming job at the engine
        state level.
        """

        with self._lock:

            job = self._jobs.get(job_id)

            if job is None:
                return False

            if job.status != StreamStatus.PAUSED:
                return False

            job.status = StreamStatus.LIVE

            instance = self._find_instance_by_job(
                job_id
            )

            if instance:
                instance.status = StreamStatus.LIVE

            return True

    # ========================================================
    # RESTART
    # ========================================================

    def restart_job(
        self,
        job_id: str,
    ) -> StreamInstance:
        """
        Stop and start a streaming job again.
        """

        with self._lock:

            job = self._jobs.get(job_id)

            if job is None:
                raise KeyError(
                    f"Stream job not found: {job_id}"
                )

            # Stop existing workers if necessary.
            if job.status not in {
                StreamStatus.CREATED,
                StreamStatus.STOPPED,
                StreamStatus.ERROR,
            }:
                self.stop_job(job_id)
            else:
                self._cleanup_job_workers(job)

            return self.start_job(job_id)

    # ========================================================
    # STOP ALL
    # ========================================================

    def stop_all(self) -> None:
        """
        Stop every active streaming job.
        """

        with self._lock:

            job_ids = [
                job.id
                for job in self._jobs.values()
                if job.status not in {
                    StreamStatus.CREATED,
                    StreamStatus.STOPPED,
                    StreamStatus.ERROR,
                }
            ]

            for job_id in job_ids:
                try:
                    self.stop_job(job_id)
                except Exception:
                    continue

            # Defensive cleanup for orphaned workers.
            orphaned_workers = list(
                self._workers.items()
            )

            for worker_id, worker in orphaned_workers:
                try:
                    worker.stop()
                except Exception:
                    pass

                self._workers.pop(
                    worker_id,
                    None,
                )

    # ========================================================
    # STATUS
    # ========================================================

    def get_status(
        self,
        job_id: str,
    ) -> Optional[dict]:
        """
        Return runtime status for one job.
        """

        with self._lock:

            job = self._jobs.get(job_id)

            if job is None:
                return None

            instance = self._find_instance_by_job(
                job_id
            )

            workers = []
            primary_metrics = None

            for worker_id in job.worker_ids:

                worker = self._workers.get(worker_id)

                if worker is None:
                    continue

                metrics = worker.metrics

                worker_metrics = {
                    "uptime_seconds": metrics.uptime_seconds,
                    "video_frames": metrics.video_frames,
                    "dropped_frames": metrics.dropped_frames,
                    "bitrate_kbps": metrics.bitrate_kbps,
                    "fps": metrics.fps,
                    "reconnect_count": metrics.reconnect_count,
                    "cpu_percent": metrics.cpu_percent,
                    "memory_percent": metrics.memory_percent,
                    "last_update": (
                        metrics.last_update.isoformat()
                        if metrics.last_update
                        else None
                    ),
                }

                workers.append(
                    {
                        "worker_id": worker_id,
                        "status": worker.status.value,
                        "process_id": worker.process_id,
                        "running": worker.is_running,
                        "metrics": worker_metrics,
                    }
                )

                if primary_metrics is None:
                    primary_metrics = worker_metrics

                    if instance is not None:
                        instance.metrics.uptime_seconds = metrics.uptime_seconds
                        instance.metrics.video_frames = metrics.video_frames
                        instance.metrics.dropped_frames = metrics.dropped_frames
                        instance.metrics.bitrate_kbps = metrics.bitrate_kbps
                        instance.metrics.fps = metrics.fps
                        instance.metrics.reconnect_count = metrics.reconnect_count
                        instance.metrics.cpu_percent = metrics.cpu_percent
                        instance.metrics.memory_percent = metrics.memory_percent
                        instance.metrics.last_update = metrics.last_update

            return {
                "job_id": job.id,
                "name": job.name,
                "status": job.status.value,
                "source": job.source.name,

                "destinations": [
                    {
                        "platform": destination.platform.value,
                        "name": destination.name,
                        "enabled": destination.enabled,
                    }
                    for destination in job.destinations
                ],

                "worker_ids": list(
                    job.worker_ids
                ),

                "workers": workers,

                "instance_id": (
                    instance.id
                    if instance
                    else None
                ),

                "process_id": (
                    instance.process_id
                    if instance
                    else None
                ),

                "worker_id": (
                    instance.worker_id
                    if instance
                    else None
                ),

                "metrics": primary_metrics,

                "started_at": (
                    instance.started_at.isoformat()
                    if instance
                    and instance.started_at
                    else None
                ),

                "error_message": (
                    instance.error_message
                    if instance
                    else job.error_message
                ),
            }

    def get_all_status(self) -> List[dict]:
        """
        Return status for every registered job.
        """

        with self._lock:

            return [
                self.get_status(job.id)
                for job in self._jobs.values()
            ]

    # ========================================================
    # INTERNAL HELPERS
    # ========================================================

    def _find_instance_by_job(
        self,
        job_id: str,
    ) -> Optional[StreamInstance]:
        """
        Find the latest runtime instance for a job.
        """

        matches = [
            instance
            for instance in self._instances.values()
            if instance.job_id == job_id
        ]

        if not matches:
            return None

        return max(
            matches,
            key=lambda instance: (
                instance.started_at
                or datetime.min
            ),
        )

    def _cleanup_job_workers(
        self,
        job: StreamJob,
    ) -> None:
        """
        Stop and remove all workers belonging to a job.
        """

        worker_ids = set(job.worker_ids)

        # Also detect workers by job-id prefix.
        prefix = f"{job.id}:"

        for worker_id in list(self._workers.keys()):
            if worker_id.startswith(prefix):
                worker_ids.add(worker_id)

        for worker_id in worker_ids:

            worker = self._workers.get(worker_id)

            if worker is not None:
                try:
                    if worker.is_running:
                        worker.stop()
                except Exception:
                    pass

            self._workers.pop(
                worker_id,
                None,
            )

        job.worker_ids.clear()

    def _remove_instance(
        self,
        instance_id: str,
    ) -> None:
        """
        Remove a runtime instance.
        """

        self._instances.pop(
            instance_id,
            None,
        )