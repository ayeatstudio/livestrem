from __future__ import annotations

import json
from pathlib import Path

from config_manager import ConfigManager


BASE_DIR = Path(__file__).resolve().parent
CONFIG_DIR = BASE_DIR / "config"
DESTINATIONS_FILE = CONFIG_DIR / "destinations.json"


class DestinationEnableManager:
    """
    Safe destination enable/disable manager.

    This module changes only the `enabled` flag in destinations.json.
    Credentials, stream keys, playlist data, and folder mappings are untouched.
    """

    def __init__(self, destinations_file: Path = DESTINATIONS_FILE):
        self.destinations_file = Path(destinations_file)
        self.config_manager = ConfigManager()
        self.destinations: dict[str, dict] = {}

    def load(self) -> None:
        destinations = self.config_manager.get_destinations()

        self.destinations = {}

        for destination in destinations:
            if not isinstance(destination, dict):
                continue

            destination_id = destination.get("id")

            if destination_id:
                self.destinations[destination_id] = destination

    def get(self, destination_id: str) -> dict | None:
        return self.destinations.get(destination_id)

    def status(self) -> dict[str, bool]:
        return {
            destination_id: bool(
                destination.get("enabled", False)
            )
            for destination_id, destination in self.destinations.items()
        }

    def set_enabled(
        self,
        destination_id: str,
        enabled: bool,
    ) -> dict:
        self.load()

        destination = self.get(destination_id)

        if not destination:
            raise ValueError(
                f"Unknown destination: {destination_id}"
            )

        self._write_enabled_flag(
            destination_id,
            enabled,
        )

        self.load()

        updated = self.get(destination_id)

        return {
            "id": destination_id,
            "name": updated.get("name"),
            "platform": updated.get("platform"),
            "enabled": bool(updated.get("enabled", False)),
        }

    def enable(self, destination_id: str) -> dict:
        return self.set_enabled(destination_id, True)

    def disable(self, destination_id: str) -> dict:
        return self.set_enabled(destination_id, False)

    def _write_enabled_flag(
        self,
        destination_id: str,
        enabled: bool,
    ) -> None:
        if not self.destinations_file.exists():
            raise FileNotFoundError(
                f"Configuration file not found:\n"
                f"{self.destinations_file}"
            )

        with self.destinations_file.open(
            "r",
            encoding="utf-8",
        ) as file:
            data = json.load(file)

        destinations = data.get("destinations")

        if not isinstance(destinations, list):
            raise ValueError(
                "destinations.json has no valid 'destinations' list."
            )

        found = False

        for destination in destinations:
            if (
                isinstance(destination, dict)
                and destination.get("id") == destination_id
            ):
                destination["enabled"] = bool(enabled)
                found = True
                break

        if not found:
            raise ValueError(
                f"Destination not found in configuration: "
                f"{destination_id}"
            )

        temp_file = self.destinations_file.with_suffix(
            ".json.tmp"
        )

        with temp_file.open(
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                data,
                file,
                indent=2,
                ensure_ascii=False,
            )
            file.write("\n")

        temp_file.replace(self.destinations_file)


def print_status(manager: DestinationEnableManager) -> None:
    manager.load()

    print("\nCurrent destination switches:")

    for destination_id, destination in manager.destinations.items():
        state = (
            "ENABLED"
            if destination.get("enabled", False)
            else "DISABLED"
        )

        print(
            f"- {destination_id} | "
            f"{destination.get('platform')} | "
            f"{destination.get('name')} | "
            f"{state}"
        )


def main():
    print("=" * 60)
    print("DESTINATION ENABLE MANAGER v1.1 TEST")
    print("=" * 60)

    manager = DestinationEnableManager()
    manager.load()

    print(
        f"\nConfiguration file:\n"
        f"{manager.destinations_file}"
    )

    print_status(manager)

    print("\nSafety test:")
    print(
        "  No credential files are modified."
    )
    print(
        "  No playlist files are modified."
    )
    print(
        "  No Google Drive files are modified."
    )
    print(
        "  No FFmpeg process is started."
    )

    print("\nAvailable destinations:")

    for destination_id, destination in manager.destinations.items():
        print(
            f"- {destination_id} | "
            f"{destination.get('platform')} | "
            f"{destination.get('name')}"
        )

    print("\nManager test: READY")
    print("No destination was enabled automatically.")
    print("No real streaming was started.")

    print("=" * 60)
    print("DESTINATION ENABLE MANAGER v1.1 TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
