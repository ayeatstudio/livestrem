from __future__ import annotations

import argparse
from pathlib import Path

from destination_enable_manager_v11 import DestinationEnableManager
from streaming_controller_v10 import StreamingController


BASE_DIR = Path(__file__).resolve().parent


class DestinationSelectorV121:
    """Compatibility-safe selector for Streaming Controller v1.0."""

    def __init__(self):
        self.enable_manager = DestinationEnableManager()
        self.controller = StreamingController()

        # Existing v1.0 controller uses load_configuration/load_playlists.
        self.controller.load_configuration()
        self.controller.load_playlists()

        self.enable_manager.load()

    def validate_destination(self, destination_id: str) -> dict:
        destination = self.controller.destinations.get(destination_id)

        if not destination:
            return {
                "ready": False,
                "reason": "DESTINATION_NOT_FOUND",
            }

        if not destination.get("enabled", False):
            return {
                "ready": False,
                "reason": "DESTINATION_DISABLED",
            }

        playlist = self.controller.playlists.get(destination_id)

        if not isinstance(playlist, dict):
            return {
                "ready": False,
                "reason": "PLAYLIST_NOT_FOUND",
            }

        videos = playlist.get("videos", [])

        if not isinstance(videos, list) or not videos:
            return {
                "ready": False,
                "reason": "PLAYLIST_EMPTY",
            }

        try:
            credential = self.controller.credential_manager.get(
                destination_id
            )
        except Exception:
            credential = None

        if not isinstance(credential, dict):
            return {
                "ready": False,
                "reason": "CREDENTIAL_NOT_CONFIGURED",
            }

        if not credential.get("rtmp_url"):
            return {
                "ready": False,
                "reason": "RTMP_URL_MISSING",
            }

        if not credential.get("stream_key"):
            return {
                "ready": False,
                "reason": "STREAM_KEY_MISSING",
            }

        first_video = videos[0]

        if not isinstance(first_video, dict):
            return {
                "ready": False,
                "reason": "INVALID_PLAYLIST_VIDEO",
            }

        local_path = first_video.get("local_path")

        if not local_path:
            return {
                "ready": False,
                "reason": "LOCAL_PATH_MISSING",
            }

        if not Path(local_path).exists():
            return {
                "ready": False,
                "reason": "CACHE_FILE_MISSING",
            }

        return {
            "ready": True,
            "reason": "READY",
        }

    def process_status(self, destination_id: str) -> dict:
        try:
            return self.controller.get_process_status(destination_id)
        except Exception:
            return {
                "status": "STOPPED",
                "pid": None,
            }

    def status(self) -> None:
        print("\nDestination status:")

        for destination_id, destination in self.controller.destinations.items():
            validation = self.validate_destination(destination_id)
            process = self.process_status(destination_id)

            print(
                f"- {destination_id} | "
                f"{destination.get('platform')} | "
                f"enabled={bool(destination.get('enabled', False))} | "
                f"validation={validation['reason']} | "
                f"process={process.get('status')} | "
                f"pid={process.get('pid')}"
            )

    def start(self, destination_id: str) -> dict:
        print(f"\n[SELECTOR] START requested: {destination_id}")

        validation = self.validate_destination(destination_id)

        if not validation["ready"]:
            result = {
                "started": False,
                "status": "SKIPPED",
                "reason": validation["reason"],
            }

            print(
                f"[SELECTOR] {destination_id} | "
                f"{result['status']} | {result['reason']}"
            )

            return result

        try:
            result = self.controller.start(destination_id)
        except Exception as exc:
            result = {
                "started": False,
                "status": "FAILED",
                "reason": str(exc),
            }

        print(
            f"[SELECTOR] {destination_id} | "
            f"{result.get('status')} | "
            f"{result.get('reason', '')}"
        )

        return result

    def stop(self, destination_id: str) -> dict:
        print(f"\n[SELECTOR] STOP requested: {destination_id}")

        if destination_id not in self.controller.destinations:
            result = {
                "stopped": False,
                "status": "SKIPPED",
                "reason": "DESTINATION_NOT_FOUND",
            }
        else:
            try:
                result = self.controller.stop(destination_id)
            except Exception as exc:
                result = {
                    "stopped": False,
                    "status": "FAILED",
                    "reason": str(exc),
                }

        print(
            f"[SELECTOR] {destination_id} | "
            f"{result.get('status')} | "
            f"{result.get('reason', '')}"
        )

        return result

    def start_all_enabled(self) -> dict:
        print("\n[SELECTOR] START ALL ENABLED")

        results = {}

        for destination_id, destination in self.controller.destinations.items():
            if not destination.get("enabled", False):
                results[destination_id] = {
                    "started": False,
                    "status": "SKIPPED_DISABLED",
                    "reason": "DESTINATION_DISABLED",
                }
                continue

            results[destination_id] = self.start(destination_id)

        for destination_id, result in results.items():
            print(
                f"- {destination_id} | "
                f"{result.get('status')} | "
                f"{result.get('reason', '')}"
            )

        return results

    def stop_all(self) -> dict:
        print("\n[SELECTOR] STOP ALL")

        results = {}

        for destination_id in self.controller.destinations:
            results[destination_id] = self.stop(destination_id)

        return results


def run_test() -> None:
    print("=" * 60)
    print("DESTINATION SELECTOR v1.2.1 TEST")
    print("=" * 60)

    selector = DestinationSelectorV121()

    print("\nLoaded destinations:",
          len(selector.controller.destinations))

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

    print("\nCleanup:")
    selector.stop_all()

    print("\nReal RTMP streaming was NOT intentionally started by this test.")
    print("=" * 60)
    print("DESTINATION SELECTOR v1.2.1 TEST COMPLETE")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Streaming Engine Destination Selector v1.2.1"
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

    if not args.command:
        run_test()
        return

    selector = DestinationSelectorV121()

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
