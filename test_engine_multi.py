from engine import StreamingEngine
from models import (
    VideoSource,
    StreamDestination,
    StreamJob,
    SourceType,
    PlatformType,
    LoopMode,
)


def show_status(engine, label):
    print(f"\n--- {label} ---")

    statuses = engine.get_all_status()

    for status in statuses:
        if isinstance(status, dict):
            job_id = status.get("job_id") or status.get("id")
            job_status = status.get("status")
            process_id = status.get("process_id")
            worker_id = status.get("worker_id")

            print(
                f"{job_id}: "
                f"status={job_status} "
                f"process_id={process_id} "
                f"worker_id={worker_id}"
            )
        else:
            print(status)


def main():
    print("=== MULTIPLE JOBS ISOLATION TEST ===")

    engine = StreamingEngine()

    # --------------------------------------------------
    # 1. Start engine
    # --------------------------------------------------
    engine.start()

    print("ENGINE STARTED:", engine.is_running)

    assert engine.is_running is True

    # --------------------------------------------------
    # 2. Shared local test source
    # --------------------------------------------------
    source = VideoSource(
        name="Isolation Test Video",
        source_type=SourceType.LOCAL_FILE,
        file_path=(
            r"D:\streaming_engine\cache\youtube_01"
            r"\Episode 1 –The Boy Who Loved the Morning Sky.mp4"
        ),
    )

    # --------------------------------------------------
    # 3. Fake/local-only destinations
    # --------------------------------------------------
    destination_a = StreamDestination(
        platform=PlatformType.YOUTUBE,
        name="Test Destination A",
        stream_url="rtmp://127.0.0.1/test_a",
        stream_key="TEST_ONLY_A",
        enabled=True,
    )

    destination_b = StreamDestination(
        platform=PlatformType.YOUTUBE,
        name="Test Destination B",
        stream_url="rtmp://127.0.0.1/test_b",
        stream_key="TEST_ONLY_B",
        enabled=True,
    )

    destination_c = StreamDestination(
        platform=PlatformType.FACEBOOK,
        name="Test Destination C",
        stream_url="rtmp://127.0.0.1/test_c",
        stream_key="TEST_ONLY_C",
        enabled=True,
    )

    # --------------------------------------------------
    # 4. Create StreamJob objects
    # --------------------------------------------------
    job_a = StreamJob(
        name="Isolation Job A",
        source=source,
        destinations=[destination_a],
        loop_mode=LoopMode.ONE,
    )

    job_b = StreamJob(
        name="Isolation Job B",
        source=source,
        destinations=[destination_b],
        loop_mode=LoopMode.ONE,
    )

    job_c = StreamJob(
        name="Isolation Job C",
        source=source,
        destinations=[destination_c],
        loop_mode=LoopMode.ONE,
    )

    # --------------------------------------------------
    # 5. Register jobs
    # --------------------------------------------------
    job_a_id = engine.create_job(job_a)
    job_b_id = engine.create_job(job_b)
    job_c_id = engine.create_job(job_c)

    print("\nJOBS CREATED:")
    print("A:", job_a_id, job_a.status.value)
    print("B:", job_b_id, job_b.status.value)
    print("C:", job_c_id, job_c.status.value)

    assert job_a_id == job_a.id
    assert job_b_id == job_b.id
    assert job_c_id == job_c.id

    assert job_a.status.value == "created"
    assert job_b.status.value == "created"
    assert job_c.status.value == "created"

    show_status(engine, "INITIAL")

    # --------------------------------------------------
    # 6. Start Job A
    # --------------------------------------------------
    print("\nSTART JOB A")

    instance_a = engine.start_job(job_a.id)

    print(
        "A instance:",
        instance_a.id if instance_a else None
    )

    print("A status:", job_a.status.value)

    assert instance_a is not None
    assert instance_a.process_id is not None
    assert instance_a.worker_id is not None
    assert job_a.status.value == "live"

    show_status(engine, "AFTER START A")

    # --------------------------------------------------
    # 7. Start Job B
    # --------------------------------------------------
    print("\nSTART JOB B")

    instance_b = engine.start_job(job_b.id)

    print(
        "B instance:",
        instance_b.id if instance_b else None
    )

    print("B status:", job_b.status.value)

    assert instance_b is not None
    assert instance_b.process_id is not None
    assert instance_b.worker_id is not None
    assert job_b.status.value == "live"

    show_status(engine, "AFTER START B")

    # --------------------------------------------------
    # 8. Isolation Check #1
    # --------------------------------------------------
    assert job_a.status.value == "live"
    assert job_b.status.value == "live"
    assert job_c.status.value == "created"

    assert instance_a.process_id != instance_b.process_id
    assert instance_a.worker_id != instance_b.worker_id

    print("\nISOLATION CHECK 1: PASS")
    print("A and B are independently running.")
    print("A PID:", instance_a.process_id)
    print("B PID:", instance_b.process_id)
    print("A Worker:", instance_a.worker_id)
    print("B Worker:", instance_b.worker_id)
    print("C remains untouched.")

    # --------------------------------------------------
    # 9. Stop Job A
    # --------------------------------------------------
    print("\nSTOP JOB A")

    stopped_a = engine.stop_job(job_a.id)

    print("A stopped:", stopped_a)
    print("A status:", job_a.status.value)
    print("B status:", job_b.status.value)
    print("C status:", job_c.status.value)

    assert stopped_a is True
    assert job_a.status.value == "stopped"

    show_status(engine, "AFTER STOP A")

    # --------------------------------------------------
    # 10. Isolation Check #2
    # --------------------------------------------------
    assert job_a.status.value == "stopped"
    assert job_b.status.value == "live"
    assert job_c.status.value == "created"

    print("\nISOLATION CHECK 2: PASS")
    print("Stopping A did not affect B or C.")
    print("B remains LIVE with PID:", instance_b.process_id)

    # --------------------------------------------------
    # 11. Stop Job B
    # --------------------------------------------------
    print("\nSTOP JOB B")

    stopped_b = engine.stop_job(job_b.id)

    print("B stopped:", stopped_b)
    print("B status:", job_b.status.value)

    assert stopped_b is True
    assert job_b.status.value == "stopped"

    # --------------------------------------------------
    # 12. Isolation Check #3
    # --------------------------------------------------
    assert job_b.status.value == "stopped"
    assert job_c.status.value == "created"

    print("\nISOLATION CHECK 3: PASS")
    print("B stopped independently.")
    print("C was never started.")

    # --------------------------------------------------
    # 13. Final job states
    # --------------------------------------------------
    print("\nFINAL JOB STATES:")

    print("A:", job_a.status.value)
    print("B:", job_b.status.value)
    print("C:", job_c.status.value)

    assert job_a.status.value == "stopped"
    assert job_b.status.value == "stopped"
    assert job_c.status.value == "created"

    # --------------------------------------------------
    # 14. Worker registry check
    # --------------------------------------------------
    print("\nWORKER REGISTRY CHECK")

    all_status = engine.get_all_status()

    for status in all_status:
        if isinstance(status, dict):
            print(
                "Job:",
                status.get("job_id"),
                "| workers:",
                status.get("workers"),
                "| worker_ids:",
                status.get("worker_ids"),
            )

            if status.get("job_id") in (job_a.id, job_b.id):
                assert status.get("workers") == []
                assert status.get("worker_ids") == []

    print("WORKER REGISTRY CHECK: PASS")

    # --------------------------------------------------
    # 15. Cleanup
    # --------------------------------------------------
    print("\nCLEANUP")

    removed_a = engine.remove_job(job_a.id)
    removed_b = engine.remove_job(job_b.id)
    removed_c = engine.remove_job(job_c.id)

    print("Removed A:", removed_a)
    print("Removed B:", removed_b)
    print("Removed C:", removed_c)

    print("Remaining jobs:", len(engine.list_jobs()))

    assert removed_a is True
    assert removed_b is True
    assert removed_c is True
    assert len(engine.list_jobs()) == 0

    # --------------------------------------------------
    # 16. Shutdown
    # --------------------------------------------------
    engine.shutdown()

    print("\nENGINE RUNNING:", engine.is_running)

    assert engine.is_running is False

    print("\n===================================")
    print("MULTIPLE JOBS ISOLATION TEST: PASS")
    print("===================================")
    print("No real RTMP streaming was started.")


if __name__ == "__main__":
    main()