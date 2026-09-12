from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional


# ============================================================
# METRICS MANAGER
# ============================================================


@dataclass
class DestinationMetrics:
    destination_id: str

    started: int = 0
    stopped: int = 0
    failures: int = 0
    restarts: int = 0

    frames: int = 0
    dropped_frames: int = 0

    bytes_sent: int = 0

    last_error: Optional[str] = None

    started_at: Optional[float] = None
    stopped_at: Optional[float] = None

    metadata: dict = field(
        default_factory=dict
    )


class MetricsManager:
    """
    Central runtime metrics manager.

    Tracks streaming statistics per destination.

    Safety:
    - Does not start FFmpeg.
    - Does not connect to RTMP.
    - Does not access stream keys.
    - Does not modify credentials.
    - Does not modify playlists.
    - Does not modify Google Drive files.
    """

    def __init__(self):
        self.metrics: dict[
            str,
            DestinationMetrics,
        ] = {}

    # ---------------------------------------------------------
    # REGISTER
    # ---------------------------------------------------------

    def register(
        self,
        destination_id: str,
    ) -> DestinationMetrics:

        if not destination_id:
            raise ValueError(
                "destination_id is required."
            )

        if destination_id not in self.metrics:
            self.metrics[destination_id] = (
                DestinationMetrics(
                    destination_id=destination_id
                )
            )

        return self.metrics[destination_id]

    # ---------------------------------------------------------
    # START
    # ---------------------------------------------------------

    def record_start(
        self,
        destination_id: str,
    ) -> DestinationMetrics:

        metric = self.register(
            destination_id
        )

        metric.started += 1
        metric.started_at = time.time()
        metric.stopped_at = None

        return metric

    # ---------------------------------------------------------
    # STOP
    # ---------------------------------------------------------

    def record_stop(
        self,
        destination_id: str,
    ) -> DestinationMetrics:

        metric = self.register(
            destination_id
        )

        metric.stopped += 1
        metric.stopped_at = time.time()

        return metric

    # ---------------------------------------------------------
    # FAILURE
    # ---------------------------------------------------------

    def record_failure(
        self,
        destination_id: str,
        error: str,
    ) -> DestinationMetrics:

        metric = self.register(
            destination_id
        )

        metric.failures += 1
        metric.last_error = str(error)

        return metric

    # ---------------------------------------------------------
    # RESTART
    # ---------------------------------------------------------

    def record_restart(
        self,
        destination_id: str,
    ) -> DestinationMetrics:

        metric = self.register(
            destination_id
        )

        metric.restarts += 1

        return metric

    # ---------------------------------------------------------
    # FRAMES
    # ---------------------------------------------------------

    def record_frames(
        self,
        destination_id: str,
        frames: int = 1,
        dropped: int = 0,
    ) -> DestinationMetrics:

        metric = self.register(
            destination_id
        )

        metric.frames += max(
            0,
            int(frames),
        )

        metric.dropped_frames += max(
            0,
            int(dropped),
        )

        return metric

    # ---------------------------------------------------------
    # BYTES
    # ---------------------------------------------------------

    def record_bytes(
        self,
        destination_id: str,
        amount: int,
    ) -> DestinationMetrics:

        metric = self.register(
            destination_id
        )

        metric.bytes_sent += max(
            0,
            int(amount),
        )

        return metric

    # ---------------------------------------------------------
    # METADATA
    # ---------------------------------------------------------

    def set_metadata(
        self,
        destination_id: str,
        key: str,
        value,
    ) -> DestinationMetrics:

        if not key:
            raise ValueError(
                "metadata key is required."
            )

        metric = self.register(
            destination_id
        )

        metric.metadata[str(key)] = value

        return metric

    # ---------------------------------------------------------
    # GET
    # ---------------------------------------------------------

    def get(
        self,
        destination_id: str,
    ) -> DestinationMetrics:

        return self.register(
            destination_id
        )

    # ---------------------------------------------------------
    # STATUS
    # ---------------------------------------------------------

    def status(
        self,
        destination_id: Optional[str] = None,
    ) -> dict:

        if destination_id:

            metric = self.get(
                destination_id
            )

            return self._serialize(
                metric
            )

        return {
            destination_id: self._serialize(
                metric
            )
            for destination_id, metric
            in self.metrics.items()
        }

    # ---------------------------------------------------------
    # SUMMARY
    # ---------------------------------------------------------

    def summary(self) -> dict:

        total = len(
            self.metrics
        )

        started = sum(
            metric.started
            for metric
            in self.metrics.values()
        )

        stopped = sum(
            metric.stopped
            for metric
            in self.metrics.values()
        )

        failures = sum(
            metric.failures
            for metric
            in self.metrics.values()
        )

        restarts = sum(
            metric.restarts
            for metric
            in self.metrics.values()
        )

        frames = sum(
            metric.frames
            for metric
            in self.metrics.values()
        )

        dropped_frames = sum(
            metric.dropped_frames
            for metric
            in self.metrics.values()
        )

        bytes_sent = sum(
            metric.bytes_sent
            for metric
            in self.metrics.values()
        )

        return {
            "destinations": total,
            "started": started,
            "stopped": stopped,
            "failures": failures,
            "restarts": restarts,
            "frames": frames,
            "dropped_frames": dropped_frames,
            "bytes_sent": bytes_sent,
        }

    # ---------------------------------------------------------
    # RESET
    # ---------------------------------------------------------

    def reset(
        self,
        destination_id: Optional[str] = None,
    ) -> None:

        if destination_id:

            self.metrics.pop(
                destination_id,
                None,
            )

            return

        self.metrics.clear()

    # ---------------------------------------------------------
    # SERIALIZE
    # ---------------------------------------------------------

    @staticmethod
    def _serialize(
        metric: DestinationMetrics,
    ) -> dict:

        return {
            "destination_id": (
                metric.destination_id
            ),
            "started": metric.started,
            "stopped": metric.stopped,
            "failures": metric.failures,
            "restarts": metric.restarts,
            "frames": metric.frames,
            "dropped_frames": (
                metric.dropped_frames
            ),
            "bytes_sent": metric.bytes_sent,
            "last_error": metric.last_error,
            "started_at": metric.started_at,
            "stopped_at": metric.stopped_at,
            "metadata": dict(
                metric.metadata
            ),
        }


# ============================================================
# TEST
# ============================================================

def main():

    print("=" * 60)
    print("METRICS MANAGER TEST")
    print("=" * 60)

    manager = MetricsManager()

    # ---------------------------------------------------------
    # Registration
    # ---------------------------------------------------------

    print("\nRegistration test:")

    metric = manager.register(
        "youtube_01"
    )

    print(
        f"- Destination: "
        f"{metric.destination_id}"
    )

    print(
        f"- Started: "
        f"{metric.started}"
    )

    print(
        f"- Failures: "
        f"{metric.failures}"
    )

    # ---------------------------------------------------------
    # Runtime metrics
    # ---------------------------------------------------------

    print("\nRuntime metrics test:")

    manager.record_start(
        "youtube_01"
    )

    manager.record_frames(
        "youtube_01",
        frames=100,
        dropped=2,
    )

    manager.record_bytes(
        "youtube_01",
        5000000,
    )

    manager.record_stop(
        "youtube_01"
    )

    status = manager.status(
        "youtube_01"
    )

    print(
        f"- Started: "
        f"{status['started']}"
    )

    print(
        f"- Stopped: "
        f"{status['stopped']}"
    )

    print(
        f"- Frames: "
        f"{status['frames']}"
    )

    print(
        f"- Dropped frames: "
        f"{status['dropped_frames']}"
    )

    print(
        f"- Bytes sent: "
        f"{status['bytes_sent']}"
    )

    # ---------------------------------------------------------
    # Failure and restart
    # ---------------------------------------------------------

    print("\nFailure/restart test:")

    manager.record_failure(
        "youtube_01",
        "TEST_FAILURE",
    )

    manager.record_restart(
        "youtube_01"
    )

    status = manager.status(
        "youtube_01"
    )

    print(
        f"- Failures: "
        f"{status['failures']}"
    )

    print(
        f"- Restarts: "
        f"{status['restarts']}"
    )

    print(
        f"- Error: "
        f"{status['last_error']}"
    )

    # ---------------------------------------------------------
    # Metadata
    # ---------------------------------------------------------

    print("\nMetadata test:")

    manager.set_metadata(
        "youtube_01",
        "platform",
        "youtube",
    )

    metadata_ok = (
        manager.status(
            "youtube_01"
        )["metadata"].get("platform")
        == "youtube"
    )

    print(
        f"- Metadata: "
        f"{'OK' if metadata_ok else 'FAILED'}"
    )

    # ---------------------------------------------------------
    # Destination isolation
    # ---------------------------------------------------------

    print("\nDestination isolation test:")

    manager.record_start(
        "youtube_02"
    )

    youtube_01 = manager.status(
        "youtube_01"
    )

    youtube_02 = manager.status(
        "youtube_02"
    )

    isolation_ok = (
        youtube_01["destination_id"]
        != youtube_02["destination_id"]
        and youtube_01["started"] == 1
        and youtube_02["started"] == 1
    )

    print(
        f"- youtube_01 started: "
        f"{youtube_01['started']}"
    )

    print(
        f"- youtube_02 started: "
        f"{youtube_02['started']}"
    )

    print(
        f"- Isolation: "
        f"{'OK' if isolation_ok else 'FAILED'}"
    )

    # ---------------------------------------------------------
    # Summary
    # ---------------------------------------------------------

    print("\nMetrics summary:")

    summary = manager.summary()

    print(
        f"- Destinations: "
        f"{summary['destinations']}"
    )

    print(
        f"- Started: "
        f"{summary['started']}"
    )

    print(
        f"- Stopped: "
        f"{summary['stopped']}"
    )

    print(
        f"- Failures: "
        f"{summary['failures']}"
    )

    print(
        f"- Restarts: "
        f"{summary['restarts']}"
    )

    print(
        f"- Frames: "
        f"{summary['frames']}"
    )

    print(
        f"- Dropped frames: "
        f"{summary['dropped_frames']}"
    )

    print(
        f"- Bytes sent: "
        f"{summary['bytes_sent']}"
    )

    # ---------------------------------------------------------
    # Reset
    # ---------------------------------------------------------

    print("\nReset test:")

    manager.reset(
        "youtube_02"
    )

    exists_after_reset = (
        "youtube_02"
        in manager.metrics
    )

    print(
        f"- youtube_02 removed: "
        f"{'YES' if not exists_after_reset else 'NO'}"
    )

    # ---------------------------------------------------------
    # Safety
    # ---------------------------------------------------------

    print("\nSafety checks:")

    print(
        "  - No FFmpeg process started."
    )

    print(
        "  - No RTMP connection started."
    )

    print(
        "  - No stream key accessed."
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
        "METRICS MANAGER TEST COMPLETE"
    )
    print("=" * 60)


if __name__ == "__main__":
    main()