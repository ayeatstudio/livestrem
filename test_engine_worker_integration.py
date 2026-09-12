import engine

from models import (
    StreamJob,
    VideoSource,
    StreamDestination,
    PlatformType,
    SourceType,
    StreamStatus,
    StreamMetrics,
)


class FakeWorker:
    def __init__(self, *args, **kwargs):
        self.worker_id = kwargs.get("worker_id", "fake_worker")
        self.process_id = None
        self.status = StreamStatus.CREATED
        self.metrics = StreamMetrics()

    @property
    def is_running(self):
        return self.status in (
            StreamStatus.STARTING,
            StreamStatus.LIVE,
        )

    def start(self):
        self.status = StreamStatus.LIVE
        return True

    def stop(self):
        self.status = StreamStatus.STOPPED
        return True


engine.FFmpegWorker = FakeWorker


def main():
    e = engine.StreamingEngine()
    e.start()

    source = VideoSource(
        name="test.mp4",
        source_type=SourceType.LOCAL_FILE,
        file_path="test.mp4",
    )

    destination = StreamDestination(
        platform=PlatformType.YOUTUBE,
        name="Test",
        stream_url="rtmp://127.0.0.1/test",
        stream_key="FAKE_KEY",
        enabled=True,
    )

    job = StreamJob(
        name="worker_integration_test",
        source=source,
        destinations=[destination],
    )

    job_id = e.create_job(job)
    instance = e.start_job(job_id)

    print("ENGINE RUNNING:", e.is_running)
    print("INSTANCE CREATED:", instance is not None)
    print("INSTANCE STATUS:", instance.status)
    print("INSTANCE ERROR:", instance.error_message)
    print("INSTANCE WORKER ID:", instance.worker_id)
    print("WORKERS TRACKED:", len(e._workers))
    print("JOB WORKER IDS:", len(job.worker_ids))

    print("STOP JOB:", e.stop_job(job_id))
    print("WORKERS AFTER STOP:", len(e._workers))

    e.shutdown()

    print("ENGINE SHUTDOWN:", not e.is_running)
    print("NO REAL FFMPEG/RTMP: PASS")


if __name__ == "__main__":
    main()