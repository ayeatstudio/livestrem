
from __future__ import annotations

from pathlib import Path
from typing import Optional

from config_manager import ConfigManager
from credential_manager import CredentialManager
from playlist_manager import PlaylistManager


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_LOGO = BASE_DIR / "assets" / "logo.png"


class BrandingProfile:
    """Independent branding profile for one destination."""

    VALID_POSITIONS = {
        "top-left",
        "top-right",
        "bottom-left",
        "bottom-right",
        "center",
    }

    def __init__(
        self,
        destination_id: str,
        config: Optional[dict] = None,
    ):
        self.destination_id = destination_id
        config = config or {}

        self.logo_enabled = bool(
            config.get("logo_enabled", True)
        )

        self.logo_path = Path(
            config.get(
                "logo_path",
                DEFAULT_LOGO,
            )
        )

        self.position = str(
            config.get(
                "logo_position",
                "top-right",
            )
        ).lower()

        self.width = int(
            config.get("logo_width", 180)
        )

        self.opacity = float(
            config.get("logo_opacity", 0.9)
        )

        self.margin_x = int(
            config.get(
                "logo_margin_x",
                config.get("logo_margin", 30),
            )
        )

        self.margin_y = int(
            config.get(
                "logo_margin_y",
                config.get("logo_margin", 30),
            )
        )

    def validate(self) -> dict:

        if not self.logo_enabled:
            return {
                "ready": True,
                "reason": "LOGO_DISABLED",
            }

        if self.position not in self.VALID_POSITIONS:
            return {
                "ready": False,
                "reason": "INVALID_LOGO_POSITION",
            }

        if self.width <= 0:
            return {
                "ready": False,
                "reason": "INVALID_LOGO_WIDTH",
            }

        if not 0.0 <= self.opacity <= 1.0:
            return {
                "ready": False,
                "reason": "INVALID_LOGO_OPACITY",
            }

        if self.margin_x < 0 or self.margin_y < 0:
            return {
                "ready": False,
                "reason": "INVALID_LOGO_MARGIN",
            }

        if not self.logo_path.is_file():
            return {
                "ready": False,
                "reason": "LOGO_ASSET_MISSING",
            }

        return {
            "ready": True,
            "reason": "READY",
        }

    def coordinates(self) -> tuple[str, str]:

        if self.position == "top-left":
            return (
                str(self.margin_x),
                str(self.margin_y),
            )

        if self.position == "top-right":
            return (
                f"W-w-{self.margin_x}",
                str(self.margin_y),
            )

        if self.position == "bottom-left":
            return (
                str(self.margin_x),
                f"H-h-{self.margin_y}",
            )

        if self.position == "bottom-right":
            return (
                f"W-w-{self.margin_x}",
                f"H-h-{self.margin_y}",
            )

        return (
            "(W-w)/2",
            "(H-h)/2",
        )

    def build_filter(self) -> Optional[str]:

        if not self.logo_enabled:
            return None

        check = self.validate()

        if not check["ready"]:
            raise ValueError(
                f"{self.destination_id}: "
                f"{check['reason']}"
            )

        x, y = self.coordinates()

        return (
            "[1:v]"
            f"scale={self.width}:-1,"
            "format=rgba,"
            f"colorchannelmixer=aa={self.opacity}"
            "[logo];"
            "[0:v][logo]"
            f"overlay={x}:{y}"
            "[vout]"
        )


class StreamingSchedulerV22:

    def __init__(self):

        self.config_manager = ConfigManager()
        self.credential_manager = CredentialManager()
        self.playlist_manager = PlaylistManager()

        self.destinations: dict[str, dict] = {}
        self.playlists: dict[str, dict] = {}
        self.branding: dict[str, BrandingProfile] = {}

    # ---------------------------------------------------------
    # LOAD
    # ---------------------------------------------------------

    def load(self):

        self.destinations = {}

        for destination in (
            self.config_manager.get_destinations()
        ):

            if (
                isinstance(destination, dict)
                and destination.get("id")
            ):

                destination_id = destination["id"]

                self.destinations[
                    destination_id
                ] = destination

        self.playlists = (
            self.playlist_manager.build_playlists()
        )

        self.branding = {}

        for destination_id, destination in (
            self.destinations.items()
        ):

            self.branding[destination_id] = (
                BrandingProfile(
                    destination_id,
                    destination.get(
                        "branding",
                        {},
                    ),
                )
            )

    # ---------------------------------------------------------
    # VALIDATION
    # ---------------------------------------------------------

    def validate(
        self,
        destination_id: str,
    ) -> dict:

        destination = self.destinations.get(
            destination_id
        )

        if not destination:
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

        if not Path(local_path).is_file():
            return {
                "ready": False,
                "reason": "VIDEO_CACHE_MISSING",
            }

        branding = self.branding.get(
            destination_id
        )

        if branding:

            branding_check = (
                branding.validate()
            )

            if not branding_check["ready"]:
                return {
                    "ready": False,
                    "reason": (
                        branding_check["reason"]
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
    # BUILD FFMPEG COMMAND
    # ---------------------------------------------------------

    def build_command(
        self,
        destination_id: str,
    ) -> list[str]:

        check = self.validate(
            destination_id
        )

        if not check["ready"]:
            raise ValueError(
                f"{destination_id}: "
                f"{check['reason']}"
            )

        playlist = self.playlists[
            destination_id
        ]

        credential = (
            self.credential_manager.get(
                destination_id
            )
        )

        video = playlist[
            "videos"
        ][0]

        output_url = (
            str(
                credential["rtmp_url"]
            ).rstrip("/")
            + "/"
            + str(
                credential["stream_key"]
            ).strip()
        )

        branding = self.branding.get(
            destination_id
        )

        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-re",
            "-stream_loop",
            "-1",
            "-i",
            str(video["local_path"]),
        ]

        if (
            branding
            and branding.logo_enabled
        ):

            command.extend([
                "-i",
                str(
                    branding.logo_path
                ),
                "-filter_complex",
                branding.build_filter(),
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
    # SAFE COMMAND
    # ---------------------------------------------------------

    def safe_command(
        self,
        destination_id: str,
    ) -> str:

        command = self.build_command(
            destination_id
        )

        credential = (
            self.credential_manager.get(
                destination_id
            )
        )

        stream_key = ""

        if credential:
            stream_key = str(
                credential.get(
                    "stream_key",
                    "",
                )
            )

        result = " ".join(command)

        if stream_key:
            result = result.replace(
                stream_key,
                "***STREAM_KEY***",
            )

        return result


# =============================================================
# TEST
# =============================================================

def main():

    print("=" * 60)
    print("STREAM SCHEDULER v2.2 TEST")
    print("=" * 60)

    scheduler = (
        StreamingSchedulerV22()
    )

    scheduler.load()

    print(
        f"\n[SCHEDULER] Destinations loaded: "
        f"{len(scheduler.destinations)}"
    )

    print("\nBranding profiles:")

    for destination_id in (
        scheduler.destinations
    ):

        branding = scheduler.branding[
            destination_id
        ]

        check = branding.validate()

        print(
            f"- {destination_id} | "
            f"enabled={branding.logo_enabled} | "
            f"position={branding.position} | "
            f"width={branding.width} | "
            f"opacity={branding.opacity} | "
            f"asset="
            f"{'FOUND' if branding.logo_path.is_file() else 'MISSING'} | "
            f"{check['reason']}"
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
        f"  Validation: "
        f"{'READY' if validation['ready'] else 'NOT READY'}"
        f" | {validation['reason']}"
    )

    print("\nFFmpeg command integration:")

    try:

        command = scheduler.safe_command(
            target
        )

        print(
            "  Command generation: OK"
        )

        print(
            f"  {command}"
        )

        branding = scheduler.branding[
            target
        ]

        if branding.logo_enabled:

            print(
                "  Logo overlay: ENABLED"
            )

            print(
                f"  Logo path: "
                f"{branding.logo_path}"
            )

            print(
                f"  Position: "
                f"{branding.position}"
            )

            print(
                f"  Width: "
                f"{branding.width}"
            )

            print(
                f"  Opacity: "
                f"{branding.opacity}"
            )

        else:

            print(
                "  Logo overlay: DISABLED"
            )

    except Exception as exc:

        print(
            f"  Command generation blocked: "
            f"{exc}"
        )

    print("\nSecurity test:")

    safe = scheduler.safe_command(
        target
    ) if validation["ready"] else ""

    if "***STREAM_KEY***" in safe:
        print(
            "  Stream key masking: OK"
        )
    elif validation["ready"]:
        print(
            "  Stream key masking: FAILED"
        )
    else:
        print(
            "  Stream key masking: "
            "NOT APPLICABLE"
        )

    print(
        "  Source video modification: NO"
    )

    print(
        "  Credential modification: NO"
    )

    print(
        "  Google Drive modification: NO"
    )

    print(
        "  Real FFmpeg execution: NO"
    )

    print(
        "  Real RTMP streaming: NO"
    )

    print("\n" + "=" * 60)
    print(
        "STREAM SCHEDULER v2.2 TEST COMPLETE"
    )
    print("=" * 60)


if __name__ == "__main__":
    main()

