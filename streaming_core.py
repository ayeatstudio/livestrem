
"""
Golden Streaming Engine
File    : streaming_core.py
Version : 4.0.0 FINAL

Central application orchestration layer.

Architecture
------------

                StreamingCore
                     |
        +------------+------------+
        |            |            |
        v            v            v
 ConfigManager  DriveSyncManager  PlaylistManager
                                  |
                                  v
                         StreamingController
                                  |
                                  v
                         FFmpegWorker x N

Responsibilities
----------------
- Application lifecycle
- Configuration loading
- Google Drive synchronization
- Playlist refresh
- Stream start/stop/restart
- All-destination orchestration
- Health/status aggregation
- Graceful shutdown

This module does NOT:
- Build FFmpeg commands directly
- Store stream keys
- Manage individual FFmpeg subprocesses
- Perform OAuth directly
- Implement playlist sequencing itself
"""

from __future__ import annotations

import logging
import threading
import time

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from config_manager import ConfigManager
from drive_sync_manager import DriveSyncManager
from playlist_manager import PlaylistManager
from streaming_controller import StreamingController


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOGGER = logging.getLogger("streaming_core")


# ---------------------------------------------------------------------------
# Core state
# ---------------------------------------------------------------------------

@dataclass
class CoreState:
    """
    Global engine state.
    """

    loaded: bool = False

    running: bool = False

    drive_sync_running: bool = False

    started_at: Optional[float] = None

    shutdown_requested: bool = False

    last_error: Optional[str] = None


# ---------------------------------------------------------------------------
# Streaming Core
# ---------------------------------------------------------------------------

class StreamingCore:
    """
    Main facade for Golden Streaming Engine.

    The UI, launcher, CLI or future API should communicate with this class
    instead of directly manipulating FFmpeg workers.
    """

    def __init__(
        self,
        drive_sync_interval: int = 300,
        reconnect_delay: float = 5.0,
        max_reconnect_delay: float = 60.0,
    ):
        self.config_manager = ConfigManager()

        self.playlist_manager = PlaylistManager()

        self.drive_sync = DriveSyncManager()

        self.controller = StreamingController(
            reconnect_delay=reconnect_delay,
            max_reconnect_delay=max_reconnect_delay,
        )

        self.state = CoreState()

        self.drive_sync_interval = max(
            30,
            int(drive_sync_interval),
        )

        self._lock = threading.RLock()

        LOGGER.info(
            "StreamingCore initialized"
        )

    # -----------------------------------------------------------------------
    # Load
    # -----------------------------------------------------------------------

    def load(self) -> Dict[str, Any]:
        """
        Load all configuration and local playlists.
        """

        with self._lock:

            LOGGER.info(
                "Loading Golden Streaming Engine"
            )

            try:

                # -----------------------------------------------------------
                # Load destinations
                # -----------------------------------------------------------

                destinations = (
                    self.config_manager.get_destinations()
                )

                LOGGER.info(
                    "Destinations loaded: %d",
                    len(destinations),
                )

                # -----------------------------------------------------------
                # Load controller
                # -----------------------------------------------------------

                controller_status = (
                    self.controller.load()
                )

                # -----------------------------------------------------------
                # Prepare Drive mappings
                # -----------------------------------------------------------

                for destination in destinations:

                    destination_id = str(
                        destination["id"]
                    )

                    drive_folder = (
                        self._default_drive_folder(
                            destination_id
                        )
                    )

                    if drive_folder:

                        self.drive_sync.set_destination_folder(
                            destination_id,
                            drive_folder,
                        )

                self.state.loaded = True

                self.state.last_error = None

                LOGGER.info(
                    "StreamingCore load complete"
                )

                return {
                    "success": True,
                    "destinations": len(
                        destinations
                    ),
                    "controller": controller_status,
                }

            except Exception as exc:

                self.state.loaded = False

                self.state.last_error = str(
                    exc
                )

                LOGGER.exception(
                    "StreamingCore load failed"
                )

                return {
                    "success": False,
                    "error": str(exc),
                }

    # -----------------------------------------------------------------------
    # Ensure loaded
    # -----------------------------------------------------------------------

    def _ensure_loaded(self) -> None:

        if not self.state.loaded:

            result = self.load()

            if not result.get(
                "success",
                False,
            ):

                raise RuntimeError(
                    result.get(
                        "error",
                        "StreamingCore failed to load",
                    )
                )

    # -----------------------------------------------------------------------
    # Drive folder mapping
    # -----------------------------------------------------------------------

    @staticmethod
    def _default_drive_folder(
        destination_id: str,
    ) -> Optional[str]:

        mapping = {
            "youtube_01": "YouTube 01",
            "youtube_02": "YouTube 02",
            "youtube_03": "YouTube 03",
            "youtube_04": "YouTube 04",
            "facebook_01": "Facebook 01",
            "facebook_02": "Facebook 02",
            "instagram_01": "Instagram 01",
        }

        return mapping.get(
            destination_id
        )

    # -----------------------------------------------------------------------
    # Synchronize one destination
    # -----------------------------------------------------------------------

    def sync_destination(
        self,
        destination_id: str,
    ) -> Dict[str, Any]:

        self._ensure_loaded()

        try:

            result = (
                self.drive_sync.sync_destination(
                    destination_id
                )
            )

            # Refresh local playlist after Drive sync.
            playlist_result = (
                self.controller.refresh_playlist(
                    destination_id
                )
            )

            return {
                "success": result.success,

                "destination_id": (
                    destination_id
                ),

                "discovered": (
                    result.discovered
                ),

                "downloaded": (
                    result.downloaded
                ),

                "skipped": (
                    result.skipped
                ),

                "failed": (
                    result.failed
                ),

                "playlist": playlist_result,

                "errors": list(
                    result.errors
                ),
            }

        except Exception as exc:

            LOGGER.exception(
                "[%s] Core sync failed",
                destination_id,
            )

            return {
                "success": False,
                "destination_id": destination_id,
                "error": str(exc),
            }

    # -----------------------------------------------------------------------
    # Synchronize all
    # -----------------------------------------------------------------------

    def sync_all(self) -> Dict[str, Any]:

        self._ensure_loaded()

        LOGGER.info(
            "Starting full Drive synchronization"
        )

        results = {}

        for destination_id in (
            self.controller.destinations.keys()
        ):

            try:

                results[destination_id] = (
                    self.sync_destination(
                        destination_id
                    )
                )

            except Exception as exc:

                LOGGER.exception(
                    "[%s] Sync failed",
                    destination_id,
                )

                results[destination_id] = {
                    "success": False,
                    "error": str(exc),
                }

        return {
            "success": all(
                item.get(
                    "success",
                    False,
                )
                for item in results.values()
            )
            if results
            else True,

            "destinations": results,
        }

    # -----------------------------------------------------------------------
    # Start Drive background sync
    # -----------------------------------------------------------------------

    def start_drive_sync(
        self,
        interval_seconds: Optional[int] = None,
    ) -> bool:

        self._ensure_loaded()

        interval = (
            self.drive_sync_interval
            if interval_seconds is None
            else max(
                30,
                int(interval_seconds),
            )
        )

        started = (
            self.drive_sync.start_background_sync(
                interval_seconds=interval
            )
        )

        with self._lock:

            self.state.drive_sync_running = (
                started
                or
                self.state.drive_sync_running
            )

        if started:

            LOGGER.info(
                "Background Drive synchronization enabled"
            )

        return started

    # -----------------------------------------------------------------------
    # Stop Drive background sync
    # -----------------------------------------------------------------------

    def stop_drive_sync(self) -> None:

        self.drive_sync.stop_background_sync()

        with self._lock:

            self.state.drive_sync_running = False

    # -----------------------------------------------------------------------
    # Start destination
    # -----------------------------------------------------------------------

    def start_destination(
        self,
        destination_id: str,
        sync_first: bool = True,
    ) -> Dict[str, Any]:

        self._ensure_loaded()

        if sync_first:

            sync_result = (
                self.sync_destination(
                    destination_id
                )
            )

            if not sync_result.get(
                "success",
                False,
            ):

                # A destination can still potentially stream from an
                # already cached playlist. Do not automatically abort
                # if playlist validation succeeds.
                LOGGER.warning(
                    "[%s] Drive sync had errors; "
                    "attempting cached playlist",
                    destination_id,
                )

        result = (
            self.controller.start(
                destination_id
            )
        )

        if result.get(
            "success",
            False,
        ):

            with self._lock:

                self.state.running = True

        return result

    # -----------------------------------------------------------------------
    # Stop destination
    # -----------------------------------------------------------------------

    def stop_destination(
        self,
        destination_id: str,
    ) -> Dict[str, Any]:

        result = (
            self.controller.stop(
                destination_id
            )
        )

        self._refresh_global_running_state()

        return result

    # -----------------------------------------------------------------------
    # Restart destination
    # -----------------------------------------------------------------------

    def restart_destination(
        self,
        destination_id: str,
        sync_first: bool = False,
    ) -> Dict[str, Any]:

        self._ensure_loaded()

        if sync_first:

            self.sync_destination(
                destination_id
            )

        result = (
            self.controller.restart(
                destination_id
            )
        )

        if result.get(
            "success",
            False,
        ):

            with self._lock:

                self.state.running = True

        return result

    # -----------------------------------------------------------------------
    # Start all enabled
    # -----------------------------------------------------------------------

    def start_all(
        self,
        sync_first: bool = True,
    ) -> Dict[str, Any]:

        self._ensure_loaded()

        LOGGER.info(
            "Starting all enabled destinations"
        )

        if sync_first:

            # Drive synchronization is intentionally independent.
            #
            # One destination failing here must not prevent another
            # destination from being started.
            self.sync_all()

        results = (
            self.controller.start_all_enabled()
        )

        started_count = 0

        for result in results.values():

            if result.get(
                "success",
                False,
            ):

                started_count += 1

        with self._lock:

            self.state.running = (
                started_count > 0
            )

            if started_count > 0:

                if self.state.started_at is None:

                    self.state.started_at = (
                        time.time()
                    )

        LOGGER.info(
            "Enabled destinations started: %d",
            started_count,
        )

        return {
            "success": True,
            "started": started_count,
            "results": results,
        }

    # -----------------------------------------------------------------------
    # Stop all
    # -----------------------------------------------------------------------

    def stop_all(self) -> Dict[str, Any]:

        LOGGER.info(
            "Stopping all destinations"
        )

        results = (
            self.controller.stop_all()
        )

        self._refresh_global_running_state()

        return results

    # -----------------------------------------------------------------------
    # Refresh playlist
    # -----------------------------------------------------------------------

    def refresh_playlist(
        self,
        destination_id: str,
    ) -> Dict[str, Any]:

        self._ensure_loaded()

        return (
            self.controller.refresh_playlist(
                destination_id
            )
        )

    # -----------------------------------------------------------------------
    # Refresh all playlists
    # -----------------------------------------------------------------------

    def refresh_all_playlists(
        self,
    ) -> Dict[str, Any]:

        self._ensure_loaded()

        results = {}

        for destination_id in (
            self.controller.destinations.keys()
        ):

            try:

                results[destination_id] = (
                    self.controller.refresh_playlist(
                        destination_id
                    )
                )

            except Exception as exc:

                results[destination_id] = {
                    "success": False,
                    "error": str(exc),
                }

        return results

    # -----------------------------------------------------------------------
    # Status - one destination
    # -----------------------------------------------------------------------

    def destination_status(
        self,
        destination_id: str,
    ) -> Dict[str, Any]:

        self._ensure_loaded()

        controller_status = (
            self.controller.status(
                destination_id
            )
        )

        drive_status = (
            self.drive_sync.status(
                destination_id
            )
        )

        return {
            "destination_id": destination_id,

            "stream": controller_status,

            "drive": drive_status,
        }

    # -----------------------------------------------------------------------
    # Status - all
    # -----------------------------------------------------------------------

    def status(self) -> Dict[str, Any]:

        if not self.state.loaded:

            return {
                "state": {
                    "loaded": False,
                    "running": False,
                },
                "destinations": {},
            }

        controller_status = (
            self.controller.all_status()
        )

        drive_status = (
            self.drive_sync.all_status()
        )

        running_count = 0

        for destination_status in (
            controller_status.values()
        ):

            if destination_status.get(
                "running",
                False,
            ):

                running_count += 1

        with self._lock:

            self.state.running = (
                running_count > 0
            )

        return {
            "state": {
                "loaded": self.state.loaded,

                "running": self.state.running,

                "drive_sync_running": (
                    self.state.drive_sync_running
                ),

                "started_at": (
                    self.state.started_at
                ),

                "shutdown_requested": (
                    self.state.shutdown_requested
                ),

                "last_error": (
                    self.state.last_error
                ),
            },

            "summary": {
                "destinations": len(
                    controller_status
                ),

                "running": running_count,
            },

            "destinations": {
                destination_id: {
                    "stream": controller_status.get(
                        destination_id
                    ),

                    "drive": drive_status.get(
                        destination_id
                    ),
                }

                for destination_id
                in controller_status
            },
        }

    # -----------------------------------------------------------------------
    # Global running state
    # -----------------------------------------------------------------------

    def _refresh_global_running_state(
        self,
    ) -> None:

        try:

            status = (
                self.controller.all_status()
            )

            running = any(
                item.get(
                    "running",
                    False,
                )
                for item in status.values()
            )

            with self._lock:

                self.state.running = running

        except Exception as exc:

            LOGGER.warning(
                "Unable to refresh global state: %s",
                exc,
            )

    # -----------------------------------------------------------------------
    # Health check
    # -----------------------------------------------------------------------

    def health(self) -> Dict[str, Any]:

        if not self.state.loaded:

            return {
                "healthy": False,
                "state": "NOT_LOADED",
            }

        controller_status = (
            self.controller.all_status()
        )

        total = len(
            controller_status
        )

        running = sum(
            1
            for item
            in controller_status.values()
            if item.get(
                "running",
                False,
            )
        )

        enabled = sum(
            1
            for item
            in controller_status.values()
            if item.get(
                "enabled",
                False,
            )
        )

        failed = sum(
            1
            for item
            in controller_status.values()
            if item.get(
                "state"
            ) == "FAILED"
        )

        if enabled == 0:

            health_state = "NO_ENABLED_DESTINATIONS"

        elif failed > 0:

            health_state = "DEGRADED"

        elif running == enabled:

            health_state = "HEALTHY"

        elif running > 0:

            health_state = "PARTIAL"

        else:

            health_state = "STOPPED"

        return {
            "healthy": (
                health_state == "HEALTHY"
            ),

            "state": health_state,

            "total_destinations": total,

            "enabled_destinations": enabled,

            "running_destinations": running,

            "failed_destinations": failed,
        }

    # -----------------------------------------------------------------------
    # Build command preview
    # -----------------------------------------------------------------------

    def build_command(
        self,
        destination_id: str,
    ) -> Optional[list]:

        self._ensure_loaded()

        return (
            self.controller.build_command(
                destination_id
            )
        )

    # -----------------------------------------------------------------------
    # Shutdown
    # -----------------------------------------------------------------------

    def shutdown(self) -> None:

        with self._lock:

            if self.state.shutdown_requested:

                return

            self.state.shutdown_requested = True

        LOGGER.info(
            "StreamingCore shutdown requested"
        )

        # ---------------------------------------------------------------
        # Stop Drive sync first.
        # ---------------------------------------------------------------

        try:

            self.stop_drive_sync()

        except Exception:

            LOGGER.exception(
                "Drive sync shutdown error"
            )

        # ---------------------------------------------------------------
        # Stop all FFmpeg destinations.
        # ---------------------------------------------------------------

        try:

            self.controller.stop_all()

        except Exception:

            LOGGER.exception(
                "Streaming controller shutdown error"
            )

        # ---------------------------------------------------------------
        # Stop controller.
        # ---------------------------------------------------------------

        try:

            self.controller.shutdown()

        except Exception:

            LOGGER.exception(
                "Controller final shutdown error"
            )

        # ---------------------------------------------------------------
        # Stop Drive manager.
        # ---------------------------------------------------------------

        try:

            self.drive_sync.shutdown()

        except Exception:

            LOGGER.exception(
                "Drive manager shutdown error"
            )

        with self._lock:

            self.state.running = False

            self.state.drive_sync_running = False

        LOGGER.info(
            "StreamingCore shutdown complete"
        )


# ---------------------------------------------------------------------------
# CLI / Smoke Test
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

    core = StreamingCore()

    try:

        print()
        print("=" * 76)
        print("GOLDEN STREAMING ENGINE")
        print("STREAMING CORE 4.0.0")
        print("=" * 76)

        result = core.load()

        print()
        print(
            "Load:",
            "OK"
            if result.get("success")
            else "FAILED",
        )

        health = core.health()

        print(
            "Health:",
            health.get("state")
        )

        status = core.status()

        summary = status.get(
            "summary",
            {},
        )

        print(
            "Destinations:",
            summary.get(
                "destinations",
                0,
            ),
        )

        print(
            "Running:",
            summary.get(
                "running",
                0,
            ),
        )

        print("=" * 76)

    finally:

        core.shutdown()


if __name__ == "__main__":
    main()

