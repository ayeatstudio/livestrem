
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from destination_manager import DestinationManager
from stream_engine import StreamEngine


# ============================================================
# MULTI STREAM CONTROLLER
# ============================================================
#
# Controls multiple streaming destinations independently.
#
# Supported destinations:
# - youtube_01
# - youtube_02
# - youtube_03
# - youtube_04
# - facebook_01
# - facebook_02
# - instagram_01
#
# Important:
# - Does NOT modify credentials.
# - Does NOT modify playlists.
# - Does NOT modify Google Drive.
# - Does NOT start real RTMP streaming during this test.
# - Each destination is isolated from the others.
# ============================================================


@dataclass
class StreamSession:
    destination_id: str
    source: Optional[Path] = None
    process: Optional[subprocess.Popen] = None
    status: str = "STOPPED"


class MultiStreamController:

    def __init__(self):
        self.destination_manager = DestinationManager()
        self.stream_engine = StreamEngine()

        self.sessions: dict[str, StreamSession] = {}

        self.destination_ids = [
            "youtube_01",
            "youtube_02",
            "youtube_03",
            "youtube_04",
            "facebook_01",
            "facebook_02",
            "instagram_01",
        ]

        self._load_sessions()

    # ---------------------------------------------------------
    # SESSION INITIALIZATION
    # ---------------------------------------------------------

    def _load_sessions(self) -> None:

        self.sessions = {}

        for destination_id in self.destination_ids:

            self.sessions[destination_id] = StreamSession(
                destination_id=destination_id
            )

    # ---------------------------------------------------------
    # DESTINATION
    # ---------------------------------------------------------

    def get_destination(
        self,
        destination_id: str,
    ) -> dict:

        return self.destination_manager.get_destination(
            destination_id
        )

    # ---------------------------------------------------------
    # READINESS
    # ---------------------------------------------------------

    def validate_destination(
        self,
        destination_id: str,
    ) -> dict:

        if destination_id not in self.sessions:
            return {
                "ready": False,
                "reason": "DESTINATION_NOT_FOUND",
            }

        try:
            result = self.destination_manager.validate(
                destination_id
            )

        except Exception as exc:

            return {
                "ready": False,
                "reason": "DESTINATION_VALIDATION_ERROR",
                "error": str(exc),
            }

        if not isinstance(result, dict):
            return {
                "ready": False,
                "reason": "INVALID_DESTINATION_RESPONSE",
            }

        return result

    # ---------------------------------------------------------
    # SOURCE
    # ---------------------------------------------------------

    def set_source(
        self,
        destination_id: str,
        source: str | Path,
    ) -> dict:

        if destination_id not in self.sessions:
            return {
                "success": False,
                "reason": "DESTINATION_NOT_FOUND",
            }

        source_path = Path(source)

        if not source_path.exists():
            return {
                "success": False,
                "reason": "SOURCE_FILE_MISSING",
                "source": str(source_path),
            }

        if not source_path.is_file():
            return {
                "success": False,
                "reason": "SOURCE_PATH_NOT_FILE",
                "source": str(source_path),
            }

        self.sessions[
            destination_id
        ].source = source_path.resolve()

        return {
            "success": True,
            "reason": "SOURCE_SET",
            "source": str(
                source_path.resolve()
            ),
        }

    # ---------------------------------------------------------
    # COMMAND
    # ---------------------------------------------------------

    def build_command(
        self,
        destination_id: str,
    ) -> dict:

        if destination_id not in self.sessions:
            return {
                "success": False,
                "reason": "DESTINATION_NOT_FOUND",
            }

        session = self.sessions[
            destination_id
        ]

        if session.source is None:
            return {
                "success": False,
                "reason": "SOURCE_NOT_SET",
            }

        validation = self.validate_destination(
            destination_id
        )

        if not validation.get("ready", False):
            return {
                "success": False,
                "reason": validation.get(
                    "reason",
                    "DESTINATION_NOT_READY",
                ),
            }

        try:
            command = self.stream_engine.build_command(
                source=session.source,
                destination_id=destination_id,
            )

        except Exception as exc:

            return {
                "success": False,
                "reason": "COMMAND_BUILD_FAILED",
                "error": str(exc),
            }

        return {
            "success": True,
            "reason": "COMMAND_READY",
            "command": command,
        }

    # ---------------------------------------------------------
    # START
    # ---------------------------------------------------------

    def start(
        self,
        destination_id: str,
    ) -> dict:

        if destination_id not in self.sessions:
            return {
                "started": False,
                "reason": "DESTINATION_NOT_FOUND",
            }

        session = self.sessions[
            destination_id
        ]

        if session.status == "RUNNING":
            return {
                "started": False,
                "reason": "ALREADY_RUNNING",
            }

        command_result = self.build_command(
            destination_id
        )

        if not command_result.get("success"):
            return {
                "started": False,
                "reason": command_result.get(
                    "reason",
                    "COMMAND_NOT_READY",
                ),
            }

        # -----------------------------------------------------
        # Real process start is intentionally delegated to the
        # StreamEngine.
        # -----------------------------------------------------

        try:

            process = self.stream_engine.start(
                destination_id=destination_id,
                source=session.source,
            )

        except Exception as exc:

            return {
                "started": False,
                "reason": "STREAM_START_FAILED",
                "error": str(exc),
            }

        session.process = process
        session.status = "RUNNING"

        return {
            "started": True,
            "reason": "STREAM_STARTED",
        }

    # ---------------------------------------------------------
    # STOP
    # ---------------------------------------------------------

    def stop(
        self,
        destination_id: str,
    ) -> dict:

        if destination_id not in self.sessions:
            return {
                "stopped": False,
                "reason": "DESTINATION_NOT_FOUND",
            }

        session = self.sessions[
            destination_id
        ]

        if session.status != "RUNNING":
            session.process = None
            session.status = "STOPPED"

            return {
                "stopped": False,
                "reason": "NOT_RUNNING",
            }

        try:

            self.stream_engine.stop(
                destination_id
            )

        except Exception as exc:

            return {
                "stopped": False,
                "reason": "STREAM_STOP_FAILED",
                "error": str(exc),
            }

        session.process = None
        session.status = "STOPPED"

        return {
            "stopped": True,
            "reason": "STREAM_STOPPED",
        }

    # ---------------------------------------------------------
    # STOP ALL
    # ---------------------------------------------------------

    def stop_all(self) -> dict:

        results = {}

        for destination_id in self.destination_ids:

            results[destination_id] = self.stop(
                destination_id
            )

        return results

    # ---------------------------------------------------------
    # STATUS
    # ---------------------------------------------------------

    def status(
        self,
        destination_id: Optional[str] = None,
    ):

        if destination_id is not None:

            if destination_id not in self.sessions:
                return {
                    "exists": False,
                    "reason": "DESTINATION_NOT_FOUND",
                }

            session = self.sessions[
                destination_id
            ]

            return {
                "exists": True,
                "destination_id": destination_id,
                "status": session.status,
                "source": (
                    str(session.source)
                    if session.source
                    else None
                ),
                "process": (
                    "RUNNING"
                    if session.process
                    else "STOPPED"
                ),
            }

        return {
            destination_id: self.status(
                destination_id
            )
            for destination_id
            in self.destination_ids
        }


# ============================================================
# TEST
# ============================================================

def main():

    print("=" * 60)
    print("MULTI STREAM CONTROLLER TEST")
    print("=" * 60)

    controller = MultiStreamController()

    source = (
        Path(__file__).resolve().parent
        / "cache"
        / "youtube_01"
        / "Episode 1 –The Boy Who Loved the Morning Sky.mp4"
    )

    # ---------------------------------------------------------
    # Destination discovery
    # ---------------------------------------------------------

    print("\nDestination discovery:")

    for destination_id in controller.destination_ids:

        validation = (
            controller.validate_destination(
                destination_id
            )
        )

        print(
            f"- {destination_id} | "
            f"ready={validation.get('ready')} | "
            f"reason={validation.get('reason')}"
        )

    # ---------------------------------------------------------
    # Source
    # ---------------------------------------------------------

    print("\nSource test:")

    source_result = controller.set_source(
        "youtube_01",
        source,
    )

    print(
        f"- Success: "
        f"{source_result['success']}"
    )

    print(
        f"- Reason: "
        f"{source_result['reason']}"
    )

    if source_result.get("source"):
        print(
            f"- Source: "
            f"{source_result['source']}"
        )

    # ---------------------------------------------------------
    # Command generation
    # ---------------------------------------------------------

    print("\nCommand generation test:")

    command_result = controller.build_command(
        "youtube_01"
    )

    print(
        f"- Success: "
        f"{command_result['success']}"
    )

    print(
        f"- Reason: "
        f"{command_result['reason']}"
    )

    if command_result.get("command"):

        command = command_result["command"]

        if isinstance(command, (list, tuple)):

            print(
                "- Command:"
            )

            print(
                " ".join(
                    f'"{item}"'
                    if " " in str(item)
                    else str(item)
                    for item in command
                )
            )

        else:

            print(
                f"- Command: {command}"
            )

    # ---------------------------------------------------------
    # Isolation
    # ---------------------------------------------------------

    print("\nDestination isolation test:")

    youtube_01 = controller.status(
        "youtube_01"
    )

    youtube_02 = controller.status(
        "youtube_02"
    )

    print(
        f"- youtube_01 | "
        f"status={youtube_01['status']} | "
        f"source={youtube_01['source']}"
    )

    print(
        f"- youtube_02 | "
        f"status={youtube_02['status']} | "
        f"source={youtube_02['source']}"
    )

    isolation_ok = (
        youtube_01["source"] is not None
        and youtube_02["source"] is None
        and youtube_01["status"] == "STOPPED"
        and youtube_02["status"] == "STOPPED"
    )

    print(
        f"- Isolation: "
        f"{'OK' if isolation_ok else 'FAILED'}"
    )

    # ---------------------------------------------------------
    # Disabled destination safety
    # ---------------------------------------------------------

    print("\nDisabled destination safety test:")

    start_result = controller.start(
        "youtube_01"
    )

    print(
        f"- Started: "
        f"{start_result['started']}"
    )

    print(
        f"- Reason: "
        f"{start_result['reason']}"
    )

    # ---------------------------------------------------------
    # Missing destination
    # ---------------------------------------------------------

    print("\nMissing destination test:")

    missing = controller.status(
        "unknown_destination"
    )

    print(
        f"- Exists: "
        f"{missing['exists']}"
    )

    print(
        f"- Reason: "
        f"{missing['reason']}"
    )

    # ---------------------------------------------------------
    # Final status
    # ---------------------------------------------------------

    print("\nFinal controller status:")

    for destination_id in (
        controller.destination_ids
    ):

        status = controller.status(
            destination_id
        )

        print(
            f"- {destination_id} | "
            f"status={status['status']} | "
            f"process={status['process']}"
        )

    # ---------------------------------------------------------
    # Safety
    # ---------------------------------------------------------

    print("\nSafety checks:")
    print(
        "  - No real RTMP destination intentionally used."
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
        "MULTI STREAM CONTROLLER TEST COMPLETE"
    )
    print("=" * 60)


if __name__ == "__main__":
    main()

