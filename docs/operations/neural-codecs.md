# Neural codec operations

Neural model weights are external runtime artifacts. They are never committed, embedded in an image or downloaded by a build, import or worker startup.

## CoD-Lite approval and runtime

The selected CoD-Lite checkpoint is the official 0.0312-bpp model. The catalog pins its Hugging Face revision, MIT model-card evidence, weight/configuration URLs and both SHA-256 values. The GenCodec implementation is pinned separately to its immutable Git commit.

The runtime is published in two phases to avoid a self-referential image digest:

1. `.github/workflows/cod-lite-runtime.yml` builds, scans and publishes `ghcr.io/d590900/smcp-cod-lite-runtime:gen-c49eb0d643cc`. This base contains the worker adapter, the pinned GenCodec source and hash-locked CUDA 12.4 dependencies, but no model weights and no newly approved catalog.
2. The published manifest digest, `sha256:791454206faacd38b9b4126f89a998a2d2ff9761f8cd1dcdc81e7030022035cf`, is recorded as `decoder_image_digest` in `model-manifests/catalog.json`.
3. `.github/workflows/cod-lite-worker.yml` overlays the enabled catalog onto that exact runtime, rescans the resulting image, generates its SBOM and publishes `ghcr.io/d590900/smcp-worker-cod-lite:cod-lite-bpp-0.0312` with provenance and SBOM attestations.

The runtime requires an NVIDIA host compatible with CUDA 12.4. `SMCP_COD_LITE_ROOT`, `SMCP_COD_LITE_PYTHON` and `SMCP_MODEL_CACHE` are set in the image. The model cache must be a persistent external volume writable only during the explicit fetch step and mounted read-only during normal worker operation.

After the catalog contains the published decoder digest, fetch the approved artifacts explicitly:

```console
cd services/compression-worker
uv run python -m smcp_worker.model_manifest fetch model-manifests/catalog.json \
  cod-lite bpp-0.0312-hf-cfda8135320f --cache /var/lib/smcp/models
```

The fetcher downloads both `weights.bin` and `config.yaml` through private temporary files, checks their declared sizes and SHA-256 values, then installs them read-only. The adapter rechecks both hashes when the cache identity changes and refuses inference after any mismatch.

Run the published GPU worker with the verified cache mounted read-only:

```console
docker run --rm --gpus all \
  --read-only --tmpfs /tmp:size=2g,mode=1777 \
  --mount type=bind,src=/var/lib/smcp/models,dst=/var/lib/smcp/models,readonly \
  --env-file .env \
  ghcr.io/d590900/smcp-worker-cod-lite:cod-lite-bpp-0.0312
```

Production deployments should pin the final worker by the digest emitted in the `cod-lite-worker` workflow artifact, not by its convenience tag. The model catalog intentionally pins the smaller decoder-runtime digest because it is the immutable decoding contract shared by derived workers.

Do not make the model cache writable by the serving process. Do not copy it into a container layer, CI artifact or source archive.
