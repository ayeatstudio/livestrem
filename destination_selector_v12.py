from __future__ import annotations

import argparse
from pathlib import Path

from destination_enable_manager_v11 import DestinationEnableManager
from streaming_controller_v10 import StreamingController


BASE_DIR = Path(__file__).resolve().parent


class DestinationSelectorV12:
    """
    Controlled destination selector.

    Commands:
      status
      start <destination_id> [destination_id ...]
      stop <destination_id> [destination_id ...]
      start-all-enabled
      stop-all

    Safety:
      - A destination must pass the controller's validation before start.
      - Disabled destinations are never started.
      - Each destination has its own FFmpeg process.
      - Stream keys are never printed.
    """

    def __init__(self):
        self.enable_manager = DestinationEnableManager()
        self.controller = StreamingController()

        self.enable_manager.load()
        self.controller.load()

    def status(self) -> None:
        print("\nDestination status:")

        for destination_id, destination in self.controller.destinations.items():
            validation = self.controller.validate_destination(destination_id)

            enabled = bool(destination.get("enabled", False))
            state = self.controller.get_process_status(destination_id)

            print(
                f"- {destination_id} | "
                f"{destination.get('platform')} | "
                f"enabled={enabled} | "
                f"validation={validation['reason']} | "
                f"process={state.get('status')} | "
                f"pid={state.get('pid')}"
            )

    def start(self, destination_id: str) -> bool:
        print(f"\n[SELECTOR] START requested: {destination_id}")

        result = self.controller.start(destination_id)

        print(
            f"[SELECTOR] {destination_id} | "
            f"{result.get('status')} | "
            f"{result.get('reason', '')}"
        )

        return bool(result.get("started", False))

    def stop(self, destination_id: str) -> bool:
        print(f"\n[SELECTOR] STOP requested: {destination_id}")

        result = self.controller.stop(destination_id)

        print(
            f"[SELECTOR] {destination_id} | "
            f"{result.get('status')} | "
            f"{result.get('reason', '')}"
        )

        return bool(result.get("stopped", False))

    def start_all_enabled(self) -> dict:
        print("\n[SELECTOR] START ALL ENABLED")

        results = self.controller.start_all_enabled()

        for destination_id, result in results.items():
            print(
                f"- {destination_id} | "
                f"{result.get('status')} | "
                f"{result.get('reason', '')}"
            )

        return results

    def stop_all(self) -> dict:
        print("\n[SELECTOR] STOP ALL")

        results = self.controller.stop_all()

        for destination_id, result in results.items():
            print(
                f"- {destination_id} | "
                f"{result.get('status')} | "
                f"{result.get('reason', '')}"
            )

        return results


def run_test() -> None:
    print("=" * 60)
    print("DESTINATION SELECTOR v1.2 TEST")
    print("=" * 60)

    selector = DestinationSelectorV12()

    print("\nLoaded destinations:", len(selector.controller.destinations))

    selector.status()

    print("\nControlled start safety test:")
    results = selector.start_all_enabled()

    started = [
        destination_id
        for destination_id, result in results.items()
        if result.get("started")
    ]

    print("\nStarted destinations:", started or "NONE")

    print("\nFinal process status:")
    selector.status()

    print("\nCleanup test:")
    selector.stop_all()

    print("\nReal RTMP streaming was NOT intentionally started by this test.")
    print("=" * 60)
    print("DESTINATION SELECTOR v1.2 TEST COMPLETE")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Streaming Engine Destination Selector v1.2"
    )

    sub = parser.add_subparsers(dest="command")

    sub.add_parser("status")

    start_parser = sub.add_parser("start")
    start_parser.add_argument("destination_ids", nargs="+")

    stop_parser = sub.add_parser("stop")
    stop_parser.add_argument("destination_ids", nargs="+")

    sub.add_parser("start-all-enabled")
    sub.add_parser("stop-all")

    args = parser.parse_args()

    selector = DestinationSelectorV12()

    if not args.command:
        run_test()
        return

    if args.command == "status":
        selector.status()

    elif args.command == "start":
        for destination_id in args.destination_ids:
            selector.start(destination_id)

    elif args.command == "stop":
        for destination_id in args.destination_ids:
            selector.stop(destination_id)

    elif args.command == "start-all-enabled":
        selector.start_all_enabled()

    elif args.command == "stop-all":
        selector.stop_all()


if __name__ == "__main__":
    main()
