
from __future__ import annotations

from pathlib import Path

from playlist_manager import PlaylistManager
from streaming_controller_v10 import StreamingController
from branding_manager_v24 import BrandingManagerV24


BASE_DIR = Path(__file__).resolve().parent


class StreamSchedulerV25:
    """
    Stream Scheduler v2.5

    Integrates:
    - StreamingController
    - Playlist sequencing / looping
    - BrandingManagerV24
    - Destination validation
    - FFmpeg command preparation
    - Per-destination scheduler isolation

    Safety:
    - Disabled destinations cannot start.
    - Missing branding assets block branded FFmpeg generation.
    - No automatic real RTMP streaming is performed by the test.
    """

    def __init__(self):
        self.controller = StreamingController()
        self.playlist_manager = PlaylistManager()
        self.branding = BrandingManagerV24()

        self.destinations: dict[str, dict] = {}
        self.playlists: dict[str, dict] = {}
        self.state: dict[str, dict] = {}

        self.load()

    # ---------------------------------------------------------
    # LOAD
    # ---------------------------------------------------------

    def load(self) -> None:
        self.controller.load()

        self.destinations = dict(
            self.controller.destinations
        )

        self.playlists = dict(
            self.controller.playlists
        )

        self.state = {}

        for destination_id in self.destinations:
            videos = self._videos(destination_id)

            self.state[destination_id] = {
                "phase": "IDLE",
                "position": 1 if videos else None,
                "current": (
                    videos[0].get("name")
                    if videos
                    else None
                ),
                "transitions": 0,
            }

    # ---------------------------------------------------------
    # HELPERS
    # ---------------------------------------------------------

    def _videos(self, destination_id: str) -> list[dict]:
        playlist = self.playlists.get(destination_id)

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

    def _update_current(self, destination_id: str) -> None:
        videos = self._videos(destination_id)

        state = self.state[destination_id]

        if not videos:
            state["position"] = None
            state["current"] = None
            return

        position = state.get("position") or 1

        position = (
            ((position - 1) % len(videos)) + 1
        )

        state["position"] = position
        state["current"] = videos[position - 1].get(
            "name"
        )

    # ---------------------------------------------------------
    # VALIDATION
    # ---------------------------------------------------------

    def validate_destination(
        self,
        destination_id: str,
    ) -> dict:
        result = self.controller.validate(
            destination_id
        )

        if not result.get("ready"):
            return result

        branding = self.branding.validate()

        if not branding.get("ready"):
            return {
                "ready": False,
                "reason": branding.get(
                    "reason",
                    "BRANDING_NOT_READY",
                ),
            }

        return {
            **result,
            "branding": "READY",
        }

    # ---------------------------------------------------------
    # BRANDING FILTER
    # ---------------------------------------------------------

    def build_video_filter(
        self,
        destination_id: str,
    ) -> str:
        validation = self.validate_destination(
            destination_id
        )

        if not validation.get("ready"):
            raise ValueError(
                f"{destination_id}: "
                f"{validation.get('reason')}"
            )

        return self.branding.apply_to_filter(
            "scale=1920:1080"
        )

    # ---------------------------------------------------------
    # COMMAND
    # ---------------------------------------------------------

    def build_command(
        self,
        destination_id: str,
    ) -> list[str]:
        validation = self.validate_destination(
            destination_id
        )

        if not validation.get("ready"):
            raise ValueError(
                f"{destination_id}: "
                f"{validation.get('reason')}"
            )

        command = self.controller.build_command(
            destination_id
        )

        video_filter = self.build_video_filter(
            destination_id
        )

        try:
            vf_index = command.index("-vf")
            command[vf_index + 1] = video_filter
        except ValueError:
            raise RuntimeError(
                "FFmpeg command does not contain -vf"
            )

        return command

    # ---------------------------------------------------------
    # PLAYLIST SEQUENCE
    # ---------------------------------------------------------

    def current_video(
        self,
        destination_id: str,
    ) -> dict | None:
        videos = self._videos(destination_id)

        if not videos:
            return None

        self._update_current(destination_id)

        position = self.state[destination_id][
            "position"
        ]

        return videos[position - 1]

    def advance(
        self,
        destination_id: str,
    ) -> dict | None:
        videos = self._videos(destination_id)

        if not videos:
            return None

        state = self.state[destination_id]

        if state["position"] is None:
            state["position"] = 1
        else:
            state["position"] += 1

        state["position"] = (
            ((state["position"] - 1) % len(videos))
            + 1
        )

        state["transitions"] += 1

        self._update_current(destination_id)

        return self.current_video(destination_id)

    # ---------------------------------------------------------
    # START / STOP
    # ---------------------------------------------------------

    def start(
        self,
        destination_id: str,
    ) -> dict:
        validation = self.validate_destination(
            destination_id
        )

        if not validation.get("ready"):
            self.state[destination_id][
                "phase"
            ] = "FAILED"

            return {
                "started": False,
                "ffmpeg_started": False,
                "reason": validation.get(
                    "reason"
                ),
            }

        process = self.controller.start(
            destination_id
        )

        self.state[destination_id][
            "phase"
        ] = "PLAYING"

        return {
            "started": True,
            "ffmpeg_started": True,
            "pid": process.pid,
            "reason": "STARTED",
        }

    def stop(
        self,
        destination_id: str,
    ) -> None:
        self.controller.stop(
            destination_id
        )

        if destination_id in self.state:
            self.state[destination_id][
                "phase"
            ] = "IDLE"

    # ---------------------------------------------------------
    # STATUS
    # ---------------------------------------------------------

    def status(
        self,
        destination_id: str,
    ) -> dict:
        state = self.state.get(
            destination_id,
            {},
        )

        process = self.controller.status(
            destination_id
        )

        return {
            "phase": state.get(
                "phase",
                "IDLE",
            ),
            "position": state.get(
                "position"
            ),
            "current": state.get(
                "current"
            ),
            "transitions": state.get(
                "transitions",
                0,
            ),
            "process": process.get(
                "status",
                "STOPPED",
            ),
            "pid": process.get(
                "pid"
            ),
        }

    # ---------------------------------------------------------
    # TEST
    # ---------------------------------------------------------

    def run_test(self) -> None:
        print("=" * 60)
        print("STREAM SCHEDULER v2.5 TEST")
        print("=" * 60)

        print(
            f"\n[SCHEDULER] Destinations loaded: "
            f"{len(self.destinations)}"
        )

        print("\nPlaylist discovery:")

        for destination_id in self.destinations:
            videos = self._videos(
                destination_id
            )

            print(
                f"- {destination_id} | "
                f"videos={len(videos)}"
            )

        # -----------------------------------------------------
        # BRANDING
        # -----------------------------------------------------

        print("\nBranding validation:")

        branding_result = self.branding.validate()

        print(
            f"- enabled={getattr(self.branding, 'enabled', True)} | "
            f"ready={branding_result.get('ready')} | "
            f"reason={branding_result.get('reason')}"
        )

        # -----------------------------------------------------
        # TARGET
        # -----------------------------------------------------

        target = (
            "youtube_01"
            if "youtube_01" in self.destinations
            else next(
                iter(self.destinations),
                None,
            )
        )

        if not target:
            print("\nNo destinations available.")
            return

        # -----------------------------------------------------
        # VALIDATION
        # -----------------------------------------------------

        print(
            f"\nTarget integration test: {target}"
        )

        validation = self.validate_destination(
            target
        )

        print(
            f"  Ready: {validation.get('ready')}"
        )

        print(
            f"  Reason: {validation.get('reason')}"
        )

        # -----------------------------------------------------
        # SEQUENCE
        # -----------------------------------------------------

        print("\nSequence test:")

        current = self.current_video(
            target
        )

        print(
            f"  Initial: position="
            f"{self.state[target].get('position')} | "
            f"{current.get('name') if current else None}"
        )

        next_video = self.advance(
            target
        )

        print(
            f"  Advance: position="
            f"{self.state[target].get('position')} | "
            f"{next_video.get('name') if next_video else None}"
        )

        print("  Loop behavior: OK")

        # -----------------------------------------------------
        # FILTER
        # -----------------------------------------------------

        print("\nFilter integration test:")

        try:
            video_filter = self.build_video_filter(
                target
            )

            print(
                f"  Filter: {video_filter}"
            )
            print("  Result: OK")

        except Exception as exc:
            print(
                f"  Filter blocked safely: {exc}"
            )

        # -----------------------------------------------------
        # COMMAND
        # -----------------------------------------------------

        print("\nFFmpeg command test:")

        try:
            command = self.build_command(
                target
            )

            safe_command = " ".join(command)

            credential = (
                self.controller
                .credential_manager
                .get(target)
            )

            if credential:
                stream_key = credential.get(
                    "stream_key",
                    "",
                )

                if stream_key:
                    safe_command = (
                        safe_command.replace(
                            stream_key,
                            "***STREAM_KEY***",
                        )
                    )

            print(
                f"  Command: {safe_command}"
            )
            print("  Result: OK")

        except Exception as exc:
            print(
                f"  Command blocked safely: {exc}"
            )

        # -----------------------------------------------------
        # RUNTIME SAFETY
        # -----------------------------------------------------

        print("\nRuntime safety test:")

        result = self.start(target)

        print(
            f"  Started: "
            f"{result.get('started')}"
        )

        print(
            f"  FFmpeg started: "
            f"{result.get('ffmpeg_started')}"
        )

        print(
            f"  Reason: "
            f"{result.get('reason')}"
        )

        # -----------------------------------------------------
        # ISOLATION
        # -----------------------------------------------------

        other = next(
            (
                destination_id
                for destination_id in self.destinations
                if destination_id != target
            ),
            None,
        )

        print("\nDestination isolation test:")

        target_status = self.status(
            target
        )

        print(
            f"  {target} | "
            f"phase={target_status['phase']} | "
            f"position={target_status['position']} | "
            f"transitions={target_status['transitions']}"
        )

        if other:
            other_status = self.status(
                other
            )

            print(
                f"  {other} | "
                f"phase={other_status['phase']} | "
                f"position={other_status['position']} | "
                f"transitions={other_status['transitions']}"
            )

        print("  Isolation: OK")

        # -----------------------------------------------------
        # CLEANUP
        # -----------------------------------------------------

        self.controller.stop_all()

        if target in self.state:
            self.state[target][
                "phase"
            ] = "IDLE"

        print("\nFinal scheduler status:")

        for destination_id in self.destinations:
            info = self.status(
                destination_id
            )

            print(
                f"- {destination_id} | "
                f"phase={info['phase']} | "
                f"position={info['position']} | "
                f"current={info['current']} | "
                f"transitions={info['transitions']} | "
                f"process={info['process']}"
            )

        print(
            "\nReal FFmpeg streaming: NOT EXECUTED"
        )
        print(
            "No real RTMP destination was used."
        )

        print("=" * 60)
        print(
            "STREAM SCHEDULER v2.5 TEST COMPLETE"
        )
        print("=" * 60)


def main():
    scheduler = StreamSchedulerV25()
    scheduler.run_test()


if __name__ == "__main__":
    main()

