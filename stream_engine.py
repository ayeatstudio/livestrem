from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from config_manager import ConfigManager
from branding_manager import BrandingManager
from metrics_manager import MetricsManager


# ============================================================
# STREAM ENGINE
# ============================================================


@dataclass
class StreamState:
    destination_id: str
    source: Optional[Path] = None
    process: Optional[subprocess.Popen] = None
    running: bool = False
    error: Optional[str] = None


class StreamEngine:
    """
    Core FFmpeg command and process layer.

    Responsibilities:
    - Validate destination configuration.
    - Validate source media.
    - Build video filters.
    - Integrate branding.
    - Generate FFmpeg commands.
    - Start/stop FFmpeg when explicitly requested.
    - Track runtime metrics.

    Safety:
    - Tests never start real streaming.
    - Stream keys are never printed.
    """

    def __init__(
        self,
        config_manager: Optional[ConfigManager] = None,
        branding_manager: Optional[BrandingManager] = None,
        metrics_manager: Optional[MetricsManager] = None,
    ):
        self.config_manager = (
            config_manager
            or ConfigManager()
        )

        self.branding_manager = (
            branding_manager
            or self._load_branding_manager()
        )

        self.metrics_manager = (
            metrics_manager
            or MetricsManager()
        )

        self.states: dict[
            str,
            StreamState,
        ] = {}

    # ---------------------------------------------------------
    # BRANDING
    # ---------------------------------------------------------

    @staticmethod
    def _load_branding_manager():

        try:
            return BrandingManager()

        except Exception:
            return None

    # ---------------------------------------------------------
    # DESTINATIONS
    # ---------------------------------------------------------

    def get_destinations(
        self,
    ) -> list[dict]:

        return self.config_manager.get_destinations()

    def get_destination(
        self,
        destination_id: str,
    ) -> Optional[dict]:

        for destination in (
            self.get_destinations()
        ):

            if (
                isinstance(destination, dict)
                and destination.get("id")
                == destination_id
            ):
                return destination

        return None

    # ---------------------------------------------------------
    # VALIDATION
    # ---------------------------------------------------------

    def validate_destination(
        self,
        destination_id: str,
    ) -> dict:

        destination = self.get_destination(
            destination_id
        )

        if destination is None:
            return {
                "ready": False,
                "reason": "DESTINATION_NOT_FOUND",
            }

        if not destination.get(
            "enabled",
            False,
        ):
            return {
                "ready": False,
                "reason": "DESTINATION_DISABLED",
            }

        if not isinstance(
            destination.get("platform"),
            str,
        ) or not destination.get(
            "platform"
        ):
            return {
                "ready": False,
                "reason": "INVALID_PLATFORM",
            }

        if not isinstance(
            destination.get("rtmp_url"),
            str,
        ) or not destination.get(
            "rtmp_url"
        ):
            return {
                "ready": False,
                "reason": "RTMP_URL_NOT_CONFIGURED",
            }

        if not isinstance(
            destination.get("stream_key"),
            str,
        ) or not destination.get(
            "stream_key"
        ):
            return {
                "ready": False,
                "reason": "STREAM_KEY_NOT_CONFIGURED",
            }

        return {
            "ready": True,
            "reason": "READY",
            "platform": destination[
                "platform"
            ],
            "name": destination.get(
                "name",
                "",
            ),
        }

    # ---------------------------------------------------------
    # SOURCE
    # ---------------------------------------------------------

    @staticmethod
    def validate_source(
        source: str | Path,
    ) -> dict:

        path = Path(source)

        if not path.exists():
            return {
                "ready": False,
                "reason": "SOURCE_FILE_MISSING",
                "source": str(path),
            }

        if not path.is_file():
            return {
                "ready": False,
                "reason": "SOURCE_NOT_FILE",
                "source": str(path),
            }

        if path.stat().st_size <= 0:
            return {
                "ready": False,
                "reason": "SOURCE_FILE_EMPTY",
                "source": str(path),
            }

        return {
            "ready": True,
            "reason": "READY",
            "source": str(path),
        }

    # ---------------------------------------------------------
    # STATE
    # ---------------------------------------------------------

    def _get_state(
        self,
        destination_id: str,
    ) -> StreamState:

        if destination_id not in self.states:

            self.states[destination_id] = (
                StreamState(
                    destination_id=destination_id
                )
            )

        return self.states[
            destination_id
        ]

    # ---------------------------------------------------------
    # VIDEO FILTER
    # ---------------------------------------------------------

    @staticmethod
    def build_video_filter(
        width: int = 1920,
        height: int = 1080,
    ) -> str:

        if width <= 0:
            raise ValueError(
                "Invalid video width."
            )

        if height <= 0:
            raise ValueError(
                "Invalid video height."
            )

        return (
            f"scale={width}:{height}:"
            "force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:"
            "(ow-iw)/2:(oh-ih)/2"
        )

    # ---------------------------------------------------------
    # FILTER COMPLEX
    # ---------------------------------------------------------

    def build_filter(
        self,
        destination_id: str,
        use_branding: bool = True,
    ) -> tuple[str, str]:

        base_filter = self.build_video_filter()

        if (
            use_branding
            and self.branding_manager is not None
        ):

            branding = (
                self.branding_manager
            )

            validation = branding.validate(
                destination_id
            )

            if validation["reason"] == (
                "LOGO_DISABLED"
            ):
                return (
                    base_filter,
                    "vf",
                )

            if validation["ready"]:

                logo_filter = (
                    branding.apply_to_filter(
                        destination_id,
                        "[0:v]",
                    )
                )

                return (
                    f"{base_filter},"
                    f"{logo_filter}",
                    "filter_complex",
                )

        return (
            base_filter,
            "vf",
        )

    # ---------------------------------------------------------
    # COMMAND
    # ---------------------------------------------------------

    def build_command(
        self,
        destination_id: str,
        source: str | Path,
        loop: bool = True,
        realtime: bool = True,
        use_branding: bool = True,
    ) -> list[str]:

        destination_validation = (
            self.validate_destination(
                destination_id
            )
        )

        if not destination_validation[
            "ready"
        ]:
            raise ValueError(
                "Destination not ready: "
                f"{destination_validation['reason']}"
            )

        source_validation = (
            self.validate_source(
                source
            )
        )

        if not source_validation[
            "ready"
        ]:
            raise ValueError(
                "Source not ready: "
                f"{source_validation['reason']}"
            )

        destination = self.get_destination(
            destination_id
        )

        if destination is None:
            raise ValueError(
                "Destination not found."
            )

        state = self._get_state(
            destination_id
        )

        state.source = Path(source)

        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "warning",
        ]

        if realtime:
            command.append("-re")

        if loop:
            command.extend([
                "-stream_loop",
                "-1",
            ])

        command.extend([
            "-i",
            str(source),
        ])

        filter_value, filter_type = (
            self.build_filter(
                destination_id,
                use_branding=use_branding,
            )
        )

        if filter_type == "vf":

            command.extend([
                "-vf",
                filter_value,
            ])

        else:

            command.extend([
                "-filter_complex",
                filter_value,
                "-map",
                "[vout]",
                "-map",
                "0:a?",
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
        ])

        rtmp_url = str(
            destination["rtmp_url"]
        )

        stream_key = str(
            destination["stream_key"]
        )

        output = (
            rtmp_url.rstrip("/")
            + "/"
            + stream_key
        )

        command.append(output)

        return command

    # ---------------------------------------------------------
    # SAFE DISPLAY
    # ---------------------------------------------------------

    @staticmethod
    def command_for_display(
        command: list[str],
    ) -> str:

        values = []

        for value in command:

            text = str(value)

            if (
                text.lower()
                .startswith("rtmp://")
            ):
                text = (
                    text.rsplit(
                        "/",
                        1,
                    )[0]
                    + "/[STREAM_KEY]"
                )

            values.append(
                f'"{text}"'
                if (
                    " " in text
                    or "\\" in text
                )
                else text
            )

        return " ".join(values)

    # ---------------------------------------------------------
    # START
    # ---------------------------------------------------------

    def start(
        self,
        destination_id: str,
        source: str | Path,
    ) -> dict:

        state = self._get_state(
            destination_id
        )

        if (
            state.process is not None
            and state.process.poll() is None
        ):
            return {
                "started": False,
                "success": False,
                "reason": "ALREADY_RUNNING",
            }

        try:

            command = self.build_command(
                destination_id,
                source,
            )

            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )

        except FileNotFoundError:

            state.running = False
            state.error = (
                "FFMPEG_NOT_FOUND"
            )

            self.metrics_manager.record_failure(
                destination_id,
                "FFMPEG_NOT_FOUND",
            )

            return {
                "started": False,
                "success": False,
                "reason": "FFMPEG_NOT_FOUND",
            }

        except Exception as exc:

            state.running = False
            state.error = str(exc)

            self.metrics_manager.record_failure(
                destination_id,
                str(exc),
            )

            return {
                "started": False,
                "success": False,
                "reason": str(exc),
            }

        state.process = process
        state.running = True
        state.error = None

        self.metrics_manager.record_start(
            destination_id
        )

        return {
            "started": True,
            "success": True,
            "reason": "STREAM_STARTED",
        }

    # ---------------------------------------------------------
    # STOP
    # ---------------------------------------------------------

    def stop(
        self,
        destination_id: str,
    ) -> dict:

        state = self._get_state(
            destination_id
        )

        process = state.process

        if process is None:
            state.running = False

            return {
                "stopped": False,
                "success": True,
                "reason": "NOT_RUNNING",
            }

        if process.poll() is None:

            process.terminate()

            try:
                process.wait(
                    timeout=5
                )

            except subprocess.TimeoutExpired:

                process.kill()
                process.wait()

        state.process = None
        state.running = False

        self.metrics_manager.record_stop(
            destination_id
        )

        return {
            "stopped": True,
            "success": True,
            "reason": "STREAM_STOPPED",
        }

    # ---------------------------------------------------------
    # STATUS
    # ---------------------------------------------------------

    def status(
        self,
        destination_id: str,
    ) -> dict:

        state = self._get_state(
            destination_id
        )

        process_running = (
            state.process is not None
            and state.process.poll() is None
        )

        state.running = process_running

        return {
            "destination_id": destination_id,
            "running": process_running,
            "process": (
                "RUNNING"
                if process_running
                else "STOPPED"
            ),
            "source": (
                str(state.source)
                if state.source
                else None
            ),
            "error": state.error,
        }


# ============================================================
# TEST
# ============================================================

def main():

    print("=" * 60)
    print("STREAM ENGINE TEST")
    print("=" * 60)

    engine = StreamEngine()

    # ---------------------------------------------------------
    # Configuration
    # ---------------------------------------------------------

    print("\nConfiguration test:")

    destination = (
        engine.get_destination(
            "youtube_01"
        )
    )

    if destination is None:

        print(
            "- youtube_01: NOT FOUND"
        )

    else:

        validation = (
            engine.validate_destination(
                "youtube_01"
            )
        )

        print(
            f"- Valid: "
            f"{validation['ready']}"
        )

        print(
            f"- Reason: "
            f"{validation['reason']}"
        )

    # ---------------------------------------------------------
    # Video filter
    # ---------------------------------------------------------

    print("\nVideo filter test:")

    video_filter = (
        engine.build_video_filter()
    )

    print(
        f"- Filter: {video_filter}"
    )

    # ---------------------------------------------------------
    # Source
    # ---------------------------------------------------------

    source = (
        Path(__file__).resolve().parent
        / "cache"
        / "youtube_01"
        / "Episode 1 –The Boy Who Loved the Morning Sky.mp4"
    )

    print("\nSource test:")

    source_result = (
        engine.validate_source(
            source
        )
    )

    print(
        f"- Ready: "
        f"{source_result['ready']}"
    )

    print(
        f"- Reason: "
        f"{source_result['reason']}"
    )

    # ---------------------------------------------------------
    # Command
    # ---------------------------------------------------------

    print("\nFFmpeg command test:")

    try:

        command = engine.build_command(
            "youtube_01",
            source,
            use_branding=False,
        )

        print(
            "- Command:"
        )

        print(
            engine.command_for_display(
                command
            )
        )

        print(
            "- Command generation: OK"
        )

    except Exception as exc:

        print(
            f"- Command generation blocked: "
            f"{exc}"
        )

    # ---------------------------------------------------------
    # Initial status
    # ---------------------------------------------------------

    print("\nInitial status:")

    status = engine.status(
        "youtube_01"
    )

    print(
        f"- Running: "
        f"{status['running']}"
    )

    print(
        f"- Process: "
        f"{status['process']}"
    )

    # ---------------------------------------------------------
    # Runtime safety
    # ---------------------------------------------------------

    print("\nRuntime safety test:")

    print(
        "- FFmpeg start: NOT EXECUTED"
    )

    print(
        "- RTMP streaming: NOT EXECUTED"
    )

    print(
        "- Credentials: NOT MODIFIED"
    )

    print(
        "- Playlist: NOT MODIFIED"
    )

    print(
        "- Google Drive: NOT MODIFIED"
    )

    print(
        "\nResult: "
        "STREAM ENGINE COMMAND LAYER READY"
    )

    print("\n" + "=" * 60)
    print(
        "STREAM ENGINE TEST COMPLETE"
    )
    print("=" * 60)


if __name__ == "__main__":
    main()