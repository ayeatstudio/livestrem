
"""
Professional Cloud Live Streaming Software
Playlist Manager
Version: 2.0.0 FINAL

Responsibilities:
    - Discover local video files.
    - Maintain one independent playlist per destination.
    - Track the current playback position.
    - Advance sequentially.
    - Loop back to the first video.
    - Never start FFmpeg.
    - Never access stream credentials.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Optional


# ============================================================
# SUPPORTED VIDEO FORMATS
# ============================================================

SUPPORTED_VIDEO_EXTENSIONS = {
    ".mp4",
    ".mov",
    ".mkv",
    ".avi",
    ".webm",
    ".m4v",
    ".ts",
}


# ============================================================
# PLAYLIST ITEM
# ============================================================

@dataclass(frozen=True)
class PlaylistItem:
    """One video inside a destination playlist."""

    path: Path
    index: int

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def local_path(self) -> str:
        return str(self.path)


# ============================================================
# PLAYLIST STATE
# ============================================================

@dataclass
class PlaylistState:
    """Runtime state for one destination playlist."""

    destination_id: str

    items: list[PlaylistItem] = field(
        default_factory=list
    )

    position: int = 0

    transitions: int = 0

    last_video: Optional[str] = None

    last_error: Optional[str] = None

    @property
    def count(self) -> int:
        return len(self.items)

    @property
    def current_item(self) -> Optional[PlaylistItem]:

        if not self.items:
            return None

        if self.position < 0:
            self.position = 0

        if self.position >= len(self.items):
            self.position = 0

        return self.items[self.position]


# ============================================================
# PLAYLIST MANAGER
# ============================================================

class PlaylistManager:
    """
    Thread-safe playlist manager.

    Each destination has its own independent PlaylistState.
    """

    def __init__(
        self,
        supported_extensions: Optional[
            set[str]
        ] = None,
    ) -> None:

        self.supported_extensions = (
            {
                ext.lower()
                for ext in (
                    supported_extensions
                    or SUPPORTED_VIDEO_EXTENSIONS
                )
            }
        )

        self._playlists: dict[
            str,
            PlaylistState,
        ] = {}

        self._lock = RLock()

    # ========================================================
    # DISCOVERY
    # ========================================================

    def discover_videos(
        self,
        folder: str | Path,
    ) -> list[Path]:
        """
        Discover valid video files in one folder.

        Only files directly inside the folder are included.
        Temporary files such as *.part are ignored.
        """

        directory = Path(folder)

        if not directory.exists():
            return []

        if not directory.is_dir():
            return []

        videos: list[Path] = []

        try:

            for path in directory.iterdir():

                if not path.is_file():
                    continue

                if path.name.startswith("."):
                    continue

                if path.name.endswith(
                    ".part"
                ):
                    continue

                if (
                    path.suffix.lower()
                    not in self.supported_extensions
                ):
                    continue

                try:

                    if path.stat().st_size <= 0:
                        continue

                except OSError:
                    continue

                videos.append(
                    path.resolve()
                )

        except OSError:
            return []

        videos.sort(
            key=lambda item: (
                item.name.lower(),
                str(item).lower(),
            )
        )

        return videos

    # ========================================================
    # SET PLAYLIST
    # ========================================================

    def set_playlist(
        self,
        destination_id: str,
        items: list[
            PlaylistItem | str | Path
        ],
        position: int = 0,
    ) -> PlaylistState:
        """
        Replace one destination's playlist.

        The position is clamped safely.
        """

        if not destination_id:
            raise ValueError(
                "destination_id is required."
            )

        normalized: list[Path] = []

        for item in items:

            if isinstance(
                item,
                PlaylistItem,
            ):
                path = item.path
            else:
                path = Path(item)

            path = path.expanduser().resolve()

            if not path.is_file():
                continue

            if path.suffix.lower() not in (
                self.supported_extensions
            ):
                continue

            normalized.append(path)

        playlist_items = [
            PlaylistItem(
                path=path,
                index=index,
            )
            for index, path in enumerate(
                normalized
            )
        ]

        if playlist_items:

            safe_position = max(
                0,
                min(
                    int(position),
                    len(playlist_items) - 1,
                ),
            )

        else:

            safe_position = 0

        with self._lock:

            previous = self._playlists.get(
                destination_id
            )

            transitions = (
                previous.transitions
                if previous
                else 0
            )

            state = PlaylistState(
                destination_id=destination_id,
                items=playlist_items,
                position=safe_position,
                transitions=transitions,
            )

            self._playlists[
                destination_id
            ] = state

            return state

    # ========================================================
    # LOAD FROM FOLDER
    # ========================================================

    def load_from_folder(
        self,
        destination_id: str,
        folder: str | Path,
    ) -> PlaylistState:

        videos = self.discover_videos(
            folder
        )

        return self.set_playlist(
            destination_id,
            videos,
        )

    # ========================================================
    # GET PLAYLIST
    # ========================================================

    def get_playlist(
        self,
        destination_id: str,
    ) -> PlaylistState:

        with self._lock:

            state = self._playlists.get(
                destination_id
            )

            if state is None:

                return PlaylistState(
                    destination_id=destination_id
                )

            return state

    # ========================================================
    # DESTINATION IDS
    # ========================================================

    def destination_ids(self) -> list[str]:

        with self._lock:

            return list(
                self._playlists.keys()
            )

    # ========================================================
    # COUNT
    # ========================================================

    def count(
        self,
        destination_id: str,
    ) -> int:

        with self._lock:

            state = self._playlists.get(
                destination_id
            )

            if state is None:
                return 0

            return len(state.items)

    # ========================================================
    # CURRENT
    # ========================================================

    def current(
        self,
        destination_id: str,
    ) -> Optional[Path]:

        item = self.current_item(
            destination_id
        )

        if item is None:
            return None

        return item.path

    # ========================================================
    # CURRENT ITEM
    # ========================================================

    def current_item(
        self,
        destination_id: str,
    ) -> Optional[PlaylistItem]:

        with self._lock:

            state = self._playlists.get(
                destination_id
            )

            if state is None:
                return None

            return state.current_item

    # ========================================================
    # POSITION
    # ========================================================

    def position(
        self,
        destination_id: str,
    ) -> int:

        with self._lock:

            state = self._playlists.get(
                destination_id
            )

            if state is None:
                return 0

            return state.position

    # ========================================================
    # ADVANCE
    # ========================================================

    def advance(
        self,
        destination_id: str,
        loop: bool = True,
    ) -> Optional[PlaylistItem]:
        """
        Move to the next video.

        Example:

            0 → 1 → 2 → 0 → 1 → ...

        When loop=False, the playlist stops after
        the last item.
        """

        with self._lock:

            state = self._playlists.get(
                destination_id
            )

            if state is None:
                return None

            if not state.items:
                return None

            previous = state.current_item

            if previous is not None:
                state.last_video = (
                    previous.name
                )

            next_position = (
                state.position + 1
            )

            if (
                next_position
                >= len(state.items)
            ):

                if not loop:

                    state.position = (
                        len(state.items) - 1
                    )

                    state.last_error = (
                        "PLAYLIST_END"
                    )

                    return None

                next_position = 0

            state.position = next_position

            state.transitions += 1
            state.last_error = None

            return state.current_item

    # ========================================================
    # RESET
    # ========================================================

    def reset(
        self,
        destination_id: str,
    ) -> Optional[PlaylistItem]:

        with self._lock:

            state = self._playlists.get(
                destination_id
            )

            if state is None:
                return None

            state.position = 0
            state.last_error = None

            return state.current_item

    # ========================================================
    # CLEAR
    # ========================================================

    def clear(
        self,
        destination_id: str,
    ) -> None:

        with self._lock:

            self._playlists.pop(
                destination_id,
                None,
            )

    # ========================================================
    # REFRESH
    # ========================================================

    def refresh(
        self,
        destination_id: str,
        folder: str | Path,
    ) -> PlaylistState:
        """
        Refresh a destination folder while trying to
        preserve the currently playing filename.
        """

        with self._lock:

            previous = self._playlists.get(
                destination_id
            )

            previous_name = None

            if previous is not None:

                current = (
                    previous.current_item
                )

                if current is not None:
                    previous_name = (
                        current.name
                    )

                transitions = (
                    previous.transitions
                )

            else:

                transitions = 0

        videos = self.discover_videos(
            folder
        )

        state = self.set_playlist(
            destination_id,
            videos,
        )

        state.transitions = transitions

        if previous_name:

            for index, item in enumerate(
                state.items
            ):

                if item.name == previous_name:

                    state.position = index
                    break

        return state

    # ========================================================
    # STATUS
    # ========================================================

    def status(
        self,
        destination_id: str,
    ) -> dict:

        with self._lock:

            state = self._playlists.get(
                destination_id
            )

            if state is None:

                return {
                    "destination_id": destination_id,
                    "count": 0,
                    "position": 0,
                    "current": None,
                    "videos": [],
                    "transitions": 0,
                    "last_video": None,
                    "last_error": None,
                }

            current = (
                state.current_item
            )

            return {
                "destination_id": (
                    destination_id
                ),
                "count": len(
                    state.items
                ),
                "position": state.position,
                "current": (
                    current.name
                    if current
                    else None
                ),
                "current_path": (
                    str(current.path)
                    if current
                    else None
                ),
                "videos": [
                    {
                        "index": item.index,
                        "name": item.name,
                        "local_path": str(
                            item.path
                        ),
                    }
                    for item in state.items
                ],
                "transitions": (
                    state.transitions
                ),
                "last_video": (
                    state.last_video
                ),
                "last_error": (
                    state.last_error
                ),
            }

    # ========================================================
    # ALL STATUS
    # ========================================================

    def all_status(self) -> dict[str, dict]:

        with self._lock:

            ids = list(
                self._playlists.keys()
            )

        return {
            destination_id: self.status(
                destination_id
            )
            for destination_id in ids
        }

    # ========================================================
    # SIMULATE
    # ========================================================

    def simulate(
        self,
        destination_id: str,
        count: int = 10,
    ) -> list[str]:
        """
        Simulate playlist progression without FFmpeg.

        Useful for testing:
            Video 1 → Video 2 → Video 3 → Video 1
        """

        result: list[str] = []

        if count <= 0:
            return result

        current = self.current_item(
            destination_id
        )

        if current is None:
            return result

        result.append(
            current.name
        )

        for _ in range(
            count - 1
        ):

            current = self.advance(
                destination_id,
                loop=True,
            )

            if current is None:
                break

            result.append(
                current.name
            )

        return result


# ============================================================
# TEST
# ============================================================

def main() -> None:

    print("=" * 60)
    print("PLAYLIST MANAGER TEST")
    print("=" * 60)

    manager = PlaylistManager()

    cache_root = (
        Path(__file__).resolve().parent
        / "cache"
    )

    destinations = [
        "youtube_01",
        "youtube_02",
        "youtube_03",
        "youtube_04",
        "facebook_01",
        "facebook_02",
        "instagram_01",
    ]

    for destination_id in destinations:

        folder = (
            cache_root
            / destination_id
        )

        state = manager.load_from_folder(
            destination_id,
            folder,
        )

        print(
            f"\n{destination_id}"
        )

        print(
            f"  Folder: {folder}"
        )

        print(
            f"  Videos: {state.count}"
        )

        current = state.current_item

        print(
            "  Current: "
            + (
                current.name
                if current
                else "NONE"
            )
        )

    print("\n" + "=" * 60)
    print("PLAYLIST MANAGER TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()

