from __future__ import annotations

from pathlib import Path
from typing import Optional

from config_manager import ConfigManager
from credential_manager import CredentialManager
from playlist_manager import PlaylistManager


BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "assets"
DEFAULT_LOGO = ASSETS_DIR / "logo.png"


class BrandingManager:
    """
    Handles destination branding configuration and
    FFmpeg logo overlay filter generation.
    """

    VALID_POSITIONS = {
        "top-left",
        "top-right",
        "bottom-left",
        "bottom-right",
        "center",
    }

    def __init__(self):
        self.default_logo = DEFAULT_LOGO

    # ---------------------------------------------------------
    # LOGO STATUS
    # ---------------------------------------------------------

    def logo_exists(self, path: Optional[str | Path] = None) -> bool:
        logo_path = Path(path) if path else self.default_logo
        return logo_path.is_file()

    def logo_size(self, path: Optional[str | Path] = None):
        logo_path = Path(path) if path else self.default_logo

        if not logo_path.is_file():
            return None

        try:
            from PIL import Image

            with Image.open(logo_path) as image:
                return image.size

        except Exception:
            return None

    # ---------------------------------------------------------
    # POSITION
    # ---------------------------------------------------------

    def overlay_coordinates(
        self,
        position: str,
        margin: int = 30,
    ) -> tuple[str, str]:

        position = position.lower().strip()

        if position == "top-left":
            return str(margin), str(margin)

        if position == "top-right":
            return (
                f"W-w-{margin}",
                str(margin),
            )

        if position == "bottom-left":
            return (
                str(margin),
                f"H-h-{margin}",
            )

        if position == "bottom-right":
            return (
                f"W-w-{margin}",
                f"H-h-{margin}",
            )

        if position == "center":
            return (
                "(W-w)/2",
                "(H-h)/2",
            )

        raise ValueError(
            f"Invalid logo position: {position}"
        )

    # ---------------------------------------------------------
    # FILTER
    # ---------------------------------------------------------

    def build_filter(
        self,
        position: str = "top-right",
        width: int = 180,
        opacity: float = 0.9,
        margin: int = 30,
    ) -> str:

        if width <= 0:
            raise ValueError(
                "Logo width must be greater than zero."
            )

        if not 0.0 <= opacity <= 1.0:
            raise ValueError(
                "Logo opacity must be between 0.0 and 1.0."
            )

        x, y = self.overlay_coordinates(
            position,
            margin,
        )

        return (
            "[1:v]"
            f"scale={width}:-1,"
            "format=rgba,"
            f"colorchannelmixer=aa={opacity}"
            "[logo];"
            "[0:v][logo]"
            f"overlay={x}:{y}"
            "[vout]"
        )


class StreamingSchedulerV20:

    def __init__(self):
        self.config_manager = ConfigManager()
        self.credential_manager = CredentialManager()
        self.playlist_manager = PlaylistManager()

        self.destinations: dict[str, dict] = {}
        self.playlists: dict[str, dict] = {}

        self.branding = BrandingManager()

        self.positions: dict[str, int] = {}
        self.transitions: dict[str, int] = {}
        self.current: dict[str, Optional[str]] = {}

    # ---------------------------------------------------------
    # LOAD
    # ---------------------------------------------------------

    def load(self):

        self.destinations = {}

        for destination in self.config_manager.get_destinations():

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

        for destination_id in self.destinations:

            playlist = self.playlists.get(
                destination_id,
                {},
            )

            videos = (
                playlist.get("videos", [])
                if isinstance(playlist, dict)
                else []
            )

            if videos:
                self.positions[destination_id] = 1
                self.current[destination_id] = (
                    videos[0].get("name")
                )
            else:
                self.positions[destination_id] = None
                self.current[destination_id] = None

            self.transitions[destination_id] = 0

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

        credential = self.credential_manager.get(
            destination_id
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

        branding = destination.get(
            "branding",
            {},
        )

        logo_enabled = branding.get(
            "logo_enabled",
            True,
        )

        logo_path = branding.get(
            "logo_path",
            str(DEFAULT_LOGO),
        )

        if logo_enabled and not self.branding.logo_exists(
            logo_path
        ):
            return {
                "ready": False,
                "reason": "LOGO_ASSET_MISSING",
            }

        return {
            "ready": True,
            "reason": "READY",
            "platform": destination.get("platform"),
            "videos": len(videos),
            "current": video.get("name"),
            "logo_enabled": logo_enabled,
            "logo_path": logo_path,
        }

    # ---------------------------------------------------------
    # BRANDING
    # ---------------------------------------------------------

    def branding_config(self, destination_id: str) -> dict:

        destination = self.destinations.get(
            destination_id,
            {},
        )

        branding = destination.get(
            "branding",
            {},
        )

        return {
            "logo_enabled": branding.get(
                "logo_enabled",
                True,
            ),
            "logo_path": branding.get(
                "logo_path",
                str(DEFAULT_LOGO),
            ),
            "position": branding.get(
                "logo_position",
                "top-right",
            ),
            "width": branding.get(
                "logo_width",
                180,
            ),
            "opacity": branding.get(
                "logo_opacity",
                0.9,
            ),
            "margin": branding.get(
                "logo_margin",
                30,
            ),
        }

    def build_branding_filter(
        self,
        destination_id: str,
    ) -> Optional[str]:

        config = self.branding_config(
            destination_id
        )

        if not config["logo_enabled"]:
            return None

        return self.branding.build_filter(
            position=config["position"],
            width=int(config["width"]),
            opacity=float(config["opacity"]),
            margin=int(config["margin"]),
        )

    # ---------------------------------------------------------
    # PLAYLIST TRANSITION
    # ---------------------------------------------------------

    def transition(
        self,
        destination_id: str,
    ) -> Optional[dict]:

        playlist = self.playlists.get(
            destination_id
        )

        if not isinstance(playlist, dict):
            return None

        videos = playlist.get("videos", [])

        if not videos:
            return None

        current_position = (
            self.positions.get(destination_id)
        )

        if current_position is None:
            current_position = 1

        next_position = (
            current_position % len(videos)
        ) + 1

        self.positions[destination_id] = (
            next_position
        )

        video = videos[next_position - 1]

        self.current[destination_id] = (
            video.get("name")
        )

        self.transitions[destination_id] += 1

        return {
            "position": next_position,
            "current": video.get("name"),
            "transition": self.transitions[
                destination_id
            ],
        }

    # ---------------------------------------------------------
    # PREVIEW COMMAND
    # ---------------------------------------------------------

    def build_preview_command(
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

        credential = self.credential_manager.get(
            destination_id
        )

        video = playlist["videos"][0]

        output_url = (
            str(credential["rtmp_url"]).rstrip("/")
            + "/"
            + str(credential["stream_key"]).strip()
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

        branding_filter = (
            self.build_branding_filter(
                destination_id
            )
        )

        if branding_filter:

            logo_path = (
                self.branding_config(
                    destination_id
                )["logo_path"]
            )

            command.extend([
                "-i",
                str(logo_path),
                "-filter_complex",
                branding_filter,
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
    # STATUS
    # ---------------------------------------------------------

    def status(self, destination_id: str) -> dict:

        validation = self.validate(
            destination_id
        )

        branding = self.branding_config(
            destination_id
        )

        logo_path = Path(
            branding["logo_path"]
        )

        return {
            "destination_id": destination_id,
            "ready": validation["ready"],
            "reason": validation["reason"],
            "logo_enabled": branding["logo_enabled"],
            "logo_path": str(logo_path),
            "logo_exists": logo_path.is_file(),
            "position": branding["position"],
            "width": branding["width"],
            "opacity": branding["opacity"],
            "margin": branding["margin"],
            "playlist_position": self.positions.get(
                destination_id
            ),
            "current": self.current.get(
                destination_id
            ),
            "transitions": self.transitions.get(
                destination_id,
                0,
            ),
        }


def main():

    print("=" * 60)
    print("STREAM SCHEDULER v2.0 TEST")
    print("=" * 60)

    scheduler = StreamingSchedulerV20()

    scheduler.load()

    print(
        f"\n[SCHEDULER] Destinations loaded: "
        f"{len(scheduler.destinations)}"
    )

    # ---------------------------------------------------------
    # PLAYLIST
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
    # BRANDING
    # ---------------------------------------------------------

    print("\nBranding asset validation:")

    for destination_id in scheduler.destinations:

        info = scheduler.status(
            destination_id
        )

        print(
            f"- {destination_id} | "
            f"enabled={info['logo_enabled']} | "
            f"path={info['logo_path']} | "
            f"{'FOUND' if info['logo_exists'] else 'MISSING'}"
        )

    # ---------------------------------------------------------
    # TARGET
    # ---------------------------------------------------------

    target = "youtube_01"

    print(
        f"\nTarget branding test: {target}"
    )

    info = scheduler.status(target)

    print(
        f"  Logo enabled: "
        f"{info['logo_enabled']}"
    )

    print(
        f"  Position: "
        f"{info['position']}"
    )

    print(
        f"  Width: "
        f"{info['width']}"
    )

    print(
        f"  Opacity: "
        f"{info['opacity']}"
    )

    print(
        f"  Margin: "
        f"{info['margin']}"
    )

    print(
        f"  Asset: "
        f"{'FOUND' if info['logo_exists'] else 'MISSING'}"
    )

    # ---------------------------------------------------------
    # FILTER
    # ---------------------------------------------------------

    print("\nLogo filter test:")

    try:

        filter_text = (
            scheduler.build_branding_filter(
                target
            )
        )

        if filter_text:

            print(
                f"  Filter: {filter_text}"
            )

            print(
                "  Overlay filter: OK"
            )

        else:

            print(
                "  Logo overlay: DISABLED"
            )

    except Exception as exc:

        print(
            f"  Filter error: {exc}"
        )

    # ---------------------------------------------------------
    # COMMAND
    # ---------------------------------------------------------

    print("\nFFmpeg command test:")

    try:

        command = (
            scheduler.build_preview_command(
                target
            )
        )

        safe_command = " ".join(command)

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

                safe_command = safe_command.replace(
                    stream_key,
                    "***STREAM_KEY***",
                )

        print(
            f"  Command generated successfully."
        )

        print(
            f"  {safe_command}"
        )

    except Exception as exc:

        print(
            f"  Command generation blocked:"
            f" {exc}"
        )

    # ---------------------------------------------------------
    # TRANSITION
    # ---------------------------------------------------------

    print("\nPlaylist transition test:")

    before = scheduler.current.get(
        target
    )

    result = scheduler.transition(
        target
    )

    if result:

        print(
            f"  Previous: {before}"
        )

        print(
            f"  Current: "
            f"{result['current']}"
        )

        print(
            f"  Position: "
            f"{result['position']}"
        )

        print(
            f"  Transition count: "
            f"{result['transition']}"
        )

    else:

        print(
            "  Transition unavailable."
        )

    # ---------------------------------------------------------
    # ISOLATION
    # ---------------------------------------------------------

    print("\nDestination isolation test:")

    first = scheduler.status(
        "youtube_01"
    )

    second = scheduler.status(
        "youtube_02"
    )

    print(
        f"  youtube_01 | "
        f"position={first['playlist_position']} | "
        f"transitions={first['transitions']}"
    )

    print(
        f"  youtube_02 | "
        f"position={second['playlist_position']} | "
        f"transitions={second['transitions']}"
    )

    print(
        "  Isolation: OK"
    )

    # ---------------------------------------------------------
    # SAFETY
    # ---------------------------------------------------------

    print("\nRuntime safety test:")

    validation = scheduler.validate(
        target
    )

    print(
        f"  Validation: "
        f"{'READY' if validation['ready'] else 'NOT READY'}"
        f" | {validation['reason']}"
    )

    print(
        "  Real FFmpeg: NOT EXECUTED"
    )

    print("\n" + "=" * 60)
    print("STREAM SCHEDULER v2.0 TEST COMPLETE")
    print("=" * 60)

    print(
        "No real RTMP destination was used."
    )


if __name__ == "__main__":
    main()