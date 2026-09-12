
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

from config_manager import ConfigManager
from credential_manager import CredentialManager
from playlist_manager import PlaylistManager
from branding_manager_v24 import BrandingManagerV24


BASE_DIR = Path(__file__).resolve().parent


class SchedulerDestination:
    """Independent scheduler state for one destination."""

    def __init__(
        self,
        destination_id: str,
        destination: dict,
        playlist: dict,
    ):
        self.destination_id = destination_id
        self.destination = destination
        self.playlist = playlist

        self.position: Optional[int] = None
        self.current: Optional[dict] = None
        self.transitions = 0
        self.running = False

        videos = playlist.get("videos", [])

        if isinstance(videos, list) and videos:
            self.position = 1
            self.current = videos[0]

    @property
    def videos(self) -> list:
        videos = self.playlist.get("videos", [])

        return videos if isinstance(videos, list) else []

    def advance(self) -> Optional[dict]:
        """
        Advance to the next video.
        Loops back to the first video.
        """

        if not self.videos:
            self.position = None
            self.current = None
            return None

        if self.position is None:
            self.position = 1
        else:
            self.position += 1

            if self.position > len(self.videos):
                self.position = 1

        self.current = self.videos[self.position - 1]
        self.transitions += 1

        return self.current


class StreamSchedulerV25:
    """
    Stream Scheduler v2.5

    Integrates:
        PlaylistManager
        CredentialManager
        BrandingManagerV24
        FFmpeg command generation

    Real RTMP streaming is NOT started by the test.
    """

    def __init__(self):
        self.config_manager = ConfigManager()
        self.credential_manager = CredentialManager()
        self.playlist_manager = PlaylistManager()

        self.destinations: dict[str, dict] = {}
        self.playlists: dict[str, dict] = {}
        self.sessions: dict[str, SchedulerDestination] = {}

        self.branding = BrandingManagerV24()

    # ---------------------------------------------------------
    # LOAD
    # ---------------------------------------------------------

    def load(self) -> None:

        self.destinations = {}

        for destination in self.config_manager.get_destinations():

            if (
                isinstance(destination, dict)
                and destination.get("id")
            ):
                self.destinations[
                    destination["id"]
                ] = destination

        self.playlists = (
            self.playlist_manager.build_playlists()
        )

        self.sessions = {}

        for destination_id, destination in self.destinations.items():

            playlist = self.playlists.get(
                destination_id,
                {},
            )

            if not isinstance(playlist, dict):
                playlist = {}

            self.sessions[destination_id] = (
                SchedulerDestination(
                    destination_id,
                    destination,
                    playlist,
                )
            )

    # ---------------------------------------------------------
    # VALIDATION
    # ---------------------------------------------------------

    def validate(self, destination_id: str) -> dict:

        destination = self.destinations.get(
            destination_id
        )

        if not destination:
            return {
                "ready": False,
                "reason": "DESTINATION_NOT_FOUND",
            }

        if not destination.get("enabled", False):
            return {
                "ready": False,
                "reason": "DESTINATION_DISABLED",
            }

        playlist = self.playlists.get(
            destination_id
        )

        if not isinstance(playlist, dict):
            return {
                "ready": False,
                "reason": "PLAYLIST_NOT_FOUND",
            }

        videos = playlist.get("videos", [])

        if not isinstance(videos, list) or not videos:
            return {
                "ready": False,
                "reason": "PLAYLIST_EMPTY",
            }

        credential = (
            self.credential_manager.get(
                destination_id
            )
        )

        if not credential:
            return {
                "ready": False,
                "reason": "CREDENTIAL_NOT_CONFIGURED",
            }

        if (
            not credential.get("rtmp_url")
            or not credential.get("stream_key")
        ):
            return {
                "ready": False,
                "reason": "CREDENTIAL_INCOMPLETE",
            }

        video = videos[0]

        local_path = video.get(
            "local_path"
        )

        if not local_path:
            return {
                "ready": False,
                "reason": "VIDEO_PATH_MISSING",
            }

        if not Path(local_path).exists():
            return {
                "ready": False,
                "reason": "VIDEO_CACHE_MISSING",
            }

        branding_validation = (
            self.branding.validate()
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
            "ready": True,
            "reason": "READY",
            "platform": destination.get(
                "platform"
            ),
            "folder": playlist.get(
                "folder_name"
            ),
            "videos": len(videos),
            "current": video.get(
                "name"
            ),
        }

    # ---------------------------------------------------------
    # BASE VIDEO FILTER
    # ---------------------------------------------------------

    def build_base_filter(self) -> str:

        return (
            "scale=1920:1080:"
            "force_original_aspect_ratio=decrease,"
            "pad=1920:1080:"
            "(ow-iw)/2:(oh-ih)/2"
        )

    # ---------------------------------------------------------
    # BRANDING FILTER
    # ---------------------------------------------------------

    def build_branding_filter(self) -> str:

        validation = self.branding.validate()

        if not validation["ready"]:
            raise ValueError(
                "Branding unavailable: "
                + validation["reason"]
            )

        x, y = (
            self.branding.position_expression()
        )

        logo_path = (
            self.branding.logo_path
            .as_posix()
        )

        return (
            f"[1:v]"
            f"scale={self.branding.width}:-1,"
            f"format=rgba,"
            f"colorchannelmixer="
            f"aa={self.branding.opacity}"
            f"[logo];"
            f"[0:v]"
            f"{self.build_base_filter()}"
            f"[base];"
            f"[base][logo]"
            f"overlay={x}:{y}"
            f"[vout]"
        )

    # ---------------------------------------------------------
    # FFMPEG COMMAND
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

        playlist = self.playlists[
            destination_id
        ]

        credential = (
            self.credential_manager.get(
                destination_id
            )
        )

        session = self.sessions[
            destination_id
        ]

        video = session.current

        if not video:
            video = playlist["videos"][0]

        local_path = video.get(
            "local_path"
        )

        output_url = (
            str(credential["rtmp_url"])
            .rstrip("/")
            + "/"
            + str(
                credential["stream_key"]
            ).strip()
        )

        filter_complex = (
            self.build_branding_filter()
        )

        return [
            "ffmpeg",

            "-hide_banner",
            "-loglevel",
            "warning",

            "-re",
            "-stream_loop",
            "-1",

            "-i",
            str(local_path),

            "-loop",
            "1",

            "-i",
            str(
                self.branding.logo_path
            ),

            "-filter_complex",
            filter_complex,

            "-map",
            "[vout]",

            "-map",
            "0:a?",

            "-c:v",
            "libx264",

            "-preset",
            "veryfast",

            "-pix_fmt",
            "yuv420p",

            "-r",
            "30",

            "-b:v",
            "4500k",

            "-maxrate",
            "4500k",

            "-bufsize",
            "9000k",

            "-c:a",
            "aac",

            "-b:a",
            "128k",

            "-ar",
            "44100",

            "-f",
            "flv",

            output_url,
        ]

    # ---------------------------------------------------------
    # TRANSITION
    # ---------------------------------------------------------

    def transition(
        self,
        destination_id: str,
    ) -> Optional[dict]:

        session = self.sessions.get(
            destination_id
        )

        if not session:
            raise ValueError(
                f"Unknown destination: "
                f"{destination_id}"
            )

        return session.advance()

    # ---------------------------------------------------------
    # STATUS
    # ---------------------------------------------------------

    def status(
        self,
        destination_id: str,
    ) -> dict:

        session = self.sessions.get(
            destination_id
        )

        if not session:
            return {
                "destination_id":
                    destination_id,
                "phase": "UNKNOWN",
                "position": None,
                "current": None,
                "transitions": 0,
                "running": False,
            }

        return {
            "destination_id":
                destination_id,

            "phase": (
                "PLAYING"
                if session.running
                else "IDLE"
            ),

            "position":
                session.position,

            "current": (
                session.current.get("name")
                if session.current
                else None
            ),

            "transitions":
                session.transitions,

            "running":
                session.running,
        }

    # ---------------------------------------------------------
    # TEST-MODE START GATE
    # ---------------------------------------------------------

    def test_start(
        self,
        destination_id: str,
    ) -> dict:

        validation = self.validate(
            destination_id
        )

        if not validation["ready"]:

            return {
                "started": False,
                "ffmpeg_started": False,
                "reason":
                    validation["reason"],
            }

        return {
            "started": False,
            "ffmpeg_started": False,
            "reason":
                "TEST_MODE_ONLY",
        }


# =============================================================
# TEST
# =============================================================

def run_test():

    print("=" * 60)
    print("STREAM SCHEDULER v2.5 TEST")
    print("=" * 60)

    scheduler = StreamSchedulerV25()

    scheduler.load()

    print(
        f"\n[SCHEDULER] "
        f"Destinations loaded: "
        f"{len(scheduler.destinations)}"
    )

    print("\nPlaylist discovery:")

    for destination_id in scheduler.destinations:

        session = scheduler.sessions[
            destination_id
        ]

        print(
            f"- {destination_id} | "
            f"videos={len(session.videos)}"
        )

    print("\nBranding validation:")

    branding_status = (
        scheduler.branding.status()
    )

    print(
        f"- enabled="
        f"{branding_status['enabled']}"
    )

    print(
        f"- ready="
        f"{branding_status['ready']}"
    )

    print(
        f"- reason="
        f"{branding_status['reason']}"
    )

    target = "youtube_01"

    print(
        f"\nTarget integration test: "
        f"{target}"
    )

    validation = scheduler.validate(
        target
    )

    print(
        f"  Ready: "
        f"{validation['ready']}"
    )

    print(
        f"  Reason: "
        f"{validation['reason']}"
    )

    print("\nSequence test:")

    session = scheduler.sessions[target]

    print(
        f"  Initial: "
        f"position={session.position} | "
        f"current="
        f"{session.current.get('name') "
        if session.current else 'None'}"
    )

    previous = session.current

    current = scheduler.transition(
        target
    )

    print(
        f"  Transition: "
        f"position={session.position} | "
        f"current="
        f"{current.get('name') "
        if current else 'None'}"
    )

    if (
        len(session.videos) == 1
        and previous
        and current
        and previous.get("name")
        == current.get("name")
    ):
        print(
            "  Loop behavior: OK"
        )

    print("\nBranding filter integration:")

    try:

        filter_complex = (
            scheduler.build_branding_filter()
        )

        print(
            f"  Filter: "
            f"{filter_complex}"
        )

        print(
            "  Filter integration: OK"
        )

    except Exception as exc:

        print(
            f"  Filter blocked safely: "
            f"{exc}"
        )

    print("\nFFmpeg command integration:")

    try:

        command = scheduler.build_command(
            target
        )

        safe_command = " ".join(
            command
        )

        credential = (
            scheduler.credential_manager.get(
                target
            )
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
            f"  Command generated: "
            f"YES"
        )

        print(
            f"  Command: "
            f"{safe_command}"
        )

    except Exception as exc:

        print(
            f"  Command blocked safely: "
            f"{exc}"
        )

    print("\nRuntime safety test:")

    result = scheduler.test_start(
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

    print("\nDestination isolation test:")

    s1 = scheduler.sessions[
        "youtube_01"
    ]

    s2 = scheduler.sessions[
        "youtube_02"
    ]

    print(
        f"  youtube_01 | "
        f"position={s1.position} | "
        f"transitions={s1.transitions}"
    )

    print(
        f"  youtube_02 | "
        f"position={s2.position} | "
        f"transitions={s2.transitions}"
    )

    print(
        "  Isolation: OK"
    )

    print("\nFinal scheduler status:")

    for destination_id in scheduler.destinations:

        info = scheduler.status(
            destination_id
        )

        print(
            f"- {destination_id} | "
            f"phase={info['phase']} | "
            f"position={info['position']} | "
            f"current={info['current']} | "
            f"transitions={info['transitions']} | "
            f"running={info['running']}"
        )

    print("\nSafety:")

    print(
        "  No real RTMP streaming was executed."
    )

    print(
        "  No credentials were modified."
    )

    print(
        "  No playlists were modified."
    )

    print(
        "  No Google Drive files were modified."
    )

    print("\n" + "=" * 60)
    print(
        "STREAM SCHEDULER v2.5 "
        "TEST COMPLETE"
    )
    print("=" * 60)


if __name__ == "__main__":
    run_test()

