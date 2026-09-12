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


class StreamSchedulerV14:
    """
    Playlist scheduler for independent streaming destinations.

    Responsibilities:
    - Maintain independent playback position per destination.
    - Select the current playlist video.
    - Advance to the next video.
    - Loop back to the first video.
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
    # PLAYLIST
    # ---------------------------------------------------------

    def _videos(self, destination_id: str) -> list[dict]:
        playlist = self.controller.playlists.get(destination_id, {})

        if not isinstance(playlist, dict):
            return []

        videos = playlist.get("videos", [])

        if not isinstance(videos, list):
            return []

        return videos

    # ---------------------------------------------------------
    # CURRENT VIDEO
    # ---------------------------------------------------------

    def current(self, destination_id: str) -> Optional[dict]:
        videos = self._videos(destination_id)

        if not videos:
            return None

        state = self.states[destination_id]

        if state.position >= len(videos):
            state.position = 0

        video = videos[state.position]

        if isinstance(video, dict):
            state.current_video = video.get("name")

        return video

    # ---------------------------------------------------------
    # ADVANCE
    # ---------------------------------------------------------

    def next(self, destination_id: str) -> Optional[dict]:
        videos = self._videos(destination_id)

        if not videos:
            return None

        state = self.states[destination_id]

        state.position += 1
        state.transitions += 1

        if state.position >= len(videos):
            state.position = 0

        video = videos[state.position]

        if isinstance(video, dict):
            state.current_video = video.get("name")

        return video

    # ---------------------------------------------------------
    # START SCHEDULER STATE
    # ---------------------------------------------------------

    def start(self, destination_id: str) -> dict:
        if destination_id not in self.controller.destinations:
            return {
                "started": False,
                "reason": "DESTINATION_NOT_FOUND",
            }

        validation = self.controller.validate(destination_id)

        if not validation["ready"]:
            return {
                "started": False,
                "reason": validation["reason"],
            }

        state = self.states[destination_id]

        current = self.current(destination_id)

        if not current:
            return {
                "started": False,
                "reason": "PLAYLIST_EMPTY",
            }

        state.running = True

        return {
            "started": True,
            "reason": "READY",
            "position": state.position + 1,
            "current": state.current_video,
        }

    # ---------------------------------------------------------
    # STOP SCHEDULER STATE
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
            }

        videos = self._videos(destination_id)

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
            for destination_id in self.controller.destinations
        }


# =============================================================
# TEST
# =============================================================

def main():
    print("=" * 60)
    print("STREAM SCHEDULER v1.4 TEST")
    print("=" * 60)

    controller = StreamingController()
    controller.load()

    scheduler = StreamSchedulerV14(controller)
    scheduler.initialize()

    print(
        f"\n[SCHEDULER] Destinations loaded: "
        f"{len(controller.destinations)}"
    )

    print("\nInitial playlist state:")

    for destination_id in controller.destinations:
        videos = scheduler._videos(destination_id)

        print(
            f"- {destination_id} | "
            f"videos={len(videos)}"
        )

    # ---------------------------------------------------------
    # youtube_01 scheduler test
    # ---------------------------------------------------------

    target = "youtube_01"

    print(f"\nScheduler target: {target}")

    validation = controller.validate(target)

    print(
        f"  Validation: "
        f"{'READY' if validation['ready'] else 'NOT READY'}"
        f" | {validation['reason']}"
    )

    if validation["ready"]:
        result = scheduler.start(target)

        print(
            f"  Start: "
            f"{'OK' if result['started'] else 'BLOCKED'}"
        )

        print(
            f"  Current: "
            f"{result.get('current')}"
        )

        print(
            f"  Position: "
            f"{result.get('position')}"
        )

        print("\nPlayback transition simulation:")

        for step in range(1, 4):
            video = scheduler.next(target)

            print(
                f"  {step}. "
                f"position={scheduler.states[target].position + 1} | "
                f"{video.get('name') if video else 'NONE'}"
            )

    else:
        print(
            "  Scheduler start blocked safely."
        )

    # ---------------------------------------------------------
    # Isolation test
    # ---------------------------------------------------------

    print("\nDestination isolation test:")

    state_01 = scheduler.states["youtube_01"]
    state_02 = scheduler.states["youtube_02"]

    print(
        f"  youtube_01 | "
        f"position={state_01.position + 1} | "
        f"transitions={state_01.transitions}"
    )

    print(
        f"  youtube_02 | "
        f"position={state_02.position + 1} | "
        f"transitions={state_02.transitions}"
    )

    if (
        state_01.transitions > 0
        and state_02.transitions == 0
    ):
        print("  Isolation: OK")
    else:
        print("  Isolation: CHECK")

    scheduler.stop(target)

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
    print("STREAM SCHEDULER v1.4 TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()