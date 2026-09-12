from engine import Engine
from models import (
    VideoSource,
    StreamDestination,
    StreamJob,
    SourceType,
    PlatformType,
    LoopMode,
)


def main():
    print("=" * 60)
    print("ENGINE TEST")
    print("=" * 60)

    # Engine তৈরি
    engine = Engine()

    # Engine চালু
    engine.start()

    print()
    print("ENGINE STATUS:")
    print("Running:", engine.is_running)

    # Local test source
    source = VideoSource(
        name="Engine Test Video",
        source_type=SourceType.LOCAL_FILE,
        file_path=(
            r"D:\streaming_engine\cache\youtube_01"
            r"\Episode 1 –The Boy Who Loved the Morning Sky.mp4"
        ),
    )

    # Fake/local test destination
    destination = StreamDestination(
        platform=PlatformType.YOUTUBE,
        name="Engine Test Destination",
        stream_url="rtmp://127.0.0.1/test",
        stream_key="TEST_ONLY",
        enabled=True,
    )

    # Stream Job
    job = StreamJob(
        name="engine_test_job",
        source=source,
        destinations=[destination],
        loop_mode=LoopMode.NONE,
    )

    print()
    print("JOB CREATED:")
    print("ID:", job.id)
    print("Name:", job.name)
    print("Can start:", job.can_start())
    print("Status:", job.status.value)

    # Job register
    result = engine.create_job(job)

    print()
    print("REGISTERED:")
    print("Result:", result)
    print("Jobs:", len(engine.list_jobs()))

    # Job start
    print()
    print("START JOB:")
    result = engine.start_job(job.id)
    print("Result:", result)

    current = engine.get_job(job.id)

    if current:
        print("Job status:", current.status.value)

    # Engine status
    print()
    print("ENGINE STATUS:")
    print(engine.get_status())

    print()
    print("ALL JOB STATUS:")
    print(engine.get_all_status())

    # Job stop
    print()
    print("STOP JOB:")
    result = engine.stop_job(job.id)
    print("Result:", result)

    current = engine.get_job(job.id)

    if current:
        print("Final job status:", current.status.value)

    # Job remove
    print()
    print("REMOVE JOB:")
    result = engine.remove_job(job.id)
    print("Result:", result)
    print("Remaining jobs:", len(engine.list_jobs()))

    # Engine shutdown
    print()
    print("SHUTDOWN:")
    engine.shutdown()
    print("Engine running:", engine.is_running)

    print()
    print("=" * 60)
    print("ENGINE TEST COMPLETE")
    print("=" * 60)
    print("No real RTMP streaming was performed.")


if __name__ == "__main__":
    main()