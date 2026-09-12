from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from config_manager import ConfigManager


# ============================================================
# DESTINATION MANAGER
# ============================================================
#
# Central destination management layer.
#
# Responsibilities:
# - Load destinations from ConfigManager
# - Find destinations by ID
# - Check enabled/disabled state
# - Validate destination configuration
# - Provide safe RTMP endpoint information
# - Never start FFmpeg
# - Never expose stream keys in logs
# - Never modify credentials
# - Never modify playlists
# - Never access Google Drive directly
# ============================================================


@dataclass
class Destination:
    id: str
    platform: str
    name: str
    rtmp_url: str
    stream_key: str
    enabled: bool = False


class DestinationManager:
    """
    Central manager for streaming destinations.

    This class only manages destination configuration.
    Actual FFmpeg execution belongs to StreamEngine.
    """

    SUPPORTED_PLATFORMS = {
        "youtube",
        "facebook",
        "instagram",
    }

    def __init__(
        self,
        config_manager: Optional[
            ConfigManager
        ] = None,
    ):
        self.config_manager = (
            config_manager
            or ConfigManager()
        )

        self.destinations: dict[
            str,
            Destination,
        ] = {}

        self.load()

    # ---------------------------------------------------------
    # LOAD
    # ---------------------------------------------------------

    def load(self) -> None:
        """
        Load all destinations from configuration.
        """

        self.destinations = {}

        items = (
            self.config_manager
            .get_destinations()
        )

        for item in items:

            destination = (
                self._create_destination(
                    item
                )
            )

            self.destinations[
                destination.id
            ] = destination

    # ---------------------------------------------------------
    # CREATE
    # ---------------------------------------------------------

    @staticmethod
    def _create_destination(
        data: dict,
    ) -> Destination:

        return Destination(
            id=str(
                data.get("id", "")
            ),
            platform=str(
                data.get("platform", "")
            ),
            name=str(
                data.get("name", "")
            ),
            rtmp_url=str(
                data.get("rtmp_url", "")
            ),
            stream_key=str(
                data.get("stream_key", "")
            ),
            enabled=bool(
                data.get("enabled", False)
            ),
        )

    # ---------------------------------------------------------
    # GET
    # ---------------------------------------------------------

    def get(
        self,
        destination_id: str,
    ) -> Optional[Destination]:

        return self.destinations.get(
            destination_id
        )

    # ---------------------------------------------------------
    # REQUIRE
    # ---------------------------------------------------------

    def require(
        self,
        destination_id: str,
    ) -> Destination:

        destination = self.get(
            destination_id
        )

        if destination is None:
            raise KeyError(
                f"Destination not found: "
                f"{destination_id}"
            )

        return destination

    # ---------------------------------------------------------
    # ALL
    # ---------------------------------------------------------

    def all(
        self,
    ) -> list[Destination]:

        return list(
            self.destinations.values()
        )

    # ---------------------------------------------------------
    # ENABLED
    # ---------------------------------------------------------

    def enabled(
        self,
    ) -> list[Destination]:

        return [
            destination
            for destination
            in self.destinations.values()
            if destination.enabled
        ]

    # ---------------------------------------------------------
    # DISABLED
    # ---------------------------------------------------------

    def disabled(
        self,
    ) -> list[Destination]:

        return [
            destination
            for destination
            in self.destinations.values()
            if not destination.enabled
        ]

    # ---------------------------------------------------------
    # COUNT
    # ---------------------------------------------------------

    def count(self) -> int:

        return len(
            self.destinations
        )

    # ---------------------------------------------------------
    # ENABLED COUNT
    # ---------------------------------------------------------

    def enabled_count(self) -> int:

        return len(
            self.enabled()
        )

    # ---------------------------------------------------------
    # PLATFORM
    # ---------------------------------------------------------

    def by_platform(
        self,
        platform: str,
    ) -> list[Destination]:

        platform = platform.lower().strip()

        return [
            destination
            for destination
            in self.destinations.values()
            if destination.platform.lower()
            == platform
        ]

    # ---------------------------------------------------------
    # ENABLED PLATFORM
    # ---------------------------------------------------------

    def enabled_by_platform(
        self,
        platform: str,
    ) -> list[Destination]:

        platform = platform.lower().strip()

        return [
            destination
            for destination
            in self.destinations.values()
            if (
                destination.enabled
                and destination.platform.lower()
                == platform
            )
        ]

    # ---------------------------------------------------------
    # ENABLE CHECK
    # ---------------------------------------------------------

    def is_enabled(
        self,
        destination_id: str,
    ) -> bool:

        destination = self.get(
            destination_id
        )

        if destination is None:
            return False

        return destination.enabled

    # ---------------------------------------------------------
    # PLATFORM CHECK
    # ---------------------------------------------------------

    def is_supported_platform(
        self,
        platform: str,
    ) -> bool:

        return (
            platform.lower().strip()
            in self.SUPPORTED_PLATFORMS
        )

    # ---------------------------------------------------------
    # VALIDATE
    # ---------------------------------------------------------

    def validate(
        self,
        destination_id: str,
    ) -> dict:

        destination = self.get(
            destination_id
        )

        if destination is None:
            return {
                "ready": False,
                "reason": "DESTINATION_NOT_FOUND",
                "destination_id":
                    destination_id,
            }

        if not destination.enabled:
            return {
                "ready": False,
                "reason": "DESTINATION_DISABLED",
                "destination_id":
                    destination.id,
                "platform":
                    destination.platform,
                "name":
                    destination.name,
            }

        if not destination.platform:
            return {
                "ready": False,
                "reason": "PLATFORM_MISSING",
                "destination_id":
                    destination.id,
            }

        if not self.is_supported_platform(
            destination.platform
        ):
            return {
                "ready": False,
                "reason":
                    "UNSUPPORTED_PLATFORM",
                "destination_id":
                    destination.id,
                "platform":
                    destination.platform,
            }

        if not destination.name.strip():
            return {
                "ready": False,
                "reason": "DESTINATION_NAME_MISSING",
                "destination_id":
                    destination.id,
            }

        if not destination.rtmp_url.strip():
            return {
                "ready": False,
                "reason": "RTMP_URL_MISSING",
                "destination_id":
                    destination.id,
            }

        if not destination.rtmp_url.lower().startswith(
            "rtmp://"
        ):
            return {
                "ready": False,
                "reason": "INVALID_RTMP_URL",
                "destination_id":
                    destination.id,
            }

        if not destination.stream_key.strip():
            return {
                "ready": False,
                "reason": "STREAM_KEY_MISSING",
                "destination_id":
                    destination.id,
            }

        return {
            "ready": True,
            "reason": "READY",
            "destination_id":
                destination.id,
            "platform":
                destination.platform,
            "name":
                destination.name,
        }

    # ---------------------------------------------------------
    # SAFE RTMP URL
    # ---------------------------------------------------------

    def get_rtmp_url(
        self,
        destination_id: str,
    ) -> str:

        destination = self.require(
            destination_id
        )

        if not destination.rtmp_url.strip():
            raise ValueError(
                f"{destination_id}: "
                "RTMP URL missing"
            )

        return destination.rtmp_url

    # ---------------------------------------------------------
    # STREAM KEY
    # ---------------------------------------------------------

    def get_stream_key(
        self,
        destination_id: str,
    ) -> str:

        destination = self.require(
            destination_id
        )

        if not destination.stream_key.strip():
            raise ValueError(
                f"{destination_id}: "
                "Stream key missing"
            )

        return destination.stream_key

    # ---------------------------------------------------------
    # RTMP OUTPUT
    # ---------------------------------------------------------

    def build_rtmp_output(
        self,
        destination_id: str,
    ) -> str:

        validation = self.validate(
            destination_id
        )

        if not validation["ready"]:
            raise ValueError(
                f"{destination_id}: "
                f"{validation['reason']}"
            )

        destination = self.require(
            destination_id
        )

        base_url = (
            destination.rtmp_url
            .rstrip("/")
        )

        stream_key = (
            destination.stream_key
            .strip()
        )

        return (
            f"{base_url}/{stream_key}"
        )

    # ---------------------------------------------------------
    # SAFE DESTINATION INFO
    # ---------------------------------------------------------

    def safe_info(
        self,
        destination_id: str,
    ) -> dict:

        destination = self.get(
            destination_id
        )

        if destination is None:
            return {
                "id":
                    destination_id,
                "exists":
                    False,
            }

        return {
            "id":
                destination.id,
            "platform":
                destination.platform,
            "name":
                destination.name,
            "enabled":
                destination.enabled,
            "rtmp_configured":
                bool(
                    destination.rtmp_url.strip()
                ),
            "stream_key_configured":
                bool(
                    destination.stream_key.strip()
                ),
        }

    # ---------------------------------------------------------
    # STATUS
    # ---------------------------------------------------------

    def status(
        self,
        destination_id: str,
    ) -> dict:

        validation = self.validate(
            destination_id
        )

        return {
            **validation,
            "safe_info":
                self.safe_info(
                    destination_id
                ),
        }


# ============================================================
# TEST
# ============================================================

def main():

    print("=" * 60)
    print("DESTINATION MANAGER TEST")
    print("=" * 60)

    try:

        manager = DestinationManager()

    except Exception as exc:

        print(
            "\nConfiguration load failed:"
        )
        print(exc)

        return

    # ---------------------------------------------------------
    # Summary
    # ---------------------------------------------------------

    print("\nDestination summary:")

    print(
        f"- Total: "
        f"{manager.count()}"
    )

    print(
        f"- Enabled: "
        f"{manager.enabled_count()}"
    )

    print(
        f"- Disabled: "
        f"{len(manager.disabled())}"
    )

    # ---------------------------------------------------------
    # Destination list
    # ---------------------------------------------------------

    print("\nDestinations:")

    for destination in manager.all():

        validation = manager.validate(
            destination.id
        )

        print(
            f"- {destination.id} | "
            f"{destination.platform} | "
            f"{destination.name} | "
            f"enabled={destination.enabled} | "
            f"ready={validation['ready']} | "
            f"reason={validation['reason']}"
        )

    # ---------------------------------------------------------
    # Platform summary
    # ---------------------------------------------------------

    print("\nPlatform summary:")

    for platform in [
        "youtube",
        "facebook",
        "instagram",
    ]:

        items = manager.by_platform(
            platform
        )

        enabled = manager.enabled_by_platform(
            platform
        )

        print(
            f"- {platform} | "
            f"total={len(items)} | "
            f"enabled={len(enabled)}"
        )

    # ---------------------------------------------------------
    # Safe info test
    # ---------------------------------------------------------

    print("\nSafe information test:")

    for destination_id in [
        "youtube_01",
        "youtube_02",
        "youtube_03",
        "youtube_04",
        "facebook_01",
        "facebook_02",
        "instagram_01",
    ]:

        info = manager.safe_info(
            destination_id
        )

        print(
            f"- {destination_id} | "
            f"exists={info.get('exists', True)} | "
            f"enabled={info.get('enabled')} | "
            f"rtmp_configured="
            f"{info.get('rtmp_configured')} | "
            f"stream_key_configured="
            f"{info.get('stream_key_configured')}"
        )

    # ---------------------------------------------------------
    # Stream key protection test
    # ---------------------------------------------------------

    print("\nCredential protection test:")

    print(
        "- Actual stream keys: NOT PRINTED"
    )

    print(
        "- Credentials modified: NO"
    )

    # ---------------------------------------------------------
    # RTMP generation test
    # ---------------------------------------------------------

    print("\nRTMP output test:")

    test_id = "youtube_01"

    validation = manager.validate(
        test_id
    )

    if validation["ready"]:

        try:

            output = (
                manager.build_rtmp_output(
                    test_id
                )
            )

            # Do NOT print the actual
            # output because it contains
            # the stream key.

            print(
                "- RTMP output generation: OK"
            )

            print(
                "- Actual RTMP output: "
                "HIDDEN"
            )

            assert output

        except Exception as exc:

            print(
                f"- RTMP output generation "
                f"failed: {exc}"
            )

    else:

        print(
            f"- RTMP output blocked safely: "
            f"{validation['reason']}"
        )

    # ---------------------------------------------------------
    # Missing destination test
    # ---------------------------------------------------------

    print("\nMissing destination test:")

    missing = manager.validate(
        "destination_does_not_exist"
    )

    print(
        f"- Ready: "
        f"{missing['ready']}"
    )

    print(
        f"- Reason: "
        f"{missing['reason']}"
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
        "  - No stream key printed."
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
        "DESTINATION MANAGER TEST COMPLETE"
    )
    print("=" * 60)


if __name__ == "__main__":
    main()