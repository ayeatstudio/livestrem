from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Optional

from config_manager import ConfigManager
from credential_manager import CredentialManager
from playlist_manager import PlaylistManager


class StreamSession:
    """Owns exactly one FFmpeg process for one destination."""

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
        if self.process.poll() is None:
            return "RUNNING"
        return "FAILED" if self.process.returncode else "STOPPED"

    @property
    def pid(self) -> Optional[int]:
        return self.process.pid if self.process else None

    @property
    def return_code(self) -> Optional[int]:
        return self.process.poll() if self.process else None

    def start(self) -> None:
        if self.status == "RUNNING":
            raise RuntimeError(f"Session already running: {self.destination_id}")

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

    def poll(self) -> str:
        if not self.process:
            return "STOPPED"

        result = self.process.poll()

        if result is None:
            return "RUNNING"

        if result != 0:
            self.last_error = (
                f"FFmpeg exited with return code {result}"
            )
            return "FAILED"

        return "STOPPED"

    def stop(self, timeout: float = 10.0) -> None:
        if not self.process or self.process.poll() is not None:
            return

        self.process.terminate()

        try:
            self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)


class SingleDestinationRuntime:
    """Validated single-destination runtime layer."""

    def __init__(self):
        self.config_manager = ConfigManager()
        self.credential_manager = CredentialManager()
        self.playlist_manager = PlaylistManager()

        self.destinations: dict[str, dict] = {}
        self.playlists: dict[str, dict] = {}
        self.sessions: dict[str, StreamSession] = {}

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
        videos = (
            playlist.get("videos", [])
            if isinstance(playlist, dict)
            else []
        )

        if not videos:
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

    def start(self, destination_id: str) -> StreamSession:
        check = self.readiness(destination_id)

        if not check["ready"]:
            raise ValueError(
                f"Cannot start {destination_id}: {check['reason']}"
            )

        old = self.sessions.get(destination_id)

        if old and old.poll() == "RUNNING":
            raise RuntimeError(
                f"Session already running: {destination_id}"
            )

        session = StreamSession(
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
            "status": session.poll(),
            "pid": session.pid,
            "return_code": session.return_code,
            "error": session.last_error,
        }


def main():
    print("=" * 60)
    print("SINGLE DESTINATION RUNTIME v0.8 TEST")
    print("=" * 60)

    runtime = SingleDestinationRuntime()
    runtime.load()

    print(
        f"\n[RUNTIME] Destinations loaded: "
        f"{len(runtime.destinations)}"
    )

    print("\nReadiness:")
    for destination_id in runtime.destinations:
        check = runtime.readiness(destination_id)
        print(
            f"- {destination_id} | "
            f"{'READY' if check['ready'] else 'NOT READY'} | "
            f"{check['reason']}"
        )

    target = "youtube_01"
    print(f"\nTarget: {target}")

    check = runtime.readiness(target)
    print(f"  Ready: {check['ready']}")
    print(f"  Reason: {check['reason']}")

    # v0.8 test intentionally does NOT start an RTMP stream.
    # Runtime start/stop methods are implemented and guarded,
    # while this test only validates the safety gate.
    print("\nRuntime start gate: VALIDATED")
    print("Real RTMP start: NOT EXECUTED")
    print("No real streaming was started.")

    print("=" * 60)
    print("SINGLE DESTINATION RUNTIME v0.8 TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
