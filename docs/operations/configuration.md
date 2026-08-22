# Configuration

Copy `.env.example` to `.env` and set secrets locally. Compose development credentials are isolated defaults, not production credentials.

## Clerk

Create a Clerk development instance with Organizations enabled. Set the publishable and secret keys. API keys are created by the backend with the active organization as `subject`, the requested `scopes`, bounded `secondsUntilExpiration`, and claims containing `smcp_issued: true`. The secret is rendered once and never persisted by SMCP.

Production refuses development authentication bypasses. Protected E2E CI supplies a Clerk test instance; forks run the verifier contract suite without external secrets.

## Storage and retention

Buckets must be private, encrypted and deny anonymous listing. Signed URLs default to five minutes. `DELETE_ORIGINALS_AFTER_SECONDS=0` means delete after successful verification; a positive value schedules bounded retention. Deletion preserves only content-free audit facts.

## Optional codecs

Optional neural adapters are disabled until an operator installs pinned dependencies, places externally obtained weights in the immutable model cache and validates their manifests. No application path downloads weights.

## CPU codec runtime

The production worker contains Brotli, Zstandard, libavif, JPEG XL, Opus and SVT-AV1/dav1d. FFmpeg 9.0.1 is built from the release tarball only after its signature and signing-key fingerprint are verified. The build uses `--disable-gpl`; do not replace it with a distribution FFmpeg package without reviewing `ffmpeg -buildconf` and the resulting image license obligations.

`GET /v1/codecs` requires `codecs:read` and returns both enabled baselines and disabled optional model families. Disabled entries include a reason and installation/manifest guidance. `GET /v1/models` returns only immutable manifests actually registered in PostgreSQL.

Baseline media gates currently enforce:

- images: four-scale structural similarity and PSNR; LPIPS and face identity remain explicitly unevaluated until versioned metric weights are approved;
- audio: canonical mono 24 kHz PCM duration and clipping; ASR intelligibility, speaker similarity and learned perceptual metrics remain explicitly unevaluated;
- generic video: VMAF when available, otherwise SSIM, plus duration and temporal-stability proxy; talking-head classification, pose and lip-sync require the disabled versioned model path.

A metric marked `not_evaluated` is never treated as a successful learned quality assertion. Project-configurable learned thresholds remain M3/M5 work.
