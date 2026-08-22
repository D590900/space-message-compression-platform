from __future__ import annotations

import hashlib
import json
import logging
import struct
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict
from fractions import Fraction
from pathlib import Path
from types import ModuleType
from typing import Any, cast
from uuid import UUID, uuid4

import boto3
import psycopg
from botocore.config import Config
from opentelemetry import propagate, trace
from psycopg.rows import dict_row
from redis import Redis
from redis.exceptions import ResponseError

from smcp_worker.adapters import audio as audio_module
from smcp_worker.adapters import image as image_module
from smcp_worker.adapters import text as text_module
from smcp_worker.adapters import video as video_module
from smcp_worker.adapters.audio import OpusAudioAdapter, generate_audio_candidates
from smcp_worker.adapters.external import run
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
from smcp_worker.content_validation import validate_content
from smcp_worker.models import EncodedCandidate, Profile, QualityReport, SourceObject
from smcp_worker.observability import (
    CAPSULE_FILL_RATIO,
    COMPRESSION_RATIO,
    DECODE_DURATION,
    ENCODE_DURATION,
    INPUT_BYTES,
    JOB_DURATION,
    JOBS,
    JOBS_FAILED,
    OUTPUT_BYTES,
    QUALITY_GATE_FAILURES,
    QUEUE_DEPTH,
    WORKER_OOM,
)
from smcp_worker.quality_policy import apply_quality_policy
from smcp_worker.settings import Settings

LOGGER = logging.getLogger(__name__)
COMPRESSION_STREAM = "smcp:compression-jobs"
DECOMPRESSION_STREAM = "smcp:decompression-jobs"
CAPSULE_STREAM = "smcp:capsule-jobs"
TRACER = trace.get_tracer("smcp.compression-worker")


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
        for stream in (COMPRESSION_STREAM, DECOMPRESSION_STREAM, CAPSULE_STREAM):
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
                connection.execute(
                    """
                    DELETE FROM codec_registry AS stale
                    WHERE stale.id = %s
                      AND stale.version <> %s
                      AND stale.enabled = false
                      AND NOT EXISTS (
                        SELECT 1 FROM encoding_candidates AS candidate
                        WHERE candidate.codec_id = stale.id
                          AND candidate.codec_version = stale.version
                      )
                    """,
                    (capability.codec_id, capability.codec_version),
                )
            connection.commit()

    def run_forever(self, on_ready: Callable[[], None] | None = None) -> None:
        self.ensure_groups()
        if on_ready is not None:
            on_ready()
        while True:
            self._delete_due_originals()
            messages = self._claim_stale_messages()
            if not messages:
                messages = cast(
                    list[tuple[str, list[tuple[str, dict[str, str]]]]],
                    self.redis.xreadgroup(
                        self.settings.worker_group,
                        self.settings.worker_consumer_name,
                        {
                            COMPRESSION_STREAM: ">",
                            DECOMPRESSION_STREAM: ">",
                            CAPSULE_STREAM: ">",
                        },
                        count=1,
                        block=self.settings.worker_block_ms,
                    ),
                )
            for queue in (COMPRESSION_STREAM, DECOMPRESSION_STREAM, CAPSULE_STREAM):
                QUEUE_DEPTH.labels(queue=queue).set(self._queue_backlog(queue))
            for stream, entries in messages:
                for message_id, fields in entries:
                    self.process_message(stream, message_id, fields)

    def _claim_stale_messages(
        self,
    ) -> list[tuple[str, list[tuple[str, dict[str, str]]]]]:
        claimed: list[tuple[str, list[tuple[str, dict[str, str]]]]] = []
        for stream in (COMPRESSION_STREAM, DECOMPRESSION_STREAM, CAPSULE_STREAM):
            response = cast(
                list[Any],
                self.redis.xautoclaim(
                    stream,
                    self.settings.worker_group,
                    self.settings.worker_consumer_name,
                    self.settings.worker_claim_idle_ms,
                    "0-0",
                    count=self.settings.worker_claim_batch,
                ),
            )
            entries = cast(list[tuple[str, dict[str, str]]], response[1])
            if entries:
                claimed.append((stream, entries))
        return claimed

    def _queue_backlog(self, stream: str) -> float:
        groups = cast(list[dict[str, Any]], self.redis.xinfo_groups(stream))
        return self._group_backlog(groups, self.settings.worker_group)

    @staticmethod
    def _group_backlog(groups: list[dict[str, Any]], group_name: str) -> float:
        for group in groups:
            if group.get("name") == group_name:
                return float(int(group.get("pending") or 0) + int(group.get("lag") or 0))
        return 0.0

    def process_message(self, stream: str, message_id: str, fields: dict[str, str]) -> None:
        id_field = {
            COMPRESSION_STREAM: "job_id",
            DECOMPRESSION_STREAM: "decompression_id",
            CAPSULE_STREAM: "capsule_id",
        }.get(stream)
        if id_field is None:
            raise ValueError("unknown worker stream")
        job_id = fields.get(id_field)
        tenant_subject = fields.get("tenant_subject")
        if not job_id or not tenant_subject:
            LOGGER.error("rejecting malformed queue message", extra={"message_id": message_id})
            self.redis.xack(stream, self.settings.worker_group, message_id)
            return
        try:
            UUID(job_id)
        except ValueError:
            LOGGER.error(
                "rejecting queue message with invalid job id",
                extra={"message_id": message_id},
            )
            self.redis.xack(stream, self.settings.worker_group, message_id)
            return
        job_type = {
            COMPRESSION_STREAM: "compression",
            DECOMPRESSION_STREAM: "decompression",
            CAPSULE_STREAM: "capsule",
        }[stream]
        started = time.perf_counter()
        parent_context = propagate.extract(fields)
        with TRACER.start_as_current_span(
            f"worker.{job_type}",
            context=parent_context,
            attributes={
                "smcp.job.id": job_id,
                "smcp.job.type": job_type,
                "smcp.request.id": fields.get("request_id", "not_provided"),
            },
        ):
            try:
                if stream == COMPRESSION_STREAM:
                    self.process_job(job_id, tenant_subject)
                elif stream == DECOMPRESSION_STREAM:
                    self.process_decompression(job_id, tenant_subject)
                elif stream == CAPSULE_STREAM:
                    self.process_capsule(job_id, tenant_subject)
                else:
                    raise ValueError("unknown worker stream")
            except MemoryError:
                WORKER_OOM.inc()
                JOBS_FAILED.labels(job_type=job_type).inc()
                JOBS.labels(job_type=job_type, outcome="oom").inc()
                raise
            except Exception:
                JOBS_FAILED.labels(job_type=job_type).inc()
                JOBS.labels(job_type=job_type, outcome="failed").inc()
                LOGGER.exception("worker job failed", extra={"job_id": job_id, "stream": stream})
                terminal = self._fail_job(stream, job_id, tenant_subject, "WORKER_FAILURE")
                if terminal:
                    self.redis.xack(stream, self.settings.worker_group, message_id)
            else:
                JOBS.labels(job_type=job_type, outcome="processed").inc()
                self.redis.xack(stream, self.settings.worker_group, message_id)
            finally:
                JOB_DURATION.labels(job_type=job_type).observe(time.perf_counter() - started)

    def process_job(self, job_id: str, tenant_subject: str) -> None:
        with psycopg.connect(self.settings.database_url, row_factory=dict_row) as connection:
            job = connection.execute(
                """
                SELECT j.*, s.object_key, s.declared_mime, s.expected_bytes,
                       s.sha256 AS expected_sha256, p.quality_policy
                FROM compression_jobs j
                JOIN source_objects s
                  ON s.id = j.source_object_id AND s.tenant_subject = j.tenant_subject
                JOIN projects p
                  ON p.id = j.project_id AND p.tenant_subject = j.tenant_subject
                WHERE j.id = %s AND j.tenant_subject = %s
                """,
                (job_id, tenant_subject),
            ).fetchone()
            if not job:
                raise ValueError("job does not exist for tenant")
            if job["status"] in {"COMPLETED", "FAILED_TERMINAL", "CANCELLED"}:
                return
            if job["status"] != "PENDING" and not self._recover_compression_job(connection, job):
                return
            if Profile(job["profile"]) == Profile.SEMANTIC:
                self._terminal_failure(connection, job, "SEMANTIC_PROFILE_UNAVAILABLE")
                return
            input_type = str(job["input_type"])
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
            validation = validate_content(
                input_type,
                str(job["declared_mime"]),
                str(job["object_key"]),
                source_bytes,
            )
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
                    validation.detected_mime,
                    job["source_object_id"],
                    tenant_subject,
                ),
            )
            connection.commit()

            if validation.error_code is not None:
                self._terminal_failure(connection, job, validation.error_code)
                return
            INPUT_BYTES.labels(content_type=input_type).inc(len(source_bytes))

            limit_error = self._media_limit_error(input_type, source_bytes)
            if limit_error is not None:
                self._terminal_failure(connection, job, limit_error)
                return
            self._transition(connection, job_id, tenant_subject, "VALIDATING", "PREPROCESSING")
            source = SourceObject(source_bytes, job["declared_mime"], job["object_key"])
            self._transition(connection, job_id, tenant_subject, "PREPROCESSING", "ENCODING")
            started = time.perf_counter_ns()
            generated_candidates = self._generate_candidates(
                input_type, source, Profile(job["profile"])
            )
            candidates = [
                (candidate, updated_report)
                for candidate, report in generated_candidates
                if (
                    updated_report := apply_quality_policy(
                        input_type, report, job["quality_policy"]
                    )
                ).quality_gate_passed
            ]
            rejected_count = len(generated_candidates) - len(candidates)
            if rejected_count:
                QUALITY_GATE_FAILURES.labels(content_type=input_type).inc(rejected_count)
            if not candidates:
                self._terminal_failure(connection, job, "NO_QUALITY_GATED_CANDIDATE")
                return
            encode_duration_ms = max(0, (time.perf_counter_ns() - started) // 1_000_000)
            ENCODE_DURATION.labels(content_type=input_type).observe(encode_duration_ms / 1_000)
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
                connection.execute(
                    """
                    INSERT INTO artifacts (
                      id, tenant_subject, job_id, candidate_id, kind,
                      object_key, bytes, sha256
                    ) VALUES (%s, %s, %s, %s, 'candidate', %s, %s, %s)
                    """,
                    (
                        str(uuid4()),
                        tenant_subject,
                        job_id,
                        candidate_id,
                        object_key,
                        len(candidate.payload),
                        hashlib.sha256(candidate.payload).digest(),
                    ),
                )
                persisted.append((candidate_id, len(candidate.payload), object_key))
            connection.commit()

            self._transition(connection, job_id, tenant_subject, "MEASURING", "SELECTING")
            selected = self._select_candidate(persisted, job["target_bytes"])
            if selected is None:
                self._terminal_failure(connection, job, "TARGET_BYTES_UNSATISFIED")
                return
            selected_id, selected_bytes, selected_key = selected
            OUTPUT_BYTES.labels(content_type=input_type).inc(selected_bytes)
            COMPRESSION_RATIO.labels(content_type=input_type).observe(
                len(source_bytes) / max(selected_bytes, 1)
            )
            connection.execute(
                """
                UPDATE artifacts SET kind = 'compressed'
                WHERE candidate_id = %s AND tenant_subject = %s
                """,
                (selected_id, tenant_subject),
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
            self._emit_outbox(
                connection,
                tenant_subject,
                str(updated["project_id"]),
                "compression.completed",
                job_id,
                {
                    "compression_id": job_id,
                    "selected_candidate_id": selected_id,
                    "payload_bytes": selected_bytes,
                },
            )
            connection.execute(
                """
                UPDATE source_objects AS source
                SET delete_after = now() + (
                  COALESCE(project.original_retention_seconds, %s) * interval '1 second'
                )
                FROM projects AS project
                WHERE source.id = %s AND source.tenant_subject = %s
                  AND project.id = source.project_id
                  AND project.tenant_subject = source.tenant_subject
                  AND source.delete_after IS NULL
                """,
                (
                    self.settings.delete_originals_after_seconds,
                    job["source_object_id"],
                    tenant_subject,
                ),
            )
            connection.commit()

    def process_capsule(self, capsule_id: str, tenant_subject: str) -> None:
        with psycopg.connect(self.settings.database_url, row_factory=dict_row) as connection:
            capsule = connection.execute(
                """
                SELECT c.*, p.report, p.ecc_percent
                FROM capsules c
                JOIN capsule_plans p
                  ON p.id = c.plan_id AND p.tenant_subject = c.tenant_subject
                WHERE c.id = %s AND c.tenant_subject = %s
                """,
                (capsule_id, tenant_subject),
            ).fetchone()
            if not capsule:
                raise ValueError("capsule does not exist for tenant")
            if capsule["status"] in {"COMPLETED", "FAILED_TERMINAL"}:
                return
            if capsule["status"] != "PENDING" and not self._recover_simple_job(
                connection, "capsules", capsule
            ):
                return
            claimed = connection.execute(
                """
                UPDATE capsules SET status = 'BUILDING'
                WHERE id = %s AND tenant_subject = %s AND status = 'PENDING'
                RETURNING id
                """,
                (capsule_id, tenant_subject),
            ).fetchone()
            if not claimed:
                connection.rollback()
                raise RuntimeError("capsule claim lost")
            connection.commit()

            raw_selections = capsule["report"].get("selections", [])
            selections = [
                selection
                for selection in raw_selections
                if selection.get("candidate_id") and selection.get("artifact_id")
            ]
            if not selections:
                raise ValueError("capsule plan selected no artifacts")
            artifact_ids = [selection["artifact_id"] for selection in selections]
            artifacts = connection.execute(
                """
                SELECT a.id AS artifact_id, a.object_key, a.bytes, a.sha256,
                       a.candidate_id, a.job_id, c.codec_id, c.codec_version,
                       j.input_type
                FROM artifacts a
                JOIN encoding_candidates c
                  ON c.id = a.candidate_id AND c.tenant_subject = a.tenant_subject
                JOIN compression_jobs j
                  ON j.id = a.job_id AND j.tenant_subject = a.tenant_subject
                WHERE a.tenant_subject = %s
                  AND j.project_id = %s
                  AND a.id = ANY(%s::uuid[])
                  AND c.quality_gate_passed = true
                """,
                (tenant_subject, capsule["project_id"], artifact_ids),
            ).fetchall()
            by_artifact = {str(row["artifact_id"]): row for row in artifacts}
            if len(by_artifact) != len(artifact_ids):
                raise ValueError("capsule plan references an unavailable artifact")

            payloads: list[tuple[dict[str, Any], dict[str, Any], bytes]] = []
            for selection in selections:
                artifact = by_artifact[str(selection["artifact_id"])]
                response = self.s3.get_object(
                    Bucket=self.settings.s3_bucket, Key=artifact["object_key"]
                )
                payload = response["Body"].read(int(artifact["bytes"]) + 1)
                if len(payload) != int(artifact["bytes"]):
                    raise ValueError("capsule artifact size mismatch")
                if hashlib.sha256(payload).digest() != bytes(artifact["sha256"]):
                    raise ValueError("capsule artifact hash mismatch")
                payloads.append((selection, artifact, payload))

            with tempfile.TemporaryDirectory(prefix="smcp-capsule-") as directory:
                root = Path(directory)
                sections = self._write_capsule_sections(
                    root, capsule_id, int(capsule["budget_bytes"]), payloads
                )
                output = root / "capsule.smcp"
                command = [
                    "smcp-capsule",
                    "build",
                    "--output",
                    str(output),
                    "--budget",
                    str(capsule["budget_bytes"]),
                    "--capsule-id",
                    capsule_id,
                    "--ecc-percent",
                    str(int(capsule["ecc_percent"])),
                ]
                if bool(capsule["build_options"].get("pad_to_budget", False)):
                    command.append("--pad")
                for kind, path in sections:
                    command.extend(("--section", f"{kind}={path}"))
                build_report = json.loads(run(command).stdout)
                changed = connection.execute(
                    """
                    UPDATE capsules SET status = 'VERIFYING'
                    WHERE id = %s AND tenant_subject = %s AND status = 'BUILDING'
                    RETURNING id
                    """,
                    (capsule_id, tenant_subject),
                ).fetchone()
                if not changed:
                    connection.rollback()
                    raise RuntimeError("capsule state changed before verification")
                connection.commit()
                verify_report = json.loads(run(("smcp-capsule", "verify", str(output))).stdout)
                encoded = output.read_bytes()

            if not verify_report.get("valid"):
                raise ValueError("capsule verifier rejected output")
            CAPSULE_FILL_RATIO.observe(len(encoded) / max(int(capsule["budget_bytes"]), 1))
            digest = hashlib.sha256(encoded).hexdigest()
            if digest != build_report.get("sha256"):
                raise ValueError("capsule build digest mismatch")
            object_key = f"{tenant_subject}/{capsule['project_id']}/capsules/{capsule_id}.smcp"
            self.s3.put_object(
                Bucket=self.settings.s3_bucket,
                Key=object_key,
                Body=encoded,
                ContentType="application/vnd.smcp.capsule",
                ServerSideEncryption="AES256",
                Metadata={"sha256": digest, "verified": "true"},
            )
            completed = connection.execute(
                """
                UPDATE capsules
                SET status = 'COMPLETED', actual_bytes = %s, object_key = %s,
                    sha256 = %s, merkle_root = %s, format_major = 1,
                    format_minor = 0, completed_at = now(), error_code = NULL
                WHERE id = %s AND tenant_subject = %s AND status = 'VERIFYING'
                RETURNING project_id
                """,
                (
                    len(encoded),
                    object_key,
                    bytes.fromhex(digest),
                    bytes.fromhex(verify_report["merkle_root"]),
                    capsule_id,
                    tenant_subject,
                ),
            ).fetchone()
            if not completed:
                connection.rollback()
                raise RuntimeError("capsule state changed before completion")
            for ordinal, (selection, artifact, payload) in enumerate(payloads):
                connection.execute(
                    """
                    INSERT INTO capsule_entries (
                      tenant_subject, capsule_id, ordinal, artifact_id,
                      candidate_id, utility, encoded_bytes
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        tenant_subject,
                        capsule_id,
                        ordinal,
                        artifact["artifact_id"],
                        artifact["candidate_id"],
                        int(selection["utility"]),
                        len(payload),
                    ),
                )
            connection.execute(
                """
                INSERT INTO audit_events (
                  tenant_subject, project_id, actor_subject, action, resource_type,
                  resource_id, request_id, outcome, metadata
                ) VALUES (%s, %s, 'compression-worker', 'capsule.completed',
                          'capsule', %s, %s, 'success', %s)
                """,
                (
                    tenant_subject,
                    completed["project_id"],
                    capsule_id,
                    f"worker:{capsule_id}",
                    json.dumps(
                        {
                            "actual_bytes": len(encoded),
                            "sha256": digest,
                            "entry_count": len(payloads),
                        },
                        sort_keys=True,
                    ),
                ),
            )
            self._emit_outbox(
                connection,
                tenant_subject,
                str(completed["project_id"]),
                "capsule.completed",
                capsule_id,
                {
                    "capsule_id": capsule_id,
                    "actual_bytes": len(encoded),
                    "budget_bytes": int(capsule["budget_bytes"]),
                    "sha256": digest,
                    "merkle_root": verify_report["merkle_root"],
                },
            )
            connection.commit()

    @staticmethod
    def _emit_outbox(
        connection: psycopg.Connection[Any],
        tenant_subject: str,
        project_id: str,
        topic: str,
        aggregate_id: str,
        payload: dict[str, Any],
    ) -> None:
        connection.execute(
            """
            INSERT INTO outbox_events (
              tenant_subject, project_id, topic, aggregate_id, payload
            ) VALUES (%s, %s, %s, %s, %s)
            """,
            (
                tenant_subject,
                project_id,
                topic,
                aggregate_id,
                json.dumps(payload, sort_keys=True, separators=(",", ":")),
            ),
        )

    @staticmethod
    def _write_capsule_sections(
        root: Path,
        capsule_id: str,
        budget_bytes: int,
        payloads: list[tuple[dict[str, Any], dict[str, Any], bytes]],
    ) -> list[tuple[str, Path]]:
        root.mkdir(parents=True, exist_ok=True)
        codecs = sorted({(row[1]["codec_id"], row[1]["codec_version"]) for row in payloads})
        registry = bytearray(CompressionWorker._varint(len(codecs)))
        for codec_id, version in codecs:
            registry.extend(CompressionWorker._length_prefixed(codec_id.encode()))
            registry.extend(CompressionWorker._length_prefixed(version.encode()))

        kind_names = {
            "TEXT": "text",
            "IMAGE": "image",
            "AUDIO": "audio",
            "VIDEO": "video",
        }
        kind_codes = {"TEXT": 1, "IMAGE": 2, "AUDIO": 3, "VIDEO": 4}
        streams: dict[str, bytearray] = {}
        index_records: list[bytes] = []
        manifest = bytearray(UUID(capsule_id).bytes)
        manifest.extend(struct.pack("<Q", budget_bytes))
        for selection, artifact, payload in payloads:
            input_type = str(artifact["input_type"])
            stream = streams.setdefault(input_type, bytearray())
            prefix = CompressionWorker._varint(len(payload))
            offset = len(stream) + len(prefix)
            stream.extend(prefix)
            stream.extend(payload)
            record = bytearray(UUID(str(artifact["job_id"])).bytes)
            record.extend(UUID(str(artifact["candidate_id"])).bytes)
            record.append(kind_codes[input_type])
            record.extend(CompressionWorker._varint(offset))
            record.extend(CompressionWorker._varint(len(payload)))
            record.extend(hashlib.sha256(payload).digest())
            index_records.append(bytes(record))
            manifest.extend(UUID(str(artifact["artifact_id"])).bytes)
            manifest.extend(UUID(str(artifact["candidate_id"])).bytes)
            manifest.extend(struct.pack("<q", int(selection["utility"])))
            manifest.extend(hashlib.sha256(payload).digest())

        index = bytearray(CompressionWorker._varint(len(index_records)))
        for record_bytes in index_records:
            index.extend(record_bytes)
        section_payloads: list[tuple[str, bytes]] = [("codec-registry", bytes(registry))]
        for input_type in ("TEXT", "IMAGE", "AUDIO", "VIDEO"):
            if input_type in streams:
                section_payloads.append((kind_names[input_type], bytes(streams[input_type])))
        section_payloads.extend(
            (("index", bytes(index)), ("manifest-digest", hashlib.sha256(manifest).digest()))
        )
        result: list[tuple[str, Path]] = []
        for ordinal, (kind, payload) in enumerate(section_payloads):
            path = root / f"{ordinal:02d}-{kind}.bin"
            path.write_bytes(payload)
            result.append((kind, path))
        return result

    @staticmethod
    def _varint(value: int) -> bytes:
        if value < 0:
            raise ValueError("varint cannot encode a negative value")
        output = bytearray()
        while value >= 0x80:
            output.append((value & 0x7F) | 0x80)
            value >>= 7
        output.append(value)
        return bytes(output)

    @staticmethod
    def _length_prefixed(value: bytes) -> bytes:
        return CompressionWorker._varint(len(value)) + value

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
            if job["status"] != "PENDING" and not self._recover_simple_job(
                connection, "decompression_jobs", job
            ):
                return

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
            decode_started = time.perf_counter()
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
            DECODE_DURATION.labels(codec_id=candidate.codec_id).observe(
                time.perf_counter() - decode_started
            )

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
            self._emit_outbox(
                connection,
                tenant_subject,
                str(completed["project_id"]),
                "decompression.completed",
                decompression_id,
                {
                    "decompression_id": decompression_id,
                    "output_bytes": len(decoded),
                    "output_sha256": output_digest,
                    "verified": True,
                },
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
    def _select_candidate(
        candidates: list[tuple[str, int, str]], target_bytes: int | None
    ) -> tuple[str, int, str] | None:
        eligible = (
            candidates
            if target_bytes is None
            else [candidate for candidate in candidates if candidate[1] <= target_bytes]
        )
        return min(eligible, key=lambda item: (item[1], item[0])) if eligible else None

    def _media_limit_error(self, input_type: str, payload: bytes) -> str | None:
        if input_type == "TEXT":
            return None
        with tempfile.TemporaryDirectory(prefix="smcp-limit-probe-") as directory:
            path = Path(directory) / "input.bin"
            path.write_bytes(payload)
            command = [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0" if input_type in {"IMAGE", "VIDEO"} else "a:0",
            ]
            if input_type == "VIDEO":
                command.append("-count_frames")
            command.extend(
                (
                    "-show_entries",
                    "format=duration:stream=codec_type,width,height,duration,"
                    "avg_frame_rate,nb_read_frames",
                    "-of",
                    "json",
                    str(path),
                )
            )
            try:
                report = json.loads(run(command, timeout=60).stdout)
            except (
                json.JSONDecodeError,
                subprocess.CalledProcessError,
                subprocess.TimeoutExpired,
            ):
                return "MEDIA_PROBE_FAILED"
        streams = report.get("streams")
        if not isinstance(streams, list) or not streams or not isinstance(streams[0], dict):
            return "MEDIA_PROBE_FAILED"
        stream = streams[0]
        if input_type in {"IMAGE", "VIDEO"}:
            try:
                pixels = int(stream["width"]) * int(stream["height"])
            except (KeyError, TypeError, ValueError):
                return "MEDIA_PROBE_FAILED"
            pixel_limit = (
                self.settings.max_image_pixels
                if input_type == "IMAGE"
                else self.settings.max_video_pixels
            )
            if pixels <= 0 or pixels > pixel_limit:
                return "PIXEL_LIMIT_EXCEEDED"
        if input_type in {"AUDIO", "VIDEO"}:
            duration = self._probe_duration(report, stream)
            if duration is None:
                return "MEDIA_PROBE_FAILED"
            duration_limit = (
                self.settings.max_audio_seconds
                if input_type == "AUDIO"
                else self.settings.max_video_seconds
            )
            if duration > duration_limit:
                return "DURATION_LIMIT_EXCEEDED"
        if input_type == "VIDEO":
            if duration is None:
                return "MEDIA_PROBE_FAILED"
            frames = self._probe_frame_count(stream, duration)
            if frames is None:
                return "MEDIA_PROBE_FAILED"
            if frames > self.settings.max_video_frames:
                return "FRAME_LIMIT_EXCEEDED"
        return None

    @staticmethod
    def _probe_duration(report: dict[str, Any], stream: dict[str, Any]) -> float | None:
        format_info = report.get("format")
        format_duration = format_info.get("duration") if isinstance(format_info, dict) else None
        raw = format_duration or stream.get("duration")
        if raw is None:
            return None
        try:
            duration = float(raw)
        except (TypeError, ValueError):
            return None
        return duration if duration >= 0 else None

    @staticmethod
    def _probe_frame_count(stream: dict[str, Any], duration: float) -> int | None:
        raw_count = stream.get("nb_read_frames")
        if raw_count is not None and raw_count != "N/A":
            try:
                count = int(str(raw_count))
            except (TypeError, ValueError):
                return None
            return count if count >= 0 else None
        try:
            rate = Fraction(str(stream["avg_frame_rate"]))
        except (KeyError, ValueError, ZeroDivisionError):
            return None
        if rate <= 0:
            return None
        return int(duration * float(rate) + 0.999999)

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
        CompressionWorker._audit_worker_failure(
            connection,
            str(job["tenant_subject"]),
            str(job["project_id"]),
            "compression",
            str(job["id"]),
            code,
            "FAILED_TERMINAL",
            int(job["attempt"]),
        )
        connection.commit()

    @staticmethod
    def _terminal_decompression_failure(
        connection: psycopg.Connection[Any],
        decompression_id: str,
        tenant_subject: str,
        code: str,
    ) -> None:
        updated = connection.execute(
            """
            UPDATE decompression_jobs
            SET status = 'FAILED_TERMINAL', error_code = %s, completed_at = now()
            WHERE id = %s AND tenant_subject = %s
            RETURNING project_id, attempt
            """,
            (code, decompression_id, tenant_subject),
        ).fetchone()
        if updated:
            CompressionWorker._audit_worker_failure(
                connection,
                tenant_subject,
                str(updated["project_id"]),
                "decompression",
                decompression_id,
                code,
                "FAILED_TERMINAL",
                int(updated["attempt"]),
            )
        connection.commit()

    @staticmethod
    def _audit_worker_failure(
        connection: psycopg.Connection[Any],
        tenant_subject: str,
        project_id: str,
        job_type: str,
        job_id: str,
        code: str,
        status: str,
        attempt: int,
    ) -> None:
        resource_types = {
            "compression": "compression_job",
            "decompression": "decompression_job",
            "capsule": "capsule",
        }
        try:
            resource_type = resource_types[job_type]
        except KeyError as error:
            raise ValueError("unsupported audited worker job type") from error
        connection.execute(
            """
            INSERT INTO audit_events (
              tenant_subject, project_id, actor_subject, action, resource_type,
              resource_id, request_id, outcome, metadata
            ) VALUES (%s, %s, 'compression-worker', %s, %s, %s, %s, 'error', %s)
            """,
            (
                tenant_subject,
                project_id,
                f"{job_type}.failed",
                resource_type,
                job_id,
                f"worker:{job_id}",
                json.dumps({"attempt": attempt, "error_code": code, "status": status}),
            ),
        )

    def _recover_compression_job(
        self, connection: psycopg.Connection[Any], job: dict[str, Any]
    ) -> bool:
        """Reset a stale delivery to a clean, replayable compression attempt."""
        crashed = job["status"] != "FAILED_RETRYABLE"
        next_attempt = int(job["attempt"]) + int(crashed)
        rows = connection.execute(
            """
            SELECT object_key FROM encoding_candidates
            WHERE job_id = %s AND tenant_subject = %s
            """,
            (job["id"], job["tenant_subject"]),
        ).fetchall()
        self._delete_objects([str(row["object_key"]) for row in rows])
        connection.execute(
            """
            UPDATE compression_jobs SET selected_candidate_id = NULL
            WHERE id = %s AND tenant_subject = %s
            """,
            (job["id"], job["tenant_subject"]),
        )
        connection.execute(
            "DELETE FROM artifacts WHERE job_id = %s AND tenant_subject = %s",
            (job["id"], job["tenant_subject"]),
        )
        connection.execute(
            "DELETE FROM encoding_candidates WHERE job_id = %s AND tenant_subject = %s",
            (job["id"], job["tenant_subject"]),
        )
        if next_attempt >= self.settings.worker_max_attempts:
            connection.execute(
                """
                UPDATE compression_jobs
                SET status = 'FAILED_TERMINAL', attempt = %s,
                    error_code = 'RETRY_EXHAUSTED', completed_at = now()
                WHERE id = %s AND tenant_subject = %s
                """,
                (next_attempt, job["id"], job["tenant_subject"]),
            )
            self._audit_worker_failure(
                connection,
                str(job["tenant_subject"]),
                str(job["project_id"]),
                "compression",
                str(job["id"]),
                "RETRY_EXHAUSTED",
                "FAILED_TERMINAL",
                next_attempt,
            )
            connection.commit()
            return False
        connection.execute(
            """
            UPDATE compression_jobs
            SET status = 'PENDING', attempt = %s, started_at = NULL,
                completed_at = NULL, error_code = NULL, error_detail_redacted = NULL
            WHERE id = %s AND tenant_subject = %s
            """,
            (next_attempt, job["id"], job["tenant_subject"]),
        )
        connection.commit()
        return True

    def _recover_simple_job(
        self,
        connection: psycopg.Connection[Any],
        table: str,
        job: dict[str, Any],
    ) -> bool:
        crashed = job["status"] != "FAILED_RETRYABLE"
        next_attempt = int(job["attempt"]) + int(crashed)
        queries = {
            "capsules": (
                """
                UPDATE capsules
                SET status = 'FAILED_TERMINAL', attempt = %s,
                    error_code = 'RETRY_EXHAUSTED', completed_at = now()
                WHERE id = %s AND tenant_subject = %s
                """,
                """
                UPDATE capsules
                SET status = 'PENDING', attempt = %s,
                    error_code = NULL, completed_at = NULL
                WHERE id = %s AND tenant_subject = %s
                """,
            ),
            "decompression_jobs": (
                """
                UPDATE decompression_jobs
                SET status = 'FAILED_TERMINAL', attempt = %s,
                    error_code = 'RETRY_EXHAUSTED', completed_at = now()
                WHERE id = %s AND tenant_subject = %s
                """,
                """
                UPDATE decompression_jobs
                SET status = 'PENDING', attempt = %s,
                    error_code = NULL, completed_at = NULL
                WHERE id = %s AND tenant_subject = %s
                """,
            ),
        }
        try:
            terminal_query, retry_query = queries[table]
        except KeyError as error:
            raise ValueError("unsupported recovery table") from error
        if next_attempt >= self.settings.worker_max_attempts:
            connection.execute(
                terminal_query,
                (next_attempt, job["id"], job["tenant_subject"]),
            )
            self._audit_worker_failure(
                connection,
                str(job["tenant_subject"]),
                str(job["project_id"]),
                "capsule" if table == "capsules" else "decompression",
                str(job["id"]),
                "RETRY_EXHAUSTED",
                "FAILED_TERMINAL",
                next_attempt,
            )
            connection.commit()
            return False
        connection.execute(
            retry_query,
            (next_attempt, job["id"], job["tenant_subject"]),
        )
        connection.commit()
        return True

    def _delete_objects(self, object_keys: list[str]) -> None:
        for offset in range(0, len(object_keys), 1_000):
            chunk = object_keys[offset : offset + 1_000]
            if chunk:
                self.s3.delete_objects(
                    Bucket=self.settings.s3_bucket,
                    Delete={"Objects": [{"Key": key} for key in chunk], "Quiet": True},
                )

    @staticmethod
    def _retention_retry_seconds(attempt: int) -> int:
        return int(min(3_600, 30 * (2 ** max(0, attempt - 1))))

    def _delete_due_originals(self) -> None:
        claim_token = str(uuid4())
        with psycopg.connect(self.settings.database_url, row_factory=dict_row) as connection:
            rows = connection.execute(
                """
                WITH due AS (
                  SELECT id
                  FROM source_objects
                  WHERE delete_after <= now() AND deleted_at IS NULL
                    AND (
                      deletion_claimed_at IS NULL
                      OR deletion_claimed_at < now() - interval '5 minutes'
                    )
                  ORDER BY delete_after, id
                  FOR UPDATE SKIP LOCKED
                  LIMIT %s
                )
                UPDATE source_objects AS source
                SET deletion_claimed_at = now(), deletion_claim_token = %s,
                    deletion_error_redacted = NULL
                FROM due
                WHERE source.id = due.id
                RETURNING source.id, source.tenant_subject, source.project_id,
                          source.object_key, source.deletion_attempt
                """,
                (self.settings.deletion_batch_size, claim_token),
            ).fetchall()
            connection.commit()
            for row in rows:
                source_id = str(row["id"])
                try:
                    self.s3.delete_object(
                        Bucket=self.settings.s3_bucket,
                        Key=str(row["object_key"]),
                    )
                    deleted = connection.execute(
                        """
                        UPDATE source_objects
                        SET deleted_at = now(), deletion_attempt = deletion_attempt + 1,
                            deletion_claimed_at = NULL, deletion_claim_token = NULL,
                            deletion_error_redacted = NULL
                        WHERE id = %s AND tenant_subject = %s
                          AND deleted_at IS NULL AND deletion_claim_token = %s
                        RETURNING id
                        """,
                        (source_id, row["tenant_subject"], claim_token),
                    ).fetchone()
                    if deleted is None:
                        connection.rollback()
                        continue
                    connection.execute(
                        """
                        INSERT INTO audit_events (
                          tenant_subject, project_id, actor_subject, action,
                          resource_type, resource_id, request_id, outcome, metadata
                        ) VALUES (
                          %s, %s, 'compression-worker', 'source.deleted',
                          'source_object', %s, %s, 'success', %s
                        )
                        """,
                        (
                            row["tenant_subject"],
                            row["project_id"],
                            source_id,
                            f"worker-retention:{claim_token}:{source_id}",
                            json.dumps({"deletion_attempt": int(row["deletion_attempt"]) + 1}),
                        ),
                    )
                except Exception as error:
                    connection.rollback()
                    attempt = int(row["deletion_attempt"]) + 1
                    LOGGER.warning(
                        "original deletion failed",
                        extra={"source_id": source_id, "error_class": type(error).__name__},
                    )
                    connection.execute(
                        """
                        UPDATE source_objects
                        SET deletion_attempt = %s, deletion_claimed_at = NULL,
                            deletion_claim_token = NULL, deletion_error_redacted = %s,
                            delete_after = now() + (%s * interval '1 second')
                        WHERE id = %s AND tenant_subject = %s AND deleted_at IS NULL
                          AND deletion_claim_token = %s
                        """,
                        (
                            attempt,
                            type(error).__name__,
                            self._retention_retry_seconds(attempt),
                            source_id,
                            row["tenant_subject"],
                            claim_token,
                        ),
                    )
                connection.commit()

    def _fail_job(self, stream: str, job_id: str, tenant_subject: str, code: str) -> bool:
        with psycopg.connect(self.settings.database_url, row_factory=dict_row) as connection:
            if stream == COMPRESSION_STREAM:
                row = connection.execute(
                    """
                    UPDATE compression_jobs
                    SET status = (
                          CASE WHEN attempt + 1 >= %s
                               THEN 'FAILED_TERMINAL' ELSE 'FAILED_RETRYABLE' END
                        )::job_status,
                        error_code = CASE WHEN attempt + 1 >= %s
                                          THEN 'RETRY_EXHAUSTED' ELSE %s END,
                        completed_at = CASE WHEN attempt + 1 >= %s THEN now() ELSE NULL END,
                        attempt = attempt + 1
                    WHERE id = %s AND tenant_subject = %s
                      AND status NOT IN ('COMPLETED', 'FAILED_TERMINAL', 'CANCELLED')
                    RETURNING status, project_id, error_code, attempt
                    """,
                    (
                        self.settings.worker_max_attempts,
                        self.settings.worker_max_attempts,
                        code,
                        self.settings.worker_max_attempts,
                        job_id,
                        tenant_subject,
                    ),
                ).fetchone()
            elif stream == DECOMPRESSION_STREAM:
                row = connection.execute(
                    """
                    UPDATE decompression_jobs
                    SET status = CASE WHEN attempt + 1 >= %s
                                      THEN 'FAILED_TERMINAL' ELSE 'FAILED_RETRYABLE' END,
                        error_code = CASE WHEN attempt + 1 >= %s
                                          THEN 'RETRY_EXHAUSTED' ELSE %s END,
                        completed_at = CASE WHEN attempt + 1 >= %s THEN now() ELSE NULL END,
                        attempt = attempt + 1
                    WHERE id = %s AND tenant_subject = %s
                      AND status NOT IN ('COMPLETED', 'FAILED_TERMINAL')
                    RETURNING status, project_id, error_code, attempt
                    """,
                    (
                        self.settings.worker_max_attempts,
                        self.settings.worker_max_attempts,
                        code,
                        self.settings.worker_max_attempts,
                        job_id,
                        tenant_subject,
                    ),
                ).fetchone()
            elif stream == CAPSULE_STREAM:
                row = connection.execute(
                    """
                    UPDATE capsules
                    SET status = CASE WHEN attempt + 1 >= %s
                                      THEN 'FAILED_TERMINAL' ELSE 'FAILED_RETRYABLE' END,
                        error_code = CASE WHEN attempt + 1 >= %s
                                          THEN 'RETRY_EXHAUSTED' ELSE %s END,
                        completed_at = CASE WHEN attempt + 1 >= %s THEN now() ELSE NULL END,
                        attempt = attempt + 1
                    WHERE id = %s AND tenant_subject = %s
                      AND status NOT IN ('COMPLETED', 'FAILED_TERMINAL')
                    RETURNING status, project_id, error_code, attempt
                    """,
                    (
                        self.settings.worker_max_attempts,
                        self.settings.worker_max_attempts,
                        code,
                        self.settings.worker_max_attempts,
                        job_id,
                        tenant_subject,
                    ),
                ).fetchone()
            else:
                raise ValueError("unknown worker stream")
            if row is not None:
                job_type = {
                    COMPRESSION_STREAM: "compression",
                    DECOMPRESSION_STREAM: "decompression",
                    CAPSULE_STREAM: "capsule",
                }[stream]
                self._audit_worker_failure(
                    connection,
                    tenant_subject,
                    str(row["project_id"]),
                    job_type,
                    job_id,
                    str(row["error_code"]),
                    str(row["status"]),
                    int(row["attempt"]),
                )
            connection.commit()
            return row is None or row["status"] == "FAILED_TERMINAL"
