
"""
Golden Streaming Engine
File    : streaming_controller.py
Version : 3.0.0 FINAL

Purpose
-------
Central supervisor for independent 24x7 streaming destinations.

Architecture
------------
ConfigManager
      ↓
PlaylistManager
      ↓
StreamingController
      ↓
7 Independent Destination Supervisors
      ↓
FFmpegWorker
      ↓
YouTube / Facebook / Instagram

Rules
-----
1. One destination = one independent supervisor.
2. One destination failure must not stop another destination.
3. Playlist items are played sequentially.
4. Normal EOF advances to the next video.
5. Last video loops back to the first video.
6. Unexpected FFmpeg failure retries the same video.
7. Stream keys are never exposed in status/log output.
"""

from __future__ import annotations

import logging
import threading
import time

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from config_manager import ConfigManager
from models import (
    LoopMode,
    SourceType,
    StreamDestination,
    StreamJob,
    VideoSource,
)

from playlist_manager import PlaylistManager, PlaylistItem

from workers.ffmpeg_worker import (
    FFmpegConfig,
    FFmpegWorker,
    FFmpegResult,
)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOGGER = logging.getLogger("streaming_controller")


# ---------------------------------------------------------------------------
# Runtime configuration
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent
CACHE_ROOT = PROJECT_ROOT / "cache"

DEFAULT_RECONNECT_DELAY = 5.0
MAX_RECONNECT_DELAY = 60.0

# Maximum number of consecutive unexpected failures before the delay is
# capped. The supervisor itself continues retrying because this is intended
# for 24x7 operation.
MAX_CONSECUTIVE_FAILURES = 10


# ---------------------------------------------------------------------------
# Destination Runtime
# ---------------------------------------------------------------------------

@dataclass
class DestinationRuntime:
    """
    Runtime state for exactly one destination.
    """

    destination_id: str

    destination: Dict[str, Any]

    worker: Optional[FFmpegWorker] = None

    supervisor_thread: Optional[threading.Thread] = None

    stop_event: threading.Event = field(
        default_factory=threading.Event
    )

    exit_event: threading.Event = field(
        default_factory=threading.Event
    )

    lock: threading.RLock = field(
        default_factory=threading.RLock
    )

    running: bool = False

    state: str = "STOPPED"

    current_video: Optional[str] = None

    current_path: Optional[str] = None

    started_at: Optional[float] = None

    current_started_at: Optional[float] = None

    last_exit_code: Optional[int] = None

    last_error: Optional[str] = None

    last_message: Optional[str] = None

    reconnect_count: int = 0

    consecutive_failures: int = 0

    transition_count: int = 0


# ---------------------------------------------------------------------------
# Streaming Controller
# ---------------------------------------------------------------------------

class StreamingController:
    """
    Final central controller.

    Each destination receives its own supervisor thread and FFmpeg worker.
    """

    def __init__(
        self,
        reconnect_delay: float = DEFAULT_RECONNECT_DELAY,
        max_reconnect_delay: float = MAX_RECONNECT_DELAY,
    ):
        self.config_manager = ConfigManager()

        self.playlist_manager = PlaylistManager()

        self.destinations: Dict[str, Dict[str, Any]] = {}

        self.runtimes: Dict[str, DestinationRuntime] = {}

        self.reconnect_delay = max(
            1.0,
            float(reconnect_delay),
        )

        self.max_reconnect_delay = max(
            self.reconnect_delay,
            float(max_reconnect_delay),
        )

        self._controller_lock = threading.RLock()

        self._loaded = False

        LOGGER.info("StreamingController initialized")

    # -----------------------------------------------------------------------
    # Load
    # -----------------------------------------------------------------------

    def load(self) -> Dict[str, Any]:
        """
        Load destinations and local playlists.
        """

        with self._controller_lock:

            LOGGER.info("Loading streaming configuration")

            loaded_destinations = (
                self.config_manager.get_destinations()
            )

            self.destinations.clear()
            self.runtimes.clear()

            for destination in loaded_destinations:

                destination_id = str(
                    destination["id"]
                )

                self.destinations[destination_id] = destination

                runtime = DestinationRuntime(
                    destination_id=destination_id,
                    destination=destination,
                )

                self.runtimes[destination_id] = runtime

                playlist_folder = (
                    CACHE_ROOT / destination_id
                )

                try:

                    playlist = (
                        self.playlist_manager.load_from_folder(
                            destination_id,
                            playlist_folder,
                        )
                    )

                    LOGGER.info(
                        "Playlist loaded: %s (%d videos)",
                        destination_id,
                        len(playlist.items),
                    )

                except Exception as exc:

                    runtime.state = "ERROR"
                    runtime.last_error = str(exc)

                    LOGGER.error(
                        "Playlist load failed for %s: %s",
                        destination_id,
                        exc,
                    )

            self._loaded = True

            LOGGER.info(
                "Configuration loaded: %d destinations",
                len(self.destinations),
            )

            return self.all_status()

    # -----------------------------------------------------------------------
    # Ensure loaded
    # -----------------------------------------------------------------------

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()

    # -----------------------------------------------------------------------
    # Destination helpers
    # -----------------------------------------------------------------------

    def get_destination(
        self,
        destination_id: str,
    ) -> Optional[Dict[str, Any]]:

        self._ensure_loaded()

        return self.destinations.get(destination_id)

    # -----------------------------------------------------------------------
    # Validation
    # -----------------------------------------------------------------------

    def validate(
        self,
        destination_id: str,
    ) -> Dict[str, Any]:
        """
        Validate one destination before starting.
        """

        self._ensure_loaded()

        destination = self.destinations.get(
            destination_id
        )

        if destination is None:

            return {
                "valid": False,
                "destination_id": destination_id,
                "error": "Destination not found",
            }

        if not bool(destination.get("enabled", False)):

            return {
                "valid": False,
                "destination_id": destination_id,
                "error": "Destination is disabled",
            }

        playlist = self.playlist_manager.get_playlist(
            destination_id
        )

        if playlist is None:

            return {
                "valid": False,
                "destination_id": destination_id,
                "error": "Playlist not loaded",
            }

        if not playlist.items:

            return {
                "valid": False,
                "destination_id": destination_id,
                "error": "Playlist is empty",
            }

        rtmp_url = str(
            destination.get("rtmp_url", "")
        ).strip()

        stream_key = str(
            destination.get("stream_key", "")
        ).strip()

        if not rtmp_url:

            return {
                "valid": False,
                "destination_id": destination_id,
                "error": "RTMP URL is empty",
            }

        if not stream_key:

            return {
                "valid": False,
                "destination_id": destination_id,
                "error": "Stream key is empty",
            }

        current = self.playlist_manager.current(
            destination_id
        )

        if current is None:

            return {
                "valid": False,
                "destination_id": destination_id,
                "error": "No current playlist item",
            }

        current_path = Path(
            current.path
        )

        if not current_path.exists():

            return {
                "valid": False,
                "destination_id": destination_id,
                "error": (
                    f"Video file does not exist: "
                    f"{current_path}"
                ),
            }

        if current_path.stat().st_size <= 0:

            return {
                "valid": False,
                "destination_id": destination_id,
                "error": (
                    f"Video file is empty: "
                    f"{current_path}"
                ),
            }

        return {
            "valid": True,
            "destination_id": destination_id,
            "video": current.name,
            "playlist_count": len(playlist.items),
        }

    # -----------------------------------------------------------------------
    # Build destination object
    # -----------------------------------------------------------------------

    def _build_destination(
        self,
        destination_id: str,
    ) -> StreamDestination:

        destination = self.destinations[
            destination_id
        ]

        return StreamDestination(
            id=destination_id,
            name=str(
                destination.get(
                    "name",
                    destination_id,
                )
            ),
            platform=destination.get(
                "platform"
            ),
            stream_url=str(
                destination.get(
                    "rtmp_url",
                    "",
                )
            ).strip(),
            stream_key=str(
                destination.get(
                    "stream_key",
                    "",
                )
            ).strip(),
            enabled=bool(
                destination.get(
                    "enabled",
                    False,
                )
            ),
        )

    # -----------------------------------------------------------------------
    # Build video source
    # -----------------------------------------------------------------------

    def _build_video_source(
        self,
        item: PlaylistItem,
    ) -> VideoSource:

        return VideoSource(
            type=SourceType.LOCAL_FILE,
            file_path=str(item.path),
            title=item.name,
        )

    # -----------------------------------------------------------------------
    # Build job
    # -----------------------------------------------------------------------

    def _build_job(
        self,
        destination_id: str,
        item: PlaylistItem,
    ) -> StreamJob:

        destination = self._build_destination(
            destination_id
        )

        source = self._build_video_source(
            item
        )

        return StreamJob(
            id=f"live:{destination_id}",
            name=f"Live Stream - {destination.name}",
            destination=destination,
            source=source,
            loop_mode=LoopMode.ONE,
        )

    # -----------------------------------------------------------------------
    # FFmpeg configuration
    # -----------------------------------------------------------------------

    def _build_worker_config(
        self,
        destination_id: str,
        item: PlaylistItem,
    ) -> FFmpegConfig:

        destination = self.destinations[
            destination_id
        ]

        rtmp_url = str(
            destination.get(
                "rtmp_url",
                "",
            )
        ).strip()

        stream_key = str(
            destination.get(
                "stream_key",
                "",
            )
        ).strip()

        output_url = (
            rtmp_url.rstrip("/")
            + "/"
            + stream_key
        )

        return FFmpegConfig(
            input_path=str(item.path),
            output_url=output_url,
        )

    # -----------------------------------------------------------------------
    # Worker callback
    # -----------------------------------------------------------------------

    def _on_worker_exit(
        self,
        destination_id: str,
        result: FFmpegResult,
    ) -> None:
        """
        Called by FFmpegWorker when the process exits.

        Important:
        Do not start another worker from this callback.

        The callback only records the result and wakes the destination
        supervisor thread.
        """

        runtime = self.runtimes.get(
            destination_id
        )

        if runtime is None:
            return

        with runtime.lock:

            runtime.last_exit_code = (
                result.return_code
            )

            runtime.last_message = (
                getattr(
                    result,
                    "message",
                    None,
                )
            )

            if result.normal_exit:

                runtime.state = "EOF"

            else:

                runtime.state = "FAILED"

                runtime.last_error = (
                    runtime.last_message
                    or
                    f"FFmpeg exited with code "
                    f"{result.return_code}"
                )

        runtime.exit_event.set()

    # -----------------------------------------------------------------------
    # Worker callback - status
    # -----------------------------------------------------------------------

    def _on_worker_status(
        self,
        destination_id: str,
        status: Any,
    ) -> None:

        runtime = self.runtimes.get(
            destination_id
        )

        if runtime is None:
            return

        with runtime.lock:

            runtime.last_message = str(
                status
            )

    # -----------------------------------------------------------------------
    # Create worker
    # -----------------------------------------------------------------------

    def _create_worker(
        self,
        destination_id: str,
        item: PlaylistItem,
    ) -> FFmpegWorker:

        config = self._build_worker_config(
            destination_id,
            item,
        )

        worker = FFmpegWorker(
            config=config,
            on_exit=lambda result: (
                self._on_worker_exit(
                    destination_id,
                    result,
                )
            ),
            on_status=lambda status: (
                self._on_worker_status(
                    destination_id,
                    status,
                )
            ),
        )

        return worker

    # -----------------------------------------------------------------------
    # Start one concrete video
    # -----------------------------------------------------------------------

    def _start_video(
        self,
        destination_id: str,
        item: PlaylistItem,
    ) -> bool:

        runtime = self.runtimes[
            destination_id
        ]

        worker = self._create_worker(
            destination_id,
            item,
        )

        with runtime.lock:

            runtime.worker = worker

            runtime.current_video = item.name

            runtime.current_path = str(
                item.path
            )

            runtime.current_started_at = time.time()

            runtime.state = "STARTING"

            runtime.exit_event.clear()

        try:

            result = worker.start()

            if not result.success:

                with runtime.lock:

                    runtime.state = "FAILED"

                    runtime.last_error = (
                        result.message
                        or "FFmpeg failed to start"
                    )

                return False

            with runtime.lock:

                runtime.running = True

                runtime.state = "RUNNING"

                if runtime.started_at is None:
                    runtime.started_at = time.time()

            LOGGER.info(
                "[%s] Streaming: %s",
                destination_id,
                item.name,
            )

            return True

        except Exception as exc:

            with runtime.lock:

                runtime.state = "FAILED"

                runtime.running = False

                runtime.last_error = str(exc)

            LOGGER.exception(
                "[%s] Worker start failed",
                destination_id,
            )

            return False

    # -----------------------------------------------------------------------
    # Supervisor
    # -----------------------------------------------------------------------

    def _supervisor(
        self,
        destination_id: str,
    ) -> None:
        """
        Independent 24x7 supervisor for one destination.
        """

        runtime = self.runtimes[
            destination_id
        ]

        LOGGER.info(
            "[%s] Supervisor started",
            destination_id,
        )

        while not runtime.stop_event.is_set():

            # ---------------------------------------------------------------
            # Refresh playlist
            # ---------------------------------------------------------------

            try:

                folder = (
                    CACHE_ROOT / destination_id
                )

                self.playlist_manager.refresh(
                    destination_id,
                    folder,
                )

            except Exception as exc:

                with runtime.lock:

                    runtime.last_error = str(exc)

                LOGGER.error(
                    "[%s] Playlist refresh failed: %s",
                    destination_id,
                    exc,
                )

            # ---------------------------------------------------------------
            # Get current playlist item
            # ---------------------------------------------------------------

            item = self.playlist_manager.current_item(
                destination_id
            )

            if item is None:

                with runtime.lock:

                    runtime.running = False

                    runtime.state = "NO_VIDEO"

                    runtime.last_error = (
                        "Playlist contains no valid video"
                    )

                runtime.stop_event.wait(
                    self.reconnect_delay
                )

                continue

            # ---------------------------------------------------------------
            # Validate current video
            # ---------------------------------------------------------------

            current_path = Path(
                item.path
            )

            if (
                not current_path.exists()
                or
                current_path.stat().st_size <= 0
            ):

                with runtime.lock:

                    runtime.state = "VIDEO_ERROR"

                    runtime.last_error = (
                        f"Video unavailable: "
                        f"{current_path}"
                    )

                LOGGER.error(
                    "[%s] Video unavailable: %s",
                    destination_id,
                    current_path,
                )

                # Skip invalid item.
                next_item = (
                    self.playlist_manager.advance(
                        destination_id,
                        loop=True,
                    )
                )

                if next_item is None:
                    runtime.stop_event.wait(
                        self.reconnect_delay
                    )

                continue

            # ---------------------------------------------------------------
            # Start video
            # ---------------------------------------------------------------

            started = self._start_video(
                destination_id,
                item,
            )

            if not started:

                with runtime.lock:

                    runtime.running = False

                    runtime.consecutive_failures += 1

                    runtime.reconnect_count += 1

                delay = self._calculate_retry_delay(
                    runtime.consecutive_failures
                )

                LOGGER.warning(
                    "[%s] FFmpeg start failed. "
                    "Retrying in %.1f seconds.",
                    destination_id,
                    delay,
                )

                runtime.stop_event.wait(
                    delay
                )

                continue

            # ---------------------------------------------------------------
            # Wait for FFmpeg exit or stop
            # ---------------------------------------------------------------

            while (
                not runtime.stop_event.is_set()
            ):

                if runtime.exit_event.wait(
                    timeout=1.0
                ):

                    break

            # ---------------------------------------------------------------
            # User requested stop
            # ---------------------------------------------------------------

            if runtime.stop_event.is_set():

                self._stop_worker_safely(
                    runtime
                )

                break

            # ---------------------------------------------------------------
            # FFmpeg exited
            # ---------------------------------------------------------------

            with runtime.lock:

                runtime.running = False

                exit_code = (
                    runtime.last_exit_code
                )

                state = runtime.state

            # ---------------------------------------------------------------
            # Normal EOF
            # ---------------------------------------------------------------

            if state == "EOF" and exit_code == 0:

                with runtime.lock:

                    runtime.consecutive_failures = 0

                    runtime.transition_count += 1

                next_item = (
                    self.playlist_manager.advance(
                        destination_id,
                        loop=True,
                    )
                )

                if next_item is None:

                    with runtime.lock:

                        runtime.state = "NO_VIDEO"

                        runtime.last_error = (
                            "Playlist ended unexpectedly"
                        )

                    runtime.stop_event.wait(
                        self.reconnect_delay
                    )

                    continue

                LOGGER.info(
                    "[%s] EOF → next video: %s",
                    destination_id,
                    next_item.name,
                )

                # Immediately continue with next item.
                continue

            # ---------------------------------------------------------------
            # Unexpected FFmpeg failure
            # ---------------------------------------------------------------

            with runtime.lock:

                runtime.consecutive_failures += 1

                runtime.reconnect_count += 1

                failures = (
                    runtime.consecutive_failures
                )

            delay = self._calculate_retry_delay(
                failures
            )

            LOGGER.warning(
                "[%s] FFmpeg stopped unexpectedly "
                "(code=%s). Retry #%d in %.1f sec.",
                destination_id,
                exit_code,
                runtime.reconnect_count,
                delay,
            )

            runtime.stop_event.wait(
                delay
            )

            # Same playlist item is retried.
            continue

        # -------------------------------------------------------------------
        # Supervisor shutdown
        # -------------------------------------------------------------------

        self._stop_worker_safely(
            runtime
        )

        with runtime.lock:

            runtime.running = False

            runtime.state = "STOPPED"

            runtime.worker = None

        LOGGER.info(
            "[%s] Supervisor stopped",
            destination_id,
        )

    # -----------------------------------------------------------------------
    # Retry delay
    # -----------------------------------------------------------------------

    def _calculate_retry_delay(
        self,
        failures: int,
    ) -> float:

        failures = max(
            1,
            int(failures),
        )

        # Gentle exponential backoff.
        delay = (
            self.reconnect_delay
            * min(
                2 ** min(
                    failures - 1,
                    4,
                ),
                16,
            )
        )

        return min(
            delay,
            self.max_reconnect_delay,
        )

    # -----------------------------------------------------------------------
    # Safe worker stop
    # -----------------------------------------------------------------------

    def _stop_worker_safely(
        self,
        runtime: DestinationRuntime,
    ) -> None:

        worker = runtime.worker

        if worker is None:
            return

        try:

            worker.stop()

        except Exception as exc:

            LOGGER.warning(
                "[%s] Worker stop error: %s",
                runtime.destination_id,
                exc,
            )

        finally:

            with runtime.lock:

                runtime.worker = None

    # -----------------------------------------------------------------------
    # Start destination
    # -----------------------------------------------------------------------

    def start(
        self,
        destination_id: str,
    ) -> Dict[str, Any]:

        self._ensure_loaded()

        runtime = self.runtimes.get(
            destination_id
        )

        if runtime is None:

            return {
                "success": False,
                "destination_id": destination_id,
                "error": "Destination not found",
            }

        with runtime.lock:

            if (
                runtime.supervisor_thread is not None
                and
                runtime.supervisor_thread.is_alive()
            ):

                return {
                    "success": True,
                    "destination_id": destination_id,
                    "message": "Already running",
                }

        validation = self.validate(
            destination_id
        )

        if not validation["valid"]:

            with runtime.lock:

                runtime.state = "ERROR"

                runtime.last_error = (
                    validation["error"]
                )

            LOGGER.error(
                "[%s] Validation failed: %s",
                destination_id,
                validation["error"],
            )

            return {
                "success": False,
                "destination_id": destination_id,
                "error": validation["error"],
            }

        # Reset runtime controls.
        with runtime.lock:

            runtime.stop_event.clear()

            runtime.exit_event.clear()

            runtime.running = False

            runtime.state = "STARTING"

            runtime.last_error = None

            runtime.last_exit_code = None

            runtime.consecutive_failures = 0

            runtime.started_at = None

        thread = threading.Thread(
            target=self._supervisor,
            args=(destination_id,),
            name=f"Supervisor-{destination_id}",
            daemon=True,
        )

        with runtime.lock:

            runtime.supervisor_thread = thread

        thread.start()

        LOGGER.info(
            "[%s] Start requested",
            destination_id,
        )

        return {
            "success": True,
            "destination_id": destination_id,
            "message": "Supervisor started",
        }

    # -----------------------------------------------------------------------
    # Stop destination
    # -----------------------------------------------------------------------

    def stop(
        self,
        destination_id: str,
        join_timeout: float = 10.0,
    ) -> Dict[str, Any]:

        self._ensure_loaded()

        runtime = self.runtimes.get(
            destination_id
        )

        if runtime is None:

            return {
                "success": False,
                "destination_id": destination_id,
                "error": "Destination not found",
            }

        runtime.stop_event.set()

        # Wake supervisor if waiting for FFmpeg.
        runtime.exit_event.set()

        worker = runtime.worker

        if worker is not None:

            try:
                worker.stop()
            except Exception as exc:
                LOGGER.warning(
                    "[%s] Stop error: %s",
                    destination_id,
                    exc,
                )

        thread = runtime.supervisor_thread

        if (
            thread is not None
            and
            thread.is_alive()
            and
            thread is not threading.current_thread()
        ):

            thread.join(
                timeout=max(
                    0.1,
                    join_timeout,
                )
            )

        with runtime.lock:

            runtime.running = False

            runtime.state = "STOPPED"

            runtime.worker = None

            runtime.supervisor_thread = None

        LOGGER.info(
            "[%s] Stopped",
            destination_id,
        )

        return {
            "success": True,
            "destination_id": destination_id,
            "message": "Stopped",
        }

    # -----------------------------------------------------------------------
    # Start all enabled
    # -----------------------------------------------------------------------

    def start_all_enabled(self) -> Dict[str, Any]:

        self._ensure_loaded()

        results = {}

        for destination_id, destination in (
            self.destinations.items()
        ):

            if not bool(
                destination.get(
                    "enabled",
                    False,
                )
            ):

                results[destination_id] = {
                    "success": False,
                    "message": "Disabled",
                }

                continue

            try:

                results[destination_id] = self.start(
                    destination_id
                )

            except Exception as exc:

                LOGGER.exception(
                    "[%s] Start failed",
                    destination_id,
                )

                results[destination_id] = {
                    "success": False,
                    "error": str(exc),
                }

        return results

    # -----------------------------------------------------------------------
    # Stop all
    # -----------------------------------------------------------------------

    def stop_all(self) -> Dict[str, Any]:

        self._ensure_loaded()

        results = {}

        destination_ids = list(
            self.runtimes.keys()
        )

        for destination_id in destination_ids:

            try:

                results[destination_id] = self.stop(
                    destination_id
                )

            except Exception as exc:

                LOGGER.exception(
                    "[%s] Stop failed",
                    destination_id,
                )

                results[destination_id] = {
                    "success": False,
                    "error": str(exc),
                }

        return results

    # -----------------------------------------------------------------------
    # Restart
    # -----------------------------------------------------------------------

    def restart(
        self,
        destination_id: str,
    ) -> Dict[str, Any]:

        self.stop(
            destination_id
        )

        time.sleep(0.5)

        return self.start(
            destination_id
        )

    # -----------------------------------------------------------------------
    # Refresh playlist
    # -----------------------------------------------------------------------

    def refresh_playlist(
        self,
        destination_id: str,
    ) -> Dict[str, Any]:

        self._ensure_loaded()

        if destination_id not in self.destinations:

            return {
                "success": False,
                "error": "Destination not found",
            }

        folder = (
            CACHE_ROOT / destination_id
        )

        try:

            playlist = (
                self.playlist_manager.refresh(
                    destination_id,
                    folder,
                )
            )

            return {
                "success": True,
                "destination_id": destination_id,
                "count": len(playlist.items),
                "current": (
                    playlist.current_item.name
                    if playlist.current_item
                    else None
                ),
            }

        except Exception as exc:

            return {
                "success": False,
                "destination_id": destination_id,
                "error": str(exc),
            }

    # -----------------------------------------------------------------------
    # Build command preview
    # -----------------------------------------------------------------------

    def build_command(
        self,
        destination_id: str,
    ) -> Optional[list]:

        self._ensure_loaded()

        validation = self.validate(
            destination_id
        )

        if not validation["valid"]:

            LOGGER.error(
                "[%s] Command validation failed: %s",
                destination_id,
                validation["error"],
            )

            return None

        item = self.playlist_manager.current_item(
            destination_id
        )

        if item is None:
            return None

        worker = self._create_worker(
            destination_id,
            item,
        )

        return worker.command_for_display()

    # -----------------------------------------------------------------------
    # Status
    # -----------------------------------------------------------------------

    def status(
        self,
        destination_id: str,
    ) -> Dict[str, Any]:

        self._ensure_loaded()

        runtime = self.runtimes.get(
            destination_id
        )

        destination = self.destinations.get(
            destination_id
        )

        if runtime is None:

            return {
                "destination_id": destination_id,
                "state": "NOT_FOUND",
            }

        playlist_status = (
            self.playlist_manager.status(
                destination_id
            )
        )

        with runtime.lock:

            return {
                "destination_id": destination_id,

                "name": (
                    destination.get("name")
                    if destination
                    else destination_id
                ),

                "platform": (
                    destination.get("platform")
                    if destination
                    else None
                ),

                "enabled": (
                    bool(
                        destination.get(
                            "enabled",
                            False,
                        )
                    )
                    if destination
                    else False
                ),

                "state": runtime.state,

                "running": runtime.running,

                "current_video": (
                    runtime.current_video
                ),

                "current_path": (
                    runtime.current_path
                ),

                "last_exit_code": (
                    runtime.last_exit_code
                ),

                "last_error": (
                    runtime.last_error
                ),

                "last_message": (
                    runtime.last_message
                ),

                "reconnect_count": (
                    runtime.reconnect_count
                ),

                "consecutive_failures": (
                    runtime.consecutive_failures
                ),

                "transition_count": (
                    runtime.transition_count
                ),

                "playlist": playlist_status,
            }

    # -----------------------------------------------------------------------
    # All status
    # -----------------------------------------------------------------------

    def all_status(self) -> Dict[str, Any]:

        if not self._loaded:

            return {}

        return {
            destination_id: self.status(
                destination_id
            )
            for destination_id in self.destinations
        }

    # -----------------------------------------------------------------------
    # Is running
    # -----------------------------------------------------------------------

    def is_running(
        self,
        destination_id: str,
    ) -> bool:

        runtime = self.runtimes.get(
            destination_id
        )

        if runtime is None:
            return False

        with runtime.lock:
            return bool(
                runtime.running
            )

    # -----------------------------------------------------------------------
    # Shutdown
    # -----------------------------------------------------------------------

    def shutdown(self) -> None:

        LOGGER.info(
            "StreamingController shutdown requested"
        )

        try:

            self.stop_all()

        except Exception:

            LOGGER.exception(
                "Controller shutdown error"
            )

        LOGGER.info(
            "StreamingController shutdown complete"
        )


# ---------------------------------------------------------------------------
# Simple CLI test
# ---------------------------------------------------------------------------

def main() -> None:

    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s | "
            "%(levelname)s | "
            "%(name)s | "
            "%(message)s"
        ),
    )

    controller = StreamingController()

    try:

        status = controller.load()

        print()
        print("=" * 70)
        print("GOLDEN STREAMING ENGINE")
        print("FINAL CONTROLLER TEST")
        print("=" * 70)

        for destination_id, data in status.items():

            print(
                f"{destination_id}: "
                f"state={data.get('state')} "
                f"enabled={data.get('enabled')} "
                f"video={data.get('current_video')}"
            )

        print("=" * 70)

    finally:

        controller.shutdown()


if __name__ == "__main__":
    main()

