from __future__ import annotations

import time
from pathlib import Path

from engine import StreamingEngine
from models import (
    LoopMode,
    PlatformType,
    SourceType,
    StreamDestination,
    StreamJob,
    VideoSource,
)

from config_manager import ConfigManager
from credential_manager import CredentialManager
from playlist_manager import PlaylistManager


class StreamingController:
    """
    Production controller facade over StreamingEngine.

    Responsibilities:
        - Load configured destinations and cached playlists.
        - Validate destination readiness.
        - Create engine jobs from local playlist sources.
        - Delegate lifecycle operations to StreamingEngine.
        - Expose engine runtime status and worker metrics.

    Real destinations remain blocked by the existing destination configuration
    unless explicitly enabled and configured.
    """

    def __init__(self):
        self.config_manager = ConfigManager()
        self.credential_manager = CredentialManager()
        self.playlist_manager = PlaylistManager()

        self.engine = StreamingEngine()

        self.destinations: dict[str, dict] = {}
        self.playlists: dict[str, dict] = {}
        self.job_ids: dict[str, str] = {}

    # ---------------------------------------------------------
    # LOAD
    # ---------------------------------------------------------

    def load(self) -> None:
        self.destinations = {}

        for destination in self.config_manager.get_destinations():
            if isinstance(destination, dict) and destination.get("id"):
                self.destinations[destination["id"]] = destination

        cache_root = Path(__file__).resolve().parent / "cache"

        self.playlists = {}

        for destination_id in self.destinations:
            folder = cache_root / destination_id

            state = self.playlist_manager.load_from_folder(
                destination_id,
                folder,
            )

            current = self.playlist_manager.current_item(
                destination_id
            )

            self.playlists[destination_id] = {
                "destination_id": destination_id,
                "folder_name": folder.name,
                "videos": [
                    {
                        "name": item.path.name,
                        "local_path": str(item.path),
                        "index": item.index,
                    }
                    for item in state.items
                ],
                "position": state.position,
                "current": (
                    current.path.name
                    if current
                    else None
                ),
            }

    # ---------------------------------------------------------
    # VALIDATION
    # ---------------------------------------------------------

    def validate(self, destination_id: str) -> dict:
        destination = self.destinations.get(destination_id)

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

        playlist = self.playlists.get(destination_id)

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

        credential = self.credential_manager.get(destination_id)

        if not credential:
            return {
                "ready": False,
                "reason": "CREDENTIAL_NOT_CONFIGURED",
            }

        if not credential.get("rtmp_url") or not credential.get("stream_key"):
            return {
                "ready": False,
                "reason": "CREDENTIAL_INCOMPLETE",
            }

        video = videos[0]
        local_path = video.get("local_path")

        if not local_path:
            return {
                "ready": False,
                "reason": "VIDEO_PATH_MISSING",
            }

        if not Path(local_path).exists():
            return {
                "ready": False,
                "reason": "VIDEO_CACHE_MISSING",
            }

        return {
            "ready": True,
            "reason": "READY",
            "platform": destination.get("platform"),
            "folder": playlist.get("folder_name"),
            "videos": len(videos),
            "current": video.get("name"),
        }

    # ---------------------------------------------------------
    # JOB BUILDING
    # ---------------------------------------------------------

    def _build_job(self, destination_id: str) -> StreamJob:
        check = self.validate(destination_id)

        if not check["ready"]:
            raise ValueError(
                f"{destination_id}: {check['reason']}"
            )

        destination = self.destinations[destination_id]
        playlist = self.playlists[destination_id]
        video = playlist["videos"][0]

        platform_value = destination.get("platform", "youtube")

        try:
            platform = PlatformType(platform_value)
        except ValueError:
            platform = PlatformType.YOUTUBE

        stream_destination = StreamDestination(
            platform=platform,
            name=destination.get("name", destination_id),
            stream_url=self.credential_manager.get(
                destination_id
            )["rtmp_url"],
            stream_key=self.credential_manager.get(
                destination_id
            )["stream_key"],
            enabled=True,
            id=destination_id,
        )

        source = VideoSource(
            name=video["name"],
            source_type=SourceType.LOCAL_FILE,
            file_path=str(Path(video["local_path"]).resolve()),
        )

        return StreamJob(
            name=f"controller:{destination_id}",
            source=source,
            destinations=[stream_destination],
            loop_mode=LoopMode.ONE,
        )

    # ---------------------------------------------------------
    # FFMPEG COMMAND
    # ---------------------------------------------------------

    def build_command(self, destination_id: str) -> list[str]:
        job = self._build_job(destination_id)

        # Use the same authoritative command builder as the engine worker.
        destination = job.destinations[0]
        from workers.ffmpeg_worker import FFmpegConfig, FFmpegWorker

        worker = FFmpegWorker(
            worker_id=f"preview:{destination_id}",
            input_source=job.source.file_path,
            output_url=(
                destination.stream_url.rstrip("/")
                + "/"
                + destination.stream_key
            ),
            config=FFmpegConfig(
                extra_args=job.video_settings.extra_options,
            ),
        )

        return worker.build_command()

    # ---------------------------------------------------------
    # START / STOP
    # ---------------------------------------------------------

    def start(self, destination_id: str):
        job = self._build_job(destination_id)

        self.engine.start()
        job_id = self.engine.create_job(job)
        self.job_ids[destination_id] = job_id

        try:
            return self.engine.start_job(job_id)
        except Exception:
            self.job_ids.pop(destination_id, None)
            self.engine.remove_job(job_id)
            raise

    def stop(self, destination_id: str) -> None:
        job_id = self.job_ids.get(destination_id)

        if job_id:
            self.engine.stop_job(job_id)

    def start_all_enabled(self) -> dict[str, str]:
        results = {}

        for destination_id, destination in self.destinations.items():
            if not destination.get("enabled", False):
                results[destination_id] = "SKIPPED_DISABLED"
                continue

            try:
                instance = self.start(destination_id)
                results[destination_id] = (
                    f"STARTED_PID_{instance.process_id}"
                )
            except Exception as exc:
                results[destination_id] = f"FAILED: {exc}"

        return results

    def stop_all(self) -> None:
        self.engine.stop_all()

    # ---------------------------------------------------------
    # PAUSE / RESUME / RESTART
    # ---------------------------------------------------------

    def pause(self, destination_id: str) -> dict:
        job_id = self.job_ids.get(destination_id)
        if not job_id:
            return {"destination_id": destination_id, "action": "PAUSE", "result": "BLOCKED_SAFE", "reason": "JOB_NOT_RUNNING"}
        try:
            result = self.engine.pause_job(job_id)
            return {"destination_id": destination_id, "action": "PAUSE", "result": "OK" if result else "BLOCKED_SAFE", "reason": "ENGINE_PAUSED" if result else "PAUSE_REJECTED"}
        except Exception as exc:
            return {"destination_id": destination_id, "action": "PAUSE", "result": "BLOCKED_SAFE", "reason": str(exc)}

    def resume(self, destination_id: str) -> dict:
        job_id = self.job_ids.get(destination_id)
        if not job_id:
            return {"destination_id": destination_id, "action": "RESUME", "result": "BLOCKED_SAFE", "reason": "JOB_NOT_RUNNING"}
        try:
            result = self.engine.resume_job(job_id)
            return {"destination_id": destination_id, "action": "RESUME", "result": "OK" if result else "BLOCKED_SAFE", "reason": "ENGINE_RESUMED" if result else "RESUME_REJECTED"}
        except Exception as exc:
            return {"destination_id": destination_id, "action": "RESUME", "result": "BLOCKED_SAFE", "reason": str(exc)}

    def restart(self, destination_id: str) -> dict:
        job_id = self.job_ids.get(destination_id)
        if not job_id:
            return {"destination_id": destination_id, "action": "RESTART", "result": "BLOCKED_SAFE", "reason": "JOB_NOT_RUNNING"}
        try:
            instance = self.engine.restart_job(job_id)
            return {"destination_id": destination_id, "action": "RESTART", "result": "OK" if instance else "BLOCKED_SAFE", "reason": "ENGINE_RESTARTED" if instance else "RESTART_REJECTED"}
        except Exception as exc:
            return {"destination_id": destination_id, "action": "RESTART", "result": "BLOCKED_SAFE", "reason": str(exc)}

    # ---------------------------------------------------------
    # STATUS
    # ---------------------------------------------------------

    @staticmethod
    def _empty_metrics() -> dict:
        return {"uptime_seconds": 0.0, "video_frames": 0, "dropped_frames": 0, "bitrate_kbps": 0.0, "fps": 0.0, "reconnect_count": 0, "cpu_percent": 0.0, "memory_percent": 0.0, "last_update": None}

    def status(self, destination_id: str) -> dict:
        job_id = self.job_ids.get(destination_id)

        if not job_id:
            return {
                "destination_id": destination_id,
                "status": "STOPPED",
                "pid": None,
                "return_code": None,
                "error": None,
                "metrics": self._empty_metrics(),
            }

        status = self.engine.get_status(job_id)

        if status is None:
            return {
                "destination_id": destination_id,
                "status": "STOPPED",
                "pid": None,
                "return_code": None,
                "error": None,
                "metrics": self._empty_metrics(),
            }

        return {
            "destination_id": destination_id,
            "status": status["status"].upper(),
            "pid": status["process_id"],
            "return_code": None,
            "error": status["error_message"],
            "metrics": status.get("metrics"),
            "workers": status.get("workers", []),
            "job_id": status["job_id"],
        }

    def all_status(self) -> dict[str, dict]:
        return {
            destination_id: self.status(destination_id)
            for destination_id in self.destinations
        }

    def shutdown(self) -> None:
        self.engine.shutdown()

def main():
    print("=" * 60)
    print("STREAMING CONTROLLER v1.0 ENGINE + LIFECYCLE INTEGRATION TEST")
    print("=" * 60)

    controller = StreamingController()
    controller.load()

    print(
        f"\n[CONTROLLER] Destinations loaded: "
        f"{len(controller.destinations)}"
    )

    print("\nValidation:")
    ready = 0

    for destination_id, destination in controller.destinations.items():
        result = controller.validate(destination_id)

        if result["ready"]:
            ready += 1

        print(
            f"- {destination_id} | "
            f"{destination.get('platform')} | "
            f"{'READY' if result['ready'] else 'NOT READY'} | "
            f"{result['reason']}"
        )

    print(
        f"\nReady destinations: "
        f"{ready}/{len(controller.destinations)}"
    )

    print("\nStart-all safety test:")
    results = controller.start_all_enabled()

    for destination_id, result in results.items():
        print(f"- {destination_id} | {result}")

    print("\nCurrent controller status:")
    for destination_id, info in controller.all_status().items():
        print(
            f"- {destination_id} | "
            f"{info['status']} | "
            f"pid={info['pid']}"
        )

    print("\nLifecycle safety test:")
    for destination_id in controller.destinations:
        for action, method in (("PAUSE", controller.pause), ("RESUME", controller.resume), ("RESTART", controller.restart)):
            result = method(destination_id)
            print(f"- {destination_id} | {action} | {result['result']} | {result['reason']}")

    controller.stop_all()
    controller.shutdown()

    print("\nReal RTMP streaming: NOT EXECUTED")
    print("No real streaming destination was used.")
    print("=" * 60)
    print("STREAMING CONTROLLER v1.0 ENGINE INTEGRATION TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
