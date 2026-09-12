from engine import StreamingEngine
from models import (
    VideoSource,
    StreamDestination,
    StreamJob,
    SourceType,
    PlatformType,
    LoopMode,
)


def show_job(engine, job_id, title):
    print()
    print(title)
    print("-" * 60)

    job = engine.get_job(job_id)

    if job:
        print("Job ID:", job.id)
        print("Name:", job.name)
        print("Status:", job.status.value)
    else:
        print("Job not found")


def main():
    print("=" * 60)
    print("ENGINE STATE CONTROL TEST")
    print("=" * 60)

    # --------------------------------------------------------
    # Engine
    # --------------------------------------------------------

    engine = StreamingEngine()
    engine.start()

    print()
    print("ENGINE STARTED")
    print("Running:", engine.is_running)

    # --------------------------------------------------------
    # Test source
    # --------------------------------------------------------

    source = VideoSource(
        name="State Test Video",
        source_type=SourceType.LOCAL_FILE,
        file_path=(
            r"D:\streaming_engine\cache\youtube_01"
            r"\Episode 1 –The Boy Who Loved the Morning Sky.mp4"
        ),
    )

    # --------------------------------------------------------
    # Fake/local destination
    # --------------------------------------------------------

    destination = StreamDestination(
        platform=PlatformType.YOUTUBE,
        name="State Test Destination",
        stream_url="rtmp://127.0.0.1/test",
        stream_key="TEST_ONLY",
        enabled=True,
    )

    # --------------------------------------------------------
    # Job
    # --------------------------------------------------------

    job = StreamJob(
        name="engine_state_test_job",
        source=source,
        destinations=[destination],
        loop_mode=LoopMode.NONE,
    )

    print()
    print("CREATE JOB")
    print("-" * 60)

    job_id = engine.create_job(job)

    print("Job ID:", job_id)
    print("Can start:", job.can_start())
    print("Initial status:", job.status.value)

    # --------------------------------------------------------
    # START
    # --------------------------------------------------------

    print()
    print("1. START JOB")
    print("-" * 60)

    result = engine.start_job(job_id)

    print("Result:", result)

    show_job(
        engine,
        job_id,
        "After START",
    )

    # --------------------------------------------------------
    # PAUSE
    # --------------------------------------------------------

    print()
    print("2. PAUSE JOB")
    print("-" * 60)

    result = engine.pause_job(job_id)

    print("Result:", result)

    show_job(
        engine,
        job_id,
        "After PAUSE",
    )

    # --------------------------------------------------------
    # RESUME
    # --------------------------------------------------------

    print()
    print("3. RESUME JOB")
    print("-" * 60)

    result = engine.resume_job(job_id)

    print("Result:", result)

    show_job(
        engine,
        job_id,
        "After RESUME",
    )

    # --------------------------------------------------------
    # RESTART
    # --------------------------------------------------------

    print()
    print("4. RESTART JOB")
    print("-" * 60)

    result = engine.restart_job(job_id)

    print("Result:", result)

    show_job(
        engine,
        job_id,
        "After RESTART",
    )

    # --------------------------------------------------------
    # STOP ALL
    # --------------------------------------------------------

    print()
    print("5. STOP ALL")
    print("-" * 60)

    result = engine.stop_all()

    print("Result:", result)

    show_job(
        engine,
        job_id,
        "After STOP ALL",
    )

    # --------------------------------------------------------
    # Final status
    # --------------------------------------------------------

    print()
    print("FINAL ENGINE STATUS")
    print("-" * 60)

    print("Running:", engine.is_running)
    print("Jobs:", len(engine.list_jobs()))
    print("All status:", engine.get_all_status())

    # --------------------------------------------------------
    # Cleanup
    # --------------------------------------------------------

    print()
    print("6. CLEANUP")
    print("-" * 60)

    removed = engine.remove_job(job_id)

    print("Job removed:", removed)
    print("Remaining jobs:", len(engine.list_jobs()))

    engine.shutdown()

    print()
    print("ENGINE SHUTDOWN")
    print("Running:", engine.is_running)

    print()
    print("=" * 60)
    print("STATE CONTROL TEST COMPLETE")
    print("=" * 60)
    print("No real RTMP streaming was performed.")


if __name__ == "__main__":
    main()