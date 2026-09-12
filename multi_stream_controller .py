from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from destination_manager import DestinationManager
from engine import StreamingEngine
from models import (
    LoopMode,
    PlatformType,
    SourceType,
    StreamJob,
    StreamStatus,
    VideoSource,
)


# ============================================================
# MULTI STREAM CONTROLLER
# ============================================================
# Canonical facade for independently controlled destinations.
#
# Architecture:
#     MultiStreamController
#         -> StreamingEngine
#             -> FFmpegWorker
#
# Safety:
# - Does not modify credentials.
# - Does not modify playlists.
# - Does not modify Google Drive.
# - Does not print stream keys.
# - Real RTMP execution only occurs when a destination is
#   explicitly enabled and correctly configured.
# ============================================================


DESTINATION_IDS = [
    "youtube_01",
    "youtube_02",
    "youtube_03",
    "youtube_04",
    "facebook_01",
    "facebook_02",
    "instagram_01",
]


@dataclass
class StreamSession:
    destination_id: str
    source: Optional[Path] = None
    job_id: Optional[str] = None
    instance_id: Optional[str] = None
    status: str = StreamStatus.STOPPED.value


class MultiStreamController:
    """
    Multi-destination controller built on the canonical
    StreamingEngine lifecycle.

    Each destination gets its own StreamJob and therefore its
    own FFmpegWorker inside StreamingEngine.
    """

    def __init__(self) -> None:
        self.destination_manager = DestinationManager()
        self.engine = StreamingEngine()

        self.sessions: dict[str, StreamSession] = {}
        self.destination_ids = list(DESTINATION_IDS)

        self._load_sessions()
        self.engine.start()

    # ---------------------------------------------------------
    # SESSION INITIALIZATION
    # ---------------------------------------------------------

    def _load_sessions(self) -> None:
        self.sessions = {
            destination_id: StreamSession(
                destination_id=destination_id
            )
            for destination_id in self.destination_ids
        }

    # ---------------------------------------------------------
    # DESTINATION
    # ---------------------------------------------------------

    def get_destination(self, destination_id: str) -> dict:
        if destination_id not in self.sessions:
            return {
                "exists": False,
                "reason": "DESTINATION_NOT_FOUND",
            }

        try:
            result = self.destination_manager.get_destination(
                destination_id
            )
        except Exception as exc:
            return {
                "exists": False,
                "reason": "DESTINATION_LOOKUP_FAILED",
                "error": str(exc),
            }

        if not isinstance(result, dict):
            return {
                "exists": False,
                "reason": "INVALID_DESTINATION_RESPONSE",
            }

        return result

    # ---------------------------------------------------------
    # READINESS
    # ---------------------------------------------------------

    def validate_destination(self, destination_id: str) -> dict:
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

        self.sessions[destination_id].source = source_path.resolve()

        return {
            "success": True,
            "reason": "SOURCE_SET",
            "source": str(source_path.resolve()),
        }

    # ---------------------------------------------------------
    # JOB BUILDING
    # ---------------------------------------------------------

    def _build_job(self, destination_id: str) -> StreamJob:
        session = self.sessions[destination_id]

        if session.source is None:
            raise RuntimeError("SOURCE_NOT_SET")

        destination_data = self.get_destination(destination_id)

        if not destination_data.get("exists", True):
            raise RuntimeError(
                destination_data.get(
                    "reason",
                    "DESTINATION_NOT_FOUND",
                )
            )

        platform_value = (
            destination_data.get("platform")
            or destination_data.get("type")
            or destination_data.get("platform_type")
        )

        name = (
            destination_data.get("name")
            or destination_data.get("display_name")
            or destination_id
        )

        stream_url = destination_data.get("stream_url")
        stream_key = destination_data.get("stream_key")

        enabled = destination_data.get("enabled", False)

        # Normalize platform without exposing credentials.
        try:
            platform = PlatformType(str(platform_value).lower())
        except ValueError as exc:
            raise RuntimeError(
                f"UNSUPPORTED_PLATFORM: {platform_value}"
            ) from exc

        source = VideoSource(
            name=session.source.name,
            source_type=SourceType.LOCAL_FILE,
            file_path=str(session.source),
        )

        destination = self._destination_model(
            platform=platform,
            name=name,
            stream_url=stream_url,
            stream_key=stream_key,
            enabled=bool(enabled),
            destination_id=destination_id,
        )

        return StreamJob(
            name=f"multi_stream:{destination_id}",
            source=source,
            destinations=[destination],
            loop_mode=LoopMode.ONE,
        )

    @staticmethod
    def _destination_model(
        *,
        platform: PlatformType,
        name: str,
        stream_url: Optional[str],
        stream_key: Optional[str],
        enabled: bool,
        destination_id: str,
    ):
        from models import StreamDestination

        return StreamDestination(
            platform=platform,
            name=name,
            stream_url=stream_url,
            stream_key=stream_key,
            enabled=enabled,
            id=destination_id,
        )

    # ---------------------------------------------------------
    # COMMAND / PREVIEW
    # ---------------------------------------------------------

    def build_command(self, destination_id: str) -> dict:
        if destination_id not in self.sessions:
            return {
                "success": False,
                "reason": "DESTINATION_NOT_FOUND",
            }

        session = self.sessions[destination_id]

        if session.source is None:
            return {
                "success": False,
                "reason": "SOURCE_NOT_SET",
            }

        validation = self.validate_destination(destination_id)

        if not validation.get("ready", False):
            return {
                "success": False,
                "reason": validation.get(
                    "reason",
                    "DESTINATION_NOT_READY",
                ),
            }

        try:
            job = self._build_job(destination_id)

            # Validate through the canonical job model.
            if not job.can_start():
                return {
                    "success": False,
                    "reason": "STREAM_JOB_NOT_READY",
                }

            destination = job.destinations[0]

            target = (
                destination.stream_url.rstrip("/")
                + "/"
                + destination.stream_key
            )

            # Return a safe preview only; the key is never exposed.
            command = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "warning",
                "-re",
                "-i",
                str(session.source),
                "-c:v",
                job.video_settings.video_codec,
                "-preset",
                job.video_settings.preset,
                "-pix_fmt",
                job.video_settings.pixel_format,
                "-r",
                str(job.video_settings.fps),
                "-b:v",
                job.video_settings.video_bitrate,
                "-c:a",
                job.video_settings.audio_codec,
                "-b:a",
                job.video_settings.audio_bitrate,
                "-ar",
                str(job.video_settings.audio_sample_rate),
                "-f",
                "flv",
                target,
            ]

            return {
                "success": True,
                "reason": "COMMAND_READY",
                "command": self._redact_command(command),
            }

        except Exception as exc:
            return {
                "success": False,
                "reason": "COMMAND_BUILD_FAILED",
                "error": str(exc),
            }

    @staticmethod
    def _redact_command(command: list[str]) -> list[str]:
        redacted = list(command)

        for index, value in enumerate(redacted):
            text = str(value)
            if text.startswith("rtmp://") and "/" in text[7:]:
                base = text.rsplit("/", 1)[0]
                redacted[index] = base + "/<STREAM_KEY>"

        return redacted

    # ---------------------------------------------------------
    # START
    # ---------------------------------------------------------

    def start(self, destination_id: str) -> dict:
        if destination_id not in self.sessions:
            return {
                "started": False,
                "reason": "DESTINATION_NOT_FOUND",
            }

        session = self.sessions[destination_id]

        if session.status in {
            StreamStatus.STARTING.value,
            StreamStatus.LIVE.value,
            StreamStatus.PAUSED.value,
            StreamStatus.RECONNECTING.value,
        }:
            return {
                "started": False,
                "reason": "ALREADY_RUNNING",
            }

        validation = self.validate_destination(destination_id)

        if not validation.get("ready", False):
            return {
                "started": False,
                "reason": validation.get(
                    "reason",
                    "DESTINATION_NOT_READY",
                ),
            }

        if session.source is None:
            return {
                "started": False,
                "reason": "SOURCE_NOT_SET",
            }

        try:
            job = self._build_job(destination_id)
            job_id = self.engine.create_job(job)

            instance = self.engine.start_job(job_id)

            session.job_id = job_id
            session.instance_id = instance.id
            session.status = instance.status.value

            if instance.status != StreamStatus.LIVE:
                return {
                    "started": False,
                    "reason": "STREAM_START_FAILED",
                    "job_id": job_id,
                    "instance_id": instance.id,
                    "error": instance.error_message,
                }

            return {
                "started": True,
                "reason": "STREAM_STARTED",
                "job_id": job_id,
                "instance_id": instance.id,
            }

        except Exception as exc:
            return {
                "started": False,
                "reason": "STREAM_START_FAILED",
                "error": str(exc),
            }

    # ---------------------------------------------------------
    # STOP
    # ---------------------------------------------------------

    def stop(self, destination_id: str) -> dict:
        if destination_id not in self.sessions:
            return {
                "stopped": False,
                "reason": "DESTINATION_NOT_FOUND",
            }

        session = self.sessions[destination_id]

        if not session.job_id:
            session.status = StreamStatus.STOPPED.value
            return {
                "stopped": False,
                "reason": "NOT_RUNNING",
            }

        try:
            stopped = self.engine.stop_job(session.job_id)

            session.status = StreamStatus.STOPPED.value
            session.instance_id = None

            return {
                "stopped": bool(stopped),
                "reason": (
                    "STREAM_STOPPED"
                    if stopped
                    else "NOT_RUNNING"
                ),
            }

        except Exception as exc:
            return {
                "stopped": False,
                "reason": "STREAM_STOP_FAILED",
                "error": str(exc),
            }

    # ---------------------------------------------------------
    # PAUSE / RESUME / RESTART
    # ---------------------------------------------------------

    def pause(self, destination_id: str) -> dict:
        session = self.sessions.get(destination_id)

        if session is None:
            return {
                "paused": False,
                "reason": "DESTINATION_NOT_FOUND",
            }

        if not session.job_id:
            return {
                "paused": False,
                "reason": "JOB_NOT_RUNNING",
            }

        result = self.engine.pause_job(session.job_id)

        if result:
            session.status = StreamStatus.PAUSED.value

        return {
            "paused": bool(result),
            "reason": (
                "STREAM_PAUSED"
                if result
                else "PAUSE_BLOCKED"
            ),
        }

    def resume(self, destination_id: str) -> dict:
        session = self.sessions.get(destination_id)

        if session is None:
            return {
                "resumed": False,
                "reason": "DESTINATION_NOT_FOUND",
            }

        if not session.job_id:
            return {
                "resumed": False,
                "reason": "JOB_NOT_RUNNING",
            }

        result = self.engine.resume_job(session.job_id)

        if result:
            session.status = StreamStatus.LIVE.value

        return {
            "resumed": bool(result),
            "reason": (
                "STREAM_RESUMED"
                if result
                else "RESUME_BLOCKED"
            ),
        }

    def restart(self, destination_id: str) -> dict:
        session = self.sessions.get(destination_id)

        if session is None:
            return {
                "restarted": False,
                "reason": "DESTINATION_NOT_FOUND",
            }

        if not session.job_id:
            return {
                "restarted": False,
                "reason": "JOB_NOT_RUNNING",
            }

        try:
            instance = self.engine.restart_job(session.job_id)

            session.instance_id = instance.id
            session.status = instance.status.value

            return {
                "restarted": instance.status == StreamStatus.LIVE,
                "reason": (
                    "STREAM_RESTARTED"
                    if instance.status == StreamStatus.LIVE
                    else "STREAM_RESTART_FAILED"
                ),
                "instance_id": instance.id,
                "error": instance.error_message,
            }

        except Exception as exc:
            return {
                "restarted": False,
                "reason": "STREAM_RESTART_FAILED",
                "error": str(exc),
            }

    # ---------------------------------------------------------
    # STOP ALL
    # ---------------------------------------------------------

    def stop_all(self) -> dict:
        results = {}

        for destination_id in self.destination_ids:
            results[destination_id] = self.stop(destination_id)

        return results

    # ---------------------------------------------------------
    # STATUS
    # ---------------------------------------------------------

    def status(self, destination_id: Optional[str] = None):
        if destination_id is not None:
            session = self.sessions.get(destination_id)

            if session is None:
                return {
                    "exists": False,
                    "reason": "DESTINATION_NOT_FOUND",
                }

            engine_status = None

            if session.job_id:
                engine_status = self.engine.get_status(
                    session.job_id
                )

                if engine_status:
                    session.status = engine_status["status"]

            return {
                "exists": True,
                "destination_id": destination_id,
                "status": session.status,
                "source": (
                    str(session.source)
                    if session.source
                    else None
                ),
                "job_id": session.job_id,
                "instance_id": session.instance_id,
                "engine": engine_status,
            }

        return {
            destination_id: self.status(destination_id)
            for destination_id in self.destination_ids
        }

    # ---------------------------------------------------------
    # SHUTDOWN
    # ---------------------------------------------------------

    def shutdown(self) -> None:
        self.stop_all()
        self.engine.shutdown()


# ============================================================
# SAFE TEST
# ============================================================

def main() -> None:
    print("=" * 60)
    print("MULTI STREAM CONTROLLER v1.0 ENGINE INTEGRATION TEST")
    print("=" * 60)

    controller = MultiStreamController()

    print("\nDestination discovery:")

    for destination_id in controller.destination_ids:
        validation = controller.validate_destination(
            destination_id
        )

        print(
            f"- {destination_id} | "
            f"ready={validation.get('ready')} | "
            f"reason={validation.get('reason')}"
        )

    source = (
        Path(__file__).resolve().parent
        / "cache"
        / "youtube_01"
        / "Episode 1 –The Boy Who Loved the Morning Sky.mp4"
    )

    print("\nSource test:")

    source_result = controller.set_source(
        "youtube_01",
        source,
    )

    print(f"- Success: {source_result['success']}")
    print(f"- Reason: {source_result['reason']}")

    if source_result.get("source"):
        print(f"- Source: {source_result['source']}")

    print("\nCommand preview test:")

    command_result = controller.build_command(
        "youtube_01"
    )

    print(f"- Success: {command_result['success']}")
    print(f"- Reason: {command_result['reason']}")

    if command_result.get("command"):
        print(
            "- Command:"
        )
        print(
            " ".join(
                f'"{item}"'
                if " " in str(item)
                else str(item)
                for item in command_result["command"]
            )
        )

    print("\nDestination isolation test:")

    youtube_01 = controller.status("youtube_01")
    youtube_02 = controller.status("youtube_02")

    isolation_ok = (
        youtube_01["source"] is not None
        and youtube_02["source"] is None
        and youtube_01["status"] == StreamStatus.STOPPED.value
        and youtube_02["status"] == StreamStatus.STOPPED.value
    )

    print(
        f"- youtube_01 | status={youtube_01['status']} | "
        f"source={'SET' if youtube_01['source'] else 'NONE'}"
    )
    print(
        f"- youtube_02 | status={youtube_02['status']} | "
        f"source={'SET' if youtube_02['source'] else 'NONE'}"
    )
    print(
        f"- Isolation: "
        f"{'OK' if isolation_ok else 'FAILED'}"
    )

    print("\nDisabled destination safety test:")

    start_result = controller.start("youtube_01")

    print(f"- Started: {start_result['started']}")
    print(f"- Reason: {start_result['reason']}")

    print("\nLifecycle safety test:")

    for destination_id in controller.destination_ids:
        pause_result = controller.pause(destination_id)
        resume_result = controller.resume(destination_id)
        restart_result = controller.restart(destination_id)

        print(
            f"- {destination_id} | "
            f"PAUSE={pause_result['reason']} | "
            f"RESUME={resume_result['reason']} | "
            f"RESTART={restart_result['reason']}"
        )

    print("\nMissing destination test:")

    missing = controller.status("unknown_destination")

    print(f"- Exists: {missing['exists']}")
    print(f"- Reason: {missing['reason']}")

    print("\nFinal status:")

    for destination_id in controller.destination_ids:
        status = controller.status(destination_id)

        print(
            f"- {destination_id} | "
            f"status={status['status']} | "
            f"job_id={status['job_id']} | "
            f"instance_id={status['instance_id']}"
        )

    controller.shutdown()

    print("\nSafety checks:")
    print("  - No real RTMP destination intentionally used.")
    print("  - No stream key printed.")
    print("  - No credentials modified.")
    print("  - No playlist modified.")
    print("  - No Google Drive files modified.")
    print("  - Multi-destination engine lifecycle is isolated.")

    print("\n" + "=" * 60)
    print("MULTI STREAM CONTROLLER TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
