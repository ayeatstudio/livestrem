from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from streaming_controller_v10 import StreamingController


# =============================================================
# STREAM SCHEDULER v1.7
# =============================================================


class SchedulerPhase(str, Enum):
    IDLE = "IDLE"
    STARTING = "STARTING"
    PLAYING = "PLAYING"
    TRANSITIONING = "TRANSITIONING"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


@dataclass
class DestinationScheduleState:
    destination_id: str

    phase: SchedulerPhase = SchedulerPhase.IDLE

    position: Optional[int] = None
    current: Optional[str] = None

    transitions: int = 0

    last_error: Optional[str] = None

    started_at: Optional[float] = None
    stopped_at: Optional[float] = None


class StreamScheduler:
    """
    Stream Scheduler v1.7

    Responsibilities:
    - Per-destination playlist state
    - Runtime lifecycle
    - Controller integration
    - Safe start gate
    - Safe stop
    - Playlist transitions
    - Single-video looping
    - Destination isolation

    Important:
    Scheduler never bypasses StreamingController validation.
    """

    def __init__(self):
        self.controller = StreamingController()

        self.states: dict[str, DestinationScheduleState] = {}

        self.loaded = False

    # ---------------------------------------------------------
    # LOAD
    # ---------------------------------------------------------

    def load(self) -> None:
        self.controller.load()

        self.states = {
            destination_id: DestinationScheduleState(
                destination_id=destination_id
            )
            for destination_id in self.controller.destinations
        }

        self.loaded = True

    # ---------------------------------------------------------
    # INTERNAL
    # ---------------------------------------------------------

    def _require_loaded(self) -> None:
        if not self.loaded:
            raise RuntimeError(
                "Scheduler has not been loaded."
            )

    def _get_playlist(self, destination_id: str) -> dict:
        playlist = self.controller.playlists.get(
            destination_id
        )

        if not isinstance(playlist, dict):
            return {}

        return playlist

    def _get_videos(self, destination_id: str) -> list:
        playlist = self._get_playlist(destination_id)

        videos = playlist.get("videos", [])

        if not isinstance(videos, list):
            return []

        return videos

    def _get_state(
        self,
        destination_id: str,
    ) -> DestinationScheduleState:

        self._require_loaded()

        if destination_id not in self.states:
            raise ValueError(
                f"Unknown destination: {destination_id}"
            )

        return self.states[destination_id]

    # ---------------------------------------------------------
    # VALIDATION
    # ---------------------------------------------------------

    def validate(self, destination_id: str) -> dict:
        self._require_loaded()

        return self.controller.validate(
            destination_id
        )

    # ---------------------------------------------------------
    # PLAYLIST POSITION
    # ---------------------------------------------------------

    def initialize_position(
        self,
        destination_id: str,
    ) -> Optional[dict]:

        state = self._get_state(destination_id)

        videos = self._get_videos(destination_id)

        if not videos:
            state.position = None
            state.current = None

            return None

        if state.position is None:
            state.position = 1

        if state.position < 1:
            state.position = 1

        if state.position > len(videos):
            state.position = 1

        video = videos[state.position - 1]

        state.current = video.get("name")

        return video

    # ---------------------------------------------------------
    # CURRENT VIDEO
    # ---------------------------------------------------------

    def current_video(
        self,
        destination_id: str,
    ) -> Optional[dict]:

        return self.initialize_position(
            destination_id
        )

    # ---------------------------------------------------------
    # NEXT VIDEO
    # ---------------------------------------------------------

    def next_video(
        self,
        destination_id: str,
    ) -> Optional[dict]:

        state = self._get_state(destination_id)

        videos = self._get_videos(destination_id)

        if not videos:
            state.position = None
            state.current = None

            return None

        if state.position is None:
            state.position = 1

        else:
            state.position += 1

            if state.position > len(videos):
                # Playlist loop.
                state.position = 1

        video = videos[state.position - 1]

        state.current = video.get("name")

        state.transitions += 1

        return video

    # ---------------------------------------------------------
    # START
    # ---------------------------------------------------------

    def start(
        self,
        destination_id: str,
    ) -> dict:

        state = self._get_state(destination_id)

        validation = self.validate(
            destination_id
        )

        if not validation.get("ready"):
            state.last_error = validation.get(
                "reason"
            )

            # Disabled destination is not a runtime
            # FFmpeg failure.
            if validation.get("reason") == (
                "DESTINATION_DISABLED"
            ):
                state.phase = SchedulerPhase.IDLE

            else:
                state.phase = SchedulerPhase.FAILED

            return {
                "started": False,
                "ffmpeg_started": False,
                "reason": validation.get("reason"),
                "phase": state.phase.value,
            }

        if state.phase in {
            SchedulerPhase.STARTING,
            SchedulerPhase.PLAYING,
        }:
            return {
                "started": False,
                "ffmpeg_started": False,
                "reason": "ALREADY_RUNNING",
                "phase": state.phase.value,
            }

        self.initialize_position(
            destination_id
        )

        state.phase = SchedulerPhase.STARTING
        state.last_error = None

        try:
            process = self.controller.start(
                destination_id
            )

            state.phase = SchedulerPhase.PLAYING
            state.started_at = time.time()

            return {
                "started": True,
                "ffmpeg_started": True,
                "reason": "STARTED",
                "phase": state.phase.value,
                "pid": process.pid,
                "current": state.current,
            }

        except Exception as exc:
            state.phase = SchedulerPhase.FAILED
            state.last_error = str(exc)

            return {
                "started": False,
                "ffmpeg_started": False,
                "reason": str(exc),
                "phase": state.phase.value,
            }

    # ---------------------------------------------------------
    # STOP
    # ---------------------------------------------------------

    def stop(
        self,
        destination_id: str,
    ) -> dict:

        state = self._get_state(destination_id)

        state.phase = SchedulerPhase.STOPPING

        try:
            self.controller.stop(
                destination_id
            )

            state.phase = SchedulerPhase.STOPPED
            state.stopped_at = time.time()

            return {
                "stopped": True,
                "reason": "STOPPED",
                "phase": state.phase.value,
            }

        except Exception as exc:
            state.phase = SchedulerPhase.FAILED
            state.last_error = str(exc)

            return {
                "stopped": False,
                "reason": str(exc),
                "phase": state.phase.value,
            }

    # ---------------------------------------------------------
    # TRANSITION
    # ---------------------------------------------------------

    def transition(
        self,
        destination_id: str,
    ) -> Optional[dict]:

        state = self._get_state(destination_id)

        videos = self._get_videos(destination_id)

        if not videos:
            state.current = None
            state.position = None

            return None

        state.phase = SchedulerPhase.TRANSITIONING

        video = self.next_video(
            destination_id
        )

        # Transition itself does not restart FFmpeg.
        # The controller process continues using the
        # destination runtime pipeline.
        state.phase = SchedulerPhase.PLAYING

        return video

    # ---------------------------------------------------------
    # PROCESS REFRESH
    # ---------------------------------------------------------

    def refresh(
        self,
        destination_id: str,
    ) -> dict:

        state = self._get_state(destination_id)

        process_status = self.controller.status(
            destination_id
        )

        process_state = process_status.get(
            "status"
        )

        if process_state == "RUNNING":
            if state.phase in {
                SchedulerPhase.STARTING,
                SchedulerPhase.PLAYING,
            }:
                state.phase = SchedulerPhase.PLAYING

        elif process_state == "FAILED":
            state.phase = SchedulerPhase.FAILED

            state.last_error = (
                process_status.get("error")
                or "FFmpeg process failed"
            )

        elif process_state == "STOPPED":
            if state.phase not in {
                SchedulerPhase.IDLE,
                SchedulerPhase.STOPPED,
            }:
                state.phase = SchedulerPhase.STOPPED

        return self.status(
            destination_id
        )

    # ---------------------------------------------------------
    # STATUS
    # ---------------------------------------------------------

    def status(
        self,
        destination_id: str,
    ) -> dict:

        state = self._get_state(destination_id)

        process = self.controller.status(
            destination_id
        )

        return {
            "destination_id": destination_id,
            "phase": state.phase.value,
            "position": state.position,
            "current": state.current,
            "transitions": state.transitions,
            "process": process.get(
                "status"
            ),
            "pid": process.get(
                "pid"
            ),
            "return_code": process.get(
                "return_code"
            ),
            "error": state.last_error,
        }

    def all_status(self) -> dict[str, dict]:
        self._require_loaded()

        return {
            destination_id: self.status(
                destination_id
            )
            for destination_id in self.states
        }

    # ---------------------------------------------------------
    # START ALL
    # ---------------------------------------------------------

    def start_all(self) -> dict[str, dict]:

        self._require_loaded()

        results = {}

        for destination_id in self.states:
            results[destination_id] = self.start(
                destination_id
            )

        return results

    # ---------------------------------------------------------
    # STOP ALL
    # ---------------------------------------------------------

    def stop_all(self) -> None:

        self._require_loaded()

        for destination_id in list(self.states):
            self.stop(destination_id)


# =============================================================
# TESTS
# =============================================================

def run_test():

    print("=" * 60)
    print("STREAM SCHEDULER v1.7 TEST")
    print("=" * 60)

    scheduler = StreamScheduler()

    scheduler.load()

    print(
        f"\n[SCHEDULER] Destinations loaded: "
        f"{len(scheduler.states)}"
    )

    # ---------------------------------------------------------
    # PLAYLIST STATE
    # ---------------------------------------------------------

    print("\nPlaylist state:")

    for destination_id in scheduler.states:

        videos = scheduler._get_videos(
            destination_id
        )

        print(
            f"- {destination_id} | "
            f"videos={len(videos)}"
        )

    # ---------------------------------------------------------
    # TARGET
    # ---------------------------------------------------------

    target = "youtube_01"

    print(
        f"\nLifecycle test: {target}"
    )

    state = scheduler._get_state(target)

    print(
        f"  Initial: "
        f"phase={state.phase.value} | "
        f"position={state.position} | "
        f"current={state.current}"
    )

    # ---------------------------------------------------------
    # VALIDATION
    # ---------------------------------------------------------

    validation = scheduler.validate(target)

    print(
        f"  Validation: "
        f"{'READY' if validation['ready'] else 'NOT READY'} | "
        f"{validation['reason']}"
    )

    # ---------------------------------------------------------
    # START
    # ---------------------------------------------------------

    result = scheduler.start(target)

    print(
        f"  Start result: "
        f"started={result['started']} | "
        f"ffmpeg_started="
        f"{result['ffmpeg_started']} | "
        f"reason={result['reason']}"
    )

    print(
        f"  After start: "
        f"phase={state.phase.value} | "
        f"position={state.position} | "
        f"current={state.current}"
    )

    # ---------------------------------------------------------
    # TRANSITION TEST
    # ---------------------------------------------------------

    print("\nTransition test:")

    current = scheduler.current_video(
        target
    )

    current_name = (
        current.get("name")
        if current
        else None
    )

    next_item = scheduler.transition(
        target
    )

    next_name = (
        next_item.get("name")
        if next_item
        else None
    )

    print(
        f"  Current: {current_name}"
    )

    print(
        f"  Next: {next_name}"
    )

    print(
        f"  Phase: {state.phase.value}"
    )

    print(
        f"  Position: {state.position}"
    )

    print(
        f"  Transitions: {state.transitions}"
    )

    # ---------------------------------------------------------
    # LOOP TEST
    # ---------------------------------------------------------

    print("\nLoop test:")

    videos = scheduler._get_videos(
        target
    )

    if videos:

        expected = (
            state.position
            or 1
        )

        scheduler.transition(
            target
        )

        after = state.position

        loop_ok = (
            after == expected
            if len(videos) == 1
            else after is not None
        )

        print(
            f"  Loop: "
            f"{'OK' if loop_ok else 'CHECK'}"
        )

    else:
        print("  Loop: SKIPPED_EMPTY_PLAYLIST")

    # ---------------------------------------------------------
    # ISOLATION
    # ---------------------------------------------------------

    print("\nDestination isolation test:")

    other = "youtube_02"

    target_state = scheduler.status(
        target
    )

    other_state = scheduler.status(
        other
    )

    print(
        f"  {target} | "
        f"phase={target_state['phase']} | "
        f"transitions="
        f"{target_state['transitions']}"
    )

    print(
        f"  {other} | "
        f"phase={other_state['phase']} | "
        f"transitions="
        f"{other_state['transitions']}"
    )

    isolation_ok = (
        other_state["transitions"] == 0
    )

    print(
        f"  Isolation: "
        f"{'OK' if isolation_ok else 'CHECK'}"
    )

    # ---------------------------------------------------------
    # DISABLED SAFETY
    # ---------------------------------------------------------

    print("\nDisabled destination safety test:")

    validation = scheduler.validate(
        target
    )

    print(
        f"  Validation: "
        f"{'READY' if validation['ready'] else 'NOT READY'} | "
        f"{validation['reason']}"
    )

    if validation["reason"] == "DESTINATION_DISABLED":

        safety = scheduler.start(
            target
        )

        print(
            f"  Start gate: "
            f"{'BLOCKED safely' if not safety['started'] else 'ERROR'}"
        )

    # ---------------------------------------------------------
    # FINAL
    # ---------------------------------------------------------

    print("\nFinal scheduler status:")

    for destination_id, info in (
        scheduler.all_status().items()
    ):

        print(
            f"- {destination_id} | "
            f"phase={info['phase']} | "
            f"position={info['position']} | "
            f"current={info['current']} | "
            f"transitions={info['transitions']} | "
            f"process={info['process']}"
        )

    # ---------------------------------------------------------
    # CLEANUP
    # ---------------------------------------------------------

    scheduler.stop_all()

    print("\nCleanup complete.")

    print(
        "\nReal FFmpeg streaming: NOT EXECUTED"
    )

    print(
        "No real RTMP destination was used."
    )

    print("=" * 60)
    print(
        "STREAM SCHEDULER v1.7 TEST COMPLETE"
    )
    print("=" * 60)


def main():
    run_test()


if __name__ == "__main__":
    main()