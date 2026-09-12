"""
Streaming Controller
Consolidated Multi-Destination Controller

Golden Streaming Engine
-----------------------

Responsibilities:
    - Manage independent destination workers
    - Manage destination playlists
    - Advance playlist on normal FFmpeg EOF
    - Start the next playlist item automatically
    - Recover failed FFmpeg workers
    - Keep every destination isolated
    - Provide live command preview
    - Provide safe local FFmpeg test command
    - Provide real controller-level EOF test
    - Maintain runtime statistics
    - Prevent stale worker callbacks
    - Support 7 independent destinations

Architecture:

    Google Drive
        |
        v
    Drive Sync / Cache
        |
        v
    Destination Playlist
        |
        v
    StreamingController
        |
        +--> FFmpeg Worker 01 --> YouTube 01
        +--> FFmpeg Worker 02 --> YouTube 02
        +--> FFmpeg Worker 03 --> YouTube 03
        +--> FFmpeg Worker 04 --> YouTube 04
        +--> FFmpeg Worker 05 --> Facebook 01
        +--> FFmpeg Worker 06 --> Facebook 02
        +--> FFmpeg Worker 07 --> Instagram 01

Playlist lifecycle:

    Video 1
       |
      EOF
       v
    Playlist.advance()
       |
       v
    Video 2
       |
      EOF
       v
    Video 3
       |
      EOF
       v
    Video 1
       |
       +--------------------> forever

Each destination is completely independent.

This controller does NOT:
    - Store credentials separately
    - Upload files to Google Drive
    - Generate stream keys
    - Mix destinations into one FFmpeg process
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Dict, Optional, List

from config_manager import ConfigManager
from playlist_manager import PlaylistManager
from workers.ffmpeg_worker import (
    FFmpegConfig,
    FFmpegResult,
    FFmpegWorker,
)


class ControllerError(RuntimeError):
    """Controller-level error."""


@dataclass
class DestinationRuntime:
    """
    Runtime state for one streaming destination.

    Every destination owns its own runtime state.
    """

    destination_id: str

    enabled: bool = False

    worker: Optional[FFmpegWorker] = None

    running: bool = False
    desired_running: bool = False

    current_video: Optional[str] = None

    restart_count: int = 0
    eof_count: int = 0
    failure_count: int = 0

    reconnect_delay: float = 5.0

    last_error: Optional[str] = None
    last_result: Optional[FFmpegResult] = None

    started_at: Optional[float] = None
    stopped_at: Optional[float] = None

    generation: int = 0

    # ----------------------------------------------------------
    # Local controller-level EOF test state
    # ----------------------------------------------------------

    local_test: bool = False

    local_test_duration: int = 10

    local_test_cycles: int = 1

    local_test_cycle: int = 0

    local_test_output_dir: Optional[str] = None

    lock: threading.RLock = field(
        default_factory=threading.RLock,
        repr=False,
    )


class StreamingController:
    """
    Consolidated multi-destination streaming controller.

    Seven independent destinations:

        youtube_01    -> Worker 01
        youtube_02    -> Worker 02
        youtube_03    -> Worker 03
        youtube_04    -> Worker 04
        facebook_01   -> Worker 05
        facebook_02   -> Worker 06
        instagram_01  -> Worker 07
    """

    VERSION = "2.0.0"

    DESTINATION_IDS = (
        "youtube_01",
        "youtube_02",
        "youtube_03",
        "youtube_04",
        "facebook_01",
        "facebook_02",
        "instagram_01",
    )

    def __init__(
        self,
        reconnect_delay: float = 5.0,
        max_reconnect_delay: float = 60.0,
    ):
        # ------------------------------------------------------
        # Reconnect configuration
        # ------------------------------------------------------

        self.reconnect_delay = max(
            0.0,
            float(reconnect_delay),
        )

        self.max_reconnect_delay = max(
            self.reconnect_delay,
            float(max_reconnect_delay),
        )

        # ------------------------------------------------------
        # Core managers
        # ------------------------------------------------------

        self.config_manager = ConfigManager()

        self.playlist_manager = PlaylistManager()

        # ------------------------------------------------------
        # Destination runtime registry
        # ------------------------------------------------------

        self.runtimes: Dict[
            str,
            DestinationRuntime,
        ] = {
            destination_id: DestinationRuntime(
                destination_id=destination_id,
                reconnect_delay=self.reconnect_delay,
            )
            for destination_id
            in self.DESTINATION_IDS
        }

        # ------------------------------------------------------
        # Controller lifecycle
        # ------------------------------------------------------

        self._loaded = False

        self._shutdown = threading.Event()

        self._controller_lock = threading.RLock()

    # ==========================================================
    # LOAD
    # ==========================================================

    def load(self) -> Dict[str, Any]:
        """
        Load destination configuration and playlists.

        This method does NOT start FFmpeg workers.
        """

        with self._controller_lock:

            destinations = (
                self.config_manager.get_destinations()
            )

            for destination_id in (
                self.DESTINATION_IDS
            ):

                runtime = self.runtimes[
                    destination_id
                ]

                destination = (
                    self._find_destination(
                        destinations,
                        destination_id,
                    )
                )

                enabled = False

                if destination is not None:

                    enabled = bool(
                        self._value(
                            destination,
                            "enabled",
                            False,
                        )
                    )

                with runtime.lock:

                    runtime.enabled = enabled

            # --------------------------------------------------
            # Load all local playlists
            # --------------------------------------------------

            self.refresh_all_playlists()

            self._loaded = True

            return {
                "version": self.VERSION,
                "loaded": True,
                "destinations": self.status(),
            }

    # ==========================================================
    # GENERIC HELPERS
    # ==========================================================

    @staticmethod
    def _value(
        obj: Any,
        key: str,
        default: Any = None,
    ) -> Any:
        """
        Read a value from either a dict or object.
        """

        if isinstance(obj, dict):

            return obj.get(
                key,
                default,
            )

        return getattr(
            obj,
            key,
            default,
        )

    @staticmethod
    def _find_destination(
        destinations: Any,
        destination_id: str,
    ) -> Any:
        """
        Find a destination configuration by ID.

        Supports:
            - dict
            - {"destinations": [...]}
            - list
            - tuple
        """

        if isinstance(
            destinations,
            dict,
        ):

            if "destinations" in destinations:

                destinations = (
                    destinations[
                        "destinations"
                    ]
                )

            if destination_id in destinations:

                return destinations[
                    destination_id
                ]

        if isinstance(
            destinations,
            (list, tuple),
        ):

            for destination in destinations:

                current_id = str(
                    StreamingController._value(
                        destination,
                        "id",
                        "",
                    )
                )

                if current_id == destination_id:

                    return destination

        return None

    def _require_loaded(self) -> None:
        """
        Ensure controller configuration is loaded.
        """

        if not self._loaded:

            raise ControllerError(
                "StreamingController is not loaded."
            )

    # ==========================================================
    # PLAYLIST MANAGEMENT
    # ==========================================================

    def refresh_playlist(
        self,
        destination_id: str,
    ) -> Dict[str, Any]:
        """
        Refresh one destination playlist from cache.
        """

        self._validate_destination_id(
            destination_id
        )

        cache_folder = (
            Path(__file__).resolve().parent
            / "cache"
            / destination_id
        )

        self.playlist_manager.refresh(
            destination_id,
            cache_folder,
        )

        return self.playlist_manager.status(
            destination_id
        )

    def refresh_all_playlists(
        self,
    ) -> Dict[str, Any]:
        """
        Refresh playlists for all destinations.
        """

        result: Dict[str, Any] = {}

        for destination_id in (
            self.DESTINATION_IDS
        ):

            try:

                result[destination_id] = (
                    self.refresh_playlist(
                        destination_id
                    )
                )

            except Exception as exc:

                result[destination_id] = {
                    "destination_id":
                        destination_id,
                    "error": str(exc),
                }

        return result

    # ==========================================================
    # DESTINATION VALIDATION
    # ==========================================================

    def _validate_destination_id(
        self,
        destination_id: str,
    ) -> None:
        """
        Validate destination ID.
        """

        if destination_id not in (
            self.runtimes
        ):

            raise ControllerError(
                f"Unknown destination: "
                f"{destination_id}"
            )

    def validate(
        self,
        destination_id: str,
    ) -> Dict[str, Any]:
        """
        Validate one destination for live streaming.

        Checks:

            - configuration exists
            - destination enabled
            - RTMP URL
            - stream key
            - playlist
            - current video
            - file existence
            - non-zero file size
        """

        self._require_loaded()

        self._validate_destination_id(
            destination_id
        )

        destination = (
            self._find_destination(
                self.config_manager.get_destinations(),
                destination_id,
            )
        )

        if destination is None:

            return {
                "success": False,
                "destination_id":
                    destination_id,
                "error": (
                    "Destination configuration "
                    "not found."
                ),
            }

        enabled = bool(
            self._value(
                destination,
                "enabled",
                False,
            )
        )

        if not enabled:

            return {
                "success": False,
                "destination_id":
                    destination_id,
                "error": (
                    "Destination is disabled."
                ),
            }

        rtmp_url = str(
            self._value(
                destination,
                "rtmp_url",
                "",
            )
            or ""
        ).strip()

        stream_key = str(
            self._value(
                destination,
                "stream_key",
                "",
            )
            or ""
        ).strip()

        if not rtmp_url:

            return {
                "success": False,
                "destination_id":
                    destination_id,
                "error": (
                    "RTMP URL is empty."
                ),
            }

        if not stream_key:

            return {
                "success": False,
                "destination_id":
                    destination_id,
                "error": (
                    "Stream key is empty."
                ),
            }

        playlist = (
            self.playlist_manager.status(
                destination_id
            )
        )

        if playlist.get(
            "count",
            0,
        ) <= 0:

            return {
                "success": False,
                "destination_id":
                    destination_id,
                "error": (
                    "Playlist is empty."
                ),
            }

        current_path = playlist.get(
            "current_path"
        )

        if not current_path:

            return {
                "success": False,
                "destination_id":
                    destination_id,
                "error": (
                    "Current playlist video "
                    "is missing."
                ),
            }

        video = Path(
            current_path
        )

        if not video.exists():

            return {
                "success": False,
                "destination_id":
                    destination_id,
                "error": (
                    f"Video does not exist: "
                    f"{video}"
                ),
            }

        if video.stat().st_size <= 0:

            return {
                "success": False,
                "destination_id":
                    destination_id,
                "error": (
                    f"Video is empty: "
                    f"{video}"
                ),
            }

        return {
            "success": True,
            "destination_id":
                destination_id,
            "video": str(video),
        }

    # ==========================================================
    # OUTPUT URL
    # ==========================================================

    def _build_output_url(
        self,
        destination_id: str,
    ) -> str:
        """
        Build live RTMP output URL.

        Credentials remain inside configuration.
        """

        destination = (
            self._find_destination(
                self.config_manager.get_destinations(),
                destination_id,
            )
        )

        if destination is None:

            raise ControllerError(
                f"Destination not found: "
                f"{destination_id}"
            )

        rtmp_url = str(
            self._value(
                destination,
                "rtmp_url",
                "",
            )
            or ""
        ).strip()

        stream_key = str(
            self._value(
                destination,
                "stream_key",
                "",
            )
            or ""
        ).strip()

        if not rtmp_url or not stream_key:

            raise ControllerError(
                "RTMP URL or stream key is empty."
            )

        return (
            rtmp_url.rstrip("/")
            + "/"
            + stream_key
        )

    # ==========================================================
    # LOCAL TEST COMMAND
    # ==========================================================

    def build_local_test_command(
        self,
        destination_id: str,
        output_file: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Build a safe local FFmpeg command.

        This never uses live RTMP credentials.
        """

        self._require_loaded()

        self._validate_destination_id(
            destination_id
        )

        playlist = (
            self.playlist_manager.status(
                destination_id
            )
        )

        current_path = playlist.get(
            "current_path"
        )

        if not current_path:

            return {
                "success": False,
                "destination_id":
                    destination_id,
                "error": (
                    "Playlist has no current video."
                ),
            }

        input_path = Path(
            current_path
        )

        if not input_path.exists():

            return {
                "success": False,
                "destination_id":
                    destination_id,
                "error": (
                    f"Video does not exist: "
                    f"{input_path}"
                ),
            }

        if input_path.stat().st_size <= 0:

            return {
                "success": False,
                "destination_id":
                    destination_id,
                "error": (
                    f"Video is empty: "
                    f"{input_path}"
                ),
            }

        if output_file:

            output_path = Path(
                output_file
            )

        else:

            output_path = (
                Path(__file__).resolve().parent
                / "test_output"
                / f"{destination_id}_local_test.flv"
            )

        output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        worker = FFmpegWorker(
            worker_id=(
                f"local-test:"
                f"{destination_id}"
            ),
            input_source=str(
                input_path
            ),
            output_url=str(
                output_path
            ),
            config=FFmpegConfig(),
        )

        return {
            "success": True,
            "mode": "LOCAL_TEST",
            "destination_id":
                destination_id,
            "input": str(
                input_path
            ),
            "output": str(
                output_path
            ),
            "command": (
                worker.command_for_display()
            ),
        }

    # ==========================================================
    # LOCAL EOF TEST
    # ==========================================================

    def start_local_eof_test(
        self,
        destination_id: str,
        duration_seconds: int = 10,
        cycles: int = 2,
        output_dir: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Start a real controller-level local EOF test.

        Example:

            Video 1
              ↓ EOF
            advance()
              ↓
            Video 1 again

        With multiple videos:

            Video 1
              ↓
            Video 2
              ↓
            Video 3
              ↓
            Video 1

        No live credentials are required.
        """

        self._require_loaded()

        self._validate_destination_id(
            destination_id
        )

        duration_seconds = int(
            duration_seconds
        )

        cycles = int(cycles)

        if duration_seconds <= 0:

            raise ControllerError(
                "duration_seconds must be "
                "greater than zero."
            )

        if cycles <= 0:

            raise ControllerError(
                "cycles must be "
                "greater than zero."
            )

        runtime = self.runtimes[
            destination_id
        ]

        playlist = (
            self.playlist_manager.status(
                destination_id
            )
        )

        if playlist.get(
            "count",
            0,
        ) <= 0:

            return {
                "success": False,
                "destination_id":
                    destination_id,
                "error": (
                    "Playlist is empty."
                ),
            }

        current_path = playlist.get(
            "current_path"
        )

        if not current_path:

            return {
                "success": False,
                "destination_id":
                    destination_id,
                "error": (
                    "Playlist has no current video."
                ),
            }

        input_path = Path(
            current_path
        )

        if not input_path.exists():

            return {
                "success": False,
                "destination_id":
                    destination_id,
                "error": (
                    f"Video does not exist: "
                    f"{input_path}"
                ),
            }

        if input_path.stat().st_size <= 0:

            return {
                "success": False,
                "destination_id":
                    destination_id,
                "error": (
                    f"Video is empty: "
                    f"{input_path}"
                ),
            }

        if output_dir:

            test_output_dir = Path(
                output_dir
            )

        else:

            test_output_dir = (
                Path(__file__).resolve().parent
                / "test_output"
                / destination_id
            )

        test_output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        # ------------------------------------------------------
        # Invalidate old worker callbacks
        # ------------------------------------------------------

        with runtime.lock:

            old_worker = runtime.worker

            runtime.generation += 1

            runtime.worker = None

            runtime.running = False

            runtime.desired_running = True

            runtime.local_test = True

            runtime.local_test_duration = (
                duration_seconds
            )

            runtime.local_test_cycles = (
                cycles
            )

            runtime.local_test_cycle = 0

            runtime.local_test_output_dir = (
                str(test_output_dir)
            )

            runtime.current_video = (
                input_path.name
            )

            runtime.last_error = None

            runtime.last_result = None

        # ------------------------------------------------------
        # Stop previous worker if present
        # ------------------------------------------------------

        if old_worker is not None:

            try:

                if old_worker.is_running():

                    old_worker.stop()

            except Exception:
                pass

        # ------------------------------------------------------
        # Start first local test item
        # ------------------------------------------------------

        try:

            self._start_current_video(
                destination_id,
                output_override=str(
                    test_output_dir
                    / "cycle_001.flv"
                ),
                extra_args=[
                    "-y",
                    "-t",
                    str(duration_seconds),
                ],
            )

        except Exception as exc:

            with runtime.lock:

                runtime.local_test = False

                runtime.desired_running = False

                runtime.running = False

                runtime.last_error = str(
                    exc
                )

            return {
                "success": False,
                "destination_id":
                    destination_id,
                "error": str(exc),
            }

        return {
            "success": True,
            "mode": "LOCAL_EOF_TEST",
            "destination_id":
                destination_id,
            "duration_seconds":
                duration_seconds,
            "cycles": cycles,
            "output_dir": str(
                test_output_dir
            ),
            "first_video":
                input_path.name,
        }
            # ==========================================================
    # LIVE COMMAND PREVIEW
    # ==========================================================

    def build_command(
        self,
        destination_id: str,
    ) -> Dict[str, Any]:
        """
        Build a safe-to-display live FFmpeg command.

        The actual stream key is redacted by FFmpegWorker.
        """

        self._require_loaded()

        self._validate_destination_id(
            destination_id
        )

        validation = self.validate(
            destination_id
        )

        if not validation["success"]:
            return validation

        playlist = (
            self.playlist_manager.status(
                destination_id
            )
        )

        current_path = playlist[
            "current_path"
        ]

        output_url = (
            self._build_output_url(
                destination_id
            )
        )

        worker = FFmpegWorker(
            worker_id=(
                f"preview:"
                f"{destination_id}"
            ),
            input_source=current_path,
            output_url=output_url,
            config=FFmpegConfig(
                reconnect_delay=(
                    self.reconnect_delay
                )
            ),
        )

        return {
            "success": True,
            "destination_id":
                destination_id,
            "input": current_path,
            "command": (
                worker.command_for_display()
            ),
        }

    # ==========================================================
    # START
    # ==========================================================

    def start(
        self,
        destination_id: str,
    ) -> Dict[str, Any]:
        """
        Start live streaming for one destination.

        One destination = one FFmpeg worker.
        """

        self._require_loaded()

        self._validate_destination_id(
            destination_id
        )

        runtime = self.runtimes[
            destination_id
        ]

        validation = self.validate(
            destination_id
        )

        if not validation["success"]:
            return validation

        with runtime.lock:

            runtime.desired_running = True

            runtime.last_error = None

            runtime.reconnect_delay = (
                self.reconnect_delay
            )

            # Ensure a previous local test cannot
            # remain active when live streaming starts.
            runtime.local_test = False

            runtime.local_test_cycle = 0

            runtime.local_test_output_dir = None

        try:

            self._start_current_video(
                destination_id
            )

            return self._destination_status(
                destination_id
            )

        except Exception as exc:

            with runtime.lock:

                runtime.last_error = str(
                    exc
                )

            self._recover_after_start_failure(
                destination_id
            )

            return {
                "success": False,
                "destination_id":
                    destination_id,
                "error": str(exc),
            }

    # ==========================================================
    # START CURRENT PLAYLIST VIDEO
    # ==========================================================

    def _start_current_video(
        self,
        destination_id: str,
        output_override: Optional[str] = None,
        extra_args: Optional[List[str]] = None,
    ) -> None:
        """
        Start FFmpeg for the current playlist item.

        output_override:
            Used by local tests.

        extra_args:
            Additional FFmpeg arguments used by tests.

        Normal live mode:
            output_override = None
            extra_args = None
        """

        runtime = self.runtimes[
            destination_id
        ]

        playlist = (
            self.playlist_manager.status(
                destination_id
            )
        )

        current_path = playlist.get(
            "current_path"
        )

        if not current_path:

            raise ControllerError(
                "No current playlist video."
            )

        input_path = Path(
            current_path
        )

        if not input_path.exists():

            raise ControllerError(
                f"Video does not exist: "
                f"{input_path}"
            )

        if input_path.stat().st_size <= 0:

            raise ControllerError(
                f"Video is empty: "
                f"{input_path}"
            )

        # ------------------------------------------------------
        # Output selection
        # ------------------------------------------------------

        if output_override:

            output_url = str(
                output_override
            )

        else:

            output_url = (
                self._build_output_url(
                    destination_id
                )
            )

        old_worker = None

        # ------------------------------------------------------
        # Create new generation
        # ------------------------------------------------------

        with runtime.lock:

            old_worker = runtime.worker

            runtime.generation += 1

            generation = runtime.generation

            runtime.current_video = (
                input_path.name
            )

            runtime.running = False

            runtime.started_at = time.time()

        # ------------------------------------------------------
        # Stop previous worker
        # ------------------------------------------------------

        if old_worker is not None:

            try:

                if old_worker.is_running():

                    old_worker.stop()

            except Exception:
                pass

        # ------------------------------------------------------
        # Create FFmpeg worker
        # ------------------------------------------------------

        worker = FFmpegWorker(
            worker_id=(
                f"{destination_id}:"
                f"{playlist.get('position', 0)}:"
                f"{time.time_ns()}"
            ),
            input_source=str(
                input_path
            ),
            output_url=output_url,
            config=FFmpegConfig(
                reconnect_delay=(
                    self.reconnect_delay
                )
            ),
            on_status=(
                self._on_worker_status
            ),
            on_log=(
                self._on_worker_log
            ),
            on_exit=(
                self._on_worker_exit
            ),
        )

        # ------------------------------------------------------
        # Local test FFmpeg arguments
        # ------------------------------------------------------

        if extra_args:

            worker.config.extra_args = list(
                extra_args
            )

        # ------------------------------------------------------
        # Register worker
        # ------------------------------------------------------

        with runtime.lock:

            if generation != (
                runtime.generation
            ):
                return

            runtime.worker = worker

            runtime.current_video = (
                input_path.name
            )

            runtime.last_error = None

        # ------------------------------------------------------
        # Start FFmpeg
        # ------------------------------------------------------

        try:

            worker.start()

        except Exception:

            with runtime.lock:

                if (
                    runtime.generation
                    == generation
                ):

                    runtime.worker = None

                    runtime.running = False

            raise

    # ==========================================================
    # STOP
    # ==========================================================

    def stop(
        self,
        destination_id: str,
    ) -> Dict[str, Any]:
        """
        Stop one destination only.

        Other destinations remain untouched.
        """

        self._require_loaded()

        self._validate_destination_id(
            destination_id
        )

        runtime = self.runtimes[
            destination_id
        ]

        with runtime.lock:

            runtime.desired_running = False

            runtime.generation += 1

            worker = runtime.worker

            runtime.worker = None

            runtime.running = False

            # Cancel local EOF test state.
            runtime.local_test = False

            runtime.local_test_cycle = 0

            runtime.local_test_output_dir = None

        if worker is not None:

            try:

                worker.stop()

            except Exception as exc:

                with runtime.lock:

                    runtime.last_error = str(
                        exc
                    )

        with runtime.lock:

            runtime.stopped_at = time.time()

        return self._destination_status(
            destination_id
        )

    # ==========================================================
    # RESTART
    # ==========================================================

    def restart(
        self,
        destination_id: str,
    ) -> Dict[str, Any]:
        """
        Stop and restart one destination.
        """

        self.stop(
            destination_id
        )

        if self._shutdown.is_set():

            return self._destination_status(
                destination_id
            )

        if self._shutdown.wait(
            self.reconnect_delay
        ):

            return self._destination_status(
                destination_id
            )

        return self.start(
            destination_id
        )

    # ==========================================================
    # START ALL ENABLED
    # ==========================================================

    def start_all_enabled(
        self,
    ) -> Dict[str, Any]:
        """
        Start every enabled destination.

        Each destination starts independently.
        """

        self._require_loaded()

        results: Dict[str, Any] = {}

        for destination_id in (
            self.DESTINATION_IDS
        ):

            runtime = self.runtimes[
                destination_id
            ]

            with runtime.lock:

                enabled = runtime.enabled

            if not enabled:

                results[destination_id] = {
                    "success": False,
                    "destination_id":
                        destination_id,
                    "skipped": True,
                    "error": (
                        "Destination is disabled."
                    ),
                }

                continue

            try:

                results[destination_id] = (
                    self.start(
                        destination_id
                    )
                )

            except Exception as exc:

                results[destination_id] = {
                    "success": False,
                    "destination_id":
                        destination_id,
                    "error": str(exc),
                }

        return results

    # ==========================================================
    # STOP ALL
    # ==========================================================

    def stop_all(
        self,
    ) -> Dict[str, Any]:
        """
        Stop every destination independently.
        """

        results: Dict[str, Any] = {}

        for destination_id in (
            self.DESTINATION_IDS
        ):

            try:

                results[destination_id] = (
                    self.stop(
                        destination_id
                    )
                )

            except Exception as exc:

                results[destination_id] = {
                    "success": False,
                    "destination_id":
                        destination_id,
                    "error": str(exc),
                }

        return results

    # ==========================================================
    # PAUSE
    # ==========================================================

    def pause(
        self,
        destination_id: str,
    ) -> Dict[str, Any]:
        """
        Pause is implemented as a safe stop.

        Resume starts the current playlist item again.
        """

        return self.stop(
            destination_id
        )

    # ==========================================================
    # RESUME
    # ==========================================================

    def resume(
        self,
        destination_id: str,
    ) -> Dict[str, Any]:

        return self.start(
            destination_id
        )

    # ==========================================================
    # WORKER CALLBACK - STATUS
    # ==========================================================

    def _on_worker_status(
        self,
        worker_id: str,
        status: Any,
    ) -> None:
        """
        Receive FFmpeg worker status updates.
        """

        destination_id = (
            self._destination_from_worker_id(
                worker_id
            )
        )

        if destination_id is None:
            return

        runtime = self.runtimes[
            destination_id
        ]

        status_name = getattr(
            status,
            "name",
            str(status),
        ).upper()

        with runtime.lock:

            worker = runtime.worker

            # Ignore stale worker callbacks.
            if (
                worker is None
                or worker.worker_id
                != worker_id
            ):
                return

            if status_name in {
                "RUNNING",
                "STARTING",
            }:

                runtime.running = True

            elif status_name in {
                "STOPPED",
                "FAILED",
                "EXITED",
            }:

                runtime.running = False

    # ==========================================================
    # WORKER CALLBACK - LOG
    # ==========================================================

    def _on_worker_log(
        self,
        worker_id: str,
        line: str,
    ) -> None:
        """
        Capture important FFmpeg error lines.
        """

        destination_id = (
            self._destination_from_worker_id(
                worker_id
            )
        )

        if destination_id is None:
            return

        runtime = self.runtimes[
            destination_id
        ]

        text = str(line)

        if any(
            word in text.lower()
            for word in (
                "error",
                "failed",
                "invalid",
                "unable",
                "connection refused",
            )
        ):

            with runtime.lock:

                if (
                    runtime.worker is None
                    or runtime.worker.worker_id
                    != worker_id
                ):
                    return

                runtime.last_error = (
                    text[-2000:]
                )

    # ==========================================================
    # WORKER CALLBACK - EXIT
    # ==========================================================

    def _on_worker_exit(
        self,
        worker_id: str,
        result: FFmpegResult,
    ) -> None:
        """
        Handle FFmpeg process exit.

        Normal exit:
            EOF -> advance playlist -> next worker.

        Unexpected exit:
            failure -> delayed recovery.

        User stop:
            do nothing.

        Stale worker:
            ignore.
        """

        destination_id = (
            self._destination_from_worker_id(
                worker_id
            )
        )

        if destination_id is None:
            return

        runtime = self.runtimes[
            destination_id
        ]

        with runtime.lock:

            current_worker = runtime.worker

            desired_running = (
                runtime.desired_running
            )

            # --------------------------------------------------
            # Ignore stale callback
            # --------------------------------------------------

            if (
                current_worker is None
                or current_worker.worker_id
                != worker_id
            ):
                return

            runtime.running = False

            runtime.last_result = result

            if result.error:

                runtime.last_error = (
                    result.error
                )

            local_test = (
                runtime.local_test
            )

        # ------------------------------------------------------
        # User intentionally stopped worker
        # ------------------------------------------------------

        if (
            result.stopped_by_user
            or self._shutdown.is_set()
            or not desired_running
        ):

            return

        # ------------------------------------------------------
        # NORMAL EOF
        # ------------------------------------------------------

        if result.normal_exit:

            with runtime.lock:

                runtime.eof_count += 1

                runtime.restart_count += 1

                runtime.reconnect_delay = (
                    self.reconnect_delay
                )

                # ----------------------------------------------
                # Local EOF test
                # ----------------------------------------------

                if local_test:

                    runtime.local_test_cycle += 1

                    completed_cycles = (
                        runtime.local_test_cycle
                    )

                    requested_cycles = (
                        runtime.local_test_cycles
                    )

                    # ------------------------------------------
                    # Test finished
                    # ------------------------------------------

                    if (
                        completed_cycles
                        >= requested_cycles
                    ):

                        runtime.desired_running = (
                            False
                        )

                        runtime.local_test = (
                            False
                        )

                        runtime.running = (
                            False
                        )

                        runtime.worker = None

                        runtime.stopped_at = (
                            time.time()
                        )

                        return

                generation = (
                    runtime.generation
                )

            # --------------------------------------------------
            # Continue playlist
            # --------------------------------------------------

            thread = threading.Thread(
                target=(
                    self._advance_and_start
                ),
                args=(
                    destination_id,
                    worker_id,
                    generation,
                ),
                daemon=True,
                name=(
                    f"playlist-"
                    f"{destination_id}"
                ),
            )

            thread.start()

            return

        # ------------------------------------------------------
        # UNEXPECTED FAILURE
        # ------------------------------------------------------

        if result.unexpected_exit:

            with runtime.lock:

                runtime.failure_count += 1

                runtime.restart_count += 1

                delay = (
                    runtime.reconnect_delay
                )

                runtime.reconnect_delay = min(
                    max(
                        self.reconnect_delay,
                        delay * 2,
                    ),
                    self.max_reconnect_delay,
                )

                generation = (
                    runtime.generation
                )

            thread = threading.Thread(
                target=(
                    self._recover_destination
                ),
                args=(
                    destination_id,
                    worker_id,
                    delay,
                    generation,
                ),
                daemon=True,
                name=(
                    f"recovery-"
                    f"{destination_id}"
                ),
            )

            thread.start()
            # ==========================================================
    # ADVANCE PLAYLIST + START NEXT VIDEO
    # ==========================================================

    def _advance_and_start(
        self,
        destination_id: str,
        previous_worker_id: Optional[str] = None,
        generation: Optional[int] = None,
    ) -> None:
        """
        Advance the destination playlist and start the next video.

        Normal mode:
            Video 1 -> Video 2 -> Video 3 -> Video 1 -> ...

        Local test:
            Same playlist progression, but every cycle is written
            to a separate local FLV output file.
        """

        runtime = self.runtimes[
            destination_id
        ]

        try:

            with runtime.lock:

                if (
                    generation is not None
                    and generation
                    != runtime.generation
                ):
                    return

                if not runtime.desired_running:
                    return

                current_worker = (
                    runtime.worker
                )

                if (
                    previous_worker_id
                    and current_worker is not None
                    and current_worker.worker_id
                    != previous_worker_id
                ):
                    return

                local_test = (
                    runtime.local_test
                )

                local_duration = (
                    runtime.local_test_duration
                )

                local_output_dir = (
                    runtime.local_test_output_dir
                )

                local_cycle = (
                    runtime.local_test_cycle
                )

            # --------------------------------------------------
            # Advance playlist
            # --------------------------------------------------

            next_item = (
                self.playlist_manager.advance(
                    destination_id,
                    loop=True,
                )
            )

            if next_item is None:

                raise ControllerError(
                    "Playlist has no next video."
                )

            # --------------------------------------------------
            # Local EOF test
            # --------------------------------------------------

            if local_test:

                if not local_output_dir:

                    raise ControllerError(
                        "Local test output directory "
                        "is not configured."
                    )

                cycle_number = (
                    local_cycle + 1
                )

                output_path = (
                    Path(local_output_dir)
                    / (
                        f"cycle_"
                        f"{cycle_number:03d}.flv"
                    )
                )

                self._start_current_video(
                    destination_id,
                    output_override=str(
                        output_path
                    ),
                    extra_args=[
                        "-y",
                        "-t",
                        str(local_duration),
                    ],
                )

                return

            # --------------------------------------------------
            # Normal live streaming
            # --------------------------------------------------

            self._start_current_video(
                destination_id
            )

        except Exception as exc:

            with runtime.lock:

                runtime.last_error = str(
                    exc
                )

                runtime.running = False

            self._recover_after_start_failure(
                destination_id
            )

    # ==========================================================
    # DESTINATION RECOVERY
    # ==========================================================

    def _recover_destination(
        self,
        destination_id: str,
        previous_worker_id: str,
        delay: float,
        generation: int,
    ) -> None:
        """
        Recover a destination after an unexpected FFmpeg crash.

        Only this destination is restarted.
        """

        runtime = self.runtimes[
            destination_id
        ]

        # ------------------------------------------------------
        # Wait before reconnect
        # ------------------------------------------------------

        if self._shutdown.wait(
            max(0.0, delay)
        ):
            return

        with runtime.lock:

            if generation != (
                runtime.generation
            ):
                return

            if not runtime.desired_running:
                return

            current_worker = (
                runtime.worker
            )

            if (
                current_worker is not None
                and current_worker.worker_id
                != previous_worker_id
            ):
                return

            local_test = (
                runtime.local_test
            )

            local_duration = (
                runtime.local_test_duration
            )

            local_output_dir = (
                runtime.local_test_output_dir
            )

            local_cycle = (
                runtime.local_test_cycle
            )

        try:

            # --------------------------------------------------
            # Local test recovery
            # --------------------------------------------------

            if local_test:

                if not local_output_dir:

                    raise ControllerError(
                        "Local test output directory "
                        "is not configured."
                    )

                cycle_number = (
                    local_cycle + 1
                )

                output_path = (
                    Path(local_output_dir)
                    / (
                        f"cycle_"
                        f"{cycle_number:03d}.flv"
                    )
                )

                self._start_current_video(
                    destination_id,
                    output_override=str(
                        output_path
                    ),
                    extra_args=[
                        "-y",
                        "-t",
                        str(local_duration),
                    ],
                )

            # --------------------------------------------------
            # Normal live recovery
            # --------------------------------------------------

            else:

                self._start_current_video(
                    destination_id
                )

            with runtime.lock:

                runtime.reconnect_delay = (
                    self.reconnect_delay
                )

        except Exception as exc:

            with runtime.lock:

                runtime.last_error = str(
                    exc
                )

                runtime.running = False

            # Schedule another recovery attempt
            # without blocking the worker callback.
            self._recover_after_start_failure(
                destination_id
            )

    # ==========================================================
    # RECOVERY AFTER START FAILURE
    # ==========================================================

    def _recover_after_start_failure(
        self,
        destination_id: str,
    ) -> None:
        """
        Schedule a retry when FFmpeg cannot start.
        """

        runtime = self.runtimes[
            destination_id
        ]

        with runtime.lock:

            if not runtime.desired_running:
                return

            delay = (
                runtime.reconnect_delay
            )

            generation = (
                runtime.generation
            )

            runtime.reconnect_delay = min(
                max(
                    self.reconnect_delay,
                    delay * 2,
                ),
                self.max_reconnect_delay,
            )

        def recovery_thread() -> None:

            if self._shutdown.wait(
                max(0.0, delay)
            ):
                return

            with runtime.lock:

                if generation != (
                    runtime.generation
                ):
                    return

                if not runtime.desired_running:
                    return

                local_test = (
                    runtime.local_test
                )

                local_duration = (
                    runtime.local_test_duration
                )

                local_output_dir = (
                    runtime.local_test_output_dir
                )

                local_cycle = (
                    runtime.local_test_cycle
                )

            try:

                # --------------------------------------------------
                # Local test retry
                # --------------------------------------------------

                if local_test:

                    if not local_output_dir:

                        raise ControllerError(
                            "Local test output directory "
                            "is not configured."
                        )

                    cycle_number = (
                        local_cycle + 1
                    )

                    output_path = (
                        Path(
                            local_output_dir
                        )
                        / (
                            f"cycle_"
                            f"{cycle_number:03d}.flv"
                        )
                    )

                    self._start_current_video(
                        destination_id,
                        output_override=str(
                            output_path
                        ),
                        extra_args=[
                            "-y",
                            "-t",
                            str(local_duration),
                        ],
                    )

                # --------------------------------------------------
                # Normal live retry
                # --------------------------------------------------

                else:

                    self._start_current_video(
                        destination_id
                    )

                with runtime.lock:

                    runtime.reconnect_delay = (
                        self.reconnect_delay
                    )

            except Exception as exc:

                with runtime.lock:

                    runtime.last_error = (
                        str(exc)
                    )

                # Retry again asynchronously.
                self._recover_after_start_failure(
                    destination_id
                )

        thread = threading.Thread(
            target=recovery_thread,
            daemon=True,
            name=(
                f"start-recovery-"
                f"{destination_id}"
            ),
        )

        thread.start()

    # ==========================================================
    # DESTINATION STATUS
    # ==========================================================

    def _destination_status(
        self,
        destination_id: str,
    ) -> Dict[str, Any]:
        """
        Return detailed runtime status for one destination.
        """

        runtime = self.runtimes[
            destination_id
        ]

        with runtime.lock:

            worker = runtime.worker

            metrics = None

            if worker is not None:

                try:

                    metrics = worker.metrics

                except Exception:
                    metrics = None

            return {
                "destination_id":
                    destination_id,

                "enabled":
                    runtime.enabled,

                "running":
                    runtime.running,

                "desired_running":
                    runtime.desired_running,

                "current_video":
                    runtime.current_video,

                "restart_count":
                    runtime.restart_count,

                "eof_count":
                    runtime.eof_count,

                "failure_count":
                    runtime.failure_count,

                "reconnect_delay":
                    runtime.reconnect_delay,

                "last_error":
                    runtime.last_error,

                "started_at":
                    runtime.started_at,

                "stopped_at":
                    runtime.stopped_at,

                "generation":
                    runtime.generation,

                "local_test":
                    runtime.local_test,

                "local_test_duration":
                    runtime.local_test_duration,

                "local_test_cycles":
                    runtime.local_test_cycles,

                "local_test_cycle":
                    runtime.local_test_cycle,

                "local_test_output_dir":
                    runtime.local_test_output_dir,

                "worker": (
                    worker.worker_id
                    if worker is not None
                    else None
                ),

                "metrics": (
                    asdict(metrics)
                    if metrics is not None
                    else None
                ),
            }

    # ==========================================================
    # GLOBAL STATUS
    # ==========================================================

    def status(
        self,
    ) -> Dict[str, Any]:
        """
        Return complete controller status.
        """

        destinations = {}

        for destination_id in (
            self.DESTINATION_IDS
        ):

            destinations[
                destination_id
            ] = self._destination_status(
                destination_id
            )

        running = sum(
            1
            for value in destinations.values()
            if value["running"]
        )

        enabled = sum(
            1
            for value in destinations.values()
            if value["enabled"]
        )

        return {
            "version":
                self.VERSION,

            "loaded":
                self._loaded,

            "shutdown":
                self._shutdown.is_set(),

            "running":
                running,

            "enabled":
                enabled,

            "total":
                len(self.DESTINATION_IDS),

            "destinations":
                destinations,
        }

    # ==========================================================
    # HEALTH
    # ==========================================================

    def health(
        self,
    ) -> Dict[str, Any]:
        """
        Return high-level controller health.
        """

        status = self.status()

        destinations = (
            status["destinations"]
        )

        failures = sum(
            value["failure_count"]
            for value in destinations.values()
        )

        running = sum(
            1
            for value in destinations.values()
            if value["running"]
        )

        enabled = sum(
            1
            for value in destinations.values()
            if value["enabled"]
        )

        if not self._loaded:

            state = "NOT_LOADED"

        elif self._shutdown.is_set():

            state = "SHUTDOWN"

        elif failures > 0:

            state = "DEGRADED"

        elif enabled == 0:

            state = "IDLE"

        elif running == enabled:

            state = "HEALTHY"

        elif running > 0:

            state = "PARTIAL"

        else:

            state = "STOPPED"

        return {
            "healthy": (
                state in {
                    "HEALTHY",
                    "IDLE",
                }
            ),

            "state":
                state,

            "loaded":
                self._loaded,

            "enabled":
                enabled,

            "running":
                running,

            "failures":
                failures,

            "total":
                len(
                    self.DESTINATION_IDS
                ),
        }

    # ==========================================================
    # WORKER ID -> DESTINATION
    # ==========================================================

    def _destination_from_worker_id(
        self,
        worker_id: str,
    ) -> Optional[str]:
        """
        Extract destination ID from a worker ID.
        """

        if not worker_id:
            return None

        for destination_id in (
            self.DESTINATION_IDS
        ):

            prefix = (
                f"{destination_id}:"
            )

            if worker_id.startswith(
                prefix
            ):

                return destination_id

        return None

    # ==========================================================
    # SHUTDOWN
    # ==========================================================

    def shutdown(
        self,
    ) -> Dict[str, Any]:
        """
        Fully shut down the controller.
        """

        if self._shutdown.is_set():

            return {
                "success": True,
                "already_shutdown": True,
            }

        self._shutdown.set()

        for destination_id in (
            self.DESTINATION_IDS
        ):

            runtime = self.runtimes[
                destination_id
            ]

            with runtime.lock:

                runtime.desired_running = (
                    False
                )

                runtime.generation += 1

                worker = runtime.worker

                runtime.worker = None

                runtime.running = False

                runtime.local_test = False

                runtime.local_test_cycle = 0

                runtime.local_test_output_dir = (
                    None
                )

            if worker is not None:

                try:

                    worker.stop()

                except Exception:
                    pass

            with runtime.lock:

                runtime.stopped_at = (
                    time.time()
                )

        return {
            "success": True,
            "shutdown": True,
        }


# ==============================================================
# CLI / DIRECT TEST
# ==============================================================

def main() -> None:
    """
    Basic command-line controller test.

    This does NOT start a real stream.
    """

    print(
        "=" * 60
    )

    print(
        "STREAMING CONTROLLER"
    )

    print(
        f"Version: "
        f"{StreamingController.VERSION}"
    )

    print(
        "=" * 60
    )

    controller = (
        StreamingController()
    )

    try:

        result = controller.load()

        print(
            "LOAD:"
        )

        print(
            result
        )

        print(
            "\nHEALTH:"
        )

        print(
            controller.health()
        )

        print(
            "\nSTATUS:"
        )

        print(
            controller.status()
        )

    finally:

        controller.shutdown()

        print(
            "\nCONTROLLER SHUTDOWN"
        )


# ==============================================================
# MODULE ENTRY POINT
# ==============================================================

if __name__ == "__main__":
    main()   