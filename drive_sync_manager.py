
"""
Golden Streaming Engine
File    : drive_sync_manager.py
Version : 1.0.0 FINAL

Purpose
-------
Google Drive -> Local Cache synchronization layer.

Responsibilities
----------------
1. Discover destination folders from Google Drive.
2. Discover video files inside each destination folder.
3. Download missing videos to cache/<destination_id>/.
4. Keep existing files untouched.
5. Use .part files during download.
6. Never expose credentials or stream keys.
7. Keep destination synchronization independent.
8. Never control FFmpeg directly.

Architecture
------------

Google Drive
     |
     +-- YouTube 01
     |       |
     |       +-- video1.mp4
     |       +-- video2.mp4
     |
     +-- YouTube 02
     |
     +-- Facebook 01
     |
     +-- ...

             |
             v

DriveSyncManager
             |
             v

cache/
    youtube_01/
    youtube_02/
    youtube_03/
    youtube_04/
    facebook_01/
    facebook_02/
    instagram_01/

             |
             v

PlaylistManager
             |
             v

StreamingController
"""

from __future__ import annotations

import logging
import threading
import time

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOGGER = logging.getLogger("drive_sync_manager")


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent
CACHE_ROOT = PROJECT_ROOT / "cache"


# ---------------------------------------------------------------------------
# Supported video formats
# ---------------------------------------------------------------------------

VIDEO_EXTENSIONS = {
    ".mp4",
    ".mov",
    ".mkv",
    ".avi",
    ".webm",
    ".m4v",
    ".ts",
}


# ---------------------------------------------------------------------------
# Google Drive folder mapping
# ---------------------------------------------------------------------------

DEFAULT_DESTINATION_FOLDERS = {
    "youtube_01": "YouTube 01",
    "youtube_02": "YouTube 02",
    "youtube_03": "YouTube 03",
    "youtube_04": "YouTube 04",
    "facebook_01": "Facebook 01",
    "facebook_02": "Facebook 02",
    "instagram_01": "Instagram 01",
}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class DriveVideo:
    """
    One Google Drive video.
    """

    file_id: str
    name: str
    mime_type: str = ""
    size: int = 0
    modified_time: str = ""
    md5_checksum: str = ""
    drive_path: str = ""


@dataclass
class SyncResult:
    """
    Result of one destination synchronization.
    """

    destination_id: str

    success: bool = False

    discovered: int = 0

    downloaded: int = 0

    skipped: int = 0

    failed: int = 0

    removed: int = 0

    files: List[str] = field(
        default_factory=list
    )

    errors: List[str] = field(
        default_factory=list
    )

    started_at: float = field(
        default_factory=time.time
    )

    finished_at: Optional[float] = None

    @property
    def duration(self) -> float:

        if self.finished_at is None:
            return time.time() - self.started_at

        return self.finished_at - self.started_at


@dataclass
class DestinationSyncState:
    """
    Runtime synchronization state for one destination.
    """

    destination_id: str

    state: str = "IDLE"

    last_sync: Optional[float] = None

    last_result: Optional[SyncResult] = None

    last_error: Optional[str] = None

    sync_count: int = 0

    failure_count: int = 0


# ---------------------------------------------------------------------------
# Drive Sync Manager
# ---------------------------------------------------------------------------

class DriveSyncManager:
    """
    Independent Google Drive synchronization manager.

    This class intentionally does not know anything about:
        - FFmpeg
        - RTMP
        - stream keys
        - YouTube authentication
        - Facebook authentication
        - Instagram authentication

    It only synchronizes videos.
    """

    def __init__(
        self,
        cache_root: Optional[Path] = None,
        destination_folders: Optional[
            Dict[str, str]
        ] = None,
        drive_provider: Any = None,
    ):
        self.cache_root = (
            Path(cache_root)
            if cache_root is not None
            else CACHE_ROOT
        )

        self.cache_root.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.destination_folders = dict(
            destination_folders
            or DEFAULT_DESTINATION_FOLDERS
        )

        self.drive_provider = drive_provider

        self.states: Dict[
            str,
            DestinationSyncState,
        ] = {}

        self._lock = threading.RLock()

        self._stop_event = threading.Event()

        self._sync_thread: Optional[
            threading.Thread
        ] = None

        LOGGER.info(
            "DriveSyncManager initialized"
        )

    # -----------------------------------------------------------------------
    # Provider
    # -----------------------------------------------------------------------

    def _get_provider(self) -> Any:
        """
        Load the existing Google Drive provider lazily.

        This keeps Drive dependencies out of the application startup path
        until synchronization is actually requested.
        """

        if self.drive_provider is not None:
            return self.drive_provider

        try:

            from sources.google_drive import (
                GoogleDriveProvider,
            )

            self.drive_provider = (
                GoogleDriveProvider()
            )

            return self.drive_provider

        except ImportError:

            # Some existing implementations may expose GoogleDrive under
            # another class name. Try the known fallback.
            try:

                from sources.google_drive import (
                    GoogleDrive,
                )

                self.drive_provider = GoogleDrive()

                return self.drive_provider

            except Exception as exc:

                raise RuntimeError(
                    "Unable to load Google Drive provider: "
                    f"{exc}"
                ) from exc

        except Exception as exc:

            raise RuntimeError(
                "Unable to initialize Google Drive provider: "
                f"{exc}"
            ) from exc

    # -----------------------------------------------------------------------
    # Destination folder
    # -----------------------------------------------------------------------

    def set_destination_folder(
        self,
        destination_id: str,
        drive_folder_name: str,
    ) -> None:

        with self._lock:

            self.destination_folders[
                destination_id
            ] = drive_folder_name

            LOGGER.info(
                "Drive folder mapping: %s -> %s",
                destination_id,
                drive_folder_name,
            )

    # -----------------------------------------------------------------------
    # Cache folder
    # -----------------------------------------------------------------------

    def cache_folder(
        self,
        destination_id: str,
    ) -> Path:

        folder = (
            self.cache_root
            / destination_id
        )

        folder.mkdir(
            parents=True,
            exist_ok=True,
        )

        return folder

    # -----------------------------------------------------------------------
    # Destination state
    # -----------------------------------------------------------------------

    def _state(
        self,
        destination_id: str,
    ) -> DestinationSyncState:

        with self._lock:

            if destination_id not in self.states:

                self.states[
                    destination_id
                ] = DestinationSyncState(
                    destination_id=destination_id
                )

            return self.states[
                destination_id
            ]

    # -----------------------------------------------------------------------
    # Provider method helper
    # -----------------------------------------------------------------------

    @staticmethod
    def _call_provider(
        provider: Any,
        method_names: List[str],
        *args,
        **kwargs,
    ) -> Any:
        """
        Call the first supported provider method.

        This allows the final sync manager to work with the existing
        Google Drive provider without forcing a second Drive implementation.
        """

        for method_name in method_names:

            method = getattr(
                provider,
                method_name,
                None,
            )

            if callable(method):

                return method(
                    *args,
                    **kwargs,
                )

        raise AttributeError(
            "Google Drive provider does not implement "
            f"any of: {', '.join(method_names)}"
        )

    # -----------------------------------------------------------------------
    # Normalize Drive file
    # -----------------------------------------------------------------------

    @staticmethod
    def _normalize_video(
        value: Any,
    ) -> Optional[DriveVideo]:
        """
        Convert provider-specific video objects or dictionaries
        into the local DriveVideo model.

        IMPORTANT
        ---------
        GoogleDriveProvider has its own DriveVideo dataclass.
        Therefore we must support both:
            1. local DriveVideo objects
            2. provider-specific DriveVideo-like objects
            3. dictionaries
        """

        # ---------------------------------------------------------------
        # Already normalized
        # ---------------------------------------------------------------

        if isinstance(value, DriveVideo):
            return value

        # ---------------------------------------------------------------
        # Provider-specific object
        # ---------------------------------------------------------------

        if value is not None and not isinstance(value, dict):

            file_id = str(
                getattr(
                    value,
                    "file_id",
                    getattr(
                        value,
                        "id",
                        "",
                    ),
                )
                or ""
            ).strip()

            name = str(
                getattr(
                    value,
                    "name",
                    "",
                )
                or ""
            ).strip()

            if not file_id or not name:
                return None

            mime_type = str(
                getattr(
                    value,
                    "mime_type",
                    getattr(
                        value,
                        "mimeType",
                        "",
                    ),
                )
                or ""
            )

            extension = Path(
                name
            ).suffix.lower()

            # Accept normal video extensions or video/* MIME types.
            if (
                extension not in VIDEO_EXTENSIONS
                and not mime_type.lower().startswith("video/")
            ):
                return None

            size_value = getattr(
                value,
                "size",
                0,
            )

            try:
                size = int(
                    size_value or 0
                )
            except (
                TypeError,
                ValueError,
            ):
                size = 0

            modified_time = str(
                getattr(
                    value,
                    "modified_time",
                    getattr(
                        value,
                        "modifiedTime",
                        "",
                    ),
                )
                or ""
            )

            md5_checksum = str(
                getattr(
                    value,
                    "md5_checksum",
                    getattr(
                        value,
                        "md5Checksum",
                        "",
                    ),
                )
                or ""
            )

            return DriveVideo(
                file_id=file_id,
                name=name,
                mime_type=mime_type,
                size=size,
                modified_time=modified_time,
                md5_checksum=md5_checksum,
            )

        # ---------------------------------------------------------------
        # Dictionary
        # ---------------------------------------------------------------

        if isinstance(value, dict):

            file_id = str(
                value.get(
                    "id",
                    value.get(
                        "file_id",
                        "",
                    ),
                )
                or ""
            ).strip()

            name = str(
                value.get(
                    "name",
                    "",
                )
                or ""
            ).strip()

            if not file_id or not name:
                return None

            extension = Path(
                name
            ).suffix.lower()

            mime_type = str(
                value.get(
                    "mimeType",
                    value.get(
                        "mime_type",
                        "",
                    ),
                )
                or ""
            )

            if (
                extension not in VIDEO_EXTENSIONS
                and not mime_type.lower().startswith("video/")
            ):
                return None

            size_value = value.get(
                "size",
                0,
            )

            try:
                size = int(
                    size_value or 0
                )
            except (
                TypeError,
                ValueError,
            ):
                size = 0

            return DriveVideo(
                file_id=file_id,
                name=name,
                mime_type=mime_type,
                size=size,
                modified_time=str(
                    value.get(
                        "modifiedTime",
                        value.get(
                            "modified_time",
                            "",
                        ),
                    )
                    or ""
                ),
                md5_checksum=str(
                    value.get(
                        "md5Checksum",
                        value.get(
                            "md5_checksum",
                            "",
                        ),
                    )
                    or ""
                ),
            )

        return None

    # -----------------------------------------------------------------------
    # List destination videos
    # -----------------------------------------------------------------------

    def list_drive_videos(
        self,
        destination_id: str,
    ) -> List[DriveVideo]:
        """
        Discover videos for one destination.

        The existing Google Drive provider may expose:
            list_videos(...)
            list_files(...)
            get_files(...)
        """

        provider = self._get_provider()

        folder_name = (
            self.destination_folders.get(
                destination_id
            )
        )

        if not folder_name:

            raise ValueError(
                f"No Drive folder mapping for "
                f"{destination_id}"
            )

        raw_files = None

        # Preferred API from the current project.
        try:

            raw_files = self._call_provider(
                provider,
                [
                    "list_videos",
                    "get_videos",
                ],
                folder_name,
            )

        except TypeError:

            # Some implementations expect a keyword.
            raw_files = self._call_provider(
                provider,
                [
                    "list_videos",
                    "get_videos",
                ],
                folder_name=folder_name,
            )

        except AttributeError:

            try:

                raw_files = self._call_provider(
                    provider,
                    [
                        "list_files",
                        "get_files",
                    ],
                    folder_name,
                )

            except TypeError:

                raw_files = self._call_provider(
                    provider,
                    [
                        "list_files",
                        "get_files",
                    ],
                    folder_name=folder_name,
                )

        if raw_files is None:
            return []

        videos: List[DriveVideo] = []

        for value in raw_files:

            video = self._normalize_video(
                value
            )

            if video is not None:

                video.drive_path = (
                    folder_name
                    + "/"
                    + video.name
                )

                videos.append(
                    video
                )

        videos.sort(
            key=lambda item: item.name.lower()
        )

        return videos

    # -----------------------------------------------------------------------
    # Find local file
    # -----------------------------------------------------------------------

    @staticmethod
    def _local_file(
        folder: Path,
        video: DriveVideo,
    ) -> Path:

        return folder / video.name

    # -----------------------------------------------------------------------
    # Verify local file
    # -----------------------------------------------------------------------

    @staticmethod
    def _local_file_valid(
        path: Path,
        video: DriveVideo,
    ) -> bool:

        if not path.exists():
            return False

        if not path.is_file():
            return False

        try:

            size = path.stat().st_size

        except OSError:

            return False

        if size <= 0:
            return False

        # If Drive reports a size, compare it.
        #
        # We deliberately don't reject files when the provider does not
        # report size metadata.
        if video.size > 0:

            if size != video.size:

                return False

        return True

    # -----------------------------------------------------------------------
    # Download one video
    # -----------------------------------------------------------------------

    def _download_video(
        self,
        destination_id: str,
        video: DriveVideo,
        folder: Path,
    ) -> Path:

        provider = self._get_provider()

        final_path = (
            folder / video.name
        )

        temp_path = Path(
            str(final_path) + ".part"
        )

        # Remove stale partial download.
        try:

            if temp_path.exists():
                temp_path.unlink()

        except OSError:

            pass

        # ---------------------------------------------------------------
        # Preferred provider API
        # ---------------------------------------------------------------

        try:

            result = self._call_provider(
                provider,
                [
                    "download",
                    "download_file",
                    "download_video",
                ],
                video.file_id,
                final_path,
            )

            # Provider may return a path.
            if result:

                returned = Path(
                    str(result)
                )

                if returned.exists():

                    if (
                        returned.resolve()
                        != final_path.resolve()
                    ):

                        returned.replace(
                            final_path
                        )

        except TypeError:

            # Alternative keyword API.
            result = self._call_provider(
                provider,
                [
                    "download",
                    "download_file",
                    "download_video",
                ],
                file_id=video.file_id,
                output_path=final_path,
            )

            if result:

                returned = Path(
                    str(result)
                )

                if returned.exists():

                    if (
                        returned.resolve()
                        != final_path.resolve()
                    ):

                        returned.replace(
                            final_path
                        )

        except AttributeError:

            # Provider's explicit cache API.
            try:

                result = self._call_provider(
                    provider,
                    [
                        "download_to_temp",
                    ],
                    video.file_id,
                    temp_path,
                )

            except TypeError:

                result = self._call_provider(
                    provider,
                    [
                        "download_to_temp",
                    ],
                    file_id=video.file_id,
                    output_path=temp_path,
                )

            if result:

                returned = Path(
                    str(result)
                )

                if returned.exists():

                    if (
                        returned.resolve()
                        != temp_path.resolve()
                    ):

                        returned.replace(
                            temp_path
                        )

            if not temp_path.exists():

                raise RuntimeError(
                    "Google Drive provider did not "
                    "produce a downloaded file"
                )

            temp_path.replace(
                final_path
            )

        # ---------------------------------------------------------------
        # Verify
        # ---------------------------------------------------------------

        if not final_path.exists():

            raise RuntimeError(
                "Download completed but local "
                f"file was not found: {final_path}"
            )

        if final_path.stat().st_size <= 0:

            raise RuntimeError(
                "Downloaded video is empty: "
                f"{final_path}"
            )

        return final_path

    # -----------------------------------------------------------------------
    # Sync one destination
    # -----------------------------------------------------------------------

    def sync_destination(
        self,
        destination_id: str,
    ) -> SyncResult:

        state = self._state(
            destination_id
        )

        result = SyncResult(
            destination_id=destination_id
        )

        with self._lock:

            state.state = "SYNCING"

            state.last_error = None

        LOGGER.info(
            "[%s] Drive synchronization started",
            destination_id,
        )

        try:

            folder = self.cache_folder(
                destination_id
            )

            videos = self.list_drive_videos(
                destination_id
            )

            result.discovered = len(
                videos
            )

            drive_names = set()

            for video in videos:

                drive_names.add(
                    video.name
                )

                local_path = (
                    self._local_file(
                        folder,
                        video,
                    )
                )

                result.files.append(
                    video.name
                )

                # -------------------------------------------------------
                # Existing valid file
                # -------------------------------------------------------

                if self._local_file_valid(
                    local_path,
                    video,
                ):

                    result.skipped += 1

                    LOGGER.debug(
                        "[%s] Already cached: %s",
                        destination_id,
                        video.name,
                    )

                    continue

                # -------------------------------------------------------
                # Download
                # -------------------------------------------------------

                try:

                    LOGGER.info(
                        "[%s] Downloading: %s",
                        destination_id,
                        video.name,
                    )

                    self._download_video(
                        destination_id,
                        video,
                        folder,
                    )

                    result.downloaded += 1

                    LOGGER.info(
                        "[%s] Download complete: %s",
                        destination_id,
                        video.name,
                    )

                except Exception as exc:

                    result.failed += 1

                    error_text = (
                        f"{video.name}: {exc}"
                    )

                    result.errors.append(
                        error_text
                    )

                    LOGGER.error(
                        "[%s] Download failed: %s",
                        destination_id,
                        error_text,
                    )

                    # Never let one video block the rest.
                    continue

            # -----------------------------------------------------------
            # Remove stale local files
            # -----------------------------------------------------------

            #
            # IMPORTANT:
            # Only remove files that are clearly video files.
            #
            # .part files are also removed if stale.
            #

            for local_path in folder.iterdir():

                if not local_path.is_file():
                    continue

                if (
                    local_path.name.endswith(
                        ".part"
                    )
                ):

                    try:

                        local_path.unlink()

                    except OSError:

                        pass

                    continue

                extension = (
                    local_path.suffix.lower()
                )

                if (
                    extension
                    not in VIDEO_EXTENSIONS
                ):
                    continue

                if (
                    local_path.name
                    not in drive_names
                ):

                    # Do not automatically delete by default.
                    #
                    # The local file may be intentionally retained
                    # while Drive content is being updated.
                    #
                    # Therefore we only report it.
                    LOGGER.debug(
                        "[%s] Local-only file retained: %s",
                        destination_id,
                        local_path.name,
                    )

            result.success = (
                result.failed == 0
            )

            result.finished_at = time.time()

            with self._lock:

                state.last_sync = (
                    result.finished_at
                )

                state.last_result = result

                state.sync_count += 1

                if result.failed:

                    state.failure_count += 1

                    state.state = "WARNING"

                else:

                    state.state = "READY"

            LOGGER.info(
                "[%s] Drive synchronization finished: "
                "found=%d downloaded=%d skipped=%d failed=%d",
                destination_id,
                result.discovered,
                result.downloaded,
                result.skipped,
                result.failed,
            )

            return result

        except Exception as exc:

            result.success = False

            result.failed += 1

            result.errors.append(
                str(exc)
            )

            result.finished_at = time.time()

            with self._lock:

                state.state = "ERROR"

                state.last_error = str(
                    exc
                )

                state.last_result = result

                state.failure_count += 1

            LOGGER.exception(
                "[%s] Drive synchronization failed",
                destination_id,
            )

            return result

    # -----------------------------------------------------------------------
    # Sync all destinations
    # -----------------------------------------------------------------------

    def sync_all(
        self,
        destination_ids: Optional[
            List[str]
        ] = None,
    ) -> Dict[str, SyncResult]:

        if destination_ids is None:

            destination_ids = list(
                self.destination_folders.keys()
            )

        results: Dict[
            str,
            SyncResult,
        ] = {}

        for destination_id in destination_ids:

            try:

                results[destination_id] = (
                    self.sync_destination(
                        destination_id
                    )
                )

            except Exception as exc:

                LOGGER.exception(
                    "[%s] Unexpected sync error",
                    destination_id,
                )

                results[destination_id] = (
                    SyncResult(
                        destination_id=destination_id,
                        success=False,
                        failed=1,
                        errors=[str(exc)],
                        finished_at=time.time(),
                    )
                )

        return results

    # -----------------------------------------------------------------------
    # Background sync loop
    # -----------------------------------------------------------------------

    def start_background_sync(
        self,
        interval_seconds: int = 300,
    ) -> bool:

        interval_seconds = max(
            30,
            int(interval_seconds),
        )

        with self._lock:

            if (
                self._sync_thread is not None
                and
                self._sync_thread.is_alive()
            ):

                return False

            self._stop_event.clear()

            self._sync_thread = (
                threading.Thread(
                    target=self._background_loop,
                    args=(interval_seconds,),
                    name="DriveSync",
                    daemon=True,
                )
            )

            self._sync_thread.start()

        LOGGER.info(
            "Background Drive sync started "
            "(interval=%ds)",
            interval_seconds,
        )

        return True

    # -----------------------------------------------------------------------
    # Background loop
    # -----------------------------------------------------------------------

    def _background_loop(
        self,
        interval_seconds: int,
    ) -> None:

        while not self._stop_event.is_set():

            try:

                self.sync_all()

            except Exception:

                LOGGER.exception(
                    "Background Drive sync error"
                )

            self._stop_event.wait(
                interval_seconds
            )

        LOGGER.info(
            "Background Drive sync stopped"
        )

    # -----------------------------------------------------------------------
    # Stop background sync
    # -----------------------------------------------------------------------

    def stop_background_sync(
        self,
        join_timeout: float = 5.0,
    ) -> None:

        self._stop_event.set()

        thread = self._sync_thread

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

        with self._lock:

            self._sync_thread = None

    # -----------------------------------------------------------------------
    # Status
    # -----------------------------------------------------------------------

    def status(
        self,
        destination_id: str,
    ) -> Dict[str, Any]:

        state = self._state(
            destination_id
        )

        with self._lock:

            result = state.last_result

            return {
                "destination_id": (
                    destination_id
                ),

                "drive_folder": (
                    self.destination_folders.get(
                        destination_id
                    )
                ),

                "cache_folder": str(
                    self.cache_folder(
                        destination_id
                    )
                ),

                "state": state.state,

                "last_sync": state.last_sync,

                "sync_count": state.sync_count,

                "failure_count": (
                    state.failure_count
                ),

                "last_error": (
                    state.last_error
                ),

                "last_result": (
                    {
                        "success": result.success,
                        "discovered": result.discovered,
                        "downloaded": result.downloaded,
                        "skipped": result.skipped,
                        "failed": result.failed,
                        "duration": result.duration,
                    }
                    if result is not None
                    else None
                ),
            }

    # -----------------------------------------------------------------------
    # All status
    # -----------------------------------------------------------------------

    def all_status(self) -> Dict[str, Any]:

        return {
            destination_id: self.status(
                destination_id
            )
            for destination_id
            in self.destination_folders
        }

    # -----------------------------------------------------------------------
    # Shutdown
    # -----------------------------------------------------------------------

    def shutdown(self) -> None:

        LOGGER.info(
            "DriveSyncManager shutdown"
        )

        self.stop_background_sync()


# ---------------------------------------------------------------------------
# CLI test
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

    manager = DriveSyncManager()

    print()
    print("=" * 72)
    print("GOLDEN STREAMING ENGINE")
    print("GOOGLE DRIVE SYNC MANAGER TEST")
    print("=" * 72)

    for destination_id, folder_name in (
        manager.destination_folders.items()
    ):

        print(
            f"{destination_id:15} -> "
            f"{folder_name}"
        )

    print("=" * 72)

    # Do not automatically contact Google Drive from the simple CLI test.
    # Actual synchronization is started explicitly by the application.

    print(
        "DriveSyncManager initialized successfully."
    )

    manager.shutdown()


if __name__ == "__main__":
    main()

