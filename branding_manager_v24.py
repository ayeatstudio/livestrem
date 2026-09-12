
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Optional


BASE_DIR = Path(__file__).resolve().parent

ASSETS_DIR = BASE_DIR / "assets"
DEFAULT_LOGO = ASSETS_DIR / "logo.png"

TEST_OUTPUT_DIR = BASE_DIR / "test_output"
TEST_OUTPUT = TEST_OUTPUT_DIR / "branding_test.mp4"


class BrandingManagerV24:
    """
    Branding Manager v2.4

    Responsibilities:
    - Validate channel logo asset
    - Validate branding configuration
    - Build FFmpeg overlay filter
    - Integrate branding into a video filter
    - Perform LOCAL FFmpeg render test
    - Never start RTMP streaming
    """

    VALID_POSITIONS = {
        "top-left",
        "top-right",
        "bottom-left",
        "bottom-right",
    }

    SUPPORTED_LOGO_FORMATS = {
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
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
        self.opacity = float(opacity)
        self.margin = margin

    # ---------------------------------------------------------
    # STATUS
    # ---------------------------------------------------------

    def status(self) -> dict:
        validation = self.validate()

        return {
            "enabled": self.enabled,
            "logo": str(self.logo_path),
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

        if self.width <= 0:
            return {
                "ready": False,
                "reason": "INVALID_WIDTH",
            }

        if not 0.0 <= self.opacity <= 1.0:
            return {
                "ready": False,
                "reason": "INVALID_OPACITY",
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

        if self.logo_path.suffix.lower() not in self.SUPPORTED_LOGO_FORMATS:
            return {
                "ready": False,
                "reason": "LOGO_FORMAT_UNSUPPORTED",
            }

        if shutil.which("ffmpeg") is None:
            return {
                "ready": False,
                "reason": "FFMPEG_NOT_FOUND",
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

        if self.position == "top-left":
            return (
                str(self.margin),
                str(self.margin),
            )

        if self.position == "top-right":
            return (
                f"W-w-{self.margin}",
                str(self.margin),
            )

        if self.position == "bottom-left":
            return (
                str(self.margin),
                f"H-h-{self.margin}",
            )

        return (
            f"W-w-{self.margin}",
            f"H-h-{self.margin}",
        )

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
                return (
                    f"[{input_label}]null"
                    f"[{output_label}]"
                )

            raise ValueError(
                f"Branding unavailable: "
                f"{validation['reason']}"
            )

        x, y = self.position_expression()

        logo_path = self.logo_path.as_posix()

        return (
            f"movie={logo_path},"
            f"scale={self.width}:-1,"
            f"format=rgba,"
            f"colorchannelmixer=aa={self.opacity}"
            f"[logo];"
            f"[{input_label}]"
            f"[logo]"
            f"overlay={x}:{y}"
            f"[{output_label}]"
        )

    # ---------------------------------------------------------
    # FULL FILTER
    # ---------------------------------------------------------

    def build_video_filter(self) -> str:

        base_filter = (
            "scale=1920:1080:"
            "force_original_aspect_ratio=decrease,"
            "pad=1920:1080:"
            "(ow-iw)/2:(oh-ih)/2"
        )

        if not self.enabled:
            return base_filter

        logo_filter = self.build_logo_filter(
            input_label="0:v",
            output_label="vout",
        )

        return (
            f"{base_filter},"
            f"format=yuv420p"
            f"[base];"
            f"{logo_filter.replace('[0:v]', '[base]')}"
        )

    # ---------------------------------------------------------
    # LOCAL FFMPEG TEST
    # ---------------------------------------------------------

    def render_test(
        self,
        input_video: str | Path,
        output_video: str | Path = TEST_OUTPUT,
        duration: int = 10,
    ) -> dict:

        input_path = Path(input_video)
        output_path = Path(output_video)

        if not input_path.exists():
            return {
                "started": False,
                "success": False,
                "reason": "TEST_VIDEO_MISSING",
                "output": str(output_path),
            }

        validation = self.validate()

        if not validation["ready"]:
            return {
                "started": False,
                "success": False,
                "reason": validation["reason"],
                "output": str(output_path),
            }

        output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        x, y = self.position_expression()

        logo_path = self.logo_path.as_posix()

        filter_complex = (
            f"[1:v]"
            f"scale={self.width}:-1,"
            f"format=rgba,"
            f"colorchannelmixer=aa={self.opacity}"
            f"[logo];"
            f"[0:v]"
            f"scale=1920:1080:"
            f"force_original_aspect_ratio=decrease,"
            f"pad=1920:1080:"
            f"(ow-iw)/2:(oh-ih)/2"
            f"[base];"
            f"[base][logo]"
            f"overlay={x}:{y}"
            f"[vout]"
        )

        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",

            "-y",

            "-t",
            str(duration),

            "-i",
            str(input_path),

            "-loop",
            "1",

            "-i",
            logo_path,

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

            "-c:a",
            "aac",

            "-b:a",
            "128k",

            "-shortest",

            str(output_path),
        ]

        try:

            result = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
            )

        except subprocess.TimeoutExpired:
            return {
                "started": True,
                "success": False,
                "reason": "FFMPEG_TIMEOUT",
                "output": str(output_path),
            }

        except Exception as exc:
            return {
                "started": False,
                "success": False,
                "reason": f"FFMPEG_START_ERROR: {exc}",
                "output": str(output_path),
            }

        if result.returncode != 0:
            return {
                "started": True,
                "success": False,
                "reason": "FFMPEG_RENDER_FAILED",
                "return_code": result.returncode,
                "stderr": result.stderr.strip(),
                "output": str(output_path),
            }

        return {
            "started": True,
            "success": output_path.exists(),
            "reason": (
                "RENDER_SUCCESS"
                if output_path.exists()
                else "OUTPUT_FILE_MISSING"
            ),
            "return_code": result.returncode,
            "output": str(output_path),
        }


# =============================================================
# TEST
# =============================================================

def run_test():

    print("=" * 60)
    print("BRANDING MANAGER v2.4 TEST")
    print("=" * 60)

    branding = BrandingManagerV24()

    print("\nConfiguration:")
    print(f"- Enabled: {branding.enabled}")
    print(f"- Logo: {branding.logo_path}")
    print(f"- Position: {branding.position}")
    print(f"- Width: {branding.width}")
    print(f"- Opacity: {branding.opacity}")
    print(f"- Margin: {branding.margin}")

    print("\nAsset validation:")

    validation = branding.validate()

    print(
        f"- Ready: {validation['ready']}"
    )

    print(
        f"- Reason: {validation['reason']}"
    )

    if branding.logo_path.exists():
        print(
            f"- Size: "
            f"{branding.logo_path.stat().st_size} bytes"
        )
    else:
        print("- Size: N/A")

    print("\nPosition test:")

    for position in sorted(
        BrandingManagerV24.VALID_POSITIONS
    ):

        test = BrandingManagerV24(
            logo_path=branding.logo_path,
            position=position,
        )

        x, y = test.position_expression()

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

    print("\nLocal render test:")

    source_video = (
        BASE_DIR
        / "cache"
        / "youtube_01"
        / "Episode 1 –The Boy Who Loved the Morning Sky.mp4"
    )

    print(
        f"  Source: {source_video}"
    )

    print(
        f"  Output: {TEST_OUTPUT}"
    )

    if not source_video.exists():

        print(
            "  Render: BLOCKED"
        )

        print(
            "  Reason: TEST_VIDEO_MISSING"
        )

    else:

        result = branding.render_test(
            source_video,
            TEST_OUTPUT,
            duration=10,
        )

        print(
            f"  Started: "
            f"{result.get('started')}"
        )

        print(
            f"  Success: "
            f"{result.get('success')}"
        )

        print(
            f"  Reason: "
            f"{result.get('reason')}"
        )

        if result.get("return_code") is not None:
            print(
                f"  Return code: "
                f"{result['return_code']}"
            )

        if result.get("stderr"):
            print(
                f"  FFmpeg error: "
                f"{result['stderr']}"
            )

    print("\nSafety checks:")
    print("  - No RTMP destination used.")
    print("  - No YouTube stream started.")
    print("  - No Facebook stream started.")
    print("  - No Instagram stream started.")
    print("  - No credentials modified.")
    print("  - No playlist modified.")
    print("  - No Google Drive files modified.")

    print("\n" + "=" * 60)
    print("BRANDING MANAGER v2.4 TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    run_test()

