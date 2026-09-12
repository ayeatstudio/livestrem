from engine import StreamingEngine
from models import (
    VideoSource,
    StreamDestination,
    StreamJob,
    SourceType,
    PlatformType,
    LoopMode,
)


def check(label, condition):
    if condition:
        print(f"{label}: PASS")
    else:
        print(f"{label}: FAIL")
        raise AssertionError(label)


def main():
    print("=== JOB LIFECYCLE / STATE TRANSITION TEST ===")

    engine = StreamingEngine()

    # 1. Engine start
    engine.start()

    check(
        "ENGINE START",
        engine.is_running is True,
    )

    # 2. Local test source
    source = VideoSource(
        name="Lifecycle Test Video",
        source_type=SourceType.LOCAL_FILE,
        file_path=(
            r"D:\streaming_engine\cache\youtube_01"
            r"\Episode 1 –The Boy Who Loved the Morning Sky.mp4"
        ),
    )

    # 3. Fake/local-only destination
    destination = StreamDestination(
        platform=PlatformType.YOUTUBE,
        name="Lifecycle Test Destination",
        stream_url="rtmp://127.0.0.1/lifecycle_test",
        stream_key="TEST_ONLY_LIFECYCLE",
        enabled=True,
    )

    # 4. Create job
    job = StreamJob(
        name="Lifecycle Test Job",
        source=source,
        destinations=[destination],
        loop_mode=LoopMode.ONE,
    )

    job_id = engine.create_job(job)

    print("\nJOB CREATED:", job_id)

    check(
        "STATE CREATED",
        job.status.value == "created",
    )

    # 5. Invalid: CREATED -> PAUSED
    print("\nINVALID TRANSITION: CREATED -> PAUSED")

    pause_created = engine.pause_job(job.id)

    print("pause result:", pause_created)
    print("current state:", job.status.value)

    check(
        "CREATED PAUSE BLOCKED",
        pause_created is False,
    )

    check(
        "STATE STILL CREATED",
        job.status.value == "created",
    )

    # 6. CREATED -> STARTING
    print("\nTRANSITION: CREATED -> STARTING")

    instance = engine.start_job(job.id)

    print(
        "instance:",
        instance.id if instance else None,
    )
    print("state:", job.status.value)

    check(
        "START RESULT",
        instance is not None,
    )

    check(
        "STATE STARTING",
        job.status.value == "starting",
    )

    # 7. STARTING -> PAUSED
    print("\nTRANSITION: STARTING -> PAUSED")

    pause_result = engine.pause_job(job.id)

    print("pause result:", pause_result)
    print("state:", job.status.value)

    check(
        "PAUSE STARTING",
        pause_result is True,
    )

    check(
        "STATE PAUSED",
        job.status.value == "paused",
    )

    # 8. PAUSED -> LIVE
    print("\nTRANSITION: PAUSED -> LIVE")

    resume_result = engine.resume_job(job.id)

    print("resume result:", resume_result)
    print("state:", job.status.value)

    check(
        "RESUME PAUSED",
        resume_result is True,
    )

    check(
        "STATE LIVE",
        job.status.value == "live",
    )

    # 9. LIVE -> PAUSED
    print("\nTRANSITION: LIVE -> PAUSED")

    pause_live = engine.pause_job(job.id)

    print("pause result:", pause_live)
    print("state:", job.status.value)

    check(
        "PAUSE LIVE",
        pause_live is True,
    )

    check(
        "STATE PAUSED AGAIN",
        job.status.value == "paused",
    )

    # 10. PAUSED -> LIVE
    print("\nTRANSITION: PAUSED -> LIVE AGAIN")

    resume_again = engine.resume_job(job.id)

    print("resume result:", resume_again)
    print("state:", job.status.value)

    check(
        "RESUME AGAIN",
        resume_again is True,
    )

    check(
        "STATE LIVE AGAIN",
        job.status.value == "live",
    )

    # 11. LIVE -> STOPPED
    print("\nTRANSITION: LIVE -> STOPPED")

    stop_result = engine.stop_job(job.id)

    print("stop result:", stop_result)
    print("state:", job.status.value)

    check(
        "STOP LIVE",
        stop_result is True,
    )

    check(
        "STATE STOPPED",
        job.status.value == "stopped",
    )

    # 12. Invalid: STOPPED -> PAUSED
    print("\nINVALID TRANSITION: STOPPED -> PAUSED")

    pause_stopped = engine.pause_job(job.id)

    print("pause result:", pause_stopped)
    print("state:", job.status.value)

    check(
        "STOPPED PAUSE BLOCKED",
        pause_stopped is False,
    )

    check(
        "STATE REMAINS STOPPED",
        job.status.value == "stopped",
    )

    # 13. Invalid: STOPPED -> LIVE
    print("\nINVALID TRANSITION: STOPPED -> LIVE")

    resume_stopped = engine.resume_job(job.id)

    print("resume result:", resume_stopped)
    print("state:", job.status.value)

    check(
        "STOPPED RESUME BLOCKED",
        resume_stopped is False,
    )

    check(
        "STATE STILL STOPPED",
        job.status.value == "stopped",
    )

    # 14. Cleanup
    print("\nCLEANUP")

    removed = engine.remove_job(job.id)

    print("removed:", removed)
    print("remaining jobs:", len(engine.list_jobs()))

    check(
        "JOB REMOVED",
        removed is True,
    )

    check(
        "NO REMAINING JOBS",
        len(engine.list_jobs()) == 0,
    )

    # 15. Shutdown
    engine.shutdown()

    check(
        "ENGINE SHUTDOWN",
        engine.is_running is False,
    )

    print("\n======================================")
    print("JOB LIFECYCLE TEST: PASS")
    print("======================================")
    print("No real RTMP streaming was started.")


if __name__ == "__main__":
    main()