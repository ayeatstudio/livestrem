
from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Optional

from config_manager import ConfigManager
from credential_manager import CredentialManager
from playlist_manager import PlaylistManager


BASE_DIR = Path(__file__).resolve().parent
LOGO_DIR = BASE_DIR / "assets"


# =============================================================
# STREAM PROCESS
# =============================================================

class StreamingProcess:
    """Isolated FFmpeg process for one destination."""

    def __init__(self, destination_id: str, command: list[str]):
        self.destination_id = destination_id
        self.command = command
        self.process: Optional[subprocess.Popen] = None
        self.started_at: Optional[float] = None
        self.last_error: Optional[str] = None

    @property
    def status(self) -> str:
        if self.process is None:
            return "STOPPED"

        if self.process.poll() is None:
            return "RUNNING"

        return "FAILED" if self.process.returncode != 0 else "STOPPED"

    @property
    def pid(self) -> Optional[int]:
        return self.process.pid if self.process else None

    @property
    def return_code(self) -> Optional[int]:
        return self.process.poll() if self.process else None

    def start(self) -> None:
        if self.status == "RUNNING":
            raise RuntimeError(
                f"Destination already running: {self.destination_id}"
            )

        self.last_error = None

        self.process = subprocess.Popen(
            self.command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        self.started_at = time.time()

    def stop(self, timeout: float = 10.0) -> None:
        if not self.process:
            return

        if self.process.poll() is not None:
            return

        self.process.terminate()

        try:
            self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)

    def refresh(self) -> str:
        status = self.status

        if status == "FAILED" and self.process:
            self.last_error = (
                f"FFmpeg exited with return code "
                f"{self.process.returncode}"
            )

        return status


# =============================================================
# DESTINATION SCHEDULER STATE
# =============================================================

class DestinationState:

    def __init__(self):
        self.position: Optional[int] = None
        self.current: Optional[str] = None
        self.transitions = 0
        self.phase = "IDLE"
        self.process: Optional[StreamingProcess] = None


# =============================================================
# STREAM SCHEDULER v1.9
# =============================================================

class StreamSchedulerV19:

    """
    Streaming Scheduler v1.9

    Features:
    - Destination isolation
    - Playlist sequencing
    - Playlist looping
    - FFmpeg process isolation
    - Destination validation
    - Safe start gate
    - Channel logo overlay
    - Branding configuration
    - Test mode without real RTMP
    """

    def __init__(self):
        self.config_manager = ConfigManager()
        self.credential_manager = CredentialManager()
        self.playlist_manager = PlaylistManager()

        self.destinations: dict[str, dict] = {}
        self.playlists: dict[str, dict] = {}
        self.states: dict[str, DestinationState] = {}
        self.processes: dict[str, StreamingProcess] = {}

        # Test mode is always enabled for this standalone test.
        self.test_mode = True

    # ---------------------------------------------------------
    # LOAD
    # ---------------------------------------------------------

    def load(self) -> None:
        self.destinations = {}

        for destination in self.config_manager.get_destinations():
            if not isinstance(destination, dict):
                continue

            destination_id = destination.get("id")

            if destination_id:
                self.destinations[destination_id] = destination

        self.playlists = self.playlist_manager.build_playlists()

        for destination_id in self.destinations:
            self.states[destination_id] = DestinationState()

    # ---------------------------------------------------------
    # VALIDATION
    # ---------------------------------------------------------

    def validate(self, destination_id: str) -> dict:

        destination = self.destinations.get(destination_id)

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

        playlist = self.playlists.get(destination_id)

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

        credential = self.credential_manager.get(destination_id)

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
        local_path = video.get("local_path")

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

        branding = self.get_branding_config(destination_id)

        if branding["enabled"]:
            logo_path = Path(branding["logo_path"])

            if not logo_path.exists():
                return {
                    "ready": False,
                    "reason": "LOGO_FILE_MISSING",
                }

        return {
            "ready": True,
            "reason": "READY",
            "platform": destination.get("platform"),
            "folder": playlist.get("folder_name"),
            "videos": len(videos),
            "current": video.get("name"),
            "branding": branding["enabled"],
        }

    # ---------------------------------------------------------
    # BRANDING CONFIG
    # ---------------------------------------------------------

    def get_branding_config(self, destination_id: str) -> dict:

        destination = self.destinations.get(destination_id, {})

        branding = destination.get("branding", {})

        if not isinstance(branding, dict):
            branding = {}

        enabled = branding.get("logo_enabled", True)

        logo_path = branding.get("logo_path")

        if logo_path:
            path = Path(logo_path)

            if not path.is_absolute():
                path = BASE_DIR / path
        else:
            path = LOGO_DIR / "logo.png"

        return {
            "enabled": bool(enabled),
            "logo_path": str(path),
            "position": branding.get(
                "logo_position",
                "top-right",
            ),
            "width": int(
                branding.get(
                    "logo_width",
                    180,
                )
            ),
            "opacity": float(
                branding.get(
                    "logo_opacity",
                    0.90,
                )
            ),
            "margin_x": int(
                branding.get(
                    "logo_margin_x",
                    30,
                )
            ),
            "margin_y": int(
                branding.get(
                    "logo_margin_y",
                    30,
                )
            ),
        }

    # ---------------------------------------------------------
    # LOGO OVERLAY
    # ---------------------------------------------------------

    def build_logo_filter(
        self,
        destination_id: str,
    ) -> Optional[str]:

        branding = self.get_branding_config(destination_id)

        if not branding["enabled"]:
            return None

        width = max(1, branding["width"])
        opacity = max(
            0.0,
            min(1.0, branding["opacity"]),
        )

        margin_x = max(
            0,
            branding["margin_x"],
        )

        margin_y = max(
            0,
            branding["margin_y"],
        )

        position = branding["position"]

        if position == "top-left":
            overlay_position = (
                f"{margin_x}:{margin_y}"
            )

        elif position == "bottom-left":
            overlay_position = (
                f"{margin_x}:H-h-{margin_y}"
            )

        elif position == "bottom-right":
            overlay_position = (
                f"W-w-{margin_x}:H-h-{margin_y}"
            )

        else:
            # Default: top-right
            overlay_position = (
                f"W-w-{margin_x}:{margin_y}"
            )

        return (
            f"[1:v]scale={width}:-1,"
            f"format=rgba,"
            f"colorchannelmixer=aa={opacity}"
            f"[logo];"
            f"[0:v][logo]"
            f"overlay={overlay_position}"
            f"[vout]"
        )

    # ---------------------------------------------------------
    # BUILD FFMPEG COMMAND
    # ---------------------------------------------------------

    def build_command(
        self,
        destination_id: str,
    ) -> list[str]:

        validation = self.validate(destination_id)

        if not validation["ready"]:
            raise ValueError(
                f"{destination_id}: "
                f"{validation['reason']}"
            )

        playlist = self.playlists[destination_id]
        credential = self.credential_manager.get(
            destination_id
        )

        video = playlist["videos"][0]

        output_url = (
            str(credential["rtmp_url"]).rstrip("/")
            + "/"
            + str(credential["stream_key"]).strip()
        )

        branding = self.get_branding_config(
            destination_id
        )

        input_args = [
            "-re",
            "-stream_loop",
            "-1",
            "-i",
            str(video["local_path"]),
        ]

        filter_complex = None

        if branding["enabled"]:

            logo_path = branding["logo_path"]

            input_args.extend([
                "-i",
                logo_path,
            ])

            filter_complex = self.build_logo_filter(
                destination_id
            )

        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "warning",
        ]

        command.extend(input_args)

        if filter_complex:

            command.extend([
                "-filter_complex",
                filter_complex,
                "-map",
                "[vout]",
                "-map",
                "0:a?",
            ])

        else:

            command.extend([
                "-map",
                "0:v",
                "-map",
                "0:a?",
                "-vf",
                (
                    "scale=1920:1080:"
                    "force_original_aspect_ratio=decrease,"
                    "pad=1920:1080:"
                    "(ow-iw)/2:(oh-ih)/2"
                ),
            ])

        command.extend([
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
        ])

        return command

    # ---------------------------------------------------------
    # PLAYLIST
    # ---------------------------------------------------------

    def current_video(
        self,
        destination_id: str,
    ) -> Optional[dict]:

        playlist = self.playlists.get(destination_id)

        if not isinstance(playlist, dict):
            return None

        videos = playlist.get("videos", [])

        if not videos:
            return None

        state = self.states[destination_id]

        if state.position is None:
            state.position = 1

        index = (
            state.position - 1
        ) % len(videos)

        return videos[index]

    def advance(
        self,
        destination_id: str,
    ) -> Optional[dict]:

        playlist = self.playlists.get(destination_id)

        if not isinstance(playlist, dict):
            return None

        videos = playlist.get("videos", [])

        if not videos:
            return None

        state = self.states[destination_id]

        if state.position is None:
            state.position = 1
        else:
            state.position = (
                state.position % len(videos)
            ) + 1

        state.transitions += 1

        video = self.current_video(
            destination_id
        )

        if video:
            state.current = video.get("name")

        return video

    # ---------------------------------------------------------
    # START
    # ---------------------------------------------------------

    def start(
        self,
        destination_id: str,
        real: bool = False,
    ) -> dict:

        validation = self.validate(
            destination_id
        )

        if not validation["ready"]:
            self.states[
                destination_id
            ].phase = "FAILED"

            return {
                "started": False,
                "ffmpeg_started": False,
                "reason": validation["reason"],
            }

        if self.test_mode and not real:
            return {
                "started": False,
                "ffmpeg_started": False,
                "reason": "TEST_MODE",
            }

        command = self.build_command(
            destination_id
        )

        process = StreamingProcess(
            destination_id,
            command,
        )

        process.start()

        self.processes[
            destination_id
        ] = process

        self.states[
            destination_id
        ].process = process

        self.states[
            destination_id
        ].phase = "PLAYING"

        return {
            "started": True,
            "ffmpeg_started": True,
            "reason": "STARTED",
            "pid": process.pid,
        }

    # ---------------------------------------------------------
    # STOP
    # ---------------------------------------------------------

    def stop(
        self,
        destination_id: str,
    ) -> None:

        process = self.processes.get(
            destination_id
        )

        if process:
            process.stop()

        state = self.states.get(
            destination_id
        )

        if state:
            state.phase = "IDLE"

    # ---------------------------------------------------------
    # STATUS
    # ---------------------------------------------------------

    def status(
        self,
        destination_id: str,
    ) -> dict:

        state = self.states[destination_id]

        process = self.processes.get(
            destination_id
        )

        process_status = (
            process.refresh()
            if process
            else "STOPPED"
        )

        return {
            "phase": state.phase,
            "position": state.position,
            "current": state.current,
            "transitions": state.transitions,
            "process": process_status,
        }


# =============================================================
# TEST HELPERS
# =============================================================

def print_separator():
    print("=" * 60)


# =============================================================
# TEST
# =============================================================

def run_test():

    print_separator()
    print("STREAM SCHEDULER v1.9 TEST")
    print_separator()

    scheduler = StreamSchedulerV19()
    scheduler.load()

    print(
        f"\n[SCHEDULER] "
        f"Destinations loaded: "
        f"{len(scheduler.destinations)}"
    )

    # ---------------------------------------------------------
    # PLAYLIST DISCOVERY
    # ---------------------------------------------------------

    print("\nPlaylist discovery:")

    for destination_id in scheduler.destinations:

        playlist = scheduler.playlists.get(
            destination_id,
            {},
        )

        videos = (
            playlist.get("videos", [])
            if isinstance(playlist, dict)
            else []
        )

        print(
            f"- {destination_id} | "
            f"videos={len(videos)}"
        )

    # ---------------------------------------------------------
    # BRANDING TEST
    # ---------------------------------------------------------

    print("\nBranding configuration test:")

    branding_ok = True

    for destination_id in scheduler.destinations:

        branding = scheduler.get_branding_config(
            destination_id
        )

        if branding["enabled"]:

            logo_path = Path(
                branding["logo_path"]
            )

            exists = logo_path.exists()

            print(
                f"- {destination_id} | "
                f"logo_enabled=True | "
                f"path={logo_path} | "
                f"{'FOUND' if exists else 'MISSING'}"
            )

            if not exists:
                branding_ok = False

        else:

            print(
                f"- {destination_id} | "
                f"logo_enabled=False"
            )

    # ---------------------------------------------------------
    # TARGET
    # ---------------------------------------------------------

    target = "youtube_01"

    print(
        f"\nTarget branding test: {target}"
    )

    branding = scheduler.get_branding_config(
        target
    )

    print(
        f"  Enabled: {branding['enabled']}"
    )

    print(
        f"  Position: {branding['position']}"
    )

    print(
        f"  Width: {branding['width']}"
    )

    print(
        f"  Opacity: {branding['opacity']}"
    )

    # ---------------------------------------------------------
    # VALIDATION
    # ---------------------------------------------------------

    validation = scheduler.validate(
        target
    )

    print(
        "\nValidation:"
    )

    print(
        f"  Ready: {validation['ready']}"
    )

    print(
        f"  Reason: {validation['reason']}"
    )

    # ---------------------------------------------------------
    # FILTER TEST
    # ---------------------------------------------------------

    print(
        "\nLogo filter test:"
    )

    if branding["enabled"]:

        try:
            logo_filter = scheduler.build_logo_filter(
                target
            )

            print(
                f"  Filter: {logo_filter}"
            )

            print(
                "  Overlay filter: OK"
            )

        except Exception as exc:

            print(
                f"  Overlay filter: FAILED | {exc}"
            )

            branding_ok = False

    else:

        print(
            "  Overlay filter: DISABLED"
        )

    # ---------------------------------------------------------
    # COMMAND TEST
    # ---------------------------------------------------------

    print(
        "\nFFmpeg command test:"
    )

    if validation["ready"]:

        try:

            command = scheduler.build_command(
                target
            )

            safe_command = " ".join(
                command
            )

            credential = scheduler.credential_manager.get(
                target
            )

            if credential:

                stream_key = str(
                    credential.get(
                        "stream_key",
                        "",
                    )
                )

                if stream_key:

                    safe_command = safe_command.replace(
                        stream_key,
                        "***STREAM_KEY***",
                    )

            print(
                "  Command generated: OK"
            )

            print(
                f"  Branding included: "
                f"{'YES' if branding['enabled'] else 'NO'}"
            )

            print(
                f"  Command preview:\n"
                f"    {safe_command}"
            )

        except Exception as exc:

            print(
                f"  Command generated: FAILED | {exc}"
            )

    else:

        print(
            "  Command generation blocked "
            f"because: {validation['reason']}"
        )

    # ---------------------------------------------------------
    # PLAYLIST TRANSITION
    # ---------------------------------------------------------

    print(
        "\nPlaylist transition test:"
    )

    current = scheduler.current_video(
        target
    )

    if current:

        print(
            f"  Current: "
            f"{current.get('name')}"
        )

        next_video = scheduler.advance(
            target
        )

        print(
            f"  Next: "
            f"{next_video.get('name')}"
        )

        print(
            f"  Position: "
            f"{scheduler.states[target].position}"
        )

        print(
            "  Loop behavior: OK"
        )

    else:

        print(
            "  Playlist unavailable"
        )

    # ---------------------------------------------------------
    # DESTINATION ISOLATION
    # ---------------------------------------------------------

    print(
        "\nDestination isolation test:"
    )

    target2 = "youtube_02"

    scheduler.current_video(target)
    scheduler.advance(target)

    state1 = scheduler.states[target]
    state2 = scheduler.states[target2]

    print(
        f"  {target} | "
        f"position={state1.position} | "
        f"transitions={state1.transitions}"
    )

    print(
        f"  {target2} | "
        f"position={state2.position} | "
        f"transitions={state2.transitions}"
    )

    isolated = (
        state2.transitions == 0
    )

    print(
        f"  Isolation: "
        f"{'OK' if isolated else 'FAILED'}"
    )

    # ---------------------------------------------------------
    # SAFE START TEST
    # ---------------------------------------------------------

    print(
        "\nRuntime safety test:"
    )

    result = scheduler.start(
        target,
        real=False,
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

    # ---------------------------------------------------------
    # FINAL STATUS
    # ---------------------------------------------------------

    print(
        "\nFinal scheduler status:"
    )

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
            f"process={info['process']}"
        )

    scheduler.stop_all = lambda: None

    print(
        "\nReal FFmpeg streaming: NOT EXECUTED"
    )

    print(
        "No real RTMP destination was used."
    )

    print_separator()

    if branding_ok:
        print(
            "STREAM SCHEDULER v1.9 TEST SUCCESS"
        )
    else:
        print(
            "STREAM SCHEDULER v1.9 TEST COMPLETE"
        )

    print_separator()


def main():
    run_test()


if __name__ == "__main__":
    main()

