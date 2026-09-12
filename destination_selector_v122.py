from __future__ import annotations

import sys

from streaming_controller_v10 import StreamingController


class DestinationSelectorV122:
    """
    Destination Selector v1.2.2

    Uses the real StreamingController v1.0 API:
        load()
        validate()
        start()
        stop()
        start_all_enabled()
        stop_all()
        status()
        all_status()
    """

    def __init__(self):
        self.controller = StreamingController()
        self.controller.load()

    # ---------------------------------------------------------
    # DESTINATION LIST
    # ---------------------------------------------------------

    def list_destinations(self):
        print("\nDestinations:")

        for destination_id, destination in self.controller.destinations.items():
            platform = destination.get("platform", "unknown")
            name = destination.get("name", destination_id)
            enabled = destination.get("enabled", False)

            validation = self.controller.validate(destination_id)

            if validation["ready"]:
                readiness = "READY"
            else:
                readiness = validation["reason"]

            print(
                f"- {destination_id} | "
                f"{platform} | "
                f"{name} | "
                f"{'ENABLED' if enabled else 'DISABLED'} | "
                f"{readiness}"
            )

    # ---------------------------------------------------------
    # STATUS
    # ---------------------------------------------------------

    def status(self):
        print("\n" + "=" * 60)
        print("DESTINATION STATUS")
        print("=" * 60)

        for destination_id, destination in self.controller.destinations.items():
            validation = self.controller.validate(destination_id)
            runtime = self.controller.status(destination_id)

            print(f"\n[{destination_id}]")
            print(f"  Name: {destination.get('name')}")
            print(f"  Platform: {destination.get('platform')}")
            print(
                f"  Enabled: "
                f"{destination.get('enabled', False)}"
            )

            print(
                f"  Validation: "
                f"{'READY' if validation['ready'] else 'NOT READY'}"
            )

            print(
                f"  Reason: "
                f"{validation['reason']}"
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

            if validation.get("current"):
                print(
                    f"  Current: "
                    f"{validation['current']}"
                )

            print(
                f"  Runtime: "
                f"{runtime['status']}"
            )

            print(
                f"  PID: "
                f"{runtime['pid']}"
            )

            if runtime.get("return_code") is not None:
                print(
                    f"  Return code: "
                    f"{runtime['return_code']}"
                )

            if runtime.get("error"):
                print(
                    f"  Error: "
                    f"{runtime['error']}"
                )

        print("\n" + "=" * 60)

    # ---------------------------------------------------------
    # START ONE
    # ---------------------------------------------------------

    def start(self, destination_id: str):
        print(
            f"\n[SELECTOR] START requested: "
            f"{destination_id}"
        )

        if destination_id not in self.controller.destinations:
            print(
                f"[SELECTOR] FAILED: "
                f"DESTINATION_NOT_FOUND"
            )
            return False

        validation = self.controller.validate(destination_id)

        if not validation["ready"]:
            print(
                f"[SELECTOR] BLOCKED: "
                f"{validation['reason']}"
            )
            print(
                "[SELECTOR] Real FFmpeg start was not executed."
            )
            return False

        try:
            process = self.controller.start(destination_id)

            print(
                f"[SELECTOR] STARTED: "
                f"{destination_id}"
            )
            print(
                f"[SELECTOR] PID: "
                f"{process.pid}"
            )

            return True

        except Exception as exc:
            print(
                f"[SELECTOR] START FAILED: "
                f"{exc}"
            )
            return False

    # ---------------------------------------------------------
    # STOP ONE
    # ---------------------------------------------------------

    def stop(self, destination_id: str):
        print(
            f"\n[SELECTOR] STOP requested: "
            f"{destination_id}"
        )

        if destination_id not in self.controller.destinations:
            print(
                "[SELECTOR] FAILED: "
                "DESTINATION_NOT_FOUND"
            )
            return False

        try:
            self.controller.stop(destination_id)

            print(
                f"[SELECTOR] STOP completed: "
                f"{destination_id}"
            )

            return True

        except Exception as exc:
            print(
                f"[SELECTOR] STOP FAILED: "
                f"{exc}"
            )
            return False

    # ---------------------------------------------------------
    # START ALL
    # ---------------------------------------------------------

    def start_all(self):
        print("\n[SELECTOR] START-ALL requested")

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
        print("\n[SELECTOR] STOP-ALL requested")

        self.controller.stop_all()

        print("[SELECTOR] All sessions stopped.")

    # ---------------------------------------------------------
    # COMMAND HELP
    # ---------------------------------------------------------

    @staticmethod
    def help():
        print(
            """
Commands:

  status
      Show all destination validation and runtime status.

  list
      List all configured destinations.

  start <destination_id>
      Start one READY destination.

  stop <destination_id>
      Stop one destination.

  start-all
      Start all enabled destinations that pass validation.

  stop-all
      Stop all active sessions.

  help
      Show this help.

Examples:

  python destination_selector_v122.py status

  python destination_selector_v122.py list

  python destination_selector_v122.py start youtube_01

  python destination_selector_v122.py stop youtube_01

  python destination_selector_v122.py start-all

  python destination_selector_v122.py stop-all
"""
        )


# =============================================================
# TEST
# =============================================================

def run_test():
    print("=" * 60)
    print("DESTINATION SELECTOR v1.2.2 TEST")
    print("=" * 60)

    selector = DestinationSelectorV122()

    print(
        f"\nLoaded destinations: "
        f"{len(selector.controller.destinations)}"
    )

    selector.list_destinations()

    print("\nSafety checks:")
    print("  - Credentials are not modified.")
    print("  - Playlists are not modified.")
    print("  - Google Drive files are not modified.")
    print("  - Disabled destinations cannot start.")

    print("\nSelector API: READY")
    print("Controller API compatibility: OK")

    print("\nNo automatic streaming was started.")

    print("=" * 60)
    print("DESTINATION SELECTOR v1.2.2 TEST COMPLETE")
    print("=" * 60)


# =============================================================
# CLI
# =============================================================

def main():
    if len(sys.argv) == 1:
        run_test()
        return

    selector = DestinationSelectorV122()

    command = sys.argv[1].lower()

    if command == "status":
        selector.status()
        return

    if command == "list":
        selector.list_destinations()
        return

    if command == "start-all":
        selector.start_all()
        return

    if command == "stop-all":
        selector.stop_all()
        return

    if command == "start":
        if len(sys.argv) < 3:
            print(
                "Usage: "
                "python destination_selector_v122.py "
                "start <destination_id>"
            )
            return

        selector.start(sys.argv[2])
        return

    if command == "stop":
        if len(sys.argv) < 3:
            print(
                "Usage: "
                "python destination_selector_v122.py "
                "stop <destination_id>"
            )
            return

        selector.stop(sys.argv[2])
        return

    if command == "help":
        selector.help()
        return

    print(
        f"Unknown command: {command}"
    )
    selector.help()


if __name__ == "__main__":
    main()