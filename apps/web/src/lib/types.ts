export type Project = {
  id: string;
  name: string;
  quality_policy: Record<string, unknown>;
  original_retention_seconds: number | null;
  created_at: string;
};

export type CompressionStatus =
  | "PENDING"
  | "VALIDATING"
  | "ENCODING"
  | "MEASURING"
  | "SELECTING"
  | "PACKAGING"
  | "COMPLETED"
  | "FAILED_RETRYABLE"
  | "FAILED_TERMINAL"
  | "CANCELLED";

export type Compression = {
  id: string;
  project_id: string;
  input_type: "TEXT" | "IMAGE" | "AUDIO" | "VIDEO";
  profile: "faithful" | "ultra" | "semantic";
  target_bytes: number | null;
  status: CompressionStatus;
  source_object_id: string;
  selected_candidate_id: string | null;
  requested_at: string;
  completed_at: string | null;
  error_code: string | null;
};

export type Candidate = {
  id: string;
  codec_id: string;
  codec_version: string;
  model_id: string | null;
  payload_bytes: number;
  container_overhead_bytes: number;
  quality_metrics: Record<string, unknown>;
  quality_gate_passed: boolean;
  encode_duration_ms: number;
  decode_duration_ms: number;
  determinism_status: string;
  sha256_hex: string;
};

export type Artifact = {
  id: string;
  project_id: string;
  job_id: string;
  candidate_id: string | null;
  kind: string;
  bytes: number;
  sha256_hex: string;
  created_at: string;
};

export type Capsule = {
  id: string;
  project_id: string;
  budget_bytes: number;
  actual_bytes: number | null;
  sha256_hex: string | null;
  merkle_root_hex: string | null;
  status: string;
  created_at: string;
};

export type Page<T> = { total_count: number; data: T[] };
