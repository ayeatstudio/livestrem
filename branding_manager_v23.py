from __future__ import annotations

from pathlib import Path
from typing import Optional


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_LOGO = BASE_DIR / "assets" / "logo.png"


class BrandingManagerV23:
    """
    Branding / channel-logo manager.

    v2.3:
    - Logo asset discovery
    - Logo validation
    - Position validation
    - Overlay filter generation
    - Safe failure when logo is missing/invalid
    """

    VALID_POSITIONS = {
        "top-left": ("30", "30"),
        "top-right": ("W-w-30", "30"),
        "bottom-left": ("30", "H-h-30"),
        "bottom-right": ("W-w-30", "H-h-30"),
    }

    def __init__(
        self,
        enabled: bool = True,
        logo_path: Optional[str | Path] = None,
        position: str = "top-right",
        width: int = 180,
        opacity: float = 0.9,
        margin: int = 30,
    ):
        self.enabled = bool(enabled)

        self.logo_path = (
            Path(logo_path)
            if logo_path
            else DEFAULT_LOGO
        )

        self.position = position
        self.width = width
        self.opacity = opacity
        self.margin = margin

    # ---------------------------------------------------------
    # STATUS
    # ---------------------------------------------------------

    def status(self) -> dict:
        validation = self.validate()

        return {
            "enabled": self.enabled,
            "path": str(self.logo_path),
            "position": self.position,
            "width": self.width,
            "opacity": self.opacity,
            "margin": self.margin,
            "ready": validation["ready"],
            "reason": validation["reason"],
        }

    # ---------------------------------------------------------
    # VALIDATION
    # ---------------------------------------------------------

    def validate(self) -> dict:
        if not self.enabled:
            return {
                "ready": True,
                "reason": "LOGO_DISABLED",
            }

        if self.position not in self.VALID_POSITIONS:
            return {
                "ready": False,
                "reason": "INVALID_POSITION",
            }

        if not isinstance(self.width, int):
            return {
                "ready": False,
                "reason": "INVALID_WIDTH",
            }

        if self.width <= 0:
            return {
                "ready": False,
                "reason": "INVALID_WIDTH",
            }

        if not isinstance(self.opacity, (int, float)):
            return {
                "ready": False,
                "reason": "INVALID_OPACITY",
            }

        if not 0.0 <= float(self.opacity) <= 1.0:
            return {
                "ready": False,
                "reason": "INVALID_OPACITY",
            }

        if not isinstance(self.margin, int):
            return {
                "ready": False,
                "reason": "INVALID_MARGIN",
            }

        if self.margin < 0:
            return {
                "ready": False,
                "reason": "INVALID_MARGIN",
            }

        if not self.logo_path.exists():
            return {
                "ready": False,
                "reason": "LOGO_FILE_MISSING",
            }

        if not self.logo_path.is_file():
            return {
                "ready": False,
                "reason": "LOGO_PATH_NOT_FILE",
            }

        if self.logo_path.stat().st_size <= 0:
            return {
                "ready": False,
                "reason": "LOGO_FILE_EMPTY",
            }

        if self.logo_path.suffix.lower() not in {
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
        }:
            return {
                "ready": False,
                "reason": "LOGO_FORMAT_UNSUPPORTED",
            }

        return {
            "ready": True,
            "reason": "READY",
        }

    # ---------------------------------------------------------
    # POSITION
    # ---------------------------------------------------------

    def position_expression(self) -> tuple[str, str]:
        if self.position not in self.VALID_POSITIONS:
            raise ValueError(
                f"Invalid logo position: {self.position}"
            )

        x, y = self.VALID_POSITIONS[self.position]

        if self.position == "top-left":
            x = str(self.margin)
            y = str(self.margin)

        elif self.position == "top-right":
            x = f"W-w-{self.margin}"
            y = str(self.margin)

        elif self.position == "bottom-left":
            x = str(self.margin)
            y = f"H-h-{self.margin}"

        elif self.position == "bottom-right":
            x = f"W-w-{self.margin}"
            y = f"H-h-{self.margin}"

        return x, y

    # ---------------------------------------------------------
    # LOGO FILTER
    # ---------------------------------------------------------

    def build_logo_filter(
        self,
        input_label: str = "0:v",
        output_label: str = "vout",
    ) -> str:

        validation = self.validate()

        if not validation["ready"]:
            if validation["reason"] == "LOGO_DISABLED":
                return f"[{input_label}]null[{output_label}]"

            raise ValueError(
                f"Branding unavailable: "
                f"{validation['reason']}"
            )

        x, y = self.position_expression()

        return (
            f"movie={self.logo_path.as_posix()},"
            f"scale={self.width}:-1,"
            f"format=rgba,"
            f"colorchannelmixer=aa={self.opacity}"
            f"[logo];"
            f"[{input_label}][logo]"
            f"overlay={x}:{y}"
            f"[{output_label}]"
        )

    # ---------------------------------------------------------
    # APPLY TO BASE FILTER
    # ---------------------------------------------------------

    def apply_to_filter(
        self,
        base_filter: str,
        input_label: str = "0:v",
        output_label: str = "vout",
    ) -> str:

        validation = self.validate()

        if not validation["ready"]:
            if validation["reason"] == "LOGO_DISABLED":
                return base_filter

            raise ValueError(
                f"Cannot apply branding: "
                f"{validation['reason']}"
            )

        logo_filter = self.build_logo_filter(
            input_label=input_label,
            output_label=output_label,
        )

        return (
            f"{base_filter};"
            f"{logo_filter}"
        )

    # ---------------------------------------------------------
    # OUTPUT LABEL
    # ---------------------------------------------------------

    def output_label(self) -> str:
        if self.enabled:
            return "[vout]"

        return "[0:v]"


def run_test():
    print("=" * 60)
    print("BRANDING MANAGER v2.3 TEST")
    print("=" * 60)

    branding = BrandingManagerV23()

    print("\nConfiguration:")
    print(f"- Enabled: {branding.enabled}")
    print(f"- Logo: {branding.logo_path}")
    print(f"- Position: {branding.position}")
    print(f"- Width: {branding.width}")
    print(f"- Opacity: {branding.opacity}")
    print(f"- Margin: {branding.margin}")

    print("\nAsset discovery:")
    print(
        f"- Exists: "
        f"{branding.logo_path.exists()}"
    )

    print(
        f"- File: "
        f"{branding.logo_path.is_file()}"
    )

    if branding.logo_path.exists():
        print(
            f"- Size: "
            f"{branding.logo_path.stat().st_size} bytes"
        )

    validation = branding.validate()

    print("\nValidation:")
    print(
        f"- Ready: {validation['ready']}"
    )
    print(
        f"- Reason: {validation['reason']}"
    )

    print("\nPosition expressions:")

    for position in BrandingManagerV23.VALID_POSITIONS:
        test_branding = BrandingManagerV23(
            logo_path=branding.logo_path,
            position=position,
        )

        x, y = test_branding.position_expression()

        print(
            f"- {position} | "
            f"x={x} | y={y}"
        )

    print("\nLogo filter test:")

    try:
        logo_filter = branding.build_logo_filter()

        print(
            f"  Filter: {logo_filter}"
        )
        print("  Result: OK")

    except Exception as exc:
        print(
            f"  Filter blocked safely: {exc}"
        )

    print("\nBase filter integration test:")

    base_filter = (
        "scale=1920:1080:"
        "force_original_aspect_ratio=decrease,"
        "pad=1920:1080:(ow-iw)/2:(oh-ih)/2"
    )

    try:
        final_filter = branding.apply_to_filter(
            base_filter
        )

        print(
            f"  Final filter: {final_filter}"
        )
        print("  Integration: OK")

    except Exception as exc:
        print(
            f"  Integration blocked safely: {exc}"
        )

    print("\nLogo-disabled test:")

    disabled = BrandingManagerV23(
        enabled=False
    )

    disabled_validation = disabled.validate()

    print(
        f"- Ready: {disabled_validation['ready']}"
    )
    print(
        f"- Reason: {disabled_validation['reason']}"
    )

    print(
        f"- Output label: "
        f"{disabled.output_label()}"
    )

    print("\nSafety checks:")
    print("  - No FFmpeg process started.")
    print("  - No RTMP destination used.")
    print("  - No credentials modified.")
    print("  - No playlist modified.")
    print("  - No Google Drive files modified.")

    print("\n" + "=" * 60)
    print("BRANDING MANAGER v2.3 TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    run_test()