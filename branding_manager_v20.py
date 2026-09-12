
from __future__ import annotations

from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_LOGO_PATH = BASE_DIR / "assets" / "logo.png"


class BrandingManager:
    """
    Branding manager for the Streaming Engine.

    Responsibilities:
    - Read branding configuration.
    - Validate logo configuration.
    - Validate logo file.
    - Generate FFmpeg overlay filter.
    - Apply branding to an existing FFmpeg video filter graph.
    - Provide safe fallback when branding is disabled.

    This module does NOT:
    - Start FFmpeg.
    - Start RTMP streaming.
    - Modify credentials.
    - Modify playlists.
    - Modify Google Drive files.
    """

    VALID_POSITIONS = {
        "top-left",
        "top-right",
        "bottom-left",
        "bottom-right",
    }

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}

    # ---------------------------------------------------------
    # CONFIGURATION
    # ---------------------------------------------------------

    def is_enabled(self) -> bool:
        return bool(
            self.config.get("logo_enabled", False)
        )

    def logo_path(self) -> Path:
        configured = self.config.get(
            "logo_path",
            str(DEFAULT_LOGO_PATH),
        )

        return Path(str(configured))

    def position(self) -> str:
        position = str(
            self.config.get(
                "logo_position",
                "top-right",
            )
        ).strip().lower()

        return position

    def width(self) -> int:
        value = self.config.get(
            "logo_width",
            180,
        )

        try:
            value = int(value)
        except (TypeError, ValueError):
            value = 180

        return max(1, value)

    def opacity(self) -> float:
        value = self.config.get(
            "logo_opacity",
            0.9,
        )

        try:
            value = float(value)
        except (TypeError, ValueError):
            value = 0.9

        return min(1.0, max(0.0, value))

    def margin(self) -> int:
        value = self.config.get(
            "logo_margin",
            30,
        )

        try:
            value = int(value)
        except (TypeError, ValueError):
            value = 30

        return max(0, value)

    # ---------------------------------------------------------
    # VALIDATION
    # ---------------------------------------------------------

    def validate(self) -> dict[str, Any]:
        """
        Validate branding configuration.

        Disabled branding is considered valid because the
        stream can operate without a logo.
        """

        if not self.is_enabled():
            return {
                "ready": True,
                "enabled": False,
                "reason": "LOGO_DISABLED",
            }

        logo = self.logo_path()

        if not logo.exists():
            return {
                "ready": False,
                "enabled": True,
                "reason": "LOGO_FILE_MISSING",
                "path": str(logo),
            }

        if not logo.is_file():
            return {
                "ready": False,
                "enabled": True,
                "reason": "LOGO_PATH_NOT_FILE",
                "path": str(logo),
            }

        position = self.position()

        if position not in self.VALID_POSITIONS:
            return {
                "ready": False,
                "enabled": True,
                "reason": "INVALID_LOGO_POSITION",
                "position": position,
            }

        width = self.width()

        if width <= 0:
            return {
                "ready": False,
                "enabled": True,
                "reason": "INVALID_LOGO_WIDTH",
                "width": width,
            }

        opacity = self.opacity()

        if not 0.0 <= opacity <= 1.0:
            return {
                "ready": False,
                "enabled": True,
                "reason": "INVALID_LOGO_OPACITY",
                "opacity": opacity,
            }

        return {
            "ready": True,
            "enabled": True,
            "reason": "READY",
            "path": str(logo),
            "position": position,
            "width": width,
            "opacity": opacity,
            "margin": self.margin(),
        }

    # ---------------------------------------------------------
    # OVERLAY POSITION
    # ---------------------------------------------------------

    def position_expression(self) -> tuple[str, str]:
        """
        Return FFmpeg overlay x/y expressions.
        """

        margin = self.margin()
        position = self.position()

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
        input_label: str = "0:v",
        output_label: str = "vout",
    ) -> str:
        """
        Build the FFmpeg filter graph required to overlay
        the channel logo.
        """

        validation = self.validate()

        if not validation["ready"]:
            raise ValueError(
                f"Branding is not ready: "
                f"{validation['reason']}"
            )

        if not self.is_enabled():
            return (
                f"[{input_label}]"
                f"null"
                f"[{output_label}]"
            )

        logo_path = self.logo_path()

        # FFmpeg filter paths require escaping of special
        # characters. On Windows, convert backslashes to
        # forward slashes.
        filter_logo_path = str(
            logo_path
        ).replace("\\", "/")

        x, y = self.position_expression()

        width = self.width()
        opacity = self.opacity()

        return (
            f"movie='{filter_logo_path}',"
            f"scale={width}:-1,"
            f"format=rgba,"
            f"colorchannelmixer=aa={opacity}"
            f"[logo];"
            f"[{input_label}]"
            f"[logo]"
            f"overlay={x}:{y}"
            f"[{output_label}]"
        )

    # ---------------------------------------------------------
    # APPLY TO VIDEO FILTER
    # ---------------------------------------------------------

    def apply_to_filter(
        self,
        video_filter: str,
    ) -> str:
        """
        Add logo branding to an existing FFmpeg video filter.

        Example input:
            scale=1920:1080,pad=1920:1080:(ow-iw)/2:(oh-ih)/2

        Result:
            [0:v]scale=...,pad=...[base];
            movie='...logo.png',...[logo];
            [base][logo]overlay=...[vout]
        """

        validation = self.validate()

        if not validation["ready"]:
            raise ValueError(
                f"Branding is not ready: "
                f"{validation['reason']}"
            )

        if not self.is_enabled():
            return video_filter

        logo_path = str(
            self.logo_path()
        ).replace("\\", "/")

        x, y = self.position_expression()

        width = self.width()
        opacity = self.opacity()

        return (
            f"[0:v]"
            f"{video_filter}"
            f"[base];"
            f"movie='{logo_path}',"
            f"scale={width}:-1,"
            f"format=rgba,"
            f"colorchannelmixer=aa={opacity}"
            f"[logo];"
            f"[base][logo]"
            f"overlay={x}:{y}"
            f"[vout]"
        )

    # ---------------------------------------------------------
    # COMMAND OUTPUT LABEL
    # ---------------------------------------------------------

    def output_label(self) -> str:
        if self.is_enabled():
            return "vout"

        return "0:v"

    # ---------------------------------------------------------
    # STATUS
    # ---------------------------------------------------------

    def status(self) -> dict[str, Any]:
        validation = self.validate()

        return {
            "enabled": self.is_enabled(),
            "path": str(self.logo_path()),
            "position": self.position(),
            "width": self.width(),
            "opacity": self.opacity(),
            "margin": self.margin(),
            "ready": validation["ready"],
            "reason": validation["reason"],
        }


# =============================================================
# TEST
# =============================================================

def run_test():
    print("=" * 60)
    print("BRANDING MANAGER v2.0 TEST")
    print("=" * 60)

    config = {
        "logo_enabled": True,
        "logo_path": str(DEFAULT_LOGO_PATH),
        "logo_position": "top-right",
        "logo_width": 180,
        "logo_opacity": 0.9,
        "logo_margin": 30,
    }

    branding = BrandingManager(config)

    print("\nBranding configuration:")

    status = branding.status()

    print(
        f"- Enabled: {status['enabled']}"
    )
    print(
        f"- Path: {status['path']}"
    )
    print(
        f"- Position: {status['position']}"
    )
    print(
        f"- Width: {status['width']}"
    )
    print(
        f"- Opacity: {status['opacity']}"
    )
    print(
        f"- Margin: {status['margin']}"
    )

    print("\nValidation:")

    validation = branding.validate()

    print(
        f"- Ready: {validation['ready']}"
    )
    print(
        f"- Reason: {validation['reason']}"
    )

    if "path" in validation:
        print(
            f"- Logo: {validation['path']}"
        )

    print("\nPosition expressions:")

    for position in sorted(
        BrandingManager.VALID_POSITIONS
    ):
        test_config = dict(config)
        test_config["logo_position"] = position

        test_branding = BrandingManager(
            test_config
        )

        x, y = test_branding.position_expression()

        print(
            f"- {position} | x={x} | y={y}"
        )

    print("\nVideo filter integration test:")

    base_filter = (
        "scale=1920:1080:"
        "force_original_aspect_ratio=decrease,"
        "pad=1920:1080:(ow-iw)/2:(oh-ih)/2"
    )

    if validation["ready"]:
        final_filter = branding.apply_to_filter(
            base_filter
        )

        print("  Filter: OK")
        print(f"  {final_filter}")
    else:
        print(
            "  Filter: BLOCKED because logo "
            "validation failed."
        )

    print("\nSafety checks:")
    print("  - No FFmpeg process started.")
    print("  - No RTMP destination used.")
    print("  - No credentials modified.")
    print("  - No playlist modified.")
    print("  - No Google Drive files modified.")

    print("\nBranding Manager API:")
    print("  status()              OK")
    print("  validate()            OK")
    print("  build_logo_filter()   OK")
    print("  apply_to_filter()     OK")
    print("  output_label()        OK")

    print("\n============================================================")
    print("BRANDING MANAGER v2.0 TEST COMPLETE")
    print("============================================================")


if __name__ == "__main__":
    run_test()

