from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from streaming_controller_v10 import StreamingController


class SchedulerPhase(str, Enum):
    IDLE = "IDLE"
    STARTING = "STARTING"
    PLAYING = "PLAYING"
    TRANSITIONING = "TRANSITIONING"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


@dataclass
class SchedulerState:
    destination_id: str
    position: int = 0
    current_video: Optional[str] = None
    transitions: int = 0
    phase: SchedulerPhase = SchedulerPhase.IDLE
    last_error: Optional[str] = None


class StreamSchedulerV16:
    """
    Scheduler + StreamingController integration.

    The scheduler owns playlist state.
    StreamingController owns FFmpeg processes.

    No automatic real RTMP streaming is performed by this module.
    """

    def __init__(self, controller: StreamingController):
        self.controller = controller
        self.states: dict[str, SchedulerState] = {}

    # ---------------------------------------------------------
    # INITIALIZATION
    # ---------------------------------------------------------

    def initialize(self) -> None:
        self.states = {
            destination_id: SchedulerState(
                destination_id=destination_id
            )
            for destination_id in self.controller.destinations
        }

    # ---------------------------------------------------------
    # PLAYLIST
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
    # CURRENT VIDEO
    # ---------------------------------------------------------

    def current(self, destination_id: str) -> Optional[dict]:
        state = self.states.get(destination_id)

        if not state:
            return None

        videos = self.get_videos(destination_id)

        if not videos:
            state.current_video = None
            state.position = 0
            return None

        if state.position >= len(videos):
            state.position = 0

        video = videos[state.position]

        state.current_video = video.get("name")

        return video

    # ---------------------------------------------------------
    # ADVANCE
    # ---------------------------------------------------------

    def advance(self, destination_id: str) -> Optional[dict]:
        state = self.states.get(destination_id)

        if not state:
            return None

        videos = self.get_videos(destination_id)

        if not videos:
            return None

        state.phase = SchedulerPhase.TRANSITIONING

        state.position += 1
        state.transitions += 1

        if state.position >= len(videos):
            state.position = 0

        video = videos[state.position]

        state.current_video = video.get("name")

        if state.phase == SchedulerPhase.TRANSITIONING:
            state.phase = SchedulerPhase.PLAYING

        return video

    # ---------------------------------------------------------
    # VALIDATION
    # ---------------------------------------------------------

    def validate(self, destination_id: str) -> dict:
        return self.controller.validate(destination_id)

    # ---------------------------------------------------------
    # START
    # ---------------------------------------------------------

    def start(
        self,
        destination_id: str,
        start_ffmpeg: bool = False,
    ) -> dict:
        state = self.states.get(destination_id)

        if not state:
            return {
                "started": False,
                "reason": "DESTINATION_NOT_FOUND",
            }

        validation = self.validate(destination_id)

        if not validation["ready"]:
            state.phase = SchedulerPhase.FAILED
            state.last_error = validation["reason"]

            return {
                "started": False,
                "reason": validation["reason"],
            }

        state.phase = SchedulerPhase.STARTING
        state.last_error = None

        video = self.current(destination_id)

        if not video:
            state.phase = SchedulerPhase.FAILED
            state.last_error = "PLAYLIST_EMPTY"

            return {
                "started": False,
                "reason": "PLAYLIST_EMPTY",
            }

        # -----------------------------------------------------
        # TEST / SAFE MODE
        # -----------------------------------------------------

        if not start_ffmpeg:
            state.phase = SchedulerPhase.PLAYING

            return {
                "started": True,
                "ffmpeg_started": False,
                "reason": "SCHEDULER_READY_TEST_MODE",
                "position": state.position + 1,
                "current": state.current_video,
            }

        # -----------------------------------------------------
        # REAL CONTROLLER INTEGRATION
        # -----------------------------------------------------

        try:
            process = self.controller.start(destination_id)

            state.phase = SchedulerPhase.PLAYING

            return {
                "started": True,
                "ffmpeg_started": True,
                "reason": "STARTED",
                "pid": process.pid,
                "position": state.position + 1,
                "current": state.current_video,
            }

        except Exception as exc:
            state.phase = SchedulerPhase.FAILED
            state.last_error = str(exc)

            return {
                "started": False,
                "ffmpeg_started": False,
                "reason": str(exc),
            }

    # ---------------------------------------------------------
    # STOP
    # ---------------------------------------------------------

    def stop(self, destination_id: str) -> None:
        state = self.states.get(destination_id)

        if not state:
            return

        state.phase = SchedulerPhase.STOPPING

        self.controller.stop(destination_id)

        state.phase = SchedulerPhase.STOPPED

    # ---------------------------------------------------------
    # RESET
    # ---------------------------------------------------------

    def reset(self, destination_id: str) -> None:
        state = self.states.get(destination_id)

        if not state:
            return

        state.position = 0
        state.current_video = None
        state.transitions = 0
        state.phase = SchedulerPhase.IDLE
        state.last_error = None

    # ---------------------------------------------------------
    # STATUS
    # ---------------------------------------------------------

    def status(self, destination_id: str) -> dict:
        state = self.states.get(destination_id)

        if not state:
            return {
                "destination_id": destination_id,
                "phase": SchedulerPhase.FAILED.value,
                "position": None,
                "current": None,
                "transitions": 0,
                "error": "DESTINATION_NOT_FOUND",
            }

        videos = self.get_videos(destination_id)

        controller_status = self.controller.status(
            destination_id
        )

        return {
            "destination_id": destination_id,
            "phase": state.phase.value,
            "position": (
                state.position + 1
                if videos
                else None
            ),
            "current": state.current_video,
            "transitions": state.transitions,
            "error": state.last_error,
            "process_status": controller_status["status"],
            "pid": controller_status["pid"],
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
    print("STREAM SCHEDULER v1.6 TEST")
    print("=" * 60)

    controller = StreamingController()
    controller.load()

    scheduler = StreamSchedulerV16(controller)
    scheduler.initialize()

    print(
        f"\n[SCHEDULER] Destinations loaded: "
        f"{len(controller.destinations)}"
    )

    # ---------------------------------------------------------
    # PLAYLIST STATE
    # ---------------------------------------------------------

    print("\nPlaylist state:")

    for destination_id in controller.destinations:
        videos = scheduler.get_videos(destination_id)

        print(
            f"- {destination_id} | "
            f"videos={len(videos)}"
        )

    # ---------------------------------------------------------
    # LIFECYCLE TEST
    # ---------------------------------------------------------

    target = "youtube_01"

    print(f"\nLifecycle test: {target}")

    initial = scheduler.status(target)

    print(
        f"  Initial: "
        f"phase={initial['phase']} | "
        f"position={initial['position']} | "
        f"current={initial['current']}"
    )

    # Safe test mode: no FFmpeg.
    result = scheduler.start(
        target,
        start_ffmpeg=False,
    )

    print(
        f"  Start result: "
        f"started={result['started']} | "
        f"ffmpeg_started={result.get('ffmpeg_started')} | "
        f"reason={result['reason']}"
    )

    started = scheduler.status(target)

    print(
        f"  After start: "
        f"phase={started['phase']} | "
        f"position={started['position']} | "
        f"current={started['current']}"
    )

    # ---------------------------------------------------------
    # TRANSITION TEST
    # ---------------------------------------------------------

    print("\nTransition test:")

    videos = scheduler.get_videos(target)

    if videos:
        first = scheduler.current(target)

        print(
            f"  Current: "
            f"{first.get('name') if first else 'NONE'}"
        )

        next_video = scheduler.advance(target)

        print(
            f"  Next: "
            f"{next_video.get('name') if next_video else 'NONE'}"
        )

        transition_status = scheduler.status(target)

        print(
            f"  Phase: "
            f"{transition_status['phase']}"
        )

        print(
            f"  Transitions: "
            f"{transition_status['transitions']}"
        )

    else:
        print("  Playlist empty.")

    # ---------------------------------------------------------
    # LOOP TEST
    # ---------------------------------------------------------

    print("\nLoop test:")

    scheduler.reset(target)

    if videos:
        scheduler.current(target)

        for _ in range(len(videos)):
            scheduler.advance(target)

        loop_state = scheduler.status(target)

        if loop_state["position"] == 1:
            print("  Loop: OK")
        else:
            print(
                f"  Loop: CHECK "
                f"(position={loop_state['position']})"
            )
    else:
        print("  Loop: SKIPPED_EMPTY_PLAYLIST")

    # ---------------------------------------------------------
    # ISOLATION TEST
    # ---------------------------------------------------------

    print("\nDestination isolation test:")

    scheduler.reset("youtube_01")
    scheduler.reset("youtube_02")

    if scheduler.get_videos("youtube_01"):
        scheduler.current("youtube_01")
        scheduler.advance("youtube_01")

    state_01 = scheduler.status("youtube_01")
    state_02 = scheduler.status("youtube_02")

    print(
        f"  youtube_01 | "
        f"phase={state_01['phase']} | "
        f"transitions={state_01['transitions']}"
    )

    print(
        f"  youtube_02 | "
        f"phase={state_02['phase']} | "
        f"transitions={state_02['transitions']}"
    )

    if (
        state_01["transitions"] == 1
        and state_02["transitions"] == 0
        and state_02["current"] is None
    ):
        print("  Isolation: OK")
    else:
        print("  Isolation: CHECK")

    # ---------------------------------------------------------
    # DISABLED SAFETY TEST
    # ---------------------------------------------------------

    print("\nDisabled destination safety test:")

    scheduler.reset(target)

    validation = scheduler.validate(target)

    print(
        f"  Validation: "
        f"{'READY' if validation['ready'] else 'NOT READY'} | "
        f"{validation['reason']}"
    )

    blocked = scheduler.start(
        target,
        start_ffmpeg=False,
    )

    if not validation["ready"] and not blocked["started"]:
        print("  Start gate: BLOCKED safely")
    else:
        print("  Start gate: CHECK")

    # ---------------------------------------------------------
    # FINAL STATUS
    # ---------------------------------------------------------

    print("\nFinal scheduler status:")

    for destination_id, info in scheduler.all_status().items():
        print(
            f"- {destination_id} | "
            f"phase={info['phase']} | "
            f"position={info['position']} | "
            f"current={info['current']} | "
            f"transitions={info['transitions']} | "
            f"process={info['process_status']}"
        )

    # Safety cleanup.
    for destination_id in controller.destinations:
        controller.stop(destination_id)

    print("\nReal FFmpeg streaming: NOT EXECUTED")
    print("No real RTMP destination was used.")

    print("=" * 60)
    print("STREAM SCHEDULER v1.6 TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()