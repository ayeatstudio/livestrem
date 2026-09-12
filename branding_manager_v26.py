from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


SUPPORTED_EXTENSIONS = (".png", ".jpg", ".jpeg")


@dataclass
class BrandingConfig:
    enabled: bool = True
    position: str = "top-right"
    width: int = 180
    opacity: float = 0.9
    margin: int = 30


class BrandingManagerV26:
    """
    Multi-destination branding manager.

    Each destination owns its own logo asset.

    Example:
        youtube_01 -> assets/youtube/youtube_01.png
        facebook_01 -> assets/facebook/facebook_01.png
        instagram_01 -> assets/instagram/instagram_01.png

    Safety:
    - Never substitutes another destination's logo.
    - Missing logo blocks branding integration.
    - Disabled branding produces video passthrough.
    - No FFmpeg process is started by this class.
    """

    POSITIONS = {
        "top-left": ("30", "30"),
        "top-right": ("W-w-30", "30"),
        "bottom-left": ("30", "H-h-30"),
        "bottom-right": ("W-w-30", "H-h-30"),
    }

    def __init__(
        self,
        root: str | Path = r"D:\streaming_engine",
    ):
        self.root = Path(root)
        self.assets_dir = self.root / "assets"

        self.configs: dict[str, BrandingConfig] = {}

    # ---------------------------------------------------------
    # CONFIGURATION
    # ---------------------------------------------------------

    def set_config(
        self,
        destination_id: str,
        *,
        enabled: bool = True,
        position: str = "top-right",
        width: int = 180,
        opacity: float = 0.9,
        margin: int = 30,
    ) -> None:
        self.configs[destination_id] = BrandingConfig(
            enabled=enabled,
            position=position,
            width=width,
            opacity=opacity,
            margin=margin,
        )

    def get_config(self, destination_id: str) -> BrandingConfig:
        return self.configs.get(
            destination_id,
            BrandingConfig(),
        )

    # ---------------------------------------------------------
    # PATH RESOLUTION
    # ---------------------------------------------------------

    def platform_from_destination(
        self,
        destination_id: str,
    ) -> Optional[str]:
        if destination_id.startswith("youtube_"):
            return "youtube"

        if destination_id.startswith("facebook_"):
            return "facebook"

        if destination_id.startswith("instagram_"):
            return "instagram"

        return None

    def resolve_logo(
        self,
        destination_id: str,
    ) -> Optional[Path]:
        """
        Resolve ONLY the logo belonging to destination_id.

        No global logo fallback is used.
        """

        platform = self.platform_from_destination(destination_id)

        if not platform:
            return None

        folder = self.assets_dir / platform

        for extension in SUPPORTED_EXTENSIONS:
            candidate = folder / f"{destination_id}{extension}"

            if candidate.is_file():
                return candidate

        return None

    # ---------------------------------------------------------
    # VALIDATION
    # ---------------------------------------------------------

    def validate(
        self,
        destination_id: str,
    ) -> dict:
        config = self.get_config(destination_id)

        if not config.enabled:
            return {
                "ready": True,
                "reason": "LOGO_DISABLED",
                "destination_id": destination_id,
                "logo": None,
            }

        if config.position not in self.POSITIONS:
            return {
                "ready": False,
                "reason": "INVALID_POSITION",
                "destination_id": destination_id,
                "logo": None,
            }

        if not isinstance(config.width, int) or config.width <= 0:
            return {
                "ready": False,
                "reason": "INVALID_WIDTH",
                "destination_id": destination_id,
                "logo": None,
            }

        if not isinstance(config.opacity, (int, float)):
            return {
                "ready": False,
                "reason": "INVALID_OPACITY",
                "destination_id": destination_id,
                "logo": None,
            }

        if not 0 < float(config.opacity) <= 1:
            return {
                "ready": False,
                "reason": "INVALID_OPACITY",
                "destination_id": destination_id,
                "logo": None,
            }

        if not isinstance(config.margin, int) or config.margin < 0:
            return {
                "ready": False,
                "reason": "INVALID_MARGIN",
                "destination_id": destination_id,
                "logo": None,
            }

        logo = self.resolve_logo(destination_id)

        if logo is None:
            return {
                "ready": False,
                "reason": "LOGO_FILE_MISSING",
                "destination_id": destination_id,
                "logo": None,
            }

        return {
            "ready": True,
            "reason": "READY",
            "destination_id": destination_id,
            "logo": str(logo),
        }

    # ---------------------------------------------------------
    # FFMPEG PATH
    # ---------------------------------------------------------

    @staticmethod
    def ffmpeg_path(path: Path) -> str:
        """
        Convert Windows path to FFmpeg-friendly path.
        """

        return str(path).replace("\\", "/")

    # ---------------------------------------------------------
    # FILTER
    # ---------------------------------------------------------

    def build_logo_filter(
        self,
        destination_id: str,
    ) -> str:
        validation = self.validate(destination_id)

        if not validation["ready"]:
            if validation["reason"] == "LOGO_DISABLED":
                return "[0:v]"

            raise ValueError(
                f"Branding unavailable: "
                f"{validation['reason']}"
            )

        config = self.get_config(destination_id)
        logo = Path(validation["logo"])

        x, y = self.POSITIONS[config.position]

        # Use configured margin rather than hard-coded 30.
        if config.position == "top-left":
            x = str(config.margin)
            y = str(config.margin)

        elif config.position == "top-right":
            x = f"W-w-{config.margin}"
            y = str(config.margin)

        elif config.position == "bottom-left":
            x = str(config.margin)
            y = f"H-h-{config.margin}"

        elif config.position == "bottom-right":
            x = f"W-w-{config.margin}"
            y = f"H-h-{config.margin}"

        logo_path = self.ffmpeg_path(logo)

        return (
            f"movie={logo_path},"
            f"scale={config.width}:-1,"
            f"format=rgba,"
            f"colorchannelmixer=aa={config.opacity}"
            f"[logo];"
            f"[0:v][logo]"
            f"overlay={x}:{y}"
            f"[vout]"
        )

    # ---------------------------------------------------------
    # BASE FILTER INTEGRATION
    # ---------------------------------------------------------

    def apply_to_filter(
        self,
        destination_id: str,
        base_filter: str = "[0:v]",
    ) -> str:
        validation = self.validate(destination_id)

        if not validation["ready"]:
            if validation["reason"] == "LOGO_DISABLED":
                return base_filter

            raise ValueError(
                f"Cannot apply branding: "
                f"{validation['reason']}"
            )

        config = self.get_config(destination_id)
        logo = Path(validation["logo"])

        logo_path = self.ffmpeg_path(logo)

        if config.position == "top-left":
            x = str(config.margin)
            y = str(config.margin)

        elif config.position == "top-right":
            x = f"W-w-{config.margin}"
            y = str(config.margin)

        elif config.position == "bottom-left":
            x = str(config.margin)
            y = f"H-h-{config.margin}"

        else:
            x = f"W-w-{config.margin}"
            y = f"H-h-{config.margin}"

        if base_filter == "[0:v]":
            video_input = "[0:v]"
        else:
            video_input = base_filter

        return (
            f"movie={logo_path},"
            f"scale={config.width}:-1,"
            f"format=rgba,"
            f"colorchannelmixer=aa={config.opacity}"
            f"[logo];"
            f"{video_input}[logo]"
            f"overlay={x}:{y}"
            f"[vout]"
        )

    # ---------------------------------------------------------
    # STATUS
    # ---------------------------------------------------------

    def status(self, destination_id: str) -> dict:
        config = self.get_config(destination_id)
        validation = self.validate(destination_id)

        return {
            "destination_id": destination_id,
            "enabled": config.enabled,
            "position": config.position,
            "width": config.width,
            "opacity": config.opacity,
            "margin": config.margin,
            "logo": validation.get("logo"),
            "ready": validation["ready"],
            "reason": validation["reason"],
        }


# =============================================================
# TEST
# =============================================================

def main():
    print("=" * 60)
    print("BRANDING MANAGER v2.6 TEST")
    print("=" * 60)

    manager = BrandingManagerV26()

    destinations = [
        "youtube_01",
        "youtube_02",
        "youtube_03",
        "youtube_04",
        "facebook_01",
        "facebook_02",
        "instagram_01",
    ]

    for destination_id in destinations:
        manager.set_config(
            destination_id,
            enabled=True,
            position="top-right",
            width=180,
            opacity=0.9,
            margin=30,
        )

    print("\nDestination logo mapping:")

    for destination_id in destinations:
        platform = manager.platform_from_destination(
            destination_id
        )

        logo = manager.resolve_logo(destination_id)

        print(
            f"- {destination_id} | "
            f"{platform} | "
            f"{logo if logo else 'MISSING'}"
        )

    print("\nValidation:")

    ready = 0

    for destination_id in destinations:
        result = manager.validate(destination_id)

        if result["ready"]:
            ready += 1

        print(
            f"- {destination_id} | "
            f"ready={result['ready']} | "
            f"reason={result['reason']}"
        )

    print(
        f"\nBranding-ready destinations: "
        f"{ready}/{len(destinations)}"
    )

    print("\nLogo-disabled test:")

    manager.set_config(
        "youtube_01",
        enabled=False,
    )

    disabled = manager.validate("youtube_01")

    print(
        f"- youtube_01 | "
        f"ready={disabled['ready']} | "
        f"reason={disabled['reason']}"
    )

    print(
        f"- passthrough: "
        f"{manager.build_logo_filter('youtube_01')}"
    )

    # Restore configuration.
    manager.set_config(
        "youtube_01",
        enabled=True,
        position="top-right",
        width=180,
        opacity=0.9,
        margin=30,
    )

    print("\nFilter generation test:")

    for destination_id in destinations:
        result = manager.validate(destination_id)

        if not result["ready"]:
            print(
                f"- {destination_id} | "
                f"FILTER BLOCKED | "
                f"{result['reason']}"
            )
            continue

        try:
            filter_text = manager.build_logo_filter(
                destination_id
            )

            print(
                f"- {destination_id} | "
                f"FILTER OK | "
                f"{filter_text}"
            )

        except Exception as exc:
            print(
                f"- {destination_id} | "
                f"FILTER FAILED | {exc}"
            )

    print("\nSafety checks:")
    print("  - No FFmpeg process started.")
    print("  - No RTMP destination used.")
    print("  - No credentials modified.")
    print("  - No playlists modified.")
    print("  - No Google Drive files modified.")
    print("  - No destination logo fallback is performed.")

    print("\n" + "=" * 60)
    print("BRANDING MANAGER v2.6 TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()