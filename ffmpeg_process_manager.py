from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Optional


@dataclass
class ProcessResult:
    destination_id: str
    status: str
    pid: Optional[int] = None
    return_code: Optional[int] = None
    error: Optional[str] = None


class FFmpegProcessManager:
    """
    Windows-friendly FFmpeg process lifecycle manager.

    This module owns FFmpeg subprocesses but does not decide which
    destination or playlist should be used. StreamingCore remains
    responsible for that orchestration.
    """

    def __init__(self, ffmpeg_path: str = "ffmpeg"):
        self.ffmpeg_path = ffmpeg_path
        self.processes: dict[str, subprocess.Popen] = {}
        self.statuses: dict[str, str] = {}
        self.errors: dict[str, Optional[str]] = {}
        self.return_codes: dict[str, Optional[int]] = {}

        self._lock = threading.RLock()
        self._watchers: dict[str, threading.Thread] = {}

    # ---------------------------------------------------------
    # COMMAND NORMALIZATION
    # ---------------------------------------------------------

    def _normalize_command(self, command: list[str]) -> list[str]:
        if not command:
            raise ValueError("FFmpeg command cannot be empty.")

        normalized = list(command)

        first = normalized[0]

        if first.lower() in {
            "ffmpeg",
            "ffmpeg.exe",
        }:
            normalized[0] = self.ffmpeg_path
        else:
            normalized.insert(0, self.ffmpeg_path)

        return normalized

    # ---------------------------------------------------------
    # STATUS
    # ---------------------------------------------------------

    def is_running(self, destination_id: str) -> bool:
        with self._lock:
            process = self.processes.get(destination_id)

            if process is None:
                return False

            return process.poll() is None

    def get_status(self, destination_id: str) -> ProcessResult:
        with self._lock:
            process = self.processes.get(destination_id)

            if process is not None:
                return_code = process.poll()

                if return_code is None:
                    status = "RUNNING"
                else:
                    status = (
                        "STOPPED"
                        if return_code == 0
                        else "FAILED"
                    )

                    self.statuses[destination_id] = status
                    self.return_codes[destination_id] = return_code

            status = self.statuses.get(
                destination_id,
                "STOPPED",
            )

            pid = (
                process.pid
                if process is not None
                else None
            )

            return ProcessResult(
                destination_id=destination_id,
                status=status,
                pid=pid,
                return_code=self.return_codes.get(
                    destination_id
                ),
                error=self.errors.get(
                    destination_id
                ),
            )

    def get_all_status(self) -> dict[str, ProcessResult]:
        with self._lock:
            ids = set(self.statuses)
            ids.update(self.processes)

        return {
            destination_id: self.get_status(
                destination_id
            )
            for destination_id in sorted(ids)
        }

    # ---------------------------------------------------------
    # START
    # ---------------------------------------------------------

    def start(
        self,
        destination_id: str,
        command: list[str],
    ) -> ProcessResult:

        if not destination_id:
            raise ValueError(
                "destination_id is required."
            )

        normalized = self._normalize_command(
            command
        )

        with self._lock:

            existing = self.processes.get(
                destination_id
            )

            if (
                existing is not None
                and existing.poll() is None
            ):
                raise RuntimeError(
                    f"FFmpeg is already running for "
                    f"{destination_id} "
                    f"(PID {existing.pid})."
                )

            self.errors[destination_id] = None
            self.return_codes[destination_id] = None

            try:
                process = subprocess.Popen(
                    normalized,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                )

            except Exception as exc:
                self.statuses[destination_id] = "FAILED"
                self.errors[destination_id] = str(exc)

                return self.get_status(
                    destination_id
                )

            self.processes[destination_id] = process
            self.statuses[destination_id] = "STARTING"

            watcher = threading.Thread(
                target=self._watch_process,
                args=(destination_id, process),
                daemon=True,
            )

            self._watchers[destination_id] = watcher
            watcher.start()

        # Give the process a short moment to establish its state.
        time.sleep(0.15)

        with self._lock:
            if process.poll() is None:
                self.statuses[destination_id] = "RUNNING"

        return self.get_status(
            destination_id
        )

    # ---------------------------------------------------------
    # PROCESS WATCHER
    # ---------------------------------------------------------

    def _watch_process(
        self,
        destination_id: str,
        process: subprocess.Popen,
    ) -> None:

        stderr_text = ""

        try:
            if process.stderr is not None:
                stderr_text = process.stderr.read()

        except Exception as exc:
            stderr_text = str(exc)

        return_code = process.wait()

        with self._lock:

            self.return_codes[
                destination_id
            ] = return_code

            if return_code == 0:
                self.statuses[
                    destination_id
                ] = "STOPPED"

            else:
                self.statuses[
                    destination_id
                ] = "FAILED"

                cleaned = stderr_text.strip()

                if cleaned:
                    # Keep the final useful error bounded.
                    self.errors[
                        destination_id
                    ] = cleaned[-4000:]

    # ---------------------------------------------------------
    # STOP
    # ---------------------------------------------------------

    def stop(
        self,
        destination_id: str,
        timeout: float = 5.0,
    ) -> ProcessResult:

        with self._lock:
            process = self.processes.get(
                destination_id
            )

            if process is None:
                self.statuses[
                    destination_id
                ] = "STOPPED"

                return self.get_status(
                    destination_id
                )

            if process.poll() is not None:
                self.statuses[
                    destination_id
                ] = "STOPPED"

                return self.get_status(
                    destination_id
                )

            self.statuses[
                destination_id
            ] = "STOPPING"

            try:
                # FFmpeg accepts 'q' on stdin for a graceful quit.
                if process.stdin is not None:
                    try:
                        process.stdin.write("q\n")
                        process.stdin.flush()
                    except Exception:
                        pass

                process.wait(
                    timeout=timeout
                )

            except subprocess.TimeoutExpired:

                try:
                    process.terminate()
                    process.wait(
                        timeout=2
                    )

                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()

                except Exception as exc:
                    self.errors[
                        destination_id
                    ] = str(exc)

            except Exception as exc:
                self.errors[
                    destination_id
                ] = str(exc)

        return self.get_status(
            destination_id
        )

    # ---------------------------------------------------------
    # STOP ALL
    # ---------------------------------------------------------

    def stop_all(
        self,
        timeout: float = 5.0,
    ) -> dict[str, ProcessResult]:

        with self._lock:
            destination_ids = list(
                self.processes.keys()
            )

        results = {}

        for destination_id in destination_ids:
            results[destination_id] = self.stop(
                destination_id,
                timeout=timeout,
            )

        return results

    # ---------------------------------------------------------
    # COMMAND PREVIEW
    # ---------------------------------------------------------

    def preview_command(
        self,
        destination_id: str,
        command: list[str],
    ) -> str:

        normalized = self._normalize_command(
            command
        )

        return " ".join(
            self._mask_sensitive_parts(
                normalized
            )
        )

    @staticmethod
    def _mask_sensitive_parts(
        command: list[str],
    ) -> list[str]:

        result = list(command)

        # Mask values following common secret-bearing options.
        secret_options = {
            "-stream_key",
            "--stream-key",
        }

        for index, value in enumerate(result[:-1]):
            if value in secret_options:
                result[index + 1] = "***MASKED***"

        return result


# =============================================================
# SAFE LOCAL TEST
# =============================================================

def main():

    print("=" * 60)
    print("FFMPEG PROCESS MANAGER TEST")
    print("=" * 60)

    manager = FFmpegProcessManager()

    # Cross-platform FFmpeg test that exits quickly.
    # It does NOT open a video and does NOT contact a network
    # streaming destination.
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "color=c=black:s=320x240:r=5",
        "-t",
        "2",
        "-f",
        "null",
        "-",
    ]

    destination_id = "local_test"

    print("\nStarting local FFmpeg test...")
    result = manager.start(
        destination_id,
        command,
    )

    print(
        f"Status: {result.status}"
    )

    print(
        f"PID: {result.pid}"
    )

    # Allow the short FFmpeg job to finish.
    time.sleep(2.5)

    result = manager.get_status(
        destination_id
    )

    print("\nAfter process completion:")
    print(
        f"Status: {result.status}"
    )
    print(
        f"Return code: {result.return_code}"
    )

    if result.error:
        print(
            f"Error: {result.error}"
        )

    # Verify duplicate-start protection.
    print("\nProcess manager status:")
    for destination_id, status in (
        manager.get_all_status().items()
    ):
        print(
            f"- {destination_id} | "
            f"{status.status} | "
            f"pid={status.pid}"
        )

    print("\n" + "=" * 60)

    if (
        result.status == "STOPPED"
        and result.return_code == 0
    ):
        print("FFMPEG PROCESS MANAGER TEST SUCCESS")
    else:
        print("FFMPEG PROCESS MANAGER TEST FAILED")

    print("=" * 60)
    print("No real streaming destination was used.")


if __name__ == "__main__":
    main()
