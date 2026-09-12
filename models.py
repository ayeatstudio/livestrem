"""
Professional Cloud Live Streaming Software
Streaming Engine Models
Version: 1.0.0
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional
from datetime import datetime
from uuid import uuid4


# ============================================================
# ENUMS
# ============================================================

class SourceType(str, Enum):
    GOOGLE_DRIVE = "google_drive"
    ONEDRIVE = "onedrive"
    LOCAL_FILE = "local_file"


class PlatformType(str, Enum):
    YOUTUBE = "youtube"
    FACEBOOK = "facebook"
    INSTAGRAM = "instagram"


class StreamStatus(str, Enum):
    CREATED = "created"
    STARTING = "starting"
    LIVE = "live"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"
    RECONNECTING = "reconnecting"
    PAUSED = "paused"


class LoopMode(str, Enum):
    NONE = "none"
    ONE = "one"
    PLAYLIST = "playlist"


# ============================================================
# SOURCE
# ============================================================

@dataclass
class VideoSource:
    """
    Represents a video source.

    A source may come from Google Drive, OneDrive,
    local storage, or another supported provider.
    """

    name: str
    source_type: SourceType
    file_id: Optional[str] = None
    file_path: Optional[str] = None
    mime_type: Optional[str] = None
    size_bytes: Optional[int] = None

    id: str = field(default_factory=lambda: str(uuid4()))
    metadata: Dict[str, str] = field(default_factory=dict)

    def is_remote(self) -> bool:
        return self.source_type in {
            SourceType.GOOGLE_DRIVE,
            SourceType.ONEDRIVE,
        }

    def is_local(self) -> bool:
        return self.source_type == SourceType.LOCAL_FILE


# ============================================================
# DESTINATION
# ============================================================

@dataclass
class StreamDestination:
    """
    Represents one streaming destination.

    Example:

        YouTube Channel A
        YouTube Channel B
        Facebook Page A
    """

    platform: PlatformType
    name: str

    stream_url: Optional[str] = None
    stream_key: Optional[str] = None

    account_id: Optional[str] = None
    channel_id: Optional[str] = None

    enabled: bool = True

    id: str = field(default_factory=lambda: str(uuid4()))
    metadata: Dict[str, str] = field(default_factory=dict)

    def is_configured(self) -> bool:
        """
        Check whether enough information exists
        to start a live stream.
        """

        return bool(
            self.enabled
            and self.stream_url
            and self.stream_key
        )


# ============================================================
# VIDEO SETTINGS
# ============================================================

@dataclass
class VideoSettings:
    """
    Encoding settings used by FFmpeg.
    """

    width: int = 1920
    height: int = 1080

    fps: int = 30

    video_bitrate: str = "4500k"
    audio_bitrate: str = "128k"

    video_codec: str = "libx264"
    audio_codec: str = "aac"

    preset: str = "veryfast"
    pixel_format: str = "yuv420p"

    audio_sample_rate: int = 48000

    extra_options: List[str] = field(default_factory=list)


# ============================================================
# STREAM SCHEDULE
# ============================================================

@dataclass
class StreamSchedule:
    """
    Defines when a stream should run.
    """

    enabled: bool = False

    start_time: Optional[datetime] = None
    stop_time: Optional[datetime] = None

    repeat: bool = False

    timezone: str = "UTC"


# ============================================================
# STREAM JOB
# ============================================================

@dataclass
class StreamJob:
    """
    Represents one independent streaming job.

    Example:

        Video A → YouTube Channel A

    is one StreamJob.

        Video A → YouTube Channel B

    is another StreamJob.
    """

    name: str

    source: VideoSource

    destinations: List[StreamDestination]

    video_settings: VideoSettings = field(
        default_factory=VideoSettings
    )

    schedule: StreamSchedule = field(
        default_factory=StreamSchedule
    )

    loop_mode: LoopMode = LoopMode.NONE

    status: StreamStatus = StreamStatus.CREATED

    id: str = field(default_factory=lambda: str(uuid4()))

    created_at: datetime = field(
        default_factory=datetime.utcnow
    )

    started_at: Optional[datetime] = None
    stopped_at: Optional[datetime] = None

    error_message: Optional[str] = None

    worker_ids: List[str] = field(default_factory=list)

    metadata: Dict[str, str] = field(default_factory=dict)

    def enabled_destinations(self) -> List[StreamDestination]:
        """
        Return only enabled destinations.
        """

        return [
            destination
            for destination in self.destinations
            if destination.enabled
        ]

    def can_start(self) -> bool:
        """
        Check whether the job is ready to start.
        """

        if not self.source:
            return False

        if not self.destinations:
            return False

        if not self.enabled_destinations():
            return False

        return all(
            destination.is_configured()
            for destination in self.enabled_destinations()
        )

    def mark_started(self) -> None:
        self.status = StreamStatus.LIVE
        self.started_at = datetime.utcnow()
        self.error_message = None

    def mark_stopped(self) -> None:
        self.status = StreamStatus.STOPPED
        self.stopped_at = datetime.utcnow()

    def mark_error(self, message: str) -> None:
        self.status = StreamStatus.ERROR
        self.error_message = message


# ============================================================
# STREAM METRICS
# ============================================================

@dataclass
class StreamMetrics:
    """
    Runtime metrics for monitoring.
    """

    uptime_seconds: float = 0.0

    video_frames: int = 0
    dropped_frames: int = 0

    bitrate_kbps: float = 0.0

    fps: float = 0.0

    reconnect_count: int = 0

    cpu_percent: float = 0.0
    memory_percent: float = 0.0

    last_update: Optional[datetime] = None


# ============================================================
# STREAM INSTANCE
# ============================================================

@dataclass
class StreamInstance:
    """
    Runtime representation of a running StreamJob.
    """

    job_id: str

    process_id: Optional[int] = None

    status: StreamStatus = StreamStatus.CREATED

    metrics: StreamMetrics = field(
        default_factory=StreamMetrics
    )

    started_at: Optional[datetime] = None

    worker_id: Optional[str] = None

    error_message: Optional[str] = None

    id: str = field(default_factory=lambda: str(uuid4()))


# ============================================================
# HELPERS
# ============================================================

def create_video_source(
    name: str,
    source_type: SourceType,
    file_id: Optional[str] = None,
    file_path: Optional[str] = None,
) -> VideoSource:

    return VideoSource(
        name=name,
        source_type=source_type,
        file_id=file_id,
        file_path=file_path,
    )


def create_destination(
    platform: PlatformType,
    name: str,
    stream_url: str,
    stream_key: str,
    account_id: Optional[str] = None,
    channel_id: Optional[str] = None,
) -> StreamDestination:

    return StreamDestination(
        platform=platform,
        name=name,
        stream_url=stream_url,
        stream_key=stream_key,
        account_id=account_id,
        channel_id=channel_id,
    )