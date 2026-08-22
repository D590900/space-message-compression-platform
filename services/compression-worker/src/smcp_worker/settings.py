from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    valkey_url: str
    s3_endpoint: str
    s3_region: str = "us-east-1"
    s3_bucket: str = "smcp-private"
    s3_access_key_id: str
    s3_secret_access_key: str
    s3_force_path_style: bool = True
    worker_consumer_name: str = "worker-1"
    worker_group: str = "compression-workers"
    worker_block_ms: int = Field(default=5_000, ge=100, le=60_000)
    worker_claim_idle_ms: int = Field(default=1_800_000, ge=10_000, le=86_400_000)
    worker_claim_batch: int = Field(default=10, ge=1, le=100)
    worker_max_attempts: int = Field(default=3, ge=1, le=20)
    max_upload_bytes: int = Field(default=1_073_741_824, gt=0)
    max_image_pixels: int = Field(default=100_000_000, gt=0)
    max_audio_seconds: float = Field(default=3_600, gt=0)
    max_video_seconds: float = Field(default=1_800, gt=0)
    max_video_pixels: int = Field(default=33_177_600, gt=0)
    max_video_frames: int = Field(default=216_000, gt=0)
    delete_originals_after_seconds: int = Field(default=0, ge=0)
    deletion_batch_size: int = Field(default=20, ge=1, le=100)
    # Container-internal health endpoint; Compose does not publish this port.
    worker_health_host: str = "0.0.0.0"  # noqa: S104
    worker_health_port: int = Field(default=8000, ge=1, le=65_535)
    environment: str = "development"
    otel_service_name: str = "smcp-compression-worker"
    otel_exporter_otlp_traces_endpoint: str | None = None

    @field_validator("otel_exporter_otlp_traces_endpoint", mode="before")
    @classmethod
    def empty_optional_url_is_none(cls, value: object) -> object:
        return None if value == "" else value
