from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from config_manager import ConfigManager


# ============================================================
# BRANDING MANAGER v2.6.1
# ============================================================
#
# Shared branding architecture:
#
# D:\streaming_engine\
# └── assets\
#     └── branding\
#         └── logo.png
#
# The same transparent PNG can be used by all destinations.
#
# Important:
# - Branding does NOT start FFmpeg by itself.
# - Branding does NOT modify credentials.
# - Branding does NOT modify playlists.
# - Branding does NOT access Google Drive.
# - Logo-disabled mode safely returns the original video filter.
# - Missing logo is reported safely.
# ============================================================


@dataclass
class BrandingConfig:
    enabled: bool = True
    logo_path: str = ""
    position: str = "top-right"
    width: int = 180
    opacity: float = 0.90
    margin: int = 30


class BrandingManager:
    """
    Shared video branding manager.

    One global PNG logo can be used across all destinations.
    Destination-specific branding settings may still be supplied
    through the destination configuration.
    """

    VALID_POSITIONS = {
        "top-left",
        "top-right",
        "bottom-left",
        "bottom-right",
    }

    def __init__(self):
        self.config_manager = ConfigManager()

        self.root = Path(__file__).resolve().parent

        self.default_logo = (
            self.root
            / "assets"
            / "branding"
            / "logo.png"
        )

        self._config = BrandingConfig(
            enabled=True,
            logo_path=str(self.default_logo),
            position="top-right",
            width=180,
            opacity=0.90,
            margin=30,
        )

        self.destinations: dict[str, dict] = {}

        self.load_destinations()

    # ---------------------------------------------------------
    # LOAD
    # ---------------------------------------------------------

    def load_destinations(self) -> None:
        self.destinations = {}

        try:
            items = self.config_manager.get_destinations()
        except Exception:
            items = []

        for destination in items:
            if (
                isinstance(destination, dict)
                and destination.get("id")
            ):
                self.destinations[
                    destination["id"]
                ] = destination

    # ---------------------------------------------------------
    # CONFIG
    # ---------------------------------------------------------

    def get_config(
        self,
        destination_id: Optional[str] = None,
    ) -> BrandingConfig:

        config = BrandingConfig(
            enabled=self._config.enabled,
            logo_path=self._config.logo_path,
            position=self._config.position,
            width=self._config.width,
            opacity=self._config.opacity,
            margin=self._config.margin,
        )

        destination = self.destinations.get(
            destination_id
        ) if destination_id else None

        if not isinstance(destination, dict):
            return config

        branding = destination.get("branding")

        if isinstance(branding, dict):

            if "enabled" in branding:
                config.enabled = bool(
                    branding["enabled"]
                )

            if branding.get("logo_path"):
                config.logo_path = str(
                    branding["logo_path"]
                )

            if branding.get("position") is not None:
                config.position = str(
                    branding["position"]
                )

            if branding.get("width") is not None:
                try:
                    config.width = int(
                        branding["width"]
                    )
                except (TypeError, ValueError):
                    pass

            if branding.get("opacity") is not None:
                try:
                    config.opacity = float(
                        branding["opacity"]
                    )
                except (TypeError, ValueError):
                    pass

            if branding.get("margin") is not None:
                try:
                    config.margin = int(
                        branding["margin"]
                    )
                except (TypeError, ValueError):
                    pass

        return config

    # ---------------------------------------------------------
    # PATH
    # ---------------------------------------------------------

    def resolve_logo_path(
        self,
        destination_id: Optional[str] = None,
    ) -> Path:

        config = self.get_config(destination_id)

        logo = Path(config.logo_path)

        if not logo.is_absolute():
            logo = self.root / logo

        return logo.resolve()

    # ---------------------------------------------------------
    # VALIDATION
    # ---------------------------------------------------------

    def validate(
        self,
        destination_id: Optional[str] = None,
    ) -> dict:

        config = self.get_config(destination_id)

        # -----------------------------------------------------
        # Disabled branding
        #
        # IMPORTANT:
        # Do this BEFORE accessing the logo path.
        #
        # This fixes the v2.6 Path(None) crash.
        # -----------------------------------------------------

        if not config.enabled:
            return {
                "ready": True,
                "reason": "LOGO_DISABLED",
                "logo": None,
                "position": config.position,
                "width": config.width,
                "opacity": config.opacity,
                "margin": config.margin,
            }

        # -----------------------------------------------------
        # Position
        # -----------------------------------------------------

        if config.position not in self.VALID_POSITIONS:
            return {
                "ready": False,
                "reason": "INVALID_LOGO_POSITION",
                "logo": str(
                    self.resolve_logo_path(
                        destination_id
                    )
                ),
                "position": config.position,
                "width": config.width,
                "opacity": config.opacity,
                "margin": config.margin,
            }

        # -----------------------------------------------------
        # Width
        # -----------------------------------------------------

        if config.width <= 0:
            return {
                "ready": False,
                "reason": "INVALID_LOGO_WIDTH",
                "logo": str(
                    self.resolve_logo_path(
                        destination_id
                    )
                ),
                "position": config.position,
                "width": config.width,
                "opacity": config.opacity,
                "margin": config.margin,
            }

        # -----------------------------------------------------
        # Opacity
        # -----------------------------------------------------

        if not 0.0 <= config.opacity <= 1.0:
            return {
                "ready": False,
                "reason": "INVALID_LOGO_OPACITY",
                "logo": str(
                    self.resolve_logo_path(
                        destination_id
                    )
                ),
                "position": config.position,
                "width": config.width,
                "opacity": config.opacity,
                "margin": config.margin,
            }

        # -----------------------------------------------------
        # Margin
        # -----------------------------------------------------

        if config.margin < 0:
            return {
                "ready": False,
                "reason": "INVALID_LOGO_MARGIN",
                "logo": str(
                    self.resolve_logo_path(
                        destination_id
                    )
                ),
                "position": config.position,
                "width": config.width,
                "opacity": config.opacity,
                "margin": config.margin,
            }

        logo = self.resolve_logo_path(
            destination_id
        )

        # -----------------------------------------------------
        # Logo file
        # -----------------------------------------------------

        if not logo.exists():
            return {
                "ready": False,
                "reason": "LOGO_FILE_MISSING",
                "logo": str(logo),
                "position": config.position,
                "width": config.width,
                "opacity": config.opacity,
                "margin": config.margin,
            }

        if not logo.is_file():
            return {
                "ready": False,
                "reason": "LOGO_PATH_NOT_FILE",
                "logo": str(logo),
                "position": config.position,
                "width": config.width,
                "opacity": config.opacity,
                "margin": config.margin,
            }

        if logo.stat().st_size <= 0:
            return {
                "ready": False,
                "reason": "LOGO_FILE_EMPTY",
                "logo": str(logo),
                "position": config.position,
                "width": config.width,
                "opacity": config.opacity,
                "margin": config.margin,
            }

        return {
            "ready": True,
            "reason": "READY",
            "logo": str(logo),
            "position": config.position,
            "width": config.width,
            "opacity": config.opacity,
            "margin": config.margin,
        }

    # ---------------------------------------------------------
    # STATUS
    # ---------------------------------------------------------

    def status(
        self,
        destination_id: Optional[str] = None,
    ) -> dict:

        validation = self.validate(
            destination_id
        )

        return validation

    # ---------------------------------------------------------
    # FFMPEG PATH
    # ---------------------------------------------------------

    @staticmethod
    def ffmpeg_path(path: Path) -> str:
        """
        Convert Windows path into an FFmpeg-friendly path.
        """

        value = str(path.resolve())

        # FFmpeg filter paths work more reliably with
        # forward slashes on Windows.
        value = value.replace("\\", "/")

        # Escape colon after drive letter.
        if len(value) >= 2 and value[1] == ":":
            value = value[0] + "\\:" + value[2:]

        return value

    # ---------------------------------------------------------
    # POSITION
    # ---------------------------------------------------------

    def position_expression(
        self,
        position: str,
        margin: int,
    ) -> tuple[str, str]:

        if position == "top-left":
            return (
                str(margin),
                str(margin),
            )

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

        raise ValueError(
            f"Invalid logo position: {position}"
        )

    # ---------------------------------------------------------
    # LOGO FILTER
    # ---------------------------------------------------------

    def build_logo_filter(
        self,
        destination_id: str,
    ) -> str:

        validation = self.validate(
            destination_id
        )

        # -----------------------------------------------------
        # FIX:
        #
        # Never call Path(None).
        #
        # Disabled branding simply passes the source video
        # through untouched.
        # -----------------------------------------------------

        if validation["reason"] == "LOGO_DISABLED":
            return "[0:v]"

        if not validation["ready"]:
            raise ValueError(
                "Branding unavailable: "
                f"{validation['reason']}"
            )

        config = self.get_config(
            destination_id
        )

        logo = Path(validation["logo"])

        x, y = self.position_expression(
            config.position,
            config.margin,
        )

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
    # APPLY TO EXISTING FILTER
    # ---------------------------------------------------------

    def apply_to_filter(
        self,
        destination_id: str,
        base_filter: str = "[0:v]",
    ) -> str:

        validation = self.validate(
            destination_id
        )

        # -----------------------------------------------------
        # Disabled branding:
        # preserve the original filter.
        # -----------------------------------------------------

        if validation["reason"] == "LOGO_DISABLED":
            return base_filter

        if not validation["ready"]:
            raise ValueError(
                "Cannot apply branding: "
                f"{validation['reason']}"
            )

        config = self.get_config(
            destination_id
        )

        logo = Path(validation["logo"])

        x, y = self.position_expression(
            config.position,
            config.margin,
        )

        logo_path = self.ffmpeg_path(logo)

        return (
            f"movie={logo_path},"
            f"scale={config.width}:-1,"
            f"format=rgba,"
            f"colorchannelmixer=aa={config.opacity}"
            f"[logo];"
            f"{base_filter}[logo]"
            f"overlay={x}:{y}"
            f"[vout]"
        )

    # ---------------------------------------------------------
    # OUTPUT LABEL
    # ---------------------------------------------------------

    def output_label(
        self,
        destination_id: str,
    ) -> str:

        validation = self.validate(
            destination_id
        )

        if validation["reason"] == "LOGO_DISABLED":
            return "[0:v]"

        if not validation["ready"]:
            raise ValueError(
                "Branding unavailable: "
                f"{validation['reason']}"
            )

        return "[vout]"

    # ---------------------------------------------------------
    # LOCAL RENDER TEST
    # ---------------------------------------------------------

    def render_test(
        self,
        destination_id: str,
        source: Path,
        output: Path,
    ) -> dict:

        validation = self.validate(
            destination_id
        )

        if not validation["ready"]:
            return {
                "started": False,
                "success": False,
                "reason": validation["reason"],
                "return_code": None,
            }

        if not source.exists():
            return {
                "started": False,
                "success": False,
                "reason": "SOURCE_FILE_MISSING",
                "return_code": None,
            }

        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        filter_value = self.build_logo_filter(
            destination_id
        )

        command = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-filter_complex",
            filter_value,
            "-map",
            "[vout]",
            "-map",
            "0:a?",
            "-t",
            "5",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            str(output),
        ]

        try:
            result = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )

        except FileNotFoundError:
            return {
                "started": False,
                "success": False,
                "reason": "FFMPEG_NOT_FOUND",
                "return_code": None,
            }

        success = (
            result.returncode == 0
            and output.exists()
            and output.stat().st_size > 0
        )

        return {
            "started": True,
            "success": success,
            "reason": (
                "RENDER_SUCCESS"
                if success
                else "RENDER_FAILED"
            ),
            "return_code": result.returncode,
            "stderr": result.stderr.strip(),
        }


# ============================================================
# TEST HELPERS
# ============================================================

def print_validation(
    manager: BrandingManager,
    destination_id: str,
) -> None:

    result = manager.validate(
        destination_id
    )

    print(
        f"- {destination_id} | "
        f"ready={result['ready']} | "
        f"reason={result['reason']}"
    )


# ============================================================
# MAIN TEST
# ============================================================

def main():

    print("=" * 60)
    print("BRANDING MANAGER v2.6.1 TEST")
    print("=" * 60)

    manager = BrandingManager()

    # ---------------------------------------------------------
    # Configuration
    # ---------------------------------------------------------

    config = manager.get_config()

    print("\nShared branding configuration:")
    print(
        f"- Enabled: {config.enabled}"
    )
    print(
        f"- Logo: {config.logo_path}"
    )
    print(
        f"- Position: {config.position}"
    )
    print(
        f"- Width: {config.width}"
    )
    print(
        f"- Opacity: {config.opacity}"
    )
    print(
        f"- Margin: {config.margin}"
    )

    # ---------------------------------------------------------
    # Logo discovery
    # ---------------------------------------------------------

    logo = manager.resolve_logo_path()

    print("\nAsset discovery:")
    print(
        f"- Exists: {logo.exists()}"
    )
    print(
        f"- File: {logo.is_file()}"
    )

    if logo.exists():
        print(
            f"- Size: {logo.stat().st_size} bytes"
        )

    # ---------------------------------------------------------
    # Destination mapping
    # ---------------------------------------------------------

    print("\nDestination logo mapping:")

    destination_ids = [
        "youtube_01",
        "youtube_02",
        "youtube_03",
        "youtube_04",
        "facebook_01",
        "facebook_02",
        "instagram_01",
    ]

    for destination_id in destination_ids:

        validation = manager.validate(
            destination_id
        )

        logo_value = validation.get(
            "logo"
        )

        if logo_value:
            print(
                f"- {destination_id} | "
                f"{logo_value} | "
                f"{validation['reason']}"
            )
        else:
            print(
                f"- {destination_id} | "
                f"LOGO_DISABLED"
            )

    # ---------------------------------------------------------
    # Validation
    # ---------------------------------------------------------

    print("\nValidation:")

    ready_count = 0

    for destination_id in destination_ids:

        validation = manager.validate(
            destination_id
        )

        if validation["ready"]:
            ready_count += 1

        print_validation(
            manager,
            destination_id,
        )

    print(
        f"\nBranding-ready destinations: "
        f"{ready_count}/{len(destination_ids)}"
    )

    # ---------------------------------------------------------
    # Position tests
    # ---------------------------------------------------------

    print("\nPosition expressions:")

    for position in [
        "top-left",
        "top-right",
        "bottom-left",
        "bottom-right",
    ]:

        x, y = manager.position_expression(
            position,
            30,
        )

        print(
            f"- {position} | "
            f"x={x} | "
            f"y={y}"
        )

    # ---------------------------------------------------------
    # Logo filter test
    # ---------------------------------------------------------

    print("\nLogo filter test:")

    try:
        filter_value = (
            manager.build_logo_filter(
                "youtube_01"
            )
        )

        print(
            f"  Filter: {filter_value}"
        )
        print("  Result: OK")

    except Exception as exc:
        print(
            f"  Filter blocked safely: {exc}"
        )

    # ---------------------------------------------------------
    # Logo disabled regression test
    # ---------------------------------------------------------

    print("\nLogo-disabled regression test:")

    original_enabled = (
        manager._config.enabled
    )

    manager._config.enabled = False

    try:

        disabled_validation = (
            manager.validate(
                "youtube_01"
            )
        )

        disabled_filter = (
            manager.build_logo_filter(
                "youtube_01"
            )
        )

        disabled_applied = (
            manager.apply_to_filter(
                "youtube_01",
                "[0:v]",
            )
        )

        print(
            f"- Ready: "
            f"{disabled_validation['ready']}"
        )
        print(
            f"- Reason: "
            f"{disabled_validation['reason']}"
        )
        print(
            f"- Logo filter: "
            f"{disabled_filter}"
        )
        print(
            f"- Applied filter: "
            f"{disabled_applied}"
        )
        print(
            "- Regression: PASS"
        )

    except Exception as exc:

        print(
            f"- Regression: FAIL | {exc}"
        )

    finally:
        manager._config.enabled = (
            original_enabled
        )

    # ---------------------------------------------------------
    # Apply filter test
    # ---------------------------------------------------------

    print("\nBase filter integration test:")

    try:

        base_filter = (
            "scale=1920:1080"
        )

        combined = (
            manager.apply_to_filter(
                "youtube_01",
                base_filter,
            )
        )

        print(
            f"  Filter: {combined}"
        )
        print(
            "  Result: OK"
        )

    except Exception as exc:

        print(
            f"  Integration blocked safely: "
            f"{exc}"
        )

    # ---------------------------------------------------------
    # Local render
    # ---------------------------------------------------------

    source = (
        manager.root
        / "cache"
        / "youtube_01"
        / "Episode 1 –The Boy Who Loved the Morning Sky.mp4"
    )

    output = (
        manager.root
        / "test_output"
        / "branding_v261_test.mp4"
    )

    print("\nLocal render test:")

    if not source.exists():

        print(
            f"  Source missing: {source}"
        )
        print(
            "  Render: NOT EXECUTED"
        )

    else:

        render = manager.render_test(
            "youtube_01",
            source,
            output,
        )

        print(
            f"  Source: {source}"
        )
        print(
            f"  Output: {output}"
        )
        print(
            f"  Started: {render['started']}"
        )
        print(
            f"  Success: {render['success']}"
        )
        print(
            f"  Reason: {render['reason']}"
        )
        print(
            f"  Return code: "
            f"{render['return_code']}"
        )

        if render.get("stderr"):
            print(
                f"  FFmpeg error: "
                f"{render['stderr']}"
            )

    # ---------------------------------------------------------
    # Safety
    # ---------------------------------------------------------

    print("\nSafety checks:")
    print(
        "  - No RTMP destination used."
    )
    print(
        "  - No YouTube stream started."
    )
    print(
        "  - No Facebook stream started."
    )
    print(
        "  - No Instagram stream started."
    )
    print(
        "  - No credentials modified."
    )
    print(
        "  - No playlist modified."
    )
    print(
        "  - No Google Drive files modified."
    )

    print("\n" + "=" * 60)
    print(
        "BRANDING MANAGER v2.6.1 TEST COMPLETE"
    )
    print("=" * 60)


if __name__ == "__main__":
    main()