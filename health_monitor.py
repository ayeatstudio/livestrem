from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional


# ============================================================
# HEALTH MONITOR
# ============================================================


@dataclass
class HealthState:
    destination_id: str
    phase: str = "IDLE"
    process_running: bool = False
    last_error: Optional[str] = None
    restart_count: int = 0
    healthy: bool = False


class HealthMonitor:
    """
    Runtime health monitor for streaming destinations.

    Responsibilities:
    - Track destination runtime state
    - Detect stopped processes
    - Track failures
    - Track restart attempts
    - Provide safe health information
    - Never print credentials
    - Never start FFmpeg by itself
    - Never connect to RTMP by itself
    """

    VALID_PHASES = {
        "IDLE",
        "STARTING",
        "RUNNING",
        "STOPPING",
        "STOPPED",
        "FAILED",
        "RESTARTING",
    }

    def __init__(
        self,
        restart_limit: int = 3,
    ):
        self.restart_limit = max(
            0,
            int(restart_limit),
        )

        self.states: dict[
            str,
            HealthState,
        ] = {}

    # ---------------------------------------------------------
    # DESTINATION
    # ---------------------------------------------------------

    def register(
        self,
        destination_id: str,
    ) -> HealthState:

        if not destination_id:
            raise ValueError(
                "destination_id is required."
            )

        if destination_id not in self.states:
            self.states[destination_id] = (
                HealthState(
                    destination_id=destination_id,
                )
            )

        return self.states[destination_id]

    # ---------------------------------------------------------
    # STATE
    # ---------------------------------------------------------

    def update(
        self,
        destination_id: str,
        phase: str,
        process_running: bool = False,
        error: Optional[str] = None,
    ) -> HealthState:

        state = self.register(
            destination_id
        )

        if phase not in self.VALID_PHASES:
            raise ValueError(
                f"Invalid phase: {phase}"
            )

        state.phase = phase
        state.process_running = bool(
            process_running
        )

        if error:
            state.last_error = str(error)

        if (
            phase == "RUNNING"
            and state.process_running
        ):
            state.healthy = True

        elif phase in {
            "FAILED",
            "STOPPED",
            "IDLE",
        }:
            state.healthy = False

        return state

    # ---------------------------------------------------------
    # PROCESS CHECK
    # ---------------------------------------------------------

    def check_process(
        self,
        destination_id: str,
        process,
    ) -> HealthState:

        state = self.register(
            destination_id
        )

        if process is None:
            state.process_running = False
            state.healthy = False

            if state.phase == "RUNNING":
                state.phase = "FAILED"
                state.last_error = (
                    "PROCESS_NOT_AVAILABLE"
                )

            return state

        try:
            return_code = process.poll()

        except Exception as exc:
            state.process_running = False
            state.healthy = False
            state.phase = "FAILED"
            state.last_error = (
                f"PROCESS_CHECK_FAILED: {exc}"
            )
            return state

        if return_code is None:
            state.process_running = True
            state.healthy = True
            state.phase = "RUNNING"

        else:
            state.process_running = False
            state.healthy = False

            if return_code == 0:
                state.phase = "STOPPED"
            else:
                state.phase = "FAILED"
                state.last_error = (
                    f"FFMPEG_EXIT_CODE_{return_code}"
                )

        return state

    # ---------------------------------------------------------
    # FAILURE
    # ---------------------------------------------------------

    def record_failure(
        self,
        destination_id: str,
        error: str,
    ) -> HealthState:

        state = self.register(
            destination_id
        )

        state.phase = "FAILED"
        state.process_running = False
        state.healthy = False
        state.last_error = str(error)

        return state

    # ---------------------------------------------------------
    # RESTART
    # ---------------------------------------------------------

    def can_restart(
        self,
        destination_id: str,
    ) -> bool:

        state = self.register(
            destination_id
        )

        return (
            state.restart_count
            < self.restart_limit
        )

    def record_restart(
        self,
        destination_id: str,
    ) -> bool:

        state = self.register(
            destination_id
        )

        if not self.can_restart(
            destination_id
        ):
            return False

        state.restart_count += 1
        state.phase = "RESTARTING"
        state.process_running = False
        state.healthy = False

        return True

    # ---------------------------------------------------------
    # RESET
    # ---------------------------------------------------------

    def reset(
        self,
        destination_id: str,
    ) -> HealthState:

        state = self.register(
            destination_id
        )

        state.phase = "IDLE"
        state.process_running = False
        state.last_error = None
        state.restart_count = 0
        state.healthy = False

        return state

    # ---------------------------------------------------------
    # STATUS
    # ---------------------------------------------------------

    def status(
        self,
        destination_id: Optional[str] = None,
    ) -> dict:

        if destination_id is not None:

            state = self.register(
                destination_id
            )

            return self._state_dict(
                state
            )

        return {
            destination_id: self._state_dict(
                state
            )
            for destination_id, state
            in self.states.items()
        }

    # ---------------------------------------------------------
    # SUMMARY
    # ---------------------------------------------------------

    def summary(self) -> dict:

        total = len(self.states)

        healthy = sum(
            1
            for state in self.states.values()
            if state.healthy
        )

        failed = sum(
            1
            for state in self.states.values()
            if state.phase == "FAILED"
        )

        running = sum(
            1
            for state in self.states.values()
            if state.process_running
        )

        return {
            "total": total,
            "healthy": healthy,
            "running": running,
            "failed": failed,
        }

    # ---------------------------------------------------------
    # INTERNAL
    # ---------------------------------------------------------

    @staticmethod
    def _state_dict(
        state: HealthState,
    ) -> dict:

        return {
            "destination_id": (
                state.destination_id
            ),
            "phase": state.phase,
            "process_running": (
                state.process_running
            ),
            "last_error": state.last_error,
            "restart_count": (
                state.restart_count
            ),
            "healthy": state.healthy,
        }


# ============================================================
# TEST
# ============================================================

def main():

    print("=" * 60)
    print("HEALTH MONITOR TEST")
    print("=" * 60)

    monitor = HealthMonitor(
        restart_limit=3
    )

    # ---------------------------------------------------------
    # Registration
    # ---------------------------------------------------------

    print("\nRegistration test:")

    state = monitor.register(
        "youtube_01"
    )

    print(
        f"- Destination: "
        f"{state.destination_id}"
    )

    print(
        f"- Phase: "
        f"{state.phase}"
    )

    print(
        f"- Healthy: "
        f"{state.healthy}"
    )

    # ---------------------------------------------------------
    # Running state
    # ---------------------------------------------------------

    print("\nRunning state test:")

    state = monitor.update(
        "youtube_01",
        "RUNNING",
        process_running=True,
    )

    print(
        f"- Phase: {state.phase}"
    )

    print(
        f"- Process running: "
        f"{state.process_running}"
    )

    print(
        f"- Healthy: "
        f"{state.healthy}"
    )

    # ---------------------------------------------------------
    # Failure
    # ---------------------------------------------------------

    print("\nFailure test:")

    state = monitor.record_failure(
        "youtube_01",
        "TEST_FAILURE",
    )

    print(
        f"- Phase: {state.phase}"
    )

    print(
        f"- Healthy: {state.healthy}"
    )

    print(
        f"- Error: {state.last_error}"
    )

    # ---------------------------------------------------------
    # Restart
    # ---------------------------------------------------------

    print("\nRestart test:")

    for index in range(4):

        allowed = monitor.record_restart(
            "youtube_01"
        )

        print(
            f"- Attempt {index + 1}: "
            f"allowed={allowed}"
        )

    # ---------------------------------------------------------
    # Reset
    # ---------------------------------------------------------

    print("\nReset test:")

    state = monitor.reset(
        "youtube_01"
    )

    print(
        f"- Phase: {state.phase}"
    )

    print(
        f"- Restart count: "
        f"{state.restart_count}"
    )

    print(
        f"- Healthy: "
        f"{state.healthy}"
    )

    # ---------------------------------------------------------
    # Multiple destinations
    # ---------------------------------------------------------

    print("\nDestination isolation test:")

    monitor.update(
        "youtube_01",
        "RUNNING",
        process_running=True,
    )

    monitor.update(
        "youtube_02",
        "FAILED",
        process_running=False,
        error="TEST_ERROR",
    )

    youtube_01 = monitor.status(
        "youtube_01"
    )

    youtube_02 = monitor.status(
        "youtube_02"
    )

    isolation_ok = (
        youtube_01["healthy"] is True
        and youtube_02["healthy"] is False
        and youtube_01["destination_id"]
        != youtube_02["destination_id"]
    )

    print(
        f"- youtube_01: "
        f"{youtube_01['phase']}"
    )

    print(
        f"- youtube_02: "
        f"{youtube_02['phase']}"
    )

    print(
        f"- Isolation: "
        f"{'OK' if isolation_ok else 'FAILED'}"
    )

    # ---------------------------------------------------------
    # Summary
    # ---------------------------------------------------------

    print("\nHealth summary:")

    summary = monitor.summary()

    print(
        f"- Total: {summary['total']}"
    )

    print(
        f"- Healthy: {summary['healthy']}"
    )

    print(
        f"- Running: {summary['running']}"
    )

    print(
        f"- Failed: {summary['failed']}"
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
        "HEALTH MONITOR TEST COMPLETE"
    )
    print("=" * 60)


if __name__ == "__main__":
    main()