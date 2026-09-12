from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from streaming_controller_v10 import StreamingController


@dataclass
class SchedulerState:
    destination_id: str
    position: int = 0
    current_video: Optional[str] = None
    transitions: int = 0
    running: bool = False


class StreamSchedulerV15:
    """
    Playlist scheduler v1.5.

    Responsibilities:
    - Maintain an independent playback cursor per destination.
    - Select the current playlist item.
    - Advance to the next item.
    - Loop back to item #1.
    - Keep destination states isolated.
    - Never start FFmpeg automatically.
    """

    def __init__(self, controller: StreamingController):
        self.controller = controller
        self.states: dict[str, SchedulerState] = {}

    # ---------------------------------------------------------
    # INITIALIZE
    # ---------------------------------------------------------

    def initialize(self) -> None:
        self.states = {}

        for destination_id in self.controller.destinations:
            self.states[destination_id] = SchedulerState(
                destination_id=destination_id
            )

    # ---------------------------------------------------------
    # PLAYLIST ACCESS
    # ---------------------------------------------------------

    def get_videos(self, destination_id: str) -> list[dict]:
        playlist = self.controller.playlists.get(
            destination_id,
            {}
        )

        if not isinstance(playlist, dict):
            return []

        videos = playlist.get("videos", [])

        if not isinstance(videos, list):
            return []

        return [
            video
            for video in videos
            if isinstance(video, dict)
        ]

    # ---------------------------------------------------------
    # CURRENT
    # ---------------------------------------------------------

    def current(self, destination_id: str) -> Optional[dict]:
        videos = self.get_videos(destination_id)

        if not videos:
            state = self.states[destination_id]
            state.current_video = None
            return None

        state = self.states[destination_id]

        if state.position >= len(videos):
            state.position = 0

        video = videos[state.position]

        state.current_video = video.get("name")

        return video

    # ---------------------------------------------------------
    # ADVANCE
    # ---------------------------------------------------------

    def advance(self, destination_id: str) -> Optional[dict]:
        videos = self.get_videos(destination_id)

        if not videos:
            return None

        state = self.states[destination_id]

        previous_position = state.position

        state.position += 1
        state.transitions += 1

        # Loop back to first video.
        if state.position >= len(videos):
            state.position = 0

        video = videos[state.position]

        state.current_video = video.get("name")

        return video

    # ---------------------------------------------------------
    # RESET
    # ---------------------------------------------------------

    def reset(self, destination_id: str) -> None:
        state = self.states[destination_id]

        state.position = 0
        state.current_video = None
        state.transitions = 0
        state.running = False

    # ---------------------------------------------------------
    # START SCHEDULER STATE
    # ---------------------------------------------------------

    def start(self, destination_id: str) -> dict:
        if destination_id not in self.states:
            return {
                "started": False,
                "reason": "DESTINATION_NOT_FOUND",
            }

        validation = self.controller.validate(
            destination_id
        )

        if not validation["ready"]:
            return {
                "started": False,
                "reason": validation["reason"],
            }

        video = self.current(destination_id)

        if not video:
            return {
                "started": False,
                "reason": "PLAYLIST_EMPTY",
            }

        state = self.states[destination_id]
        state.running = True

        return {
            "started": True,
            "reason": "READY",
            "position": state.position + 1,
            "current": state.current_video,
        }

    # ---------------------------------------------------------
    # STOP
    # ---------------------------------------------------------

    def stop(self, destination_id: str) -> None:
        state = self.states.get(destination_id)

        if state:
            state.running = False

    # ---------------------------------------------------------
    # STATUS
    # ---------------------------------------------------------

    def status(self, destination_id: str) -> dict:
        state = self.states.get(destination_id)

        if not state:
            return {
                "destination_id": destination_id,
                "running": False,
                "position": None,
                "current": None,
                "transitions": 0,
                "playlist_size": 0,
            }

        videos = self.get_videos(destination_id)

        return {
            "destination_id": destination_id,
            "running": state.running,
            "position": (
                state.position + 1
                if videos
                else None
            ),
            "current": state.current_video,
            "transitions": state.transitions,
            "playlist_size": len(videos),
        }

    def all_status(self) -> dict[str, dict]:
        return {
            destination_id: self.status(destination_id)
            for destination_id in self.states
        }


# =============================================================
# TEST
# =============================================================

def main():
    print("=" * 60)
    print("STREAM SCHEDULER v1.5 TEST")
    print("=" * 60)

    controller = StreamingController()
    controller.load()

    scheduler = StreamSchedulerV15(controller)
    scheduler.initialize()

    print(
        f"\n[SCHEDULER] Destinations loaded: "
        f"{len(controller.destinations)}"
    )

    # ---------------------------------------------------------
    # PLAYLIST DISCOVERY
    # ---------------------------------------------------------

    print("\nPlaylist discovery:")

    for destination_id in controller.destinations:
        videos = scheduler.get_videos(destination_id)

        print(
            f"- {destination_id} | "
            f"videos={len(videos)}"
        )

    # ---------------------------------------------------------
    # SEQUENCING TEST
    # ---------------------------------------------------------

    target = "youtube_01"

    videos = scheduler.get_videos(target)

    print(f"\nSequence test: {target}")

    if not videos:
        print("  Playlist empty.")
    else:
        # Initialize current item.
        first = scheduler.current(target)

        print(
            f"  Initial: "
            f"position=1 | "
            f"{first.get('name') if first else 'NONE'}"
        )

        # Advance twice.
        for step in range(1, 3):
            video = scheduler.advance(target)

            print(
                f"  Advance {step}: "
                f"position="
                f"{scheduler.states[target].position + 1} | "
                f"{video.get('name') if video else 'NONE'}"
            )

        # -----------------------------------------------------
        # LOOP TEST
        # -----------------------------------------------------

        state = scheduler.states[target]

        expected_position = 0

        if (
            len(videos) == 1
            and state.position == expected_position
        ):
            print("  Loop behavior: OK")
        elif len(videos) > 1:
            # For multiple videos, explicitly advance until
            # we return to position zero.
            scheduler.reset(target)

            scheduler.current(target)

            for _ in range(len(videos)):
                scheduler.advance(target)

            if scheduler.states[target].position == 0:
                print("  Loop behavior: OK")
            else:
                print("  Loop behavior: CHECK")
        else:
            print("  Loop behavior: CHECK")

    # ---------------------------------------------------------
    # ISOLATION TEST
    # ---------------------------------------------------------

    print("\nDestination isolation test:")

    scheduler.reset("youtube_01")
    scheduler.reset("youtube_02")

    youtube_01_videos = scheduler.get_videos("youtube_01")

    # Snapshot youtube_02 before mutating youtube_01.
    before_02 = scheduler.status("youtube_02")

    # Only mutate youtube_01.
    if youtube_01_videos:
        scheduler.current("youtube_01")
        scheduler.advance("youtube_01")

    after_01 = scheduler.status("youtube_01")
    after_02 = scheduler.status("youtube_02")

    print(
        f"  youtube_01 | "
        f"position={after_01['position']} | "
        f"transitions={after_01['transitions']}"
    )

    print(
        f"  youtube_02 | "
        f"position={after_02['position']} | "
        f"transitions={after_02['transitions']}"
    )

    isolation_ok = (
        after_02["transitions"] == before_02["transitions"]
        and after_02["current"] == before_02["current"]
        and after_02["running"] == before_02["running"]
    )

    if isolation_ok:
        print("  Isolation: OK")
    else:
        print("  Isolation: CHECK")

    # ---------------------------------------------------------
    # FINAL STATUS
    # ---------------------------------------------------------

    print("\nFinal scheduler status:")

    for destination_id, info in scheduler.all_status().items():
        print(
            f"- {destination_id} | "
            f"running={info['running']} | "
            f"position={info['position']} | "
            f"current={info['current']} | "
            f"transitions={info['transitions']}"
        )

    print("\nReal FFmpeg streaming: NOT EXECUTED")
    print("No real RTMP destination was used.")

    print("=" * 60)
    print("STREAM SCHEDULER v1.5 TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()