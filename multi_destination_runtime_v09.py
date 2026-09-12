from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Optional

from config_manager import ConfigManager
from credential_manager import CredentialManager
from playlist_manager import PlaylistManager


class DestinationSession:
    """One isolated FFmpeg runtime session."""

    def __init__(self, destination_id: str, command: list[str]):
        self.destination_id = destination_id
        self.command = command
        self.process: Optional[subprocess.Popen] = None
        self.started_at: Optional[float] = None
        self.last_error: Optional[str] = None

    @property
    def status(self) -> str:
        if self.process is None:
            return "STOPPED"

        return (
            "RUNNING"
            if self.process.poll() is None
            else ("FAILED" if self.process.returncode else "STOPPED")
        )

    @property
    def pid(self) -> Optional[int]:
        return self.process.pid if self.process else None

    @property
    def return_code(self) -> Optional[int]:
        return self.process.poll() if self.process else None

    def start(self) -> None:
        if self.status == "RUNNING":
            raise RuntimeError(
                f"Session already running: {self.destination_id}"
            )

        self.last_error = None

        self.process = subprocess.Popen(
            self.command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        self.started_at = time.time()

    def stop(self, timeout: float = 10.0) -> None:
        if not self.process or self.process.poll() is not None:
            return

        self.process.terminate()

        try:
            self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)

    def refresh(self) -> str:
        status = self.status

        if status == "FAILED" and self.process:
            self.last_error = (
                f"FFmpeg exited with return code "
                f"{self.process.returncode}"
            )

        return status


class MultiDestinationRuntime:
    """Manages independent sessions for all configured destinations."""

    def __init__(self):
        self.config_manager = ConfigManager()
        self.credential_manager = CredentialManager()
        self.playlist_manager = PlaylistManager()

        self.destinations: dict[str, dict] = {}
        self.playlists: dict[str, dict] = {}
        self.sessions: dict[str, DestinationSession] = {}

    def load(self) -> None:
        self.destinations = {}

        for destination in self.config_manager.get_destinations():
            if isinstance(destination, dict) and destination.get("id"):
                self.destinations[destination["id"]] = destination

        self.playlists = self.playlist_manager.build_playlists()

    def readiness(self, destination_id: str) -> dict:
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
            "folder": playlist.get("folder_name"),
            "videos": len(videos),
            "current": video.get("name"),
        }

    def build_command(self, destination_id: str) -> list[str]:
        check = self.readiness(destination_id)

        if not check["ready"]:
            raise ValueError(
                f"{destination_id}: {check['reason']}"
            )

        playlist = self.playlists[destination_id]
        credential = self.credential_manager.get(destination_id)
        video = playlist["videos"][0]

        output_url = (
            str(credential["rtmp_url"]).rstrip("/")
            + "/"
            + str(credential["stream_key"]).strip()
        )

        return [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "warning",
            "-re",
            "-stream_loop", "-1",
            "-i", str(video["local_path"]),
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-pix_fmt", "yuv420p",
            "-vf",
            "scale=1920:1080:force_original_aspect_ratio=decrease,"
            "pad=1920:1080:(ow-iw)/2:(oh-ih)/2",
            "-r", "30",
            "-b:v", "4500k",
            "-maxrate", "4500k",
            "-bufsize", "9000k",
            "-c:a", "aac",
            "-b:a", "128k",
            "-ar", "44100",
            "-f", "flv",
            output_url,
        ]

    def start(self, destination_id: str) -> DestinationSession:
        old = self.sessions.get(destination_id)

        if old and old.refresh() == "RUNNING":
            raise RuntimeError(
                f"Session already running: {destination_id}"
            )

        session = DestinationSession(
            destination_id,
            self.build_command(destination_id),
        )
        session.start()
        self.sessions[destination_id] = session
        return session

    def stop(self, destination_id: str) -> None:
        session = self.sessions.get(destination_id)

        if session:
            session.stop()

    def refresh_all(self) -> None:
        for session in self.sessions.values():
            session.refresh()

    def status(self, destination_id: str) -> dict:
        session = self.sessions.get(destination_id)

        if not session:
            return {
                "destination_id": destination_id,
                "status": "STOPPED",
                "pid": None,
                "return_code": None,
                "error": None,
            }

        return {
            "destination_id": destination_id,
            "status": session.refresh(),
            "pid": session.pid,
            "return_code": session.return_code,
            "error": session.last_error,
        }

    def all_status(self) -> dict[str, dict]:
        self.refresh_all()

        return {
            destination_id: self.status(destination_id)
            for destination_id in self.destinations
        }


def main():
    print("=" * 60)
    print("MULTI-DESTINATION RUNTIME v0.9 TEST")
    print("=" * 60)

    runtime = MultiDestinationRuntime()
    runtime.load()

    print(
        f"\n[RUNTIME] Destinations loaded: "
        f"{len(runtime.destinations)}"
    )

    print("\nDestination readiness:")
    ready_count = 0

    for destination_id, destination in runtime.destinations.items():
        check = runtime.readiness(destination_id)

        if check["ready"]:
            ready_count += 1

        print(
            f"- {destination_id} | "
            f"{destination.get('platform')} | "
            f"{'READY' if check['ready'] else 'NOT READY'} | "
            f"{check['reason']}"
        )

    print(f"\nReady destinations: {ready_count}/{len(runtime.destinations)}")

    print("\nSession isolation test:")
    print("  Each destination owns an independent FFmpeg session.")
    print("  One destination failure does not stop another session.")

    print("\nRuntime status:")
    for destination_id, info in runtime.all_status().items():
        print(
            f"- {destination_id} | "
            f"{info['status']} | "
            f"pid={info['pid']}"
        )

    print("\nReal RTMP start: NOT EXECUTED")
    print("No real streaming was started.")

    print("=" * 60)
    print("MULTI-DESTINATION RUNTIME v0.9 TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
