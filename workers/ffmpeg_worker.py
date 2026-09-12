"""
Professional Cloud Live Streaming Software
FFmpeg Worker
Version: 2.1.0 FINAL

Responsibilities:
    - Manage exactly one FFmpeg process.
    - Stream exactly one resolved video source.
    - Report normal EOF separately from unexpected failure.
    - Continuously consume FFmpeg stderr.
    - Collect FFmpeg progress and system metrics.
    - Gracefully stop and force-kill when necessary.
    - Never manage playlists.
    - Never construct credentials.
    - Never control another destination.

Architecture:

    Playlist/Supervisor
          |
          v
    FFmpegWorker
          |
          v
       FFmpeg
          |
          v
       RTMP/FLV
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, List, Optional

import psutil

from models import StreamMetrics, StreamStatus


# ============================================================
# CONFIGURATION
# ============================================================

@dataclass
class FFmpegConfig:
    """Configuration for one FFmpeg worker."""

    executable: str = "ffmpeg"

    startup_timeout: float = 15.0
    shutdown_timeout: float = 10.0

    reconnect_delay: float = 5.0

    loglevel: str = "warning"

    video_codec: str = "libx264"
    video_preset: str = "veryfast"
    pixel_format: str = "yuv420p"

    video_fps: int = 30
    video_bitrate: str = "4500k"

    audio_codec: str = "aac"
    audio_bitrate: str = "128k"
    audio_sample_rate: int = 48000

    extra_args: List[str] = field(default_factory=list)

    enable_progress: bool = True
    enable_system_metrics: bool = True

    # Safe diagnostic logging.
    enable_command_logging: bool = True


# ============================================================
# RESULT
# ============================================================

@dataclass
class FFmpegResult:
    """Result of a worker lifecycle operation."""

    return_code: Optional[int] = None
    started: bool = False
    stopped_by_user: bool = False
    normal_exit: bool = False
    unexpected_exit: bool = False
    error: Optional[str] = None
    runtime_seconds: float = 0.0


# ============================================================
# WORKER
# ============================================================

class FFmpegWorker:
    """
    Manages one independent FFmpeg process.

    One worker = one destination + one video.

    Playlist sequencing belongs to the supervisor/controller.
    """

    def __init__(
        self,
        worker_id: str,
        input_source: str,
        output_url: str,
        config: Optional[FFmpegConfig] = None,
        on_status: Optional[
            Callable[[str, StreamStatus], None]
        ] = None,
        on_log: Optional[
            Callable[[str, str], None]
        ] = None,
        on_exit: Optional[
            Callable[[str, FFmpegResult], None]
        ] = None,
    ) -> None:

        self.worker_id = worker_id
        self.input_source = input_source
        self.output_url = output_url
        self.config = config or FFmpegConfig()

        self.on_status = on_status
        self.on_log = on_log
        self.on_exit = on_exit

        self._process: Optional[subprocess.Popen] = None
        self._psutil_process: Optional[psutil.Process] = None

        self._monitor_thread: Optional[threading.Thread] = None
        self._stderr_thread: Optional[threading.Thread] = None

        self._stop_event = threading.Event()
        self._stderr_done = threading.Event()

        self._status = StreamStatus.CREATED

        self._started_at: Optional[float] = None
        self._stopped_by_user = False
        self._exit_handled = False

        self._last_return_code: Optional[int] = None

        self._lock = threading.RLock()

        self.metrics = StreamMetrics()

    # ========================================================
    # PROPERTIES
    # ========================================================

    @property
    def status(self) -> StreamStatus:
        with self._lock:
            return self._status

    @property
    def process_id(self) -> Optional[int]:
        with self._lock:
            if self._process is None:
                return None

            return self._process.pid

    @property
    def is_running(self) -> bool:
        with self._lock:
            process = self._process

            if process is None:
                return False

            return process.poll() is None

    @property
    def return_code(self) -> Optional[int]:
        with self._lock:
            return self._last_return_code

    @property
    def stopped_by_user(self) -> bool:
        with self._lock:
            return self._stopped_by_user

    # ========================================================
    # START
    # ========================================================

    def start(self) -> None:
        """
        Start one FFmpeg process.

        The source must be a concrete video file.
        """

        with self._lock:

            if self.is_running:
                raise RuntimeError(
                    f"FFmpeg worker '{self.worker_id}' "
                    "is already running."
                )

            self._cleanup_finished_process()

            source = os.path.abspath(
                os.path.expanduser(
                    self.input_source
                )
            )

            if not os.path.isfile(source):
                raise FileNotFoundError(
                    f"Input video not found: {source}"
                )

            if os.path.getsize(source) <= 0:
                raise ValueError(
                    f"Input video is empty: {source}"
                )

            self.input_source = source

            self._stop_event.clear()
            self._stderr_done.clear()

            self._stopped_by_user = False
            self._exit_handled = False
            self._started_at = None
            self._last_return_code = None

            self.metrics = StreamMetrics()
            self._psutil_process = None

            self._set_status(
                StreamStatus.STARTING
            )

            command = self.build_command()

            # ------------------------------------------------
            # SAFE COMMAND DIAGNOSTIC
            # ------------------------------------------------

            if self.config.enable_command_logging:

                self._emit_log(
                    "FFmpeg executable: "
                    + self._safe_executable(
                        self.config.executable
                    )
                )

                self._emit_log(
                    "FFmpeg input: "
                    + self.input_source
                )

                self._emit_log(
                    "FFmpeg output: "
                    + self._redact_output_url(
                        self.output_url
                    )
                )

                self._emit_log(
                    "FFmpeg command: "
                    + self._format_command_safe(
                        command
                    )
                )

            try:

                popen_kwargs = {
                    "stdout": subprocess.DEVNULL,
                    "stderr": subprocess.PIPE,
                    "stdin": subprocess.PIPE,
                    "text": True,
                    "bufsize": 1,
                    "universal_newlines": True,
                }

                if os.name == "nt":

                    popen_kwargs["creationflags"] = (
                        getattr(
                            subprocess,
                            "CREATE_NEW_PROCESS_GROUP",
                            0,
                        )
                    )

                else:

                    popen_kwargs[
                        "start_new_session"
                    ] = True

                self._process = subprocess.Popen(
                    command,
                    **popen_kwargs,
                )

            except FileNotFoundError as exc:

                self._process = None

                self._set_status(
                    StreamStatus.ERROR
                )

                raise RuntimeError(
                    "FFmpeg executable was not found. "
                    "Install FFmpeg or set the correct "
                    "FFmpeg executable path."
                ) from exc

            except Exception as exc:

                self._process = None

                self._set_status(
                    StreamStatus.ERROR
                )

                raise RuntimeError(
                    f"Unable to start FFmpeg: {exc}"
                ) from exc

            self._started_at = time.monotonic()

            self._initialize_system_metrics()

            process = self._process

            self._stderr_thread = threading.Thread(
                target=self._read_stderr,
                args=(process,),
                name=f"FFmpegLog-{self.worker_id}",
                daemon=True,
            )

            self._stderr_thread.start()

            if not self._wait_for_startup():

                return_code = process.poll()

                self._stopped_by_user = False
                self._stop_event.set()

                self._terminate_process()

                self._update_metrics()

                self._set_status(
                    StreamStatus.ERROR
                )

                raise RuntimeError(
                    "FFmpeg exited during startup"
                    + (
                        f" with code {return_code}."
                        if return_code is not None
                        else "."
                    )
                )

            self._update_metrics()

            self._set_status(
                StreamStatus.LIVE
            )

            self._monitor_thread = threading.Thread(
                target=self._monitor_process,
                name=f"FFmpegWorker-{self.worker_id}",
                daemon=True,
            )

            self._monitor_thread.start()

    # ========================================================
    # SAFE DIAGNOSTICS
    # ========================================================

    @staticmethod
    def _safe_executable(
        executable: str,
    ) -> str:

        if not executable:
            return "<EMPTY>"

        return str(executable)

    @staticmethod
    def _redact_output_url(
        output_url: str,
    ) -> str:

        if not output_url:
            return "<EMPTY>"

        text = str(output_url)

        if "/" not in text:
            return "<REDACTED>"

        base, _, secret = text.rpartition("/")

        if not secret:
            return text

        return (
            f"{base}/<STREAM_KEY>"
        )

    def _format_command_safe(
        self,
        command: List[str],
    ) -> str:

        safe = list(command)

        if safe:

            last = safe[-1]

            if isinstance(last, str):

                safe[-1] = (
                    self._redact_output_url(
                        last
                    )
                )

        return repr(safe)

    # ========================================================
    # STARTUP VALIDATION
    # ========================================================

    def _wait_for_startup(self) -> bool:

        process = self._process

        if process is None:
            return False

        timeout = max(
            0.0,
            float(
                self.config.startup_timeout
            ),
        )

        # IMPORTANT:
        # Use the actual configured startup timeout.
        # Previous implementation incorrectly capped this
        # to 0.50 seconds.
        deadline = (
            time.monotonic()
            + timeout
        )

        while time.monotonic() < deadline:

            if self._stop_event.is_set():
                return False

            return_code = process.poll()

            if return_code is not None:
                return False

            time.sleep(0.05)

        return process.poll() is None

    # ========================================================
    # SYSTEM METRICS
    # ========================================================

    def _initialize_system_metrics(self) -> None:

        if not self.config.enable_system_metrics:
            return

        process = self._process

        if process is None:
            return

        try:

            self._psutil_process = psutil.Process(
                process.pid
            )

            self._psutil_process.cpu_percent(
                interval=None
            )

        except (
            psutil.NoSuchProcess,
            psutil.AccessDenied,
            psutil.ZombieProcess,
        ):

            self._psutil_process = None

    def _update_system_metrics(self) -> None:

        process = self._psutil_process

        if process is None:
            return

        try:

            if not process.is_running():
                return

            cpu = process.cpu_percent(
                interval=None
            )

            memory = process.memory_percent()

            self.metrics.cpu_percent = max(
                0.0,
                float(cpu),
            )

            self.metrics.memory_percent = max(
                0.0,
                float(memory),
            )

        except (
            psutil.NoSuchProcess,
            psutil.AccessDenied,
            psutil.ZombieProcess,
        ):

            return

        except Exception as exc:

            self._emit_log(
                f"System metrics error: {exc}"
            )

    # ========================================================
    # STOP
    # ========================================================

    def stop(self) -> FFmpegResult:

        with self._lock:

            process = self._process

            if process is None:

                return FFmpegResult(
                    return_code=self._last_return_code,
                    started=False,
                    stopped_by_user=True,
                    normal_exit=False,
                    unexpected_exit=False,
                    runtime_seconds=0.0,
                )

            return_code = process.poll()

            if return_code is not None:

                self._stopped_by_user = True
                self._stop_event.set()

                self._update_metrics()
                self._join_threads()

                result = FFmpegResult(
                    return_code=return_code,
                    started=True,
                    stopped_by_user=True,
                    normal_exit=(
                        return_code == 0
                    ),
                    unexpected_exit=(
                        return_code != 0
                    ),
                    runtime_seconds=self._runtime(),
                )

                self._last_return_code = (
                    return_code
                )

                self._set_status(
                    StreamStatus.STOPPED
                )

                self._cleanup_finished_process()

                return result

            self._stopped_by_user = True
            self._stop_event.set()

            self._set_status(
                StreamStatus.STOPPING
            )

            error_message = None

            try:

                self._send_quit(process)

                try:

                    process.wait(
                        timeout=max(
                            0.0,
                            float(
                                self.config.shutdown_timeout
                            ),
                        )
                    )

                except subprocess.TimeoutExpired:

                    self._terminate_process()

            except Exception as exc:

                error_message = str(exc)

                self._terminate_process()

            return_code = process.poll()

            self._last_return_code = return_code

            self._update_metrics()
            self._join_threads()

            if return_code is None:

                error_message = (
                    error_message
                    or "FFmpeg process could not be stopped."
                )

                self._set_status(
                    StreamStatus.ERROR
                )

            else:

                self._set_status(
                    StreamStatus.STOPPED
                )

            result = FFmpegResult(
                return_code=return_code,
                started=True,
                stopped_by_user=True,
                normal_exit=(
                    return_code == 0
                ),
                unexpected_exit=(
                    return_code is not None
                    and return_code != 0
                ),
                error=error_message,
                runtime_seconds=self._runtime(),
            )

            self._cleanup_finished_process()

            return result

    # ========================================================
    # QUIT
    # ========================================================

    @staticmethod
    def _send_quit(
        process: subprocess.Popen,
    ) -> None:

        if process.stdin is None:
            return

        try:

            process.stdin.write("q\n")
            process.stdin.flush()

        except (
            BrokenPipeError,
            OSError,
            ValueError,
        ):

            pass

    # ========================================================
    # FORCE TERMINATION
    # ========================================================

    def _terminate_process(self) -> None:

        process = self._process

        if process is None:
            return

        if process.poll() is not None:
            return

        try:

            if os.name == "nt":

                try:

                    process.send_signal(
                        signal.CTRL_BREAK_EVENT
                    )

                except (
                    OSError,
                    ValueError,
                ):

                    process.terminate()

            else:

                process.terminate()

            try:

                process.wait(
                    timeout=3.0
                )

            except subprocess.TimeoutExpired:

                process.kill()

                try:

                    process.wait(
                        timeout=2.0
                    )

                except subprocess.TimeoutExpired:

                    pass

        except Exception:

            try:
                process.kill()
            except Exception:
                pass

    # ========================================================
    # RESTART SAME SOURCE
    # ========================================================

    def restart(self) -> FFmpegResult:

        result = self.stop()

        delay = max(
            0.0,
            float(
                self.config.reconnect_delay
            ),
        )

        if delay:
            time.sleep(delay)

        self.start()

        self.metrics.reconnect_count += 1
        self.metrics.last_update = datetime_now()

        return result

    # ========================================================
    # COMMAND BUILDER
    # ========================================================

    def build_command(self) -> List[str]:
        """
        Build one finite FFmpeg playback command.

        No -stream_loop is used.

        FFmpeg exits naturally at EOF.
        The supervisor selects the next playlist item.
        """

        command: List[str] = [
            self.config.executable,

            "-hide_banner",

            "-loglevel",
            self.config.loglevel,

            "-re",

            "-i",
            self.input_source,

            "-c:v",
            self.config.video_codec,

            "-preset",
            self.config.video_preset,

            "-pix_fmt",
            self.config.pixel_format,

            "-r",
            str(self.config.video_fps),

            "-b:v",
            self.config.video_bitrate,

            "-c:a",
            self.config.audio_codec,

            "-b:a",
            self.config.audio_bitrate,

            "-ar",
            str(
                self.config.audio_sample_rate
            ),

            "-f",
            "flv",
        ]

        if self.config.extra_args:

            command[1:1] = list(
                self.config.extra_args
            )

        if self.config.enable_progress:

            command[1:1] = [
                "-progress",
                "pipe:2",
                "-nostats",
            ]

        command.append(
            self.output_url
        )

        return command

    # ========================================================
    # DISPLAY COMMAND
    # ========================================================

    def command_for_display(self) -> List[str]:
        """
        Return command with output credential redacted.
        """

        command = self.build_command()

        if not command:
            return command

        display = list(command)

        display[-1] = (
            self._redact_output_url(
                display[-1]
            )
        )

        return display

    # ========================================================
    # PROCESS MONITOR
    # ========================================================

    def _monitor_process(self) -> None:

        process = self._process

        if process is None:
            return

        return_code = process.wait()

        self._last_return_code = (
            return_code
        )

        self._update_metrics()

        self._handle_process_exit(
            return_code
        )

    # ========================================================
    # STDERR READER
    # ========================================================

    def _read_stderr(
        self,
        process: subprocess.Popen,
    ) -> None:

        if process.stderr is None:

            self._stderr_done.set()
            return

        try:

            for raw_line in process.stderr:

                line = raw_line.strip()

                if not line:
                    continue

                if self._parse_progress_line(
                    line
                ):
                    continue

                self._emit_log(line)

        except Exception as exc:

            self._emit_log(
                f"FFmpeg log reader error: {exc}"
            )

        finally:

            self._stderr_done.set()

    # ========================================================
    # PROGRESS PARSER
    # ========================================================

    def _parse_progress_line(
        self,
        line: str,
    ) -> bool:

        if "=" not in line:
            return False

        key, value = line.split(
            "=",
            1,
        )

        key = key.strip().lower()
        value = value.strip()

        try:

            if key == "frame":

                self.metrics.video_frames = int(
                    float(value)
                )

                self._touch_metrics()

                return True

            if key == "fps":

                parsed = self._parse_float(
                    value
                )

                if parsed is not None:
                    self.metrics.fps = parsed

                self._touch_metrics()

                return True

            if key == "bitrate":

                parsed = self._parse_bitrate(
                    value
                )

                if parsed is not None:
                    self.metrics.bitrate_kbps = (
                        parsed
                    )

                self._touch_metrics()

                return True

            if key in {
                "drop",
                "drop_frames",
            }:

                self.metrics.dropped_frames = int(
                    float(value)
                )

                self._touch_metrics()

                return True

            if key in {
                "out_time",
                "out_time_us",
                "out_time_ms",
                "speed",
                "total_size",
                "dup_frames",
                "progress",
            }:

                self._touch_metrics()

                return True

        except (
            TypeError,
            ValueError,
        ):

            return True

        return False

    # ========================================================
    # VALUE PARSERS
    # ========================================================

    @staticmethod
    def _parse_float(
        value: str,
    ) -> Optional[float]:

        try:
            return float(value)

        except (
            TypeError,
            ValueError,
        ):

            return None

    @staticmethod
    def _parse_bitrate(
        value: str,
    ) -> Optional[float]:

        if not value:
            return None

        text = value.strip().lower()

        if text in {
            "n/a",
            "na",
            "unknown",
        }:
            return None

        match = re.match(
            r"^\s*"
            r"([0-9]+(?:\.[0-9]+)?)"
            r"\s*"
            r"([kmgt]?)"
            r"\s*"
            r"(?:b/s)?"
            r"\s*$",
            text,
        )

        if not match:
            return None

        number = float(
            match.group(1)
        )

        unit = match.group(2)

        multipliers = {
            "": 1.0,
            "k": 1.0,
            "m": 1000.0,
            "g": 1000000.0,
            "t": 1000000000.0,
        }

        return (
            number
            * multipliers.get(
                unit,
                1.0,
            )
        )

    # ========================================================
    # PROCESS EXIT
    # ========================================================

    def _handle_process_exit(
        self,
        return_code: int,
    ) -> None:

        with self._lock:

            if self._exit_handled:
                return

            self._exit_handled = True

            stopped_by_user = (
                self._stopped_by_user
            )

        self._update_metrics()

        if stopped_by_user:

            self._set_status(
                StreamStatus.STOPPED
            )

            result = FFmpegResult(
                return_code=return_code,
                started=True,
                stopped_by_user=True,
                normal_exit=False,
                unexpected_exit=False,
                runtime_seconds=self._runtime(),
            )

            self._emit_exit(result)
            return

        if return_code == 0:

            self._set_status(
                StreamStatus.STOPPED
            )

            result = FFmpegResult(
                return_code=0,
                started=True,
                stopped_by_user=False,
                normal_exit=True,
                unexpected_exit=False,
                runtime_seconds=self._runtime(),
            )

            self._emit_exit(result)
            return

        self._set_status(
            StreamStatus.ERROR
        )

        message = (
            "FFmpeg exited unexpectedly "
            f"with code {return_code}"
        )

        self._emit_log(message)

        result = FFmpegResult(
            return_code=return_code,
            started=True,
            stopped_by_user=False,
            normal_exit=False,
            unexpected_exit=True,
            error=message,
            runtime_seconds=self._runtime(),
        )

        self._emit_exit(result)

    # ========================================================
    # EXIT CALLBACK
    # ========================================================

    def _emit_exit(
        self,
        result: FFmpegResult,
    ) -> None:

        callback = self.on_exit

        if callback is None:
            return

        try:

            callback(
                self.worker_id,
                result,
            )

        except Exception as exc:

            self._emit_log(
                f"Exit callback error: {exc}"
            )

    # ========================================================
    # CLEANUP
    # ========================================================

    def _cleanup_finished_process(
        self,
    ) -> None:

        process = self._process

        if process is None:
            return

        if process.poll() is None:
            return

        try:

            if process.stdin:
                process.stdin.close()

        except Exception:
            pass

        try:

            if process.stderr:
                process.stderr.close()

        except Exception:
            pass

        self._process = None
        self._psutil_process = None

    # ========================================================
    # THREAD JOIN
    # ========================================================

    def _join_threads(self) -> None:

        current = threading.current_thread()

        monitor = self._monitor_thread

        if (
            monitor is not None
            and monitor is not current
            and monitor.is_alive()
        ):

            monitor.join(
                timeout=2.0
            )

        stderr_thread = (
            self._stderr_thread
        )

        if (
            stderr_thread is not None
            and stderr_thread is not current
            and stderr_thread.is_alive()
        ):

            stderr_thread.join(
                timeout=2.0
            )

    # ========================================================
    # STATUS
    # ========================================================

    def _set_status(
        self,
        status: StreamStatus,
    ) -> None:

        with self._lock:

            self._status = status

        callback = self.on_status

        if callback is None:
            return

        try:

            callback(
                self.worker_id,
                status,
            )

        except Exception:
            pass

    # ========================================================
    # LOG
    # ========================================================

    def _emit_log(
        self,
        message: str,
    ) -> None:

        callback = self.on_log

        if callback is None:
            return

        try:

            callback(
                self.worker_id,
                message,
            )

        except Exception:
            pass

    # ========================================================
    # METRICS
    # ========================================================

    def _update_metrics(self) -> None:

        if self._started_at is None:
            return

        self.metrics.uptime_seconds = (
            self._runtime()
        )

        if self.config.enable_system_metrics:
            self._update_system_metrics()

        self.metrics.last_update = (
            datetime_now()
        )

    def _touch_metrics(self) -> None:

        self.metrics.uptime_seconds = (
            self._runtime()
        )

        self.metrics.last_update = (
            datetime_now()
        )

    # ========================================================
    # RUNTIME
    # ========================================================

    def _runtime(self) -> float:

        if self._started_at is None:
            return 0.0

        return max(
            0.0,
            time.monotonic()
            - self._started_at,
        )


# ============================================================
# DATETIME
# ============================================================

def datetime_now() -> datetime:
    """Return current UTC datetime."""

    return datetime.now(
        timezone.utc
    )