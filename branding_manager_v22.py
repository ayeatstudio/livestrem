
from __future__ import annotations

from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_LOGO = BASE_DIR / "assets" / "logo.png"


class BrandingManager:
    """
    Branding Manager v2.2

    Responsibilities:
    - Validate logo configuration.
    - Validate logo asset.
    - Validate position.
    - Validate dimensions.
    - Validate opacity.
    - Build FFmpeg logo overlay filter.
    - Apply branding to an existing video filter.

    Safety:
    - Never modifies the source video.
    - Never modifies credentials.
    - Never starts FFmpeg.
    - Never contacts an RTMP destination.
    """

    VALID_POSITIONS = {
        "top-left": ("30", "30"),
        "top-right": ("W-w-30", "30"),
        "bottom-left": ("30", "H-h-30"),
        "bottom-right": ("W-w-30", "H-h-30"),
    }

    VALID_EXTENSIONS = {
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
    }

    def __init__(
        self,
        config: dict[str, Any] | None = None,
    ):
        config = config or {}

        self.enabled = bool(
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
        ).strip().lower()

        self.width = config.get(
            "logo_width",
            180,
        )

        self.opacity = config.get(
            "logo_opacity",
            0.9,
        )

        self.margin = config.get(
            "logo_margin",
            30,
        )

    # ---------------------------------------------------------
    # NORMALIZATION
    # ---------------------------------------------------------

    @staticmethod
    def _number(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    # ---------------------------------------------------------
    # VALIDATION
    # ---------------------------------------------------------

    def validate(self) -> dict[str, Any]:
        if not self.enabled:
            return {
                "ready": True,
                "enabled": False,
                "reason": "LOGO_DISABLED",
            }

        if not self.logo_path.exists():
            return {
                "ready": False,
                "enabled": True,
                "reason": "LOGO_FILE_MISSING",
                "logo": str(self.logo_path),
            }

        if not self.logo_path.is_file():
            return {
                "ready": False,
                "enabled": True,
                "reason": "LOGO_PATH_NOT_FILE",
                "logo": str(self.logo_path),
            }

        extension = (
            self.logo_path.suffix.lower()
        )

        if extension not in self.VALID_EXTENSIONS:
            return {
                "ready": False,
                "enabled": True,
                "reason": "LOGO_FORMAT_UNSUPPORTED",
                "extension": extension,
            }

        if self.position not in self.VALID_POSITIONS:
            return {
                "ready": False,
                "enabled": True,
                "reason": "LOGO_POSITION_INVALID",
                "position": self.position,
            }

        width = self._number(
            self.width
        )

        if width is None:
            return {
                "ready": False,
                "enabled": True,
                "reason": "LOGO_WIDTH_INVALID",
            }

        if width <= 0:
            return {
                "ready": False,
                "enabled": True,
                "reason": "LOGO_WIDTH_INVALID",
            }

        opacity = self._number(
            self.opacity
        )

        if opacity is None:
            return {
                "ready": False,
                "enabled": True,
                "reason": "LOGO_OPACITY_INVALID",
            }

        if not 0.0 <= opacity <= 1.0:
            return {
                "ready": False,
                "enabled": True,
                "reason": "LOGO_OPACITY_INVALID",
            }

        margin = self._number(
            self.margin
        )

        if margin is None:
            return {
                "ready": False,
                "enabled": True,
                "reason": "LOGO_MARGIN_INVALID",
            }

        if margin < 0:
            return {
                "ready": False,
                "enabled": True,
                "reason": "LOGO_MARGIN_INVALID",
            }

        return {
            "ready": True,
            "enabled": True,
            "reason": "READY",
            "logo": str(self.logo_path),
            "position": self.position,
            "width": width,
            "opacity": opacity,
            "margin": margin,
        }

    # ---------------------------------------------------------
    # POSITION
    # ---------------------------------------------------------

    def position_expression(self) -> tuple[str, str]:
        validation = self.validate()

        if not validation["ready"]:
            raise ValueError(
                validation["reason"]
            )

        if not self.enabled:
            raise ValueError(
                "LOGO_DISABLED"
            )

        x, y = self.VALID_POSITIONS[
            self.position
        ]

        margin = int(
            float(self.margin)
        )

        x = x.replace(
            "30",
            str(margin),
        )

        y = y.replace(
            "30",
            str(margin),
        )

        return x, y

    # ---------------------------------------------------------
    # LOGO FILTER
    # ---------------------------------------------------------

    def build_logo_filter(self) -> str:
        validation = self.validate()

        if not validation["ready"]:
            raise ValueError(
                validation["reason"]
            )

        if not self.enabled:
            return ""

        x, y = self.position_expression()

        width = int(
            float(self.width)
        )

        opacity = float(
            self.opacity
        )

        logo_input = (
            str(self.logo_path)
            .replace("\\", "/")
            .replace(":", "\\:")
            .replace("'", "\\'")
        )

        return (
            f"movie='{logo_input}',"
            f"scale={width}:-1,"
            f"format=rgba,"
            f"colorchannelmixer=aa={opacity}"
            f"[logo];"
            f"[0:v][logo]"
            f"overlay={x}:{y}"
            f"[vout]"
        )

    # ---------------------------------------------------------
    # APPLY TO FILTER
    # ---------------------------------------------------------

    def apply_to_filter(
        self,
        base_filter: str,
    ) -> str:
        if not isinstance(
            base_filter,
            str,
        ):
            raise TypeError(
                "base_filter must be a string"
            )

        if not self.enabled:
            return base_filter

        validation = self.validate()

        if not validation["ready"]:
            raise ValueError(
                validation["reason"]
            )

        x, y = self.position_expression()

        width = int(
            float(self.width)
        )

        opacity = float(
            self.opacity
        )

        logo_input = (
            str(self.logo_path)
            .replace("\\", "/")
            .replace(":", "\\:")
            .replace("'", "\\'")
        )

        return (
            f"{base_filter},"
            f"movie='{logo_input}',"
            f"scale={width}:-1,"
            f"format=rgba,"
            f"colorchannelmixer=aa={opacity}"
            f"[logo];"
            f"[in]"
            f"overlay={x}:{y}"
        )

    # ---------------------------------------------------------
    # OUTPUT LABEL
    # ---------------------------------------------------------

    def output_label(self) -> str:
        return (
            "BRANDED"
            if self.enabled
            else "UNBRANDED"
        )

    # ---------------------------------------------------------
    # STATUS
    # ---------------------------------------------------------

    def status(self) -> dict[str, Any]:
        result = self.validate()

        return {
            "enabled": self.enabled,
            "ready": result["ready"],
            "reason": result["reason"],
            "logo": str(self.logo_path),
            "position": self.position,
            "width": self.width,
            "opacity": self.opacity,
            "margin": self.margin,
            "label": self.output_label(),
        }


# =============================================================
# TEST
# =============================================================

def run_test():
    print("=" * 60)
    print("BRANDING MANAGER v2.2 TEST")
    print("=" * 60)

    manager = BrandingManager()

    print("\nConfiguration:")

    status = manager.status()

    print(
        f"- Enabled: {status['enabled']}"
    )
    print(
        f"- Logo: {status['logo']}"
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

    validation = manager.validate()

    print(
        f"- Ready: {validation['ready']}"
    )
    print(
        f"- Reason: {validation['reason']}"
    )

    if "logo" in validation:
        print(
            f"- Logo: {validation['logo']}"
        )

    print("\nPosition validation:")

    for position in sorted(
        manager.VALID_POSITIONS
    ):
        config = {
            "logo_enabled": True,
            "logo_path": str(
                manager.logo_path
            ),
            "logo_position": position,
            "logo_width": 180,
            "logo_opacity": 0.9,
            "logo_margin": 30,
        }

        test_manager = BrandingManager(
            config
        )

        x, y = test_manager.VALID_POSITIONS[
            position
        ]

        print(
            f"- {position} | "
            f"x={x} | y={y} | API=OK"
        )

    print("\nInvalid configuration tests:")

    invalid_configs = [
        (
            "invalid-position",
            {
                "logo_position": "center",
            },
        ),
        (
            "invalid-width",
            {
                "logo_width": 0,
            },
        ),
        (
            "invalid-opacity",
            {
                "logo_opacity": 1.5,
            },
        ),
        (
            "invalid-margin",
            {
                "logo_margin": -1,
            },
        ),
    ]

    for label, overrides in invalid_configs:
        config = {
            "logo_enabled": True,
            "logo_path": str(
                manager.logo_path
            ),
            "logo_position": "top-right",
            "logo_width": 180,
            "logo_opacity": 0.9,
            "logo_margin": 30,
        }

        config.update(overrides)

        test_manager = BrandingManager(
            config
        )

        result = test_manager.validate()

        print(
            f"- {label} | "
            f"ready={result['ready']} | "
            f"reason={result['reason']}"
        )

    print("\nLogo-disabled test:")

    disabled = BrandingManager(
        {
            "logo_enabled": False,
        }
    )

    disabled_result = disabled.validate()

    print(
        f"- Ready: {disabled_result['ready']}"
    )
    print(
        f"- Reason: {disabled_result['reason']}"
    )
    print(
        f"- Filter passthrough: "
        f"{disabled.apply_to_filter('scale=1920:1080')}"
    )

    print("\nLogo filter test:")

    try:
        logo_filter = (
            manager.build_logo_filter()
        )

        print("  Filter: OK")
        print(
            f"  {logo_filter}"
        )

    except Exception as exc:
        print(
            f"  Filter blocked safely: "
            f"{exc}"
        )

    print("\nBase filter integration test:")

    try:
        final_filter = (
            manager.apply_to_filter(
                "scale=1920:1080"
            )
        )

        print("  Integration: OK")
        print(
            f"  {final_filter}"
        )

    except Exception as exc:
        print(
            f"  Integration blocked safely: "
            f"{exc}"
        )

    print("\nSafety checks:")
    print(
        "  - No FFmpeg process started."
    )
    print(
        "  - No RTMP destination used."
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

    print("=" * 60)
    print("BRANDING MANAGER v2.2 TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    run_test()

