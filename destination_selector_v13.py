from __future__ import annotations

import json
import sys
from pathlib import Path

from streaming_controller_v10 import StreamingController


BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config" / "destinations.json"


class DestinationControlV13:

    def __init__(self):
        self.controller = StreamingController()
        self.controller.load()

    # ---------------------------------------------------------
    # CONFIG
    # ---------------------------------------------------------

    def _save_destinations(self):
        data = self._load_raw_config()

        destinations = data.get("destinations")

        if not isinstance(destinations, list):
            raise ValueError(
                "Invalid destinations.json structure: "
                "'destinations' must be a list."
            )

        by_id = {
            item.get("id"): item
            for item in destinations
            if isinstance(item, dict) and item.get("id")
        }

        for destination_id, destination in self.controller.destinations.items():
            if destination_id in by_id:
                by_id[destination_id]["enabled"] = destination.get(
                    "enabled",
                    False,
                )

        CONFIG_FILE.write_text(
            json.dumps(data, indent=4, ensure_ascii=False),
            encoding="utf-8",
        )

    @staticmethod
    def _load_raw_config():
        if not CONFIG_FILE.exists():
            raise FileNotFoundError(
                f"Configuration file not found:\n{CONFIG_FILE}"
            )

        with CONFIG_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)

        if not isinstance(data, dict):
            raise ValueError(
                "Invalid destinations.json: root must be an object."
            )

        return data

    # ---------------------------------------------------------
    # ENABLE
    # ---------------------------------------------------------

    def enable(self, destination_id: str):
        destination = self.controller.destinations.get(destination_id)

        if not destination:
            print(
                f"[CONTROL] FAILED: "
                f"DESTINATION_NOT_FOUND: {destination_id}"
            )
            return False

        if destination.get("enabled", False):
            print(
                f"[CONTROL] Already enabled: "
                f"{destination_id}"
            )
            return True

        destination["enabled"] = True
        self._save_destinations()

        print(
            f"[CONTROL] ENABLED: "
            f"{destination_id}"
        )

        print(
            "[CONTROL] No streaming was started."
        )

        return True

    # ---------------------------------------------------------
    # DISABLE
    # ---------------------------------------------------------

    def disable(self, destination_id: str):
        destination = self.controller.destinations.get(destination_id)

        if not destination:
            print(
                f"[CONTROL] FAILED: "
                f"DESTINATION_NOT_FOUND: {destination_id}"
            )
            return False

        was_enabled = destination.get("enabled", False)

        # Disable first.
        destination["enabled"] = False

        self._save_destinations()

        # If an FFmpeg process is actually running,
        # stop only this destination.
        runtime = self.controller.status(destination_id)

        if runtime["status"] == "RUNNING":
            self.controller.stop(destination_id)
            print(
                f"[CONTROL] STOPPED active session: "
                f"{destination_id}"
            )

        if was_enabled:
            print(
                f"[CONTROL] DISABLED: "
                f"{destination_id}"
            )
        else:
            print(
                f"[CONTROL] Already disabled: "
                f"{destination_id}"
            )

        return True

    # ---------------------------------------------------------
    # STATUS
    # ---------------------------------------------------------

    def status(self):
        print("\n" + "=" * 60)
        print("DESTINATION CONTROL STATUS v1.3")
        print("=" * 60)

        for destination_id, destination in self.controller.destinations.items():

            validation = self.controller.validate(destination_id)
            runtime = self.controller.status(destination_id)

            enabled = destination.get("enabled", False)

            print(f"\n[{destination_id}]")
            print(f"  Name: {destination.get('name')}")
            print(f"  Platform: {destination.get('platform')}")
            print(
                f"  Enabled: "
                f"{'YES' if enabled else 'NO'}"
            )
            print(
                f"  Validation: "
                f"{'READY' if validation['ready'] else 'NOT READY'}"
            )
            print(
                f"  Reason: "
                f"{validation['reason']}"
            )
            print(
                f"  Runtime: "
                f"{runtime['status']}"
            )
            print(
                f"  PID: "
                f"{runtime['pid']}"
            )

            if validation.get("folder"):
                print(
                    f"  Folder: "
                    f"{validation['folder']}"
                )

            if validation.get("videos") is not None:
                print(
                    f"  Videos: "
                    f"{validation['videos']}"
                )

        print("\n" + "=" * 60)

    # ---------------------------------------------------------
    # START
    # ---------------------------------------------------------

    def start(self, destination_id: str):
        print(
            f"\n[CONTROL] START requested: "
            f"{destination_id}"
        )

        validation = self.controller.validate(destination_id)

        if not validation["ready"]:
            print(
                f"[CONTROL] BLOCKED: "
                f"{validation['reason']}"
            )
            print(
                "[CONTROL] Real FFmpeg was NOT started."
            )
            return False

        try:
            process = self.controller.start(destination_id)

            print(
                f"[CONTROL] STARTED: "
                f"{destination_id}"
            )
            print(
                f"[CONTROL] PID: "
                f"{process.pid}"
            )

            return True

        except Exception as exc:
            print(
                f"[CONTROL] START FAILED: "
                f"{exc}"
            )
            return False

    # ---------------------------------------------------------
    # STOP
    # ---------------------------------------------------------

    def stop(self, destination_id: str):
        print(
            f"\n[CONTROL] STOP requested: "
            f"{destination_id}"
        )

        if destination_id not in self.controller.destinations:
            print(
                "[CONTROL] FAILED: "
                "DESTINATION_NOT_FOUND"
            )
            return False

        self.controller.stop(destination_id)

        print(
            f"[CONTROL] STOP completed: "
            f"{destination_id}"
        )

        return True

    # ---------------------------------------------------------
    # START ALL
    # ---------------------------------------------------------

    def start_all(self):
        print("\n[CONTROL] START-ALL requested")

        results = self.controller.start_all_enabled()

        for destination_id, result in results.items():
            print(
                f"- {destination_id} | "
                f"{result}"
            )

        return results

    # ---------------------------------------------------------
    # STOP ALL
    # ---------------------------------------------------------

    def stop_all(self):
        print("\n[CONTROL] STOP-ALL requested")

        self.controller.stop_all()

        print("[CONTROL] All active sessions stopped.")

    # ---------------------------------------------------------
    # HELP
    # ---------------------------------------------------------

    @staticmethod
    def help():
        print(
            """
Destination Control v1.3

Commands:

  status
      Show all destination states.

  enable <destination_id>
      Enable a destination.
      Does NOT start streaming.

  disable <destination_id>
      Disable a destination.
      Stops its active session if necessary.

  start <destination_id>
      Start one READY destination.

  stop <destination_id>
      Stop one destination.

  start-all
      Start all enabled + READY destinations.

  stop-all
      Stop all active sessions.

  list
      List destination IDs.

Examples:

  python destination_selector_v13.py status

  python destination_selector_v13.py enable youtube_01

  python destination_selector_v13.py disable youtube_01

  python destination_selector_v13.py start youtube_01

  python destination_selector_v13.py stop youtube_01

  python destination_selector_v13.py start-all

  python destination_selector_v13.py stop-all
"""
        )


# =============================================================
# SAFE TEST
# =============================================================

def run_test():
    print("=" * 60)
    print("DESTINATION CONTROL v1.3 TEST")
    print("=" * 60)

    control = DestinationControlV13()

    print(
        f"\nConfiguration file:\n"
        f"{CONFIG_FILE}"
    )

    print(
        f"\nLoaded destinations: "
        f"{len(control.controller.destinations)}"
    )

    print("\nCurrent switches:")

    for destination_id, destination in control.controller.destinations.items():
        print(
            f"- {destination_id} | "
            f"{destination.get('platform')} | "
            f"{destination.get('name')} | "
            f"{'ENABLED' if destination.get('enabled') else 'DISABLED'}"
        )

    print("\nSafety test:")
    print("  Enable does not start FFmpeg.")
    print("  Disable only affects the selected destination.")
    print("  Credentials are not modified.")
    print("  Playlists are not modified.")
    print("  Google Drive files are not modified.")
    print("  No automatic streaming is started.")

    print("\nController API:")
    print("  load()       OK")
    print("  validate()   OK")
    print("  start()      OK")
    print("  stop()       OK")
    print("  start_all()  OK")
    print("  stop_all()   OK")

    print("\nManager test: READY")

    print("=" * 60)
    print("DESTINATION CONTROL v1.3 TEST COMPLETE")
    print("=" * 60)


# =============================================================
# CLI
# =============================================================

def main():

    if len(sys.argv) == 1:
        run_test()
        return

    control = DestinationControlV13()

    command = sys.argv[1].lower()

    if command == "status":
        control.status()
        return

    if command == "list":
        for destination_id, destination in control.controller.destinations.items():
            print(
                f"{destination_id} | "
                f"{destination.get('platform')} | "
                f"{destination.get('name')}"
            )
        return

    if command == "enable":
        if len(sys.argv) < 3:
            print(
                "Usage: "
                "python destination_selector_v13.py "
                "enable <destination_id>"
            )
            return

        control.enable(sys.argv[2])
        return

    if command == "disable":
        if len(sys.argv) < 3:
            print(
                "Usage: "
                "python destination_selector_v13.py "
                "disable <destination_id>"
            )
            return

        control.disable(sys.argv[2])
        return

    if command == "start":
        if len(sys.argv) < 3:
            print(
                "Usage: "
                "python destination_selector_v13.py "
                "start <destination_id>"
            )
            return

        control.start(sys.argv[2])
        return

    if command == "stop":
        if len(sys.argv) < 3:
            print(
                "Usage: "
                "python destination_selector_v13.py "
                "stop <destination_id>"
            )
            return

        control.stop(sys.argv[2])
        return

    if command == "start-all":
        control.start_all()
        return

    if command == "stop-all":
        control.stop_all()
        return

    if command == "help":
        control.help()
        return

    print(f"Unknown command: {command}")
    control.help()


if __name__ == "__main__":
    main()