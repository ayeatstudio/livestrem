from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional


BASE_DIR = Path(__file__).resolve().parent
PLAYLIST_FILE = BASE_DIR / "config" / "playlists.json"


class PlaylistPlaybackEngine:
    """
    Local playlist playback controller.

    This module does NOT start FFmpeg or any real stream.
    It only manages the ordered local files belonging to
    each destination and supports sequential looping.
    """

    def __init__(self, playlist_file: Path = PLAYLIST_FILE):
        self.playlist_file = Path(playlist_file)
        self.playlists: dict = {}
        self.positions: dict[str, int] = {}

    # ---------------------------------------------------------
    # LOAD
    # ---------------------------------------------------------

    def load(self) -> dict:
        if not self.playlist_file.exists():
            raise FileNotFoundError(
                f"Playlist file not found:\n{self.playlist_file}"
            )

        with self.playlist_file.open(
            "r",
            encoding="utf-8",
        ) as file:
            data = json.load(file)

        if not isinstance(data, dict):
            raise ValueError(
                "playlists.json must contain a JSON object."
            )

        self.playlists = data

        for destination_id in self.playlists:
            self.positions.setdefault(destination_id, 0)

        return self.playlists

    # ---------------------------------------------------------
    # DESTINATIONS
    # ---------------------------------------------------------

    def destination_ids(self) -> list[str]:
        return list(self.playlists.keys())

    def get_playlist(self, destination_id: str) -> list[dict]:
        data = self.playlists.get(destination_id)

        if not isinstance(data, dict):
            return []

        videos = data.get("videos", [])

        if not isinstance(videos, list):
            return []

        return videos

    # ---------------------------------------------------------
    # STATUS
    # ---------------------------------------------------------

    def status(self, destination_id: str) -> dict:
        videos = self.get_playlist(destination_id)

        if not videos:
            return {
                "destination_id": destination_id,
                "total_videos": 0,
                "current_index": None,
                "current_video": None,
                "ready": False,
            }

        position = self.positions.get(
            destination_id,
            0,
        )

        position %= len(videos)
        self.positions[destination_id] = position

        current = videos[position]

        local_path = Path(
            current.get("local_path", "")
        )

        return {
            "destination_id": destination_id,
            "total_videos": len(videos),
            "current_index": position + 1,
            "current_video": current.get("name"),
            "local_path": str(local_path),
            "file_exists": local_path.exists(),
            "ready": local_path.exists(),
        }

    # ---------------------------------------------------------
    # CURRENT VIDEO
    # ---------------------------------------------------------

    def current(self, destination_id: str) -> Optional[dict]:
        videos = self.get_playlist(destination_id)

        if not videos:
            return None

        position = self.positions.get(
            destination_id,
            0,
        )

        position %= len(videos)
        self.positions[destination_id] = position

        return videos[position]

    # ---------------------------------------------------------
    # NEXT VIDEO
    # ---------------------------------------------------------

    def next(self, destination_id: str) -> Optional[dict]:
        videos = self.get_playlist(destination_id)

        if not videos:
            return None

        position = self.positions.get(
            destination_id,
            0,
        )

        position += 1

        if position >= len(videos):
            # Playlist loop.
            position = 0

        self.positions[destination_id] = position

        return videos[position]

    # ---------------------------------------------------------
    # RESET
    # ---------------------------------------------------------

    def reset(self, destination_id: str) -> None:
        if destination_id in self.playlists:
            self.positions[destination_id] = 0

    # ---------------------------------------------------------
    # PREVIEW
    # ---------------------------------------------------------

    def preview_destination(
        self,
        destination_id: str,
    ) -> None:

        playlist = self.get_playlist(destination_id)

        print(f"\n[{destination_id}]")

        if not playlist:
            print("  Playlist: EMPTY")
            return

        folder_name = self.playlists[
            destination_id
        ].get(
            "folder_name",
            "UNKNOWN",
        )

        print(f"  Folder: {folder_name}")
        print(f"  Videos: {len(playlist)}")

        for item in playlist:
            index = item.get("index", "?")
            name = item.get("name", "UNKNOWN")
            local_path = item.get(
                "local_path",
                "",
            )

            exists = Path(local_path).exists()

            print(
                f"    {index}. {name}"
            )

            print(
                f"       "
                f"{'READY' if exists else 'MISSING'}"
            )

    # ---------------------------------------------------------
    # LOOP PREVIEW
    # ---------------------------------------------------------

    def simulate_loop(
        self,
        destination_id: str,
        cycles: int = 2,
    ) -> None:

        if cycles < 1:
            raise ValueError(
                "cycles must be >= 1"
            )

        playlist = self.get_playlist(
            destination_id
        )

        print(
            f"\nLoop simulation: "
            f"{destination_id}"
        )

        if not playlist:
            print("  Playlist is empty.")
            return

        self.reset(destination_id)

        total_steps = len(playlist) * cycles

        for step in range(total_steps):

            current = self.current(
                destination_id
            )

            if not current:
                break

            index = current.get(
                "index",
                "?",
            )

            name = current.get(
                "name",
                "UNKNOWN",
            )

            print(
                f"  {step + 1:02d}. "
                f"[playlist #{index}] "
                f"{name}"
            )

            self.next(destination_id)

    # ---------------------------------------------------------
    # ALL DESTINATIONS
    # ---------------------------------------------------------

    def preview_all(self) -> None:

        print("\n" + "=" * 60)
        print("PLAYLIST PLAYBACK ENGINE")
        print("=" * 60)

        for destination_id in self.destination_ids():
            self.preview_destination(
                destination_id
            )

        print("\n" + "=" * 60)
        print("PLAYBACK ENGINE STATUS")
        print("=" * 60)

        for destination_id in self.destination_ids():

            info = self.status(
                destination_id
            )

            print(
                f"{destination_id}: "
                f"videos={info['total_videos']} | "
                f"current="
                f"{info['current_video'] or 'NONE'} | "
                f"ready={info['ready']}"
            )

        print("\nNo FFmpeg process was started.")
        print("No real streaming destination was used.")


# =============================================================
# TEST
# =============================================================

def main():

    print("=" * 60)
    print("PLAYLIST PLAYBACK ENGINE TEST")
    print("=" * 60)

    engine = PlaylistPlaybackEngine()

    print(
        f"Playlist file:\n"
        f"{engine.playlist_file}"
    )

    engine.load()

    print(
        f"\nLoaded destinations: "
        f"{len(engine.destination_ids())}"
    )

    engine.preview_all()

    # Demonstrate looping only when a playlist has videos.
    for destination_id in engine.destination_ids():

        if engine.get_playlist(destination_id):

            engine.simulate_loop(
                destination_id,
                cycles=2,
            )

            break

    print("\n" + "=" * 60)
    print("PLAYLIST PLAYBACK TEST SUCCESS")
    print("=" * 60)

    print(
        "Playlist sequencing and looping were tested."
    )

    print(
        "No FFmpeg process was started."
    )


if __name__ == "__main__":
    main()
