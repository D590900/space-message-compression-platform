# Model manifests

Optional neural codecs remain disabled until a manifest in this directory contains immutable, independently verified code and weight provenance and a real decoder runtime is registered. Builds and imports never download weights. CoD-Lite, SNAC, Mimi, EnCodec 48 kHz and detector-free LivePortrait are enabled and pin their published CUDA and CPU runtimes by digest.

`catalog.json` pins the reviewed implementation revision, parameter origin and license evidence for every optional family. CoD-Lite's selected 0.0312-bpp checkpoint and SNAC 24 kHz have separately reviewed MIT terms, while Mimi 24 kHz pins Apache-2.0 Transformers code and CC-BY-4.0 checkpoint terms. EnCodec 48 kHz separately declares MIT checkpoint terms in its official immutable model card and uses the same pinned Apache-2.0 Transformers runtime. LivePortrait pins its four official MIT human-model files and excludes every InsightFace, landmark and retargeting artifact. All approved external checkpoints use immutable Hugging Face revisions and verified weight/configuration hashes. Cool-Chic image/video and HiNeRV replace CompressAI, MLVC and DCVC with per-asset neural representations: their parameters are created during encoding, embedded in the authenticated stream and require no external model artifact. Only entries with published decoder images may be enabled. An implementation repository license alone is not evidence for an independently published checkpoint license.

Validate the catalog:

```console
uv run python -m smcp_worker.model_manifest validate model-manifests/catalog.json
```

An enabled entry must additionally provide either one HTTPS weight URL/hash pair or a list of independently named and hashed weight artifacts, an HTTPS configuration URL/hash, weight-license evidence, an immutable decoder image digest, an input contract and an installed adapter entrypoint. Only then can an operator explicitly fetch the artifacts into an external immutable cache:

```console
uv run python -m smcp_worker.model_manifest fetch model-manifests/catalog.json \
  MODEL_ID VERSION --cache /var/lib/smcp/models
```

The fetch command writes through private temporary files, verifies every SHA-256 value, marks the results read-only and atomically installs them as `weights.bin` plus `config.yaml`, or as the declared multi-file checkpoint set plus `config.yaml`. Builds, imports and catalog validation never download weights.

The two-phase runtime publication and external-cache procedure are documented in [`docs/operations/neural-codecs.md`](../../../docs/operations/neural-codecs.md).
