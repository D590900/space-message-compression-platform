# Model manifests

Optional neural codecs remain disabled until a manifest in this directory contains immutable, independently verified code and weight provenance and a real decoder runtime is registered. Builds and imports never download weights. CoD-Lite and SNAC are enabled and pin their published CUDA and CPU runtimes by digest. Mimi has passed the provenance and local real-inference gates but remains disabled pending runtime publication.

`catalog.json` pins the reviewed implementation revision and code-license evidence for every optional family. CoD-Lite's selected 0.0312-bpp checkpoint and SNAC 24 kHz have separately reviewed MIT terms, immutable Hugging Face revisions, verified weight/configuration hashes and published decoder images. Mimi 24 kHz pins Apache-2.0 Transformers code, CC-BY-4.0 checkpoint evidence, an immutable Hugging Face revision and verified weight/configuration hashes; it will be enabled only after its decoder image digest is published. The other five families' weight terms remain `UNKNOWN`. An implementation repository license alone is not evidence for a checkpoint license.

Validate the catalog:

```console
uv run python -m smcp_worker.model_manifest validate model-manifests/catalog.json
```

An enabled entry must additionally provide HTTPS weight and configuration URLs, SHA-256 for both files, weight-license evidence, immutable decoder image digest, input contract and installed adapter entrypoint. Only then can an operator explicitly fetch both artifacts into an external immutable cache:

```console
uv run python -m smcp_worker.model_manifest fetch model-manifests/catalog.json \
  MODEL_ID VERSION --cache /var/lib/smcp/models
```

The fetch command writes through private temporary files, verifies both SHA-256 values, marks the results read-only and atomically installs them as `weights.bin` and `config.yaml`. Builds, imports and catalog validation never download weights.

The two-phase runtime publication and external-cache procedure are documented in [`docs/operations/neural-codecs.md`](../../../docs/operations/neural-codecs.md).
