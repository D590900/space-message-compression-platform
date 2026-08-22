from pydantic import Field
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
    max_upload_bytes: int = Field(default=1_073_741_824, gt=0)
    # Container-internal health endpoint; Compose does not publish this port.
    worker_health_host: str = "0.0.0.0"  # noqa: S104
    worker_health_port: int = Field(default=8000, ge=1, le=65_535)
    environment: str = "development"
    otel_service_name: str = "smcp-compression-worker"
    otel_exporter_otlp_traces_endpoint: str | None = None
