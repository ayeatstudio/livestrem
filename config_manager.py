from __future__ import annotations

import json
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
CONFIG_DIR = BASE_DIR / "config"
CONFIG_FILE = CONFIG_DIR / "destinations.json"


class ConfigManager:

    def __init__(
        self,
        config_file: str | Path = CONFIG_FILE,
    ):
        self.config_file = Path(config_file)

    # ---------------------------------------------------------
    # LOAD
    # ---------------------------------------------------------

    def load(self) -> dict:
        if not self.config_file.exists():
            raise FileNotFoundError(
                f"Configuration file not found:\n"
                f"{self.config_file}"
            )

        try:
            with self.config_file.open(
                "r",
                encoding="utf-8",
            ) as file:
                data = json.load(file)

        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Invalid JSON configuration:\n{exc}"
            ) from exc

        self._validate(data)

        return data

    # ---------------------------------------------------------
    # VALIDATION
    # ---------------------------------------------------------

    def _validate(self, data: dict) -> None:

        if not isinstance(data, dict):
            raise ValueError(
                "Configuration root must be an object."
            )

        destinations = data.get(
            "destinations"
        )

        if not isinstance(destinations, list):
            raise ValueError(
                "'destinations' must be a list."
            )

        ids = set()

        for index, destination in enumerate(
            destinations,
            start=1,
        ):

            if not isinstance(destination, dict):
                raise ValueError(
                    f"Destination #{index} "
                    f"must be an object."
                )

            required = [
                "id",
                "platform",
                "name",
                "rtmp_url",
                "stream_key",
                "enabled",
            ]

            for field in required:

                if field not in destination:
                    raise ValueError(
                        f"Destination #{index} "
                        f"is missing '{field}'."
                    )

            destination_id = destination["id"]

            if not isinstance(
                destination_id,
                str,
            ) or not destination_id.strip():

                raise ValueError(
                    f"Destination #{index} "
                    f"has invalid id."
                )

            if destination_id in ids:
                raise ValueError(
                    f"Duplicate destination id: "
                    f"{destination_id}"
                )

            ids.add(destination_id)

            if not isinstance(
                destination["platform"],
                str,
            ):
                raise ValueError(
                    f"{destination_id}: "
                    f"'platform' must be a string."
                )

            if not isinstance(
                destination["name"],
                str,
            ):
                raise ValueError(
                    f"{destination_id}: "
                    f"'name' must be a string."
                )

            if not isinstance(
                destination["rtmp_url"],
                str,
            ):
                raise ValueError(
                    f"{destination_id}: "
                    f"'rtmp_url' must be a string."
                )

            if not isinstance(
                destination["stream_key"],
                str,
            ):
                raise ValueError(
                    f"{destination_id}: "
                    f"'stream_key' must be a string."
                )

            if not isinstance(
                destination["enabled"],
                bool,
            ):
                raise ValueError(
                    f"{destination_id}: "
                    f"'enabled' must be true or false."
                )

    # ---------------------------------------------------------
    # DESTINATIONS
    # ---------------------------------------------------------

    def get_destinations(self) -> list[dict]:

        config = self.load()

        return config["destinations"]

    def get_enabled_destinations(self) -> list[dict]:

        return [
            destination
            for destination
            in self.get_destinations()
            if destination["enabled"]
        ]


# =============================================================
# TEST
# =============================================================

def main():

    print("=" * 60)
    print("CONFIGURATION MANAGER TEST")
    print("=" * 60)

    manager = ConfigManager()

    print("\nConfiguration file:")
    print(manager.config_file)

    config = manager.load()

    print("\nConfiguration loaded successfully.")

    print(
        f"\nTotal destinations: "
        f"{len(config['destinations'])}"
    )

    print("\nDestinations:")

    for destination in config["destinations"]:

        # IMPORTANT:
        # Never print the actual stream key.
        key_status = (
            "CONFIGURED"
            if destination["stream_key"]
            else "NOT CONFIGURED"
        )

        print(
            f"- {destination['id']} | "
            f"{destination['platform']} | "
            f"{destination['name']} | "
            f"enabled={destination['enabled']} | "
            f"stream_key={key_status}"
        )

    print("\nEnabled destinations:")

    for destination in (
        manager.get_enabled_destinations()
    ):

        print(
            f"- {destination['id']} | "
            f"{destination['name']}"
        )

    print("\n" + "=" * 60)
    print("CONFIGURATION MANAGER TEST SUCCESS")
    print("=" * 60)


if __name__ == "__main__":
    main()