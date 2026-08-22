# Model manifests

Optional neural codecs remain disabled until a manifest in this directory contains immutable, independently verified code and weight provenance. Builds and imports never download weights.

`catalog.json` pins the reviewed implementation revision and code-license evidence for every optional family. Weight terms remain `UNKNOWN` until independently verified, so every entry is disabled. That is intentional: an implementation repository license is not evidence for a checkpoint license.

Validate the catalog:

```console
uv run python -m smcp_worker.model_manifest validate model-manifests/catalog.json
```

An enabled entry must additionally provide an HTTPS weight URL, SHA-256 for weights and configuration, weight-license evidence, immutable decoder image digest, input contract and installed adapter entrypoint. Only then can an operator explicitly fetch weights into an external immutable cache:

```console
uv run python -m smcp_worker.model_manifest fetch model-manifests/catalog.json \
  MODEL_ID VERSION --cache /var/lib/smcp/models
```

The fetch command writes through a private temporary file, verifies SHA-256, marks the result read-only and atomically installs it. Builds, imports and catalog validation never download weights.
