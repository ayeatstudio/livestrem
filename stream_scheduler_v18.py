from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from streaming_controller_v10 import StreamingController


@dataclass
class DestinationPlayback:
    destination_id: str

    position: int = 0
    phase: str = "IDLE"

    transitions: int = 0
    failures: int = 0

    current: Optional[dict] = None
    last_error: Optional[str] = None

    started_at: Optional[float] = None

    # -----------------------------------------------------
    # PLAYLIST
    # -----------------------------------------------------

    def load(self, playlist: dict) -> None:
        videos = playlist.get("videos", [])

        if not isinstance(videos, list) or not videos:
            self.position = 0
            self.current = None
            self.phase = "IDLE"
            return

        if self.position < 1 or self.position > len(videos):
            self.position = 1

        self.current = videos[self.position - 1]

    def advance(self, playlist: dict) -> Optional[dict]:
        videos = playlist.get("videos", [])

        if not isinstance(videos, list) or not videos:
            self.current = None
            self.position = 0
            return None

        if self.position < 1:
            self.position = 1

        else:
            self.position += 1

            if self.position > len(videos):
                self.position = 1

        self.current = videos[self.position - 1]
        self.transitions += 1

        return self.current


class StreamSchedulerV18:
    """
    Scheduler v1.8

    Responsibilities:
    - Maintain independent playback state per destination.
    - Sequence playlist videos.
    - Loop playlists.
    - Keep destination state isolated.
    - Validate before runtime start.
    - Integrate with StreamingController.
    - Never automatically start real RTMP during tests.
    """

    def __init__(self):
        self.controller = StreamingController()
        self.controller.load()

        self.playback: dict[str, DestinationPlayback] = {}

        for destination_id in self.controller.destinations:
            state = DestinationPlayback(destination_id)

            playlist = self.controller.playlists.get(
                destination_id,
                {},
            )

            if isinstance(playlist, dict):
                state.load(playlist)

            self.playback[destination_id] = state

    # ---------------------------------------------------------
    # DESTINATION
    # ---------------------------------------------------------

    def get_destination_ids(self) -> list[str]:
        return list(self.controller.destinations.keys())

    # ---------------------------------------------------------
    # PLAYLIST
    # ---------------------------------------------------------

    def playlist(self, destination_id: str) -> dict:
        playlist = self.controller.playlists.get(
            destination_id,
            {},
        )

        return playlist if isinstance(playlist, dict) else {}

    def current_video(self, destination_id: str) -> Optional[dict]:
        state = self.playback.get(destination_id)

        if not state:
            return None

        return state.current

    def current_name(self, destination_id: str) -> Optional[str]:
        video = self.current_video(destination_id)

        if not video:
            return None

        return video.get("name")

    # ---------------------------------------------------------
    # TRANSITION
    # ---------------------------------------------------------

    def transition(self, destination_id: str) -> Optional[dict]:
        state = self.playback.get(destination_id)

        if not state:
            raise ValueError(
                f"Unknown destination: {destination_id}"
            )

        playlist = self.playlist(destination_id)

        if not playlist.get("videos"):
            state.current = None
            state.position = 0
            state.phase = "IDLE"

            return None

        next_video = state.advance(playlist)

        if next_video:
            state.phase = "PLAYING"

        return next_video

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
        execute: bool = False,
    ) -> dict:

        state = self.playback.get(destination_id)

        if not state:
            return {
                "started": False,
                "reason": "DESTINATION_NOT_FOUND",
                "ffmpeg_started": False,
            }

        validation = self.validate(destination_id)

        if not validation.get("ready"):
            state.phase = "FAILED"
            state.last_error = validation.get("reason")

            return {
                "started": False,
                "reason": validation.get("reason"),
                "ffmpeg_started": False,
            }

        playlist = self.playlist(destination_id)

        state.load(playlist)

        if not state.current:
            state.phase = "FAILED"
            state.last_error = "PLAYLIST_EMPTY"

            return {
                "started": False,
                "reason": "PLAYLIST_EMPTY",
                "ffmpeg_started": False,
            }

        # -----------------------------------------------------
        # SAFETY GATE
        # -----------------------------------------------------
        #
        # v1.8 tests do NOT execute RTMP unless explicitly
        # requested through execute=True.
        #

        if not execute:
            state.phase = "PLAYING"
            state.started_at = time.time()

            return {
                "started": True,
                "reason": "VALIDATED_TEST_MODE",
                "ffmpeg_started": False,
                "current": state.current.get("name"),
                "position": state.position,
            }

        # -----------------------------------------------------
        # REAL CONTROLLER START
        # -----------------------------------------------------

        try:
            process = self.controller.start(destination_id)

            state.phase = "PLAYING"
            state.started_at = time.time()
            state.last_error = None

            return {
                "started": True,
                "reason": "FFMPEG_STARTED",
                "ffmpeg_started": True,
                "pid": process.pid,
                "current": state.current.get("name"),
                "position": state.position,
            }

        except Exception as exc:
            state.phase = "FAILED"
            state.failures += 1
            state.last_error = str(exc)

            return {
                "started": False,
                "reason": str(exc),
                "ffmpeg_started": False,
            }

    # ---------------------------------------------------------
    # STOP
    # ---------------------------------------------------------

    def stop(self, destination_id: str) -> None:
        state = self.playback.get(destination_id)

        if not state:
            return

        self.controller.stop(destination_id)

        state.phase = "IDLE"
        state.started_at = None

    # ---------------------------------------------------------
    # STOP ALL
    # ---------------------------------------------------------

    def stop_all(self) -> None:
        self.controller.stop_all()

        for state in self.playback.values():
            state.phase = "IDLE"
            state.started_at = None

    # ---------------------------------------------------------
    # RUNTIME TRANSITION
    # ---------------------------------------------------------

    def runtime_transition(
        self,
        destination_id: str,
        execute: bool = False,
    ) -> dict:

        state = self.playback.get(destination_id)

        if not state:
            return {
                "success": False,
                "reason": "DESTINATION_NOT_FOUND",
            }

        playlist = self.playlist(destination_id)

        videos = playlist.get("videos", [])

        if not isinstance(videos, list) or not videos:
            state.phase = "FAILED"
            state.last_error = "PLAYLIST_EMPTY"

            return {
                "success": False,
                "reason": "PLAYLIST_EMPTY",
            }

        previous = state.current

        # -----------------------------------------------------
        # Stop current FFmpeg session first.
        # -----------------------------------------------------

        if execute:
            self.controller.stop(destination_id)

        next_video = state.advance(playlist)

        if not next_video:
            state.phase = "FAILED"

            return {
                "success": False,
                "reason": "NEXT_VIDEO_NOT_FOUND",
            }

        # -----------------------------------------------------
        # TEST MODE
        # -----------------------------------------------------

        if not execute:
            state.phase = "PLAYING"

            return {
                "success": True,
                "previous": (
                    previous.get("name")
                    if previous
                    else None
                ),
                "current": next_video.get("name"),
                "position": state.position,
                "transition": state.transitions,
                "ffmpeg_started": False,
            }

        # -----------------------------------------------------
        # REAL MODE
        # -----------------------------------------------------

        try:
            process = self.controller.start(destination_id)

            state.phase = "PLAYING"
            state.started_at = time.time()
            state.last_error = None

            return {
                "success": True,
                "previous": (
                    previous.get("name")
                    if previous
                    else None
                ),
                "current": next_video.get("name"),
                "position": state.position,
                "transition": state.transitions,
                "ffmpeg_started": True,
                "pid": process.pid,
            }

        except Exception as exc:
            state.phase = "FAILED"
            state.failures += 1
            state.last_error = str(exc)

            return {
                "success": False,
                "reason": str(exc),
                "previous": (
                    previous.get("name")
                    if previous
                    else None
                ),
                "current": next_video.get("name"),
                "position": state.position,
                "ffmpeg_started": False,
            }

    # ---------------------------------------------------------
    # STATUS
    # ---------------------------------------------------------

    def status(self, destination_id: str) -> dict:
        state = self.playback.get(destination_id)

        if not state:
            return {
                "destination_id": destination_id,
                "phase": "NOT FOUND",
            }

        process_status = self.controller.status(
            destination_id
        )

        return {
            "destination_id": destination_id,
            "phase": state.phase,
            "position": (
                state.position
                if state.position > 0
                else None
            ),
            "current": (
                state.current.get("name")
                if state.current
                else None
            ),
            "transitions": state.transitions,
            "failures": state.failures,
            "process": process_status.get(
                "status",
                "STOPPED",
            ),
            "pid": process_status.get("pid"),
            "error": state.last_error,
        }

    def all_status(self) -> dict[str, dict]:
        return {
            destination_id: self.status(destination_id)
            for destination_id in self.playback
        }


# =============================================================
# TEST
# =============================================================

def main():
    print("=" * 60)
    print("STREAM SCHEDULER v1.8 TEST")
    print("=" * 60)

    scheduler = StreamSchedulerV18()

    print(
        f"\n[SCHEDULER] Destinations loaded: "
        f"{len(scheduler.get_destination_ids())}"
    )

    # ---------------------------------------------------------
    # PLAYLIST DISCOVERY
    # ---------------------------------------------------------

    print("\nPlaylist discovery:")

    for destination_id in scheduler.get_destination_ids():
        playlist = scheduler.playlist(destination_id)
        videos = playlist.get("videos", [])

        print(
            f"- {destination_id} | "
            f"videos={len(videos) if isinstance(videos, list) else 0}"
        )

    # ---------------------------------------------------------
    # LIFECYCLE TEST
    # ---------------------------------------------------------

    target = "youtube_01"

    print(f"\nLifecycle test: {target}")

    state = scheduler.status(target)

    print(
        f"  Initial: "
        f"phase={state['phase']} | "
        f"position={state['position']} | "
        f"current={state['current']}"
    )

    result = scheduler.start(
        target,
        execute=False,
    )

    print(
        f"  Start result: "
        f"started={result.get('started')} | "
        f"ffmpeg_started={result.get('ffmpeg_started')} | "
        f"reason={result.get('reason')}"
    )

    state = scheduler.status(target)

    print(
        f"  After start: "
        f"phase={state['phase']} | "
        f"position={state['position']} | "
        f"current={state['current']}"
    )

    # ---------------------------------------------------------
    # TRANSITION TEST
    # ---------------------------------------------------------

    print("\nRuntime transition test:")

    transition = scheduler.runtime_transition(
        target,
        execute=False,
    )

    print(
        f"  Previous: {transition.get('previous')}"
    )

    print(
        f"  Current: {transition.get('current')}"
    )

    print(
        f"  Position: {transition.get('position')}"
    )

    print(
        f"  Transition count: "
        f"{transition.get('transition')}"
    )

    print(
        f"  FFmpeg started: "
        f"{transition.get('ffmpeg_started')}"
    )

    # ---------------------------------------------------------
    # LOOP TEST
    # ---------------------------------------------------------

    print("\nLoop test:")

    playlist = scheduler.playlist(target)
    videos = playlist.get("videos", [])

    if isinstance(videos, list) and videos:
        expected_position = (
            ((len(videos) - 1) % len(videos)) + 1
        )

        scheduler.runtime_transition(
            target,
            execute=False,
        )

        state = scheduler.status(target)

        print(
            f"  Playlist size: {len(videos)}"
        )

        print(
            f"  Position after transition: "
            f"{state['position']}"
        )

        print(
            "  Loop behavior: "
            f"{'OK' if state['position'] == 1 else 'CHECK'}"
        )

    else:
        print("  Playlist empty: SKIPPED")

    # ---------------------------------------------------------
    # DESTINATION ISOLATION
    # ---------------------------------------------------------

    print("\nDestination isolation test:")

    first = scheduler.status("youtube_01")
    second = scheduler.status("youtube_02")

    print(
        f"  youtube_01 | "
        f"phase={first['phase']} | "
        f"position={first['position']} | "
        f"transitions={first['transitions']}"
    )

    print(
        f"  youtube_02 | "
        f"phase={second['phase']} | "
        f"position={second['position']} | "
        f"transitions={second['transitions']}"
    )

    isolated = (
        first["transitions"] > second["transitions"]
        and second["transitions"] == 0
    )

    print(
        f"  Isolation: "
        f"{'OK' if isolated else 'CHECK'}"
    )

    # ---------------------------------------------------------
    # SAFETY TEST
    # ---------------------------------------------------------

    print("\nDisabled destination safety test:")

    validation = scheduler.validate(target)

    print(
        f"  Validation: "
        f"{'READY' if validation['ready'] else 'NOT READY'} | "
        f"{validation['reason']}"
    )

    # We deliberately do not execute real RTMP.
    safe_start = scheduler.start(
        target,
        execute=False,
    )

    print(
        f"  Test-mode start: "
        f"{'ALLOWED' if safe_start['started'] else 'BLOCKED'}"
    )

    print(
        "  Real FFmpeg: NOT EXECUTED"
    )

    # ---------------------------------------------------------
    # CLEANUP
    # ---------------------------------------------------------

    scheduler.stop_all()

    print("\nFinal scheduler status:")

    for destination_id, info in scheduler.all_status().items():
        print(
            f"- {destination_id} | "
            f"phase={info['phase']} | "
            f"position={info['position']} | "
            f"current={info['current']} | "
            f"transitions={info['transitions']} | "
            f"process={info['process']}"
        )

    print("\nReal FFmpeg streaming: NOT EXECUTED")
    print("No real RTMP destination was used.")

    print("=" * 60)
    print("STREAM SCHEDULER v1.8 TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()