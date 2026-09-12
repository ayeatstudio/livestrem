from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Optional

from config_manager import ConfigManager
from credential_manager import CredentialManager
from playlist_manager import PlaylistManager


class StreamSession:
    def __init__(self, destination_id: str, command: list[str]):
        self.destination_id = destination_id
        self.command = command
        self.process: Optional[subprocess.Popen] = None
        self.started_at: Optional[float] = None

    @property
    def status(self) -> str:
        if self.process is None:
            return "STOPPED"
        return "RUNNING" if self.process.poll() is None else "STOPPED"

    @property
    def pid(self) -> Optional[int]:
        return self.process.pid if self.process else None

    @property
    def return_code(self) -> Optional[int]:
        return self.process.poll() if self.process else None

    def start(self) -> None:
        if self.status == "RUNNING":
            raise RuntimeError(f"Already running: {self.destination_id}")
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


class StreamSessionManager:
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

    def validate_destination(self, destination_id: str):
        destination = self.destinations.get(destination_id)
        if not destination:
            raise ValueError(f"Unknown destination: {destination_id}")
        if not destination.get("enabled", False):
            raise ValueError(f"Destination is disabled: {destination_id}")

        playlist = self.playlists.get(destination_id)
        videos = playlist.get("videos", []) if isinstance(playlist, dict) else []
        if not videos:
            raise ValueError(f"Playlist is empty: {destination_id}")

        credential = self.credential_manager.get(destination_id)
        if not credential:
            raise ValueError(f"Credential not configured: {destination_id}")

        if not credential.get("rtmp_url") or not credential.get("stream_key"):
            raise ValueError(f"Incomplete credential: {destination_id}")

        return destination, playlist, credential

    def build_command(self, destination_id: str) -> list[str]:
        _, playlist, credential = self.validate_destination(destination_id)
        video = playlist["videos"][0]
        input_path = video.get("local_path")
        if not input_path:
            raise ValueError(f"Playlist video has no local_path: {destination_id}")

        input_file = Path(input_path)
        if not input_file.exists():
            raise FileNotFoundError(f"Cached video not found: {input_file}")

        output_url = (
            str(credential["rtmp_url"]).rstrip("/")
            + "/"
            + str(credential["stream_key"]).strip()
        )

        return [
            "ffmpeg", "-hide_banner", "-loglevel", "warning",
            "-re", "-stream_loop", "-1", "-i", str(input_file),
            "-c:v", "libx264", "-preset", "veryfast",
            "-pix_fmt", "yuv420p",
            "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,"
                   "pad=1920:1080:(ow-iw)/2:(oh-ih)/2",
            "-r", "30", "-b:v", "4500k", "-maxrate", "4500k",
            "-bufsize", "9000k", "-c:a", "aac", "-b:a", "128k",
            "-ar", "44100", "-f", "flv", output_url,
        ]

    def start(self, destination_id: str) -> StreamSession:
        command = self.build_command(destination_id)
        session = StreamSession(destination_id, command)
        session.start()
        self.sessions[destination_id] = session
        return session

    def stop(self, destination_id: str) -> None:
        session = self.sessions.get(destination_id)
        if session:
            session.stop()

    def get_status(self, destination_id: str) -> dict:
        session = self.sessions.get(destination_id)
        if not session:
            return {"destination_id": destination_id, "status": "STOPPED",
                    "pid": None, "return_code": None}
        return {"destination_id": destination_id, "status": session.status,
                "pid": session.pid, "return_code": session.return_code}


def main():
    print("=" * 60)
    print("STREAM SESSION MANAGER v0.6 TEST")
    print("=" * 60)

    manager = StreamSessionManager()
    manager.load()

    print(f"\n[SESSION] Destinations loaded: {len(manager.destinations)}")

    destination_id = "youtube_01"
    destination = manager.destinations.get(destination_id, {})
    playlist = manager.playlists.get(destination_id, {})

    print(f"[SESSION] Target: {destination_id}")
    print(f"  Enabled: {destination.get('enabled', False)}")
    print(f"  Folder: {playlist.get('folder_name', 'NONE')}")
    print(f"  Videos: {len(playlist.get('videos', []))}")

    try:
        command = manager.build_command(destination_id)
        credential = manager.credential_manager.get(destination_id)
        safe = " ".join(command).replace(
            str(credential.get("stream_key", "")),
            "***STREAM_KEY***"
        )
        print("\n[SESSION] Command validation: OK")
        print(f"  {safe}")
    except Exception as exc:
        print(f"\n[SESSION] NOT READY: {exc}")

    print("\n[SESSION] Test mode: no real streaming started.")
    print("=" * 60)
    print("STREAM SESSION MANAGER v0.6 TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
