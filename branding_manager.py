from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# ============================================================
# BRANDING MANAGER
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
CONFIG_DIR = BASE_DIR / "config"
BRANDING_CONFIG_FILE = CONFIG_DIR / "branding.json"
BRANDING_DIR = BASE_DIR / "branding"


@dataclass
class BrandingConfig:
    enabled: bool = False
    logo: Optional[str] = None
    x: str = "20"
    y: str = "20"
    width: int = 180
    opacity: float = 1.0


class BrandingManager:

    def __init__(
        self,
        config_file: str | Path = BRANDING_CONFIG_FILE,
    ):
        self.config_file = Path(config_file)
        self.config: dict = {}

        self.load()

    # ---------------------------------------------------------
    # LOAD
    # ---------------------------------------------------------

    def load(self) -> dict:

        if not self.config_file.exists():

            self.config = {
                "default": {
                    "enabled": False,
                    "logo": None,
                    "x": "20",
                    "y": "20",
                    "width": 180,
                    "opacity": 1.0,
                },
                "destinations": {},
            }

            return self.config

        try:

            with self.config_file.open(
                "r",
                encoding="utf-8",
            ) as file:

                data = json.load(file)

        except json.JSONDecodeError as exc:

            raise ValueError(
                f"Invalid branding configuration:\n{exc}"
            ) from exc

        if not isinstance(data, dict):

            raise ValueError(
                "Branding configuration root "
                "must be an object."
            )

        data.setdefault(
            "default",
            {
                "enabled": False,
                "logo": None,
                "x": "20",
                "y": "20",
                "width": 180,
                "opacity": 1.0,
            },
        )

        data.setdefault(
            "destinations",
            {},
        )

        self.config = data

        return self.config

    # ---------------------------------------------------------
    # SAVE
    # ---------------------------------------------------------

    def save(self) -> None:

        self.config_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with self.config_file.open(
            "w",
            encoding="utf-8",
        ) as file:

            json.dump(
                self.config,
                file,
                indent=4,
                ensure_ascii=False,
            )

    # ---------------------------------------------------------
    # DESTINATION CONFIG
    # ---------------------------------------------------------

    def get_config(
        self,
        destination_id: Optional[str] = None,
    ) -> BrandingConfig:

        default = self.config.get(
            "default",
            {},
        )

        values = dict(default)

        if destination_id:

            destinations = self.config.get(
                "destinations",
                {},
            )

            destination_config = (
                destinations.get(
                    destination_id,
                    {},
                )
            )

            if isinstance(
                destination_config,
                dict,
            ):
                values.update(
                    destination_config
                )

        return BrandingConfig(
            enabled=bool(
                values.get(
                    "enabled",
                    False,
                )
            ),
            logo=values.get(
                "logo"
            ),
            x=str(
                values.get(
                    "x",
                    "20",
                )
            ),
            y=str(
                values.get(
                    "y",
                    "20",
                )
            ),
            width=int(
                values.get(
                    "width",
                    180,
                )
            ),
            opacity=float(
                values.get(
                    "opacity",
                    1.0,
                )
            ),
        )

    # ---------------------------------------------------------
    # VALIDATE
    # ---------------------------------------------------------

    def validate(
        self,
        destination_id: Optional[str] = None,
    ) -> dict:

        config = self.get_config(
            destination_id
        )

        if not config.enabled:

            return {
                "ready": False,
                "reason": "LOGO_DISABLED",
                "enabled": False,
                "logo": None,
            }

        if not config.logo:

            return {
                "ready": False,
                "reason": "LOGO_NOT_CONFIGURED",
                "enabled": True,
                "logo": None,
            }

        logo_path = Path(
            config.logo
        )

        if not logo_path.is_absolute():

            logo_path = (
                BRANDING_DIR
                / logo_path
            )

        if not logo_path.exists():

            return {
                "ready": False,
                "reason": "LOGO_FILE_MISSING",
                "enabled": True,
                "logo": str(logo_path),
            }

        if not logo_path.is_file():

            return {
                "ready": False,
                "reason": "LOGO_NOT_FILE",
                "enabled": True,
                "logo": str(logo_path),
            }

        if logo_path.stat().st_size <= 0:

            return {
                "ready": False,
                "reason": "LOGO_FILE_EMPTY",
                "enabled": True,
                "logo": str(logo_path),
            }

        if config.width <= 0:

            return {
                "ready": False,
                "reason": "INVALID_LOGO_WIDTH",
                "enabled": True,
                "logo": str(logo_path),
            }

        if not 0.0 <= config.opacity <= 1.0:

            return {
                "ready": False,
                "reason": "INVALID_LOGO_OPACITY",
                "enabled": True,
                "logo": str(logo_path),
            }

        return {
            "ready": True,
            "reason": "READY",
            "enabled": True,
            "logo": str(logo_path),
        }

    # ---------------------------------------------------------
    # LOGO PATH
    # ---------------------------------------------------------

    def get_logo_path(
        self,
        destination_id: Optional[str] = None,
    ) -> Optional[Path]:

        config = self.get_config(
            destination_id
        )

        if not config.logo:
            return None

        logo_path = Path(
            config.logo
        )

        if not logo_path.is_absolute():

            logo_path = (
                BRANDING_DIR
                / logo_path
            )

        return logo_path

    # ---------------------------------------------------------
    # FILTER
    # ---------------------------------------------------------

    def apply_to_filter(
        self,
        destination_id: str,
        video_input: str = "[0:v]",
    ) -> str:

        validation = self.validate(
            destination_id
        )

        if not validation["ready"]:

            raise ValueError(
                "Branding not ready: "
                f"{validation['reason']}"
            )

        config = self.get_config(
            destination_id
        )

        logo_path = self.get_logo_path(
            destination_id
        )

        if logo_path is None:

            raise ValueError(
                "Logo path is not configured."
            )

        escaped_logo = (
            str(logo_path)
            .replace("\\", "/")
            .replace(":", r"\:")
            .replace("'", r"\'")
        )

        opacity = max(
            0.0,
            min(
                1.0,
                config.opacity,
            ),
        )

        logo_width = config.width

        return (
            f"movie='{escaped_logo}',"
            f"format=rgba,"
            f"colorchannelmixer=aa={opacity}"
            f"[logo];"
            f"[logo]scale={logo_width}:-1"
            f"[logo_scaled];"
            f"{video_input}[logo_scaled]"
            f"overlay={config.x}:{config.y}"
            f"[vout]"
        )

    # ---------------------------------------------------------
    # ENABLE / DISABLE
    # ---------------------------------------------------------

    def set_enabled(
        self,
        enabled: bool,
        destination_id: Optional[str] = None,
    ) -> None:

        if destination_id:

            destinations = self.config.setdefault(
                "destinations",
                {},
            )

            destination = destinations.setdefault(
                destination_id,
                {},
            )

            destination["enabled"] = bool(
                enabled
            )

        else:

            default = self.config.setdefault(
                "default",
                {},
            )

            default["enabled"] = bool(
                enabled
            )

        self.save()

    # ---------------------------------------------------------
    # SET LOGO
    # ---------------------------------------------------------

    def set_logo(
        self,
        logo: str | Path,
        destination_id: Optional[str] = None,
    ) -> None:

        logo_value = str(logo)

        if destination_id:

            destinations = self.config.setdefault(
                "destinations",
                {},
            )

            destination = destinations.setdefault(
                destination_id,
                {},
            )

            destination["logo"] = logo_value

        else:

            default = self.config.setdefault(
                "default",
                {},
            )

            default["logo"] = logo_value

        self.save()

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

        config = self.get_config(
            destination_id
        )

        return {
            "destination_id": destination_id,
            "enabled": config.enabled,
            "ready": validation["ready"],
            "reason": validation["reason"],
            "logo": validation.get(
                "logo"
            ),
        }


# ============================================================
# TEST
# ============================================================

def main():

    print("=" * 60)
    print("BRANDING MANAGER TEST")
    print("=" * 60)

    manager = BrandingManager()

    # ---------------------------------------------------------
    # Class test
    # ---------------------------------------------------------

    print("\nManager test:")

    print(
        "- BrandingManager: AVAILABLE"
    )

    print(
        f"- Config file: "
        f"{manager.config_file}"
    )

    # ---------------------------------------------------------
    # Default validation
    # ---------------------------------------------------------

    print("\nDefault branding validation:")

    result = manager.validate(
        "youtube_01"
    )

    print(
        f"- Enabled: "
        f"{result['enabled']}"
    )

    print(
        f"- Ready: "
        f"{result['ready']}"
    )

    print(
        f"- Reason: "
        f"{result['reason']}"
    )

    # ---------------------------------------------------------
    # Destination status
    # ---------------------------------------------------------

    print("\nDestination status:")

    status = manager.status(
        "youtube_01"
    )

    print(
        f"- Destination: "
        f"{status['destination_id']}"
    )

    print(
        f"- Enabled: "
        f"{status['enabled']}"
    )

    print(
        f"- Ready: "
        f"{status['ready']}"
    )

    print(
        f"- Reason: "
        f"{status['reason']}"
    )

    # ---------------------------------------------------------
    # Safety
    # ---------------------------------------------------------

    print("\nSafety checks:")

    print(
        "  - No FFmpeg process started."
    )

    print(
        "  - No RTMP connection started."
    )

    print(
        "  - No stream key accessed."
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
        "BRANDING MANAGER TEST COMPLETE"
    )
    print("=" * 60)


if __name__ == "__main__":
    main()