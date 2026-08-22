# Configuration

Copy `.env.example` to `.env` and set secrets locally. Compose development credentials are isolated defaults, not production credentials.

## Clerk

Create a Clerk development instance with Organizations enabled. Set the publishable and secret keys. API keys are created by the backend with the active organization as `subject`, the requested `scopes`, bounded `secondsUntilExpiration`, and claims containing `smcp_issued: true`. The secret is rendered once and never persisted by SMCP.

Production refuses development authentication bypasses. Protected E2E CI supplies a Clerk test instance; forks run the verifier contract suite without external secrets.

## Storage and retention

Buckets must be private, encrypted and deny anonymous listing. Signed URLs default to five minutes. `DELETE_ORIGINALS_AFTER_SECONDS=0` means delete after successful verification; a positive value schedules bounded retention. Deletion preserves only content-free audit facts.

## Optional codecs

Optional neural adapters are disabled until an operator installs pinned dependencies, places externally obtained weights in the immutable model cache and validates their manifests. No application path downloads weights.

