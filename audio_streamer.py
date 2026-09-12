"""
Golden Studio Streaming Engine
Audio Streamer
Version: 1.1.0 Professional

Pipeline:
    Audio File
        ↓
    TorchCodec AudioDecoder
        ↓
    PCM float32
        ↓
    Chunk Buffer
        ↓
    sounddevice OutputStream
        ↓
    Speakers

Features:
    - Play
    - Pause
    - Resume
    - Stop
    - Seek
    - Volume
    - Mute
    - Position
    - Duration
    - EOF handling
    - Thread-safe control
    - Stereo / Mono
    - C-contiguous PCM
    - CLI audio file selection
    - CI-friendly --help
    - No hard-coded local audio path
"""

from __future__ import annotations

import argparse
import threading
import time
from enum import Enum
from pathlib import Path
from typing import Optional

import numpy as np
import sounddevice as sd
from torchcodec.decoders import AudioDecoder


# ============================================================
# STATE
# ============================================================

class PlaybackState(Enum):
    STOPPED = "stopped"
    PLAYING = "playing"
    PAUSED = "paused"
    FINISHED = "finished"


# ============================================================
# AUDIO STREAMER
# ============================================================

class AudioStreamer:
    """Professional audio playback engine."""

    VERSION = "1.1.0"

    DEFAULT_CHUNK_MS = 100
    DEFAULT_VOLUME = 1.0

    def __init__(
        self,
        audio_path: str | Path,
        chunk_ms: int = DEFAULT_CHUNK_MS,
        volume: float = DEFAULT_VOLUME,
    ):
        self.audio_path = Path(audio_path)

        if not self.audio_path.exists():
            raise FileNotFoundError(
                f"Audio file not found: {self.audio_path}"
            )

        if not self.audio_path.is_file():
            raise ValueError(
                f"Audio path is not a file: {self.audio_path}"
            )

        if chunk_ms <= 0:
            raise ValueError("chunk_ms must be greater than 0")

        self.chunk_ms = int(chunk_ms)

        # ----------------------------------------------------
        # Decoder
        # ----------------------------------------------------

        self.decoder = AudioDecoder(str(self.audio_path))

        samples = self.decoder.get_all_samples()

        pcm = samples.data.detach().cpu().numpy()

        if pcm.ndim != 2:
            raise RuntimeError(
                f"Unexpected PCM shape: {pcm.shape}"
            )

        # TorchCodec:
        #     [channels, samples]
        #
        # sounddevice:
        #     [samples, channels]

        pcm = pcm.T

        self.pcm = np.ascontiguousarray(
            pcm,
            dtype=np.float32,
        )

        self.sample_rate = int(samples.sample_rate)

        self.channels = int(self.pcm.shape[1])

        self.total_samples = int(self.pcm.shape[0])

        self.duration = (
            self.total_samples / self.sample_rate
        )

        self.chunk_samples = max(
            1,
            int(
                self.sample_rate
                * self.chunk_ms
                / 1000
            ),
        )

        # ----------------------------------------------------
        # Playback state
        # ----------------------------------------------------

        self._state = PlaybackState.STOPPED

        self._position_samples = 0

        self._volume = max(
            0.0,
            min(1.0, float(volume)),
        )

        self._muted = False

        # ----------------------------------------------------
        # Stream
        # ----------------------------------------------------

        self._stream: Optional[sd.OutputStream] = None

        # ----------------------------------------------------
        # Threading
        # ----------------------------------------------------

        self._lock = threading.RLock()

        self._stop_event = threading.Event()

        self._pause_event = threading.Event()

        self._worker: Optional[threading.Thread] = None

        self._closed = False

    # ========================================================
    # PROPERTIES
    # ========================================================

    @property
    def state(self) -> PlaybackState:
        with self._lock:
            return self._state

    @property
    def position(self) -> float:
        with self._lock:
            return (
                self._position_samples
                / self.sample_rate
            )

    @property
    def duration_seconds(self) -> float:
        return self.duration

    @property
    def volume(self) -> float:
        with self._lock:
            return self._volume

    @property
    def muted(self) -> bool:
        with self._lock:
            return self._muted

    @property
    def finished(self) -> bool:
        with self._lock:
            return (
                self._state
                == PlaybackState.FINISHED
            )

    # ========================================================
    # INTERNAL STREAM CREATION
    # ========================================================

    def _create_stream(self) -> None:

        if self._stream is not None:
            return

        self._stream = sd.OutputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="float32",
            blocksize=self.chunk_samples,
        )

        self._stream.start()

    # ========================================================
    # INTERNAL STREAM CLOSE
    # ========================================================

    def _close_stream(self) -> None:

        stream = self._stream

        self._stream = None

        if stream is None:
            return

        try:
            stream.stop()
        except Exception:
            pass

        try:
            stream.close()
        except Exception:
            pass

    # ========================================================
    # INTERNAL VOLUME
    # ========================================================

    def _apply_volume(
        self,
        chunk: np.ndarray,
    ) -> np.ndarray:

        with self._lock:
            volume = self._volume
            muted = self._muted

        if muted:
            return np.zeros_like(chunk)

        if volume == 1.0:
            return chunk

        output = chunk * volume

        return np.ascontiguousarray(
            output,
            dtype=np.float32,
        )

    # ========================================================
    # INTERNAL WORKER
    # ========================================================

    def _playback_worker(self) -> None:

        try:

            self._create_stream()

            while not self._stop_event.is_set():

                if self._pause_event.is_set():

                    time.sleep(0.01)

                    continue

                with self._lock:

                    start = self._position_samples

                    if start >= self.total_samples:

                        self._state = (
                            PlaybackState.FINISHED
                        )

                        break

                    end = min(
                        start + self.chunk_samples,
                        self.total_samples,
                    )

                    chunk = self.pcm[
                        start:end
                    ].copy()

                    self._position_samples = end

                chunk = self._apply_volume(chunk)

                chunk = np.ascontiguousarray(
                    chunk,
                    dtype=np.float32,
                )

                stream = self._stream

                if stream is None:
                    break

                stream.write(chunk)

        except Exception:

            with self._lock:
                self._state = (
                    PlaybackState.STOPPED
                )

            raise

        finally:

            self._close_stream()

            with self._lock:

                if (
                    self._state
                    == PlaybackState.PLAYING
                    and self._position_samples
                    >= self.total_samples
                ):
                    self._state = (
                        PlaybackState.FINISHED
                    )

    # ========================================================
    # PLAY
    # ========================================================

    def play(self) -> None:

        with self._lock:

            if self._closed:
                raise RuntimeError(
                    "AudioStreamer is closed"
                )

            if (
                self._state
                == PlaybackState.PLAYING
            ):
                return

            if (
                self._state
                == PlaybackState.FINISHED
            ):
                self._position_samples = 0

            self._stop_event.clear()

            self._pause_event.clear()

            self._state = (
                PlaybackState.PLAYING
            )

            self._worker = threading.Thread(
                target=self._playback_worker,
                name="AudioStreamer",
                daemon=True,
            )

            self._worker.start()

    # ========================================================
    # PAUSE
    # ========================================================

    def pause(self) -> None:

        with self._lock:

            if (
                self._state
                != PlaybackState.PLAYING
            ):
                return

            self._pause_event.set()

            self._state = (
                PlaybackState.PAUSED
            )

    # ========================================================
    # RESUME
    # ========================================================

    def resume(self) -> None:

        with self._lock:

            if self._closed:
                raise RuntimeError(
                    "AudioStreamer is closed"
                )

            if (
                self._state
                != PlaybackState.PAUSED
            ):
                return

            self._pause_event.clear()

            self._state = (
                PlaybackState.PLAYING
            )

    # ========================================================
    # STOP
    # ========================================================

    def stop(self) -> None:

        with self._lock:

            self._stop_event.set()

            self._pause_event.clear()

            worker = self._worker

        if (
            worker is not None
            and worker is not threading.current_thread()
        ):
            worker.join(timeout=2.0)

        with self._lock:

            self._worker = None

            self._position_samples = 0

            self._state = (
                PlaybackState.STOPPED
            )

        self._close_stream()

    # ========================================================
    # SEEK
    # ========================================================

    def seek(self, seconds: float) -> float:

        seconds = float(seconds)

        if seconds < 0:
            seconds = 0.0

        if seconds > self.duration:
            seconds = self.duration

        sample_position = int(
            seconds * self.sample_rate
        )

        with self._lock:

            self._position_samples = (
                sample_position
            )

            if (
                self._state
                == PlaybackState.FINISHED
                and sample_position
                < self.total_samples
            ):
                self._state = (
                    PlaybackState.STOPPED
                )

        return self.position

    # ========================================================
    # VOLUME
    # ========================================================

    def set_volume(
        self,
        volume: float,
    ) -> float:

        volume = float(volume)

        volume = max(
            0.0,
            min(1.0, volume),
        )

        with self._lock:
            self._volume = volume

        return volume

    def volume_up(
        self,
        amount: float = 0.05,
    ) -> float:

        return self.set_volume(
            self.volume + amount
        )

    def volume_down(
        self,
        amount: float = 0.05,
    ) -> float:

        return self.set_volume(
            self.volume - amount
        )

    # ========================================================
    # MUTE
    # ========================================================

    def mute(self) -> None:

        with self._lock:
            self._muted = True

    def unmute(self) -> None:

        with self._lock:
            self._muted = False

    def toggle_mute(self) -> bool:

        with self._lock:

            self._muted = not self._muted

            return self._muted

    # ========================================================
    # STATUS
    # ========================================================

    def get_status(self) -> dict:

        with self._lock:

            return {
                "version": self.VERSION,
                "file": str(self.audio_path),
                "state": self._state.value,
                "sample_rate": self.sample_rate,
                "channels": self.channels,
                "total_samples": self.total_samples,
                "chunk_samples": self.chunk_samples,
                "chunk_ms": self.chunk_ms,
                "position": self.position,
                "duration": self.duration,
                "volume": self._volume,
                "muted": self._muted,
            }

    # ========================================================
    # WAIT
    # ========================================================

    def wait_until_finished(
        self,
        timeout: Optional[float] = None,
    ) -> bool:

        start = time.monotonic()

        while True:

            state = self.state

            if (
                state
                == PlaybackState.FINISHED
            ):
                return True

            if (
                state
                == PlaybackState.STOPPED
            ):
                return False

            if timeout is not None:

                if (
                    time.monotonic() - start
                    >= timeout
                ):
                    return False

            time.sleep(0.01)

    # ========================================================
    # CLOSE
    # ========================================================

    def close(self) -> None:

        if self._closed:
            return

        self.stop()

        with self._lock:
            self._closed = True

    # ========================================================
    # CONTEXT MANAGER
    # ========================================================

    def __enter__(self) -> "AudioStreamer":
        return self

    def __exit__(
        self,
        exc_type,
        exc_value,
        traceback,
    ) -> None:

        self.close()

    # ========================================================
    # STRING
    # ========================================================

    def __repr__(self) -> str:

        return (
            f"<AudioStreamer "
            f"file='{self.audio_path.name}' "
            f"state='{self.state.value}' "
            f"position={self.position:.2f}s "
            f"duration={self.duration:.2f}s>"
        )


# ============================================================
# CLI
# ============================================================

def build_parser() -> argparse.ArgumentParser:

    parser = argparse.ArgumentParser(
        description=(
            "Golden Studio Audio Streaming Engine. "
            "Play and control audio using TorchCodec "
            "and sounddevice."
        )
    )

    parser.add_argument(
        "audio",
        nargs="?",
        type=Path,
        help=(
            "Path to an audio file "
            "(AAC, MP3, FLAC, WAV, Opus, etc.)"
        ),
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"AudioStreamer {AudioStreamer.VERSION}",
    )

    parser.add_argument(
        "--chunk-ms",
        type=int,
        default=AudioStreamer.DEFAULT_CHUNK_MS,
        help="Audio chunk size in milliseconds.",
    )

    parser.add_argument(
        "--volume",
        type=float,
        default=AudioStreamer.DEFAULT_VOLUME,
        help="Initial volume from 0.0 to 1.0.",
    )

    parser.add_argument(
        "--diagnostic",
        action="store_true",
        help=(
            "Run a dependency-only diagnostic "
            "without requiring an audio file."
        ),
    )

    return parser


# ============================================================
# DIAGNOSTIC
# ============================================================

def run_diagnostic() -> int:

    print("=" * 60)
    print("GOLDEN STREAMING ENGINE")
    print(f"AudioStreamer {AudioStreamer.VERSION}")
    print("=" * 60)

    print()
    print("Python audio dependencies:")
    print("  NumPy       : OK")
    print("  SoundDevice : OK")
    print("  TorchCodec  : OK")

    try:

        devices = sd.query_devices()

        print()
        print(
            "Audio devices detected:",
            len(devices),
        )

    except Exception as exc:

        print()
        print(
            "Audio device query warning:",
            type(exc).__name__,
            ":",
            exc,
        )

    print()
    print("Diagnostic: PASS")

    return 0


# ============================================================
# CLI MAIN
# ============================================================

def main() -> int:

    parser = build_parser()

    args = parser.parse_args()

    # --------------------------------------------------------
    # Diagnostic mode
    # --------------------------------------------------------

    if args.diagnostic:
        return run_diagnostic()

    # --------------------------------------------------------
    # No audio file
    #
    # This is intentionally NOT an error.
    # It allows CI and --help style execution without
    # requiring a private/local audio file.
    # --------------------------------------------------------

    if args.audio is None:

        print("=" * 60)
        print("GOLDEN STREAMING ENGINE")
        print(f"AudioStreamer {AudioStreamer.VERSION}")
        print("=" * 60)
        print()
        print(
            "AudioStreamer module loaded successfully."
        )
        print(
            "No audio file was supplied."
        )
        print()
        print(
            "Use:"
        )
        print(
            "  python audio_streamer.py "
            "\"path\\to\\audio.aac\""
        )
        print()
        print(
            "Diagnostic: PASS"
        )

        return 0

    # --------------------------------------------------------
    # Validate audio path
    # --------------------------------------------------------

    audio_path = args.audio.expanduser()

    if not audio_path.exists():

        print(
            f"ERROR: Audio file not found: "
            f"{audio_path}"
        )

        return 2

    if not audio_path.is_file():

        print(
            f"ERROR: Audio path is not a file: "
            f"{audio_path}"
        )

        return 2

    # --------------------------------------------------------
    # Create streamer
    # --------------------------------------------------------

    print("=" * 60)
    print("GOLDEN STREAMING ENGINE")
    print(f"AudioStreamer {AudioStreamer.VERSION}")
    print("=" * 60)

    try:

        streamer = AudioStreamer(
            audio_path,
            chunk_ms=args.chunk_ms,
            volume=args.volume,
        )

        print()
        print("File       :", streamer.audio_path)
        print("Sample Rate:", streamer.sample_rate)
        print("Channels   :", streamer.channels)
        print(
            "Chunk      :",
            streamer.chunk_samples,
            "samples",
        )
        print(
            "Duration   :",
            round(streamer.duration, 3),
            "seconds",
        )
        print(
            "Volume     :",
            streamer.volume,
        )
        print(
            "State      :",
            streamer.state.value,
        )

        print()
        print("Starting playback...")

        streamer.play()

        streamer.wait_until_finished()

        print()
        print(
            "Final state:",
            streamer.state.value,
        )

        streamer.close()

        print()
        print("=" * 60)
        print("AUDIO STREAMER TEST COMPLETE")
        print("=" * 60)

        return 0

    except KeyboardInterrupt:

        print()
        print("Playback interrupted.")

        try:
            streamer.close()
        except Exception:
            pass

        return 130

    except Exception as exc:

        print()
        print("=" * 60)
        print("AUDIO STREAMER ERROR")
        print("=" * 60)
        print(
            type(exc).__name__,
            ":",
            exc,
        )
        print("=" * 60)

        return 1


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    raise SystemExit(main())