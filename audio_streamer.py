
"""
Golden Studio Streaming Engine
Audio Streamer
Version: 1.0.0 Professional

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

Supported:
    AAC
    MP3
    FLAC
    WAV
    Opus
    Other formats supported by TorchCodec/FFmpeg

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
    - Underrun protection
    - Stereo / Mono
    - C-contiguous PCM
"""

from __future__ import annotations

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
    """
    Professional audio streaming engine.

    Example:

        streamer = AudioStreamer("music.aac")

        streamer.play()

        time.sleep(5)

        streamer.pause()

        time.sleep(2)

        streamer.resume()

        streamer.set_volume(0.5)

        time.sleep(5)

        streamer.stop()
    """

    VERSION = "1.0.0"

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

        self._volume = 1.0
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
            return self._position_samples / self.sample_rate

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
            return self._state == PlaybackState.FINISHED

    # ========================================================
    # INTERNAL STREAM CREATION
    # ========================================================

    def _create_stream(self) -> None:
        """
        Create and start sounddevice output stream.
        """

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
        """
        Safely close output stream.
        """

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
        """
        Apply volume and mute state.
        """

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
        """
        Background playback worker.
        """

        try:
            self._create_stream()

            while not self._stop_event.is_set():

                # ------------------------------------------------
                # Pause
                # ------------------------------------------------

                if self._pause_event.is_set():

                    time.sleep(0.01)

                    continue

                # ------------------------------------------------
                # End of file
                # ------------------------------------------------

                with self._lock:

                    start = self._position_samples

                    if start >= self.total_samples:

                        self._state = PlaybackState.FINISHED

                        break

                    end = min(
                        start + self.chunk_samples,
                        self.total_samples,
                    )

                    chunk = self.pcm[start:end].copy()

                    self._position_samples = end

                # ------------------------------------------------
                # Volume
                # ------------------------------------------------

                chunk = self._apply_volume(chunk)

                # ------------------------------------------------
                # Ensure contiguous memory
                # ------------------------------------------------

                chunk = np.ascontiguousarray(
                    chunk,
                    dtype=np.float32,
                )

                # ------------------------------------------------
                # Output
                # ------------------------------------------------

                stream = self._stream

                if stream is None:
                    break

                stream.write(chunk)

        except Exception:

            with self._lock:
                self._state = PlaybackState.STOPPED

            raise

        finally:

            self._close_stream()

            with self._lock:

                if (
                    self._state == PlaybackState.PLAYING
                    and self._position_samples
                    >= self.total_samples
                ):
                    self._state = PlaybackState.FINISHED

    # ========================================================
    # PLAY
    # ========================================================

    def play(self) -> None:
        """
        Start playback.

        If paused:
            resumes playback.

        If finished:
            starts again from beginning.
        """

        with self._lock:

            if self._closed:
                raise RuntimeError(
                    "AudioStreamer is closed"
                )

            if self._state == PlaybackState.PLAYING:
                return

            if self._state == PlaybackState.FINISHED:
                self._position_samples = 0

            self._stop_event.clear()

            self._pause_event.clear()

            self._state = PlaybackState.PLAYING

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
        """
        Pause playback.
        """

        with self._lock:

            if self._state != PlaybackState.PLAYING:
                return

            self._pause_event.set()

            self._state = PlaybackState.PAUSED

    # ========================================================
    # RESUME
    # ========================================================

    def resume(self) -> None:
        """
        Resume paused playback.
        """

        with self._lock:

            if self._closed:
                raise RuntimeError(
                    "AudioStreamer is closed"
                )

            if self._state != PlaybackState.PAUSED:
                return

            self._pause_event.clear()

            self._state = PlaybackState.PLAYING

    # ========================================================
    # STOP
    # ========================================================

    def stop(self) -> None:
        """
        Stop playback and reset position.
        """

        with self._lock:

            self._stop_event.set()

            self._pause_event.clear()

            worker = self._worker

        if worker is not None:
            worker.join(timeout=2.0)

        with self._lock:

            self._worker = None

            self._position_samples = 0

            self._state = PlaybackState.STOPPED

        self._close_stream()

    # ========================================================
    # SEEK
    # ========================================================

    def seek(self, seconds: float) -> float:
        """
        Seek to a specific position.

        Returns actual position.
        """

        if seconds < 0:
            seconds = 0.0

        if seconds > self.duration:
            seconds = self.duration

        sample_position = int(
            seconds * self.sample_rate
        )

        with self._lock:

            self._position_samples = sample_position

            if (
                self._state == PlaybackState.FINISHED
                and sample_position < self.total_samples
            ):
                self._state = PlaybackState.STOPPED

        return self.position

    # ========================================================
    # SET VOLUME
    # ========================================================

    def set_volume(self, volume: float) -> float:
        """
        Set volume from 0.0 to 1.0.
        """

        volume = float(volume)

        volume = max(
            0.0,
            min(1.0, volume),
        )

        with self._lock:
            self._volume = volume

        return volume

    # ========================================================
    # VOLUME UP
    # ========================================================

    def volume_up(
        self,
        amount: float = 0.05,
    ) -> float:

        return self.set_volume(
            self.volume + amount
        )

    # ========================================================
    # VOLUME DOWN
    # ========================================================

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

    # ========================================================
    # UNMUTE
    # ========================================================

    def unmute(self) -> None:

        with self._lock:
            self._muted = False

    # ========================================================
    # TOGGLE MUTE
    # ========================================================

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
        """
        Wait until playback finishes.

        Returns:
            True  = finished
            False = timeout
        """

        start = time.monotonic()

        while True:

            state = self.state

            if state == PlaybackState.FINISHED:
                return True

            if state == PlaybackState.STOPPED:
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
        """
        Permanently close streamer.
        """

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
# SIMPLE TEST
# ============================================================

if __name__ == "__main__":

    TEST_FILE = Path(
        r"D:\streaming_engine\mamun voice.aac"
    )

    print()
    print("=" * 60)
    print("GOLDEN STREAMING ENGINE")
    print("AudioStreamer 1.0.0")
    print("=" * 60)

    try:

        streamer = AudioStreamer(
            TEST_FILE,
            chunk_ms=100,
        )

        print()
        print("File       :", streamer.audio_path)
        print("Sample Rate:", streamer.sample_rate)
        print("Channels   :", streamer.channels)
        print("Chunk      :", streamer.chunk_samples, "samples")
        print("Duration   :", streamer.duration)
        print("Volume     :", streamer.volume)
        print("State      :", streamer.state.value)

        print()
        print("Starting playback...")

        streamer.play()

        time.sleep(3)

        print(
            "Position:",
            round(streamer.position, 3),
            "seconds",
        )

        print("Pausing...")

        streamer.pause()

        time.sleep(2)

        print(
            "Position while paused:",
            round(streamer.position, 3),
            "seconds",
        )

        print("Resuming...")

        streamer.resume()

        time.sleep(2)

        print(
            "Position:",
            round(streamer.position, 3),
            "seconds",
        )

        print("Setting volume to 50%...")

        streamer.set_volume(0.5)

        print("Volume:", streamer.volume)

        print("Seeking to 10 seconds...")

        actual = streamer.seek(10.0)

        print(
            "Actual position:",
            round(actual, 3),
            "seconds",
        )

        print("Waiting for playback...")

        streamer.wait_until_finished()

        print()
        print("Final state:", streamer.state.value)

        streamer.close()

        print()
        print("=" * 60)
        print("AUDIO STREAMER TEST COMPLETE")
        print("=" * 60)

    except Exception as exc:

        print()
        print("=" * 60)
        print("AUDIO STREAMER ERROR")
        print("=" * 60)
        print(type(exc).__name__, ":", exc)
        print("=" * 60)

