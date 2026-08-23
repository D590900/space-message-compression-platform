# Neural codec operations

Neural model weights are external runtime artifacts. They are never committed, embedded in an image or downloaded by a build, import or worker startup.

## CoD-Lite approval and runtime

The selected CoD-Lite checkpoint is the official 0.0312-bpp model. The catalog pins its Hugging Face revision, MIT model-card evidence, weight/configuration URLs and both SHA-256 values. The GenCodec implementation is pinned separately to its immutable Git commit.

The runtime is published in two phases to avoid a self-referential image digest:

1. `.github/workflows/cod-lite-runtime.yml` builds, scans and publishes `ghcr.io/d590900/smcp-cod-lite-runtime:gen-c49eb0d643cc`. This base contains the worker adapter, the pinned GenCodec source and hash-locked CUDA 12.4 dependencies, but no model weights and no newly approved catalog.
2. The published manifest digest is recorded as `decoder_image_digest` in `model-manifests/catalog.json`. Only then may the catalog entry become enabled and a final worker image inherit the audited runtime by digest.

The runtime requires an NVIDIA host compatible with CUDA 12.4. `SMCP_COD_LITE_ROOT`, `SMCP_COD_LITE_PYTHON` and `SMCP_MODEL_CACHE` are set in the image. The model cache must be a persistent external volume writable only during the explicit fetch step and mounted read-only during normal worker operation.

After the catalog contains the published decoder digest, fetch the approved artifacts explicitly:

```console
cd services/compression-worker
uv run python -m smcp_worker.model_manifest fetch model-manifests/catalog.json \
  cod-lite bpp-0.0312-hf-cfda8135320f --cache /var/lib/smcp/models
```

The fetcher downloads both `weights.bin` and `config.yaml` through private temporary files, checks their declared sizes and SHA-256 values, then installs them read-only. The adapter rechecks both hashes when the cache identity changes and refuses inference after any mismatch.

Do not make the model cache writable by the serving process. Do not copy it into a container layer, CI artifact or source archive.
