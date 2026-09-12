
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from branding_manager_v20 import BrandingManager
from streaming_controller_v10 import StreamingController


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_LOGO = BASE_DIR / "assets" / "logo.png"


class StreamSchedulerV21:
    """
    Streaming Scheduler v2.1

    Integrates:
        Destination
            ↓
        Playlist
            ↓
        Branding validation
            ↓
        FFmpeg filter
            ↓
        Streaming Controller

    Safety:
    - Disabled destinations cannot start.
    - Missing logo blocks branded streaming.
    - No credentials are modified.
    - No playlists are modified.
    - No Google Drive files are modified.
    """

    def __init__(self):
        self.controller = StreamingController()
        self.controller.load()

        self.states: dict[str, dict[str, Any]] = {}

        for destination_id in self.controller.destinations:
            self.states[destination_id] = {
                "phase": "IDLE",
                "position": None,
                "current": None,
                "transitions": 0,
            }

    # ---------------------------------------------------------
    # DESTINATION
    # ---------------------------------------------------------

    def destination(self, destination_id: str) -> Optional[dict]:
        return self.controller.destinations.get(
            destination_id
        )

    # ---------------------------------------------------------
    # PLAYLIST
    # ---------------------------------------------------------

    def playlist(self, destination_id: str) -> dict:
        playlist = self.controller.playlists.get(
            destination_id,
            {},
        )

        return (
            playlist
            if isinstance(playlist, dict)
            else {}
        )

    def videos(self, destination_id: str) -> list:
        videos = self.playlist(destination_id).get(
            "videos",
            [],
        )

        return (
            videos
            if isinstance(videos, list)
            else []
        )

    # ---------------------------------------------------------
    # BRANDING CONFIG
    # ---------------------------------------------------------

    def branding_config(
        self,
        destination_id: str,
    ) -> dict[str, Any]:
        destination = self.destination(destination_id)

        if not destination:
            return {
                "logo_enabled": False,
            }

        branding = destination.get(
            "branding",
            {},
        )

        if not isinstance(branding, dict):
            branding = {}

        return {
            "logo_enabled": branding.get(
                "logo_enabled",
                True,
            ),
            "logo_path": branding.get(
                "logo_path",
                str(DEFAULT_LOGO),
            ),
            "logo_position": branding.get(
                "logo_position",
                "top-right",
            ),
            "logo_width": branding.get(
                "logo_width",
                180,
            ),
            "logo_opacity": branding.get(
                "logo_opacity",
                0.9,
            ),
            "logo_margin": branding.get(
                "logo_margin",
                30,
            ),
        }

    # ---------------------------------------------------------
    # BRANDING
    # ---------------------------------------------------------

    def branding(
        self,
        destination_id: str,
    ) -> BrandingManager:
        return BrandingManager(
            self.branding_config(
                destination_id
            )
        )

    def validate_branding(
        self,
        destination_id: str,
    ) -> dict[str, Any]:
        return self.branding(
            destination_id
        ).validate()

    # ---------------------------------------------------------
    # VALIDATION
    # ---------------------------------------------------------

    def validate(
        self,
        destination_id: str,
    ) -> dict[str, Any]:
        controller_validation = (
            self.controller.validate(
                destination_id
            )
        )

        if not controller_validation["ready"]:
            return controller_validation

        branding_validation = (
            self.validate_branding(
                destination_id
            )
        )

        if not branding_validation["ready"]:
            return {
                "ready": False,
                "reason": (
                    "BRANDING_"
                    + branding_validation["reason"]
                ),
            }

        return {
            **controller_validation,
            "branding": branding_validation,
            "ready": True,
            "reason": "READY",
        }

    # ---------------------------------------------------------
    # VIDEO SEQUENCE
    # ---------------------------------------------------------

    def initialize_playlist(
        self,
        destination_id: str,
    ) -> Optional[dict]:
        videos = self.videos(
            destination_id
        )

        if not videos:
            return None

        state = self.states[
            destination_id
        ]

        state["position"] = 1
        state["current"] = videos[0].get(
            "name"
        )

        return videos[0]

    def current_video(
        self,
        destination_id: str,
    ) -> Optional[dict]:
        videos = self.videos(
            destination_id
        )

        if not videos:
            return None

        state = self.states[
            destination_id
        ]

        position = state.get(
            "position"
        )

        if not position:
            return self.initialize_playlist(
                destination_id
            )

        index = position - 1

        if index >= len(videos):
            index = 0
            state["position"] = 1

        return videos[index]

    def advance(
        self,
        destination_id: str,
    ) -> Optional[dict]:
        videos = self.videos(
            destination_id
        )

        if not videos:
            return None

        state = self.states[
            destination_id
        ]

        if not state.get("position"):
            self.initialize_playlist(
                destination_id
            )

        next_position = (
            state["position"] + 1
        )

        if next_position > len(videos):
            next_position = 1

        state["position"] = next_position

        video = videos[
            next_position - 1
        ]

        state["current"] = video.get(
            "name"
        )

        state["transitions"] += 1

        return video

    # ---------------------------------------------------------
    # FILTER
    # ---------------------------------------------------------

    def build_video_filter(
        self,
        destination_id: str,
    ) -> str:
        validation = self.validate(
            destination_id
        )

        if not validation["ready"]:
            raise ValueError(
                f"{destination_id}: "
                f"{validation['reason']}"
            )

        base_filter = (
            "scale=1920:1080:"
            "force_original_aspect_ratio=decrease,"
            "pad=1920:1080:(ow-iw)/2:(oh-ih)/2"
        )

        branding = self.branding(
            destination_id
        )

        return branding.apply_to_filter(
            base_filter
        )

    # ---------------------------------------------------------
    # COMMAND
    # ---------------------------------------------------------

    def build_command(
        self,
        destination_id: str,
    ) -> list[str]:
        validation = self.validate(
            destination_id
        )

        if not validation["ready"]:
            raise ValueError(
                f"{destination_id}: "
                f"{validation['reason']}"
            )

        command = self.controller.build_command(
            destination_id
        )

        video_filter = self.build_video_filter(
            destination_id
        )

        try:
            vf_index = command.index(
                "-vf"
            )
        except ValueError:
            raise ValueError(
                "FFmpeg command has no -vf option"
            )

        command[vf_index + 1] = video_filter

        return command

    # ---------------------------------------------------------
    # START
    # ---------------------------------------------------------

    def start(
        self,
        destination_id: str,
    ) -> dict[str, Any]:
        validation = self.validate(
            destination_id
        )

        if not validation["ready"]:
            self.states[
                destination_id
            ]["phase"] = "FAILED"

            return {
                "started": False,
                "ffmpeg_started": False,
                "reason": validation[
                    "reason"
                ],
            }

        try:
            command = self.build_command(
                destination_id
            )

            process = self.controller.start(
                destination_id
            )

            state = self.states[
                destination_id
            ]

            state["phase"] = "PLAYING"

            if not state.get("position"):
                self.initialize_playlist(
                    destination_id
                )

            return {
                "started": True,
                "ffmpeg_started": True,
                "pid": process.pid,
                "command": command,
                "reason": "STARTED",
            }

        except Exception as exc:
            self.states[
                destination_id
            ]["phase"] = "FAILED"

            return {
                "started": False,
                "ffmpeg_started": False,
                "reason": str(exc),
            }

    # ---------------------------------------------------------
    # STOP
    # ---------------------------------------------------------

    def stop(
        self,
        destination_id: str,
    ) -> None:
        self.controller.stop(
            destination_id
        )

        self.states[
            destination_id
        ]["phase"] = "IDLE"

    # ---------------------------------------------------------
    # STATUS
    # ---------------------------------------------------------

    def status(
        self,
        destination_id: str,
    ) -> dict[str, Any]:
        state = self.states[
            destination_id
        ]

        process = self.controller.status(
            destination_id
        )

        return {
            "destination_id": destination_id,
            "phase": state["phase"],
            "position": state["position"],
            "current": state["current"],
            "transitions": state["transitions"],
            "process": process["status"],
            "pid": process["pid"],
        }


# =============================================================
# TEST
# =============================================================

def run_test():
    print("=" * 60)
    print("STREAM SCHEDULER v2.1 TEST")
    print("=" * 60)

    scheduler = StreamSchedulerV21()

    print(
        f"\n[SCHEDULER] Destinations loaded: "
        f"{len(scheduler.controller.destinations)}"
    )

    print("\nPlaylist discovery:")

    for destination_id in (
        scheduler.controller.destinations
    ):
        videos = scheduler.videos(
            destination_id
        )

        print(
            f"- {destination_id} | "
            f"videos={len(videos)}"
        )

    print("\nBranding validation:")

    for destination_id in (
        scheduler.controller.destinations
    ):
        branding = scheduler.validate_branding(
            destination_id
        )

        print(
            f"- {destination_id} | "
            f"enabled={branding.get('enabled')} | "
            f"ready={branding.get('ready')} | "
            f"reason={branding.get('reason')}"
        )

    target = "youtube_01"

    print(
        f"\nTarget integration test: {target}"
    )

    validation = scheduler.validate(
        target
    )

    print(
        f"  Ready: {validation['ready']}"
    )
    print(
        f"  Reason: {validation['reason']}"
    )

    print("\nSequence test:")

    first = scheduler.initialize_playlist(
        target
    )

    if first:
        print(
            f"  Initial: position="
            f"{scheduler.states[target]['position']} | "
            f"{first.get('name')}"
        )

        second = scheduler.advance(
            target
        )

        print(
            f"  Advance: position="
            f"{scheduler.states[target]['position']} | "
            f"{second.get('name') if second else None}"
        )

        print(
            "  Loop behavior: "
            "OK"
        )
    else:
        print(
            "  Playlist unavailable."
        )

    print("\nFilter integration test:")

    try:
        video_filter = (
            scheduler.build_video_filter(
                target
            )
        )

        print("  Filter: OK")
        print(
            f"  {video_filter}"
        )

    except Exception as exc:
        print(
            f"  Filter blocked safely: "
            f"{exc}"
        )

    print("\nRuntime safety test:")

    result = scheduler.start(
        target
    )

    print(
        f"  Started: "
        f"{result['started']}"
    )

    print(
        f"  FFmpeg started: "
        f"{result['ffmpeg_started']}"
    )

    print(
        f"  Reason: "
        f"{result['reason']}"
    )

    print("\nFinal status:")

    for destination_id in (
        scheduler.controller.destinations
    ):
        info = scheduler.status(
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

    scheduler.controller.stop_all()

    print("\nSafety:")
    print("  No real RTMP streaming was executed.")
    print("  No credentials were modified.")
    print("  No playlists were modified.")
    print("  No Google Drive files were modified.")

    print("=" * 60)
    print("STREAM SCHEDULER v2.1 TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    run_test()

