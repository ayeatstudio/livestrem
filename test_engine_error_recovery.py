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


def make_job(name, enabled=True):
    source = VideoSource(
        name="Recovery Test Video",
        source_type=SourceType.LOCAL_FILE,
        file_path=(
            r"D:\streaming_engine\cache\youtube_01"
            r"\Episode 1 –The Boy Who Loved the Morning Sky.mp4"
        ),
    )

    destination = StreamDestination(
        platform=PlatformType.YOUTUBE,
        name=f"{name} Destination",
        stream_url=f"rtmp://127.0.0.1/{name.lower().replace(' ', '_')}",
        stream_key="TEST_ONLY_RECOVERY",
        enabled=enabled,
    )

    return StreamJob(
        name=name,
        source=source,
        destinations=[destination],
        loop_mode=LoopMode.ONE,
    )


def main():
    print("=== ENGINE ERROR HANDLING / RECOVERY TEST ===")

    engine = StreamingEngine()

    # --------------------------------------------------
    # 1. Engine must start
    # --------------------------------------------------
    engine.start()

    check(
        "ENGINE START",
        engine.is_running is True,
    )

    # --------------------------------------------------
    # 2. Missing job operations
    # --------------------------------------------------
    fake_job_id = "THIS_JOB_DOES_NOT_EXIST"

    print("\nMISSING JOB TEST")

    missing = engine.get_job(fake_job_id)

    print("get_job:", missing)

    check(
        "MISSING GET RETURNS NONE",
        missing is None,
    )

    print("\nMISSING START TEST")

    try:
        missing_start = engine.start_job(fake_job_id)
        print("start_job:", missing_start)
        missing_start_safe = missing_start is None
    except KeyError as exc:
        print("start_job raised:", type(exc).__name__, str(exc))
        missing_start_safe = True

    check(
        "MISSING START SAFE",
        missing_start_safe,
    )

    missing_stop = engine.stop_job(fake_job_id)

    print("stop_job:", missing_stop)

    check(
        "MISSING STOP RETURNS FALSE",
        missing_stop is False,
    )

    print("\nMISSING START TEST")

    try:
        missing_start = engine.start_job(fake_job_id)
        print("start_job:", missing_start)
        missing_start_safe = missing_start is None
    except KeyError as exc:
        print("start_job raised:", type(exc).__name__, str(exc))
        missing_start_safe = True

    check(
        "MISSING START SAFE",
        missing_start_safe,
    )

    print("\nMISSING STOP TEST")

    try:
        missing_stop = engine.stop_job(fake_job_id)
        print("stop_job:", missing_stop)
        missing_stop_safe = missing_stop is False
    except (KeyError, ValueError) as exc:
        print("stop_job raised:", type(exc).__name__, str(exc))
        missing_stop_safe = True

    check(
        "MISSING STOP SAFE",
        missing_stop_safe,
    )

    print("\nMISSING PAUSE TEST")

    try:
        missing_pause = engine.pause_job(fake_job_id)
        print("pause_job:", missing_pause)
        missing_pause_safe = missing_pause is False
    except (KeyError, ValueError) as exc:
        print("pause_job raised:", type(exc).__name__, str(exc))
        missing_pause_safe = True

    check(
        "MISSING PAUSE SAFE",
        missing_pause_safe,
    )

    print("\nMISSING RESUME TEST")

    try:
        missing_resume = engine.resume_job(fake_job_id)
        print("resume_job:", missing_resume)
        missing_resume_safe = missing_resume is False
    except (KeyError, ValueError) as exc:
        print("resume_job raised:", type(exc).__name__, str(exc))
        missing_resume_safe = True

    check(
        "MISSING RESUME SAFE",
        missing_resume_safe,
    )

    print("\nMISSING REMOVE TEST")

    try:
        missing_remove = engine.remove_job(fake_job_id)
        print("remove_job:", missing_remove)
        missing_remove_safe = missing_remove is False
    except (KeyError, ValueError) as exc:
        print("remove_job raised:", type(exc).__name__, str(exc))
        missing_remove_safe = True

    check(
        "MISSING REMOVE SAFE",
        missing_remove_safe,
    )

    # --------------------------------------------------
    # 3. Create valid job
    # --------------------------------------------------
    job = make_job("Recovery Job")

    job_id = engine.create_job(job)

    print("\nVALID JOB CREATED:", job_id)

    check(
        "JOB CREATED",
        job_id == job.id,
    )

    check(
        "INITIAL STATE CREATED",
        job.status.value == "created",
    )

    # --------------------------------------------------
    # 4. Duplicate create must be rejected
    # --------------------------------------------------
    print("\nDUPLICATE JOB REGISTRATION TEST")

    duplicate_rejected = False

    try:
        duplicate_result = engine.create_job(job)
        print("duplicate result:", duplicate_result)

        # If implementation returns same ID, treat it as idempotent.
        duplicate_rejected = (
            duplicate_result == job.id
            and len(engine.list_jobs()) == 1
        )

    except Exception as exc:
        print("duplicate exception:", type(exc).__name__, str(exc))
        duplicate_rejected = True

    check(
        "DUPLICATE CREATE SAFE",
        duplicate_rejected,
    )

    # --------------------------------------------------
    # 5. Start valid job
    # --------------------------------------------------
    print("\nSTART VALID JOB")

    instance = engine.start_job(job.id)

    print(
        "instance:",
        instance.id if instance else None,
    )

    print("state:", job.status.value)

    check(
        "VALID START",
        instance is not None,
    )

    check(
        "STATE LIVE",
        job.status.value == "live",
    )

    # --------------------------------------------------
    # 6. Start already-started job
    # --------------------------------------------------
   

    print("\nDUPLICATE START TEST")
    try:
       second_start = engine.start_job(job.id)
       print("second_start:", second_start)
       duplicate_start_safe = second_start is None
    except RuntimeError as exc:
       print("duplicate start exception:", type(exc).__name__, str(exc))
       duplicate_start_safe = True

    check(
       "DUPLICATE START SAFE",
        duplicate_start_safe,
    )


    # --------------------------------------------------
    # 7. Pause job
    # --------------------------------------------------
    print("\nPAUSE")

    pause_result = engine.pause_job(job.id)

    print("pause:", pause_result)
    print("state:", job.status.value)

    check(
        "PAUSE SUCCESS",
        pause_result is True,
    )

    check(
        "STATE PAUSED",
        job.status.value == "paused",
    )

    # --------------------------------------------------
    # 8. Duplicate pause
    # --------------------------------------------------
    print("\nDUPLICATE PAUSE TEST")

    second_pause = engine.pause_job(job.id)

    print("second pause:", second_pause)

    check(
        "DUPLICATE PAUSE BLOCKED",
        second_pause is False,
    )

    check(
        "STATE STILL PAUSED",
        job.status.value == "paused",
    )

    # --------------------------------------------------
    # 9. Resume
    # --------------------------------------------------
    print("\nRESUME")

    resume_result = engine.resume_job(job.id)

    print("resume:", resume_result)
    print("state:", job.status.value)

    check(
        "RESUME SUCCESS",
        resume_result is True,
    )

    check(
        "STATE LIVE",
        job.status.value == "live",
    )

    # --------------------------------------------------
    # 10. Duplicate resume
    # --------------------------------------------------
    print("\nDUPLICATE RESUME TEST")

    second_resume = engine.resume_job(job.id)

    print("second resume:", second_resume)

    check(
        "DUPLICATE RESUME BLOCKED",
        second_resume is False,
    )

    check(
        "STATE STILL LIVE",
        job.status.value == "live",
    )

    # --------------------------------------------------
    # 11. Stop
    # --------------------------------------------------
    print("\nSTOP")

    stop_result = engine.stop_job(job.id)

    print("stop:", stop_result)
    print("state:", job.status.value)

    check(
        "STOP SUCCESS",
        stop_result is True,
    )

    check(
        "STATE STOPPED",
        job.status.value == "stopped",
    )

    # --------------------------------------------------
    # 12. Duplicate stop
    # --------------------------------------------------
    print("\nDUPLICATE STOP TEST")

    second_stop = engine.stop_job(job.id)

    print("second stop:", second_stop)

    check(
        "DUPLICATE STOP BLOCKED",
        second_stop is False,
    )

    check(
        "STATE STILL STOPPED",
        job.status.value == "stopped",
    )

    # --------------------------------------------------
    # 13. Remove
    # --------------------------------------------------
    print("\nREMOVE VALID JOB")

    removed = engine.remove_job(job.id)

    print("removed:", removed)

    check(
        "REMOVE SUCCESS",
        removed is True,
    )

    check(
        "JOB NO LONGER EXISTS",
        engine.get_job(job.id) is None,
    )

    # --------------------------------------------------
    # 14. Operations after removal
    # --------------------------------------------------
    print("\nREMOVED JOB OPERATION TEST")

    try:
        removed_start = engine.start_job(job.id)
        print("removed start:", removed_start)
        removed_start_safe = removed_start is None
    except KeyError as exc:
        print("removed start exception:", type(exc).__name__, str(exc))
        removed_start_safe = True

    check(
        "REMOVED START SAFE",
        removed_start_safe,
    )

    # --------------------------------------------------
    # 15. Engine cleanup
    # --------------------------------------------------
    print("\nCLEANUP")

    engine.stop_all()
    engine.shutdown()

    check(
        "ENGINE SHUTDOWN",
        engine.is_running is False,
    )

    check(
        "NO REMAINING JOBS",
        len(engine.list_jobs()) == 0,
    )

    print("\n======================================")
    print("ENGINE ERROR / RECOVERY TEST: PASS")
    print("======================================")
    print("No real RTMP streaming was started.")


if __name__ == "__main__":
    main()