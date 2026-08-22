from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import asdict
from pathlib import Path
from types import ModuleType
from typing import Any, cast
from uuid import uuid4

import boto3
import psycopg
from botocore.config import Config
from psycopg.rows import dict_row
from redis import Redis
from redis.exceptions import ResponseError

from smcp_worker.adapters import audio as audio_module
from smcp_worker.adapters import image as image_module
from smcp_worker.adapters import text as text_module
from smcp_worker.adapters import video as video_module
from smcp_worker.adapters.audio import OpusAudioAdapter, generate_audio_candidates
from smcp_worker.adapters.image import (
    AvifImageAdapter,
    JpegXlImageAdapter,
    generate_image_candidates,
)
from smcp_worker.adapters.text import (
    BrotliTextAdapter,
    ZstandardTextAdapter,
    generate_text_candidates,
)
from smcp_worker.adapters.video import Av1VideoAdapter, generate_video_candidates
from smcp_worker.capabilities import all_capabilities
from smcp_worker.models import EncodedCandidate, Profile, QualityReport, SourceObject
from smcp_worker.settings import Settings

LOGGER = logging.getLogger(__name__)
COMPRESSION_STREAM = "smcp:compression-jobs"
DECOMPRESSION_STREAM = "smcp:decompression-jobs"


class CompressionWorker:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.redis: Redis = Redis.from_url(settings.valkey_url, decode_responses=True)
        self.s3 = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
            config=Config(
                s3={"addressing_style": "path" if settings.s3_force_path_style else "virtual"}
            ),
        )

    def ensure_groups(self) -> None:
        self._sync_codec_registry()
        for stream in (COMPRESSION_STREAM, DECOMPRESSION_STREAM):
            try:
                self.redis.xgroup_create(stream, self.settings.worker_group, id="0", mkstream=True)
            except ResponseError as error:
                if "BUSYGROUP" not in str(error):
                    raise

    def _sync_codec_registry(self) -> None:
        with psycopg.connect(self.settings.database_url) as connection:
            for capability in all_capabilities():
                module_file = self._adapter_module(capability.content_types[0]).__file__
                if module_file is None:
                    raise RuntimeError("codec adapter module has no source file")
                implementation_hash = hashlib.sha256(Path(module_file).read_bytes()).digest()
                connection.execute(
                    """
                    INSERT INTO codec_registry (
                      id, version, content_type, implementation_sha256,
                      deterministic, enabled, disabled_reason, capability
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id, version) DO UPDATE
                    SET implementation_sha256 = EXCLUDED.implementation_sha256,
                        deterministic = EXCLUDED.deterministic,
                        enabled = EXCLUDED.enabled,
                        disabled_reason = EXCLUDED.disabled_reason,
                        capability = EXCLUDED.capability
                    """,
                    (
                        capability.codec_id,
                        capability.codec_version,
                        capability.content_types[0],
                        implementation_hash,
                        capability.deterministic,
                        capability.enabled,
                        capability.disabled_reason,
                        json.dumps(
                            {
                                "profiles": [profile.value for profile in capability.profiles],
                                "install_hint": capability.install_hint,
                                "device": "cpu" if capability.enabled else None,
                            },
                            sort_keys=True,
                        ),
                    ),
                )
            connection.commit()

    def run_forever(self) -> None:
        self.ensure_groups()
        while True:
            messages = cast(
                list[tuple[str, list[tuple[str, dict[str, str]]]]],
                self.redis.xreadgroup(
                    self.settings.worker_group,
                    self.settings.worker_consumer_name,
                    {COMPRESSION_STREAM: ">", DECOMPRESSION_STREAM: ">"},
                    count=1,
                    block=self.settings.worker_block_ms,
                ),
            )
            for stream, entries in messages:
                for message_id, fields in entries:
                    self.process_message(stream, message_id, fields)

    def process_message(self, stream: str, message_id: str, fields: dict[str, str]) -> None:
        id_field = "job_id" if stream == COMPRESSION_STREAM else "decompression_id"
        job_id = fields.get(id_field)
        tenant_subject = fields.get("tenant_subject")
        if not job_id or not tenant_subject:
            LOGGER.error("rejecting malformed queue message", extra={"message_id": message_id})
            self.redis.xack(stream, self.settings.worker_group, message_id)
            return
        try:
            if stream == COMPRESSION_STREAM:
                self.process_job(job_id, tenant_subject)
            elif stream == DECOMPRESSION_STREAM:
                self.process_decompression(job_id, tenant_subject)
            else:
                raise ValueError("unknown worker stream")
        except Exception:
            LOGGER.exception("worker job failed", extra={"job_id": job_id, "stream": stream})
            self._fail_job(stream, job_id, tenant_subject, "WORKER_FAILURE")
            raise
        else:
            self.redis.xack(stream, self.settings.worker_group, message_id)

    def process_job(self, job_id: str, tenant_subject: str) -> None:
        with psycopg.connect(self.settings.database_url, row_factory=dict_row) as connection:
            job = connection.execute(
                """
                SELECT j.*, s.object_key, s.declared_mime, s.expected_bytes,
                       s.sha256 AS expected_sha256
                FROM compression_jobs j
                JOIN source_objects s
                  ON s.id = j.source_object_id AND s.tenant_subject = j.tenant_subject
                WHERE j.id = %s AND j.tenant_subject = %s
                """,
                (job_id, tenant_subject),
            ).fetchone()
            if not job:
                raise ValueError("job does not exist for tenant")
            if job["status"] in {"COMPLETED", "FAILED_TERMINAL", "CANCELLED"}:
                return
            self._transition(connection, job_id, tenant_subject, "PENDING", "VALIDATING")
            response = self.s3.get_object(Bucket=self.settings.s3_bucket, Key=job["object_key"])
            source_bytes = response["Body"].read(self.settings.max_upload_bytes + 1)
            if len(source_bytes) > self.settings.max_upload_bytes:
                self._terminal_failure(connection, job, "INPUT_TOO_LARGE")
                return
            if len(source_bytes) != job["expected_bytes"]:
                self._terminal_failure(connection, job, "SIZE_MISMATCH")
                return
            digest = hashlib.sha256(source_bytes).digest()
            expected_digest = job["expected_sha256"]
            if expected_digest is not None and bytes(expected_digest) != digest:
                self._terminal_failure(connection, job, "HASH_MISMATCH")
                return
            detected_mime = self._detected_mime(job["input_type"], job["declared_mime"])
            connection.execute(
                """
                UPDATE source_objects
                SET actual_bytes = %s, sha256 = %s,
                    detected_mime = %s, validated_at = now()
                WHERE id = %s AND tenant_subject = %s
                """,
                (
                    len(source_bytes),
                    digest,
                    detected_mime,
                    job["source_object_id"],
                    tenant_subject,
                ),
            )
            connection.commit()

            self._transition(connection, job_id, tenant_subject, "VALIDATING", "PREPROCESSING")
            source = SourceObject(source_bytes, job["declared_mime"], job["object_key"])
            self._transition(connection, job_id, tenant_subject, "PREPROCESSING", "ENCODING")
            started = time.perf_counter_ns()
            input_type = str(job["input_type"])
            candidates = self._generate_candidates(input_type, source, Profile(job["profile"]))
            if not candidates:
                self._terminal_failure(connection, job, "NO_QUALITY_GATED_CANDIDATE")
                return
            encode_duration_ms = max(0, (time.perf_counter_ns() - started) // 1_000_000)
            self._transition(connection, job_id, tenant_subject, "ENCODING", "MEASURING")

            persisted: list[tuple[str, int, str]] = []
            module_file = self._adapter_module(input_type).__file__
            if module_file is None:
                raise RuntimeError("codec adapter module has no source file")
            implementation_hash = hashlib.sha256(Path(module_file).read_bytes()).digest()
            for candidate, report in candidates:
                candidate_id = str(uuid4())
                object_key = f"{tenant_subject}/{job['project_id']}/candidates/{candidate_id}.bin"
                self.s3.put_object(
                    Bucket=self.settings.s3_bucket,
                    Key=object_key,
                    Body=candidate.payload,
                    ContentType=self._candidate_content_type(candidate.codec_id),
                    ServerSideEncryption="AES256",
                    Metadata={
                        "sha256": hashlib.sha256(candidate.payload).hexdigest(),
                        "codec-id": candidate.codec_id,
                    },
                )
                config_bytes = json.dumps(
                    candidate.config, sort_keys=True, separators=(",", ":")
                ).encode()
                connection.execute(
                    """
                    INSERT INTO codec_registry (
                      id, version, content_type, implementation_sha256,
                      deterministic, enabled, capability
                    ) VALUES (%s, %s, %s, %s, true, true, %s)
                    ON CONFLICT (id, version) DO UPDATE
                    SET implementation_sha256 = EXCLUDED.implementation_sha256,
                        enabled = true,
                        disabled_reason = NULL,
                        capability = EXCLUDED.capability
                    """,
                    (
                        candidate.codec_id,
                        candidate.codec_version,
                        input_type,
                        implementation_hash,
                        json.dumps(
                            {
                                "profiles": ["faithful", "ultra"],
                                "quality_gate": (
                                    "byte_exact" if input_type == "TEXT" else "perceptual"
                                ),
                                "device": "cpu",
                            }
                        ),
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO encoding_candidates (
                      id, tenant_subject, job_id, codec_id, codec_version,
                      config_hash, profile, payload_bytes, container_overhead_bytes,
                      quality_metrics, quality_gate_passed, encode_duration_ms,
                      decode_duration_ms, hardware, determinism_status, object_key, sha256
                    ) VALUES (
                      %s, %s, %s, %s, %s, %s, %s, %s, 0, %s, true, %s, 0,
                      %s, %s, %s, %s
                    )
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        candidate_id,
                        tenant_subject,
                        job_id,
                        candidate.codec_id,
                        candidate.codec_version,
                        hashlib.sha256(config_bytes).digest(),
                        job["profile"],
                        len(candidate.payload),
                        json.dumps(asdict(report), sort_keys=True),
                        encode_duration_ms,
                        json.dumps({"runtime": "python", "device": "cpu"}),
                        "BIT_EXACT" if input_type == "TEXT" else "REPRODUCIBLE_CONFIG",
                        object_key,
                        hashlib.sha256(candidate.payload).digest(),
                    ),
                )
                persisted.append((candidate_id, len(candidate.payload), object_key))
            connection.commit()

            self._transition(connection, job_id, tenant_subject, "MEASURING", "SELECTING")
            selected_id, selected_bytes, selected_key = min(
                persisted, key=lambda item: (item[1], item[0])
            )
            artifact_id = str(uuid4())
            connection.execute(
                """
                INSERT INTO artifacts (
                  id, tenant_subject, job_id, candidate_id, kind, object_key, bytes, sha256
                )
                SELECT %s, tenant_subject, job_id, id, 'compressed', object_key,
                       payload_bytes, sha256
                FROM encoding_candidates
                WHERE id = %s AND tenant_subject = %s
                """,
                (artifact_id, selected_id, tenant_subject),
            )
            connection.commit()
            self._transition(connection, job_id, tenant_subject, "SELECTING", "PACKAGING")
            updated = connection.execute(
                """
                UPDATE compression_jobs
                SET status = 'COMPLETED', selected_candidate_id = %s, completed_at = now()
                WHERE id = %s AND tenant_subject = %s AND status = 'PACKAGING'
                RETURNING project_id
                """,
                (selected_id, job_id, tenant_subject),
            ).fetchone()
            if not updated:
                connection.rollback()
                raise RuntimeError("job state changed before completion")
            connection.execute(
                """
                INSERT INTO audit_events (
                  tenant_subject, project_id, actor_subject, action, resource_type,
                  resource_id, request_id, outcome, metadata
                ) VALUES (%s, %s, 'compression-worker', 'compression.completed',
                          'compression_job', %s, %s, 'success', %s)
                """,
                (
                    tenant_subject,
                    updated["project_id"],
                    job_id,
                    f"worker:{job_id}",
                    json.dumps(
                        {
                            "selected_candidate_id": selected_id,
                            "payload_bytes": selected_bytes,
                            "object_key_hash": hashlib.sha256(selected_key.encode()).hexdigest(),
                        }
                    ),
                ),
            )
            connection.commit()

    def process_decompression(self, decompression_id: str, tenant_subject: str) -> None:
        with psycopg.connect(self.settings.database_url, row_factory=dict_row) as connection:
            job = connection.execute(
                """
                SELECT d.*, a.object_key AS artifact_object_key,
                       c.codec_id, c.codec_version, c.quality_metrics,
                       c.sha256 AS candidate_sha256
                FROM decompression_jobs d
                JOIN artifacts a
                  ON a.id = d.artifact_id AND a.tenant_subject = d.tenant_subject
                JOIN encoding_candidates c
                  ON c.id = a.candidate_id AND c.tenant_subject = a.tenant_subject
                WHERE d.id = %s AND d.tenant_subject = %s
                """,
                (decompression_id, tenant_subject),
            ).fetchone()
            if not job:
                raise ValueError("decompression job does not exist for tenant")
            if job["status"] in {"COMPLETED", "FAILED_TERMINAL"}:
                return
            if job["status"] != "PENDING":
                raise RuntimeError("decompression job is not claimable")

            updated = connection.execute(
                """
                UPDATE decompression_jobs SET status = 'DECODING'
                WHERE id = %s AND tenant_subject = %s AND status = 'PENDING'
                RETURNING id
                """,
                (decompression_id, tenant_subject),
            ).fetchone()
            if not updated:
                connection.rollback()
                raise RuntimeError("decompression claim lost")
            connection.commit()

            response = self.s3.get_object(
                Bucket=self.settings.s3_bucket, Key=job["artifact_object_key"]
            )
            payload = response["Body"].read(self.settings.max_upload_bytes + 1)
            if len(payload) > self.settings.max_upload_bytes:
                self._terminal_decompression_failure(
                    connection, decompression_id, tenant_subject, "ARTIFACT_TOO_LARGE"
                )
                return
            if hashlib.sha256(payload).digest() != bytes(job["candidate_sha256"]):
                self._terminal_decompression_failure(
                    connection, decompression_id, tenant_subject, "ARTIFACT_HASH_MISMATCH"
                )
                return

            candidate = EncodedCandidate(
                codec_id=job["codec_id"],
                codec_version=job["codec_version"],
                config={"dictionary_sha256": None},
                payload=payload,
            )
            if candidate.codec_id == "text.brotli":
                decoded = BrotliTextAdapter().decode(candidate)
            elif candidate.codec_id == "text.zstandard":
                decoded = ZstandardTextAdapter().decode(candidate)
            elif candidate.codec_id == "image.avif":
                decoded = AvifImageAdapter().decode(candidate)
            elif candidate.codec_id == "image.jpeg-xl":
                decoded = JpegXlImageAdapter().decode(candidate)
            elif candidate.codec_id == "audio.opus":
                decoded = OpusAudioAdapter().decode(candidate)
            elif candidate.codec_id == "video.av1":
                decoded = Av1VideoAdapter().decode(candidate)
            else:
                self._terminal_decompression_failure(
                    connection, decompression_id, tenant_subject, "DECODER_UNAVAILABLE"
                )
                return

            connection.execute(
                """
                UPDATE decompression_jobs SET status = 'VERIFYING'
                WHERE id = %s AND tenant_subject = %s AND status = 'DECODING'
                """,
                (decompression_id, tenant_subject),
            )
            connection.commit()

            output_digest = hashlib.sha256(decoded).hexdigest()
            expected_digest = job["quality_metrics"].get("decoded_sha256")
            if output_digest != expected_digest:
                self._terminal_decompression_failure(
                    connection, decompression_id, tenant_subject, "ROUND_TRIP_MISMATCH"
                )
                return
            output_key = (
                f"{tenant_subject}/{job['project_id']}/decompressions/{decompression_id}.bin"
            )
            self.s3.put_object(
                Bucket=self.settings.s3_bucket,
                Key=output_key,
                Body=decoded,
                ContentType=self._decoded_content_type(candidate.codec_id),
                ServerSideEncryption="AES256",
                Metadata={"sha256": output_digest, "verified": "true"},
            )
            completed = connection.execute(
                """
                UPDATE decompression_jobs
                SET status = 'COMPLETED', output_object_key = %s, output_bytes = %s,
                    output_sha256 = %s, verified = true, completed_at = now()
                WHERE id = %s AND tenant_subject = %s AND status = 'VERIFYING'
                RETURNING project_id
                """,
                (
                    output_key,
                    len(decoded),
                    bytes.fromhex(output_digest),
                    decompression_id,
                    tenant_subject,
                ),
            ).fetchone()
            if not completed:
                connection.rollback()
                raise RuntimeError("decompression state changed before completion")
            connection.execute(
                """
                INSERT INTO audit_events (
                  tenant_subject, project_id, actor_subject, action, resource_type,
                  resource_id, request_id, outcome, metadata
                ) VALUES (%s, %s, 'compression-worker', 'decompression.completed',
                          'decompression_job', %s, %s, 'success', %s)
                """,
                (
                    tenant_subject,
                    completed["project_id"],
                    decompression_id,
                    f"worker:{decompression_id}",
                    json.dumps({"output_bytes": len(decoded), "output_sha256": output_digest}),
                ),
            )
            connection.commit()

    @staticmethod
    def _generate_candidates(
        input_type: str, source: SourceObject, profile: Profile
    ) -> list[tuple[EncodedCandidate, QualityReport]]:
        if input_type == "TEXT":
            return generate_text_candidates(source, profile)
        if input_type == "IMAGE":
            return generate_image_candidates(source, profile)
        if input_type == "AUDIO":
            return generate_audio_candidates(source, profile)
        if input_type == "VIDEO":
            return generate_video_candidates(source, profile)
        raise ValueError(f"unsupported content type: {input_type}")

    @staticmethod
    def _adapter_module(input_type: str) -> ModuleType:
        modules = {
            "TEXT": text_module,
            "IMAGE": image_module,
            "AUDIO": audio_module,
            "VIDEO": video_module,
        }
        try:
            return modules[input_type]
        except KeyError as error:
            raise ValueError(f"unsupported content type: {input_type}") from error

    @staticmethod
    def _detected_mime(input_type: str, declared_mime: str) -> str:
        if input_type == "TEXT":
            return "text/plain"
        return declared_mime

    @staticmethod
    def _candidate_content_type(codec_id: str) -> str:
        return {
            "text.brotli": "application/vnd.smcp.brotli",
            "text.zstandard": "application/zstd",
            "image.avif": "image/avif",
            "image.jpeg-xl": "image/jxl",
            "audio.opus": "audio/ogg; codecs=opus",
            "video.av1": "video/x-matroska; codecs=av1,opus",
        }.get(codec_id, "application/vnd.smcp.candidate")

    @staticmethod
    def _decoded_content_type(codec_id: str) -> str:
        return {
            "text.brotli": "text/plain; charset=utf-8",
            "text.zstandard": "text/plain; charset=utf-8",
            "image.avif": "image/png",
            "image.jpeg-xl": "image/png",
            "audio.opus": "audio/wav",
            "video.av1": "video/x-msvideo; codecs=ffv1,pcm_s16le",
        }.get(codec_id, "application/octet-stream")

    @staticmethod
    def _transition(
        connection: psycopg.Connection[Any],
        job_id: str,
        tenant_subject: str,
        expected: str,
        target: str,
    ) -> None:
        updated = connection.execute(
            """
            UPDATE compression_jobs
            SET status = %s, started_at = COALESCE(started_at, now())
            WHERE id = %s AND tenant_subject = %s AND status = %s
            RETURNING id
            """,
            (target, job_id, tenant_subject, expected),
        ).fetchone()
        if not updated:
            connection.rollback()
            raise RuntimeError(f"invalid job transition {expected} -> {target}")
        connection.commit()

    @staticmethod
    def _terminal_failure(
        connection: psycopg.Connection[Any], job: dict[str, Any], code: str
    ) -> None:
        connection.execute(
            """
            UPDATE compression_jobs
            SET status = 'FAILED_TERMINAL', error_code = %s, completed_at = now()
            WHERE id = %s AND tenant_subject = %s
            """,
            (code, job["id"], job["tenant_subject"]),
        )
        connection.commit()

    @staticmethod
    def _terminal_decompression_failure(
        connection: psycopg.Connection[Any],
        decompression_id: str,
        tenant_subject: str,
        code: str,
    ) -> None:
        connection.execute(
            """
            UPDATE decompression_jobs
            SET status = 'FAILED_TERMINAL', error_code = %s, completed_at = now()
            WHERE id = %s AND tenant_subject = %s
            """,
            (code, decompression_id, tenant_subject),
        )
        connection.commit()

    def _fail_job(self, stream: str, job_id: str, tenant_subject: str, code: str) -> None:
        with psycopg.connect(self.settings.database_url) as connection:
            if stream == COMPRESSION_STREAM:
                connection.execute(
                    """
                    UPDATE compression_jobs
                    SET status = 'FAILED_RETRYABLE', error_code = %s, attempt = attempt + 1
                    WHERE id = %s AND tenant_subject = %s
                      AND status NOT IN ('COMPLETED', 'FAILED_TERMINAL', 'CANCELLED')
                    """,
                    (code, job_id, tenant_subject),
                )
            else:
                connection.execute(
                    """
                    UPDATE decompression_jobs
                    SET status = 'FAILED_RETRYABLE', error_code = %s
                    WHERE id = %s AND tenant_subject = %s
                      AND status NOT IN ('COMPLETED', 'FAILED_TERMINAL')
                    """,
                    (code, job_id, tenant_subject),
                )
