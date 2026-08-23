# Neural codec operations

Neural model weights are external runtime artifacts. They are never committed, embedded in an image or downloaded by a build, import or worker startup.

## CoD-Lite approval and runtime

The selected CoD-Lite checkpoint is the official 0.0312-bpp model. The catalog pins its Hugging Face revision, MIT model-card evidence, weight/configuration URLs and both SHA-256 values. The GenCodec implementation is pinned separately to its immutable Git commit.

The runtime is published in two phases to avoid a self-referential image digest:

1. `.github/workflows/cod-lite-runtime.yml` builds, scans and publishes `ghcr.io/d590900/smcp-cod-lite-runtime:gen-c49eb0d643cc`. This base contains the worker adapter, the pinned GenCodec source and hash-locked CUDA 12.4 dependencies, but no model weights and no newly approved catalog.
2. The published manifest digest, `sha256:791454206faacd38b9b4126f89a998a2d2ff9761f8cd1dcdc81e7030022035cf`, is recorded as `decoder_image_digest` in `model-manifests/catalog.json`.
3. `.github/workflows/cod-lite-worker.yml` overlays the enabled catalog onto that exact runtime, rescans the resulting image, generates its SBOM and publishes `ghcr.io/d590900/smcp-worker-cod-lite:cod-lite-bpp-0.0312` with provenance and SBOM attestations.

The runtime requires an NVIDIA host compatible with CUDA 12.4. `SMCP_COD_LITE_ROOT`, `SMCP_COD_LITE_PYTHON` and `SMCP_MODEL_CACHE` are set in the image. The model cache must be a persistent external volume writable only during the explicit fetch step and mounted read-only during normal worker operation.

After the catalog contains the published decoder digest, choose the published worker image (pin its final digest in production), create a private cache owned by the image's non-root `smcp` user and run the explicit fetch as that same UID:

```console
export SMCP_COD_LITE_WORKER=ghcr.io/d590900/smcp-worker-cod-lite:cod-lite-bpp-0.0312
export SMCP_UID=$(docker run --rm --entrypoint /usr/bin/id "$SMCP_COD_LITE_WORKER" -u smcp)
export SMCP_GID=$(docker run --rm --entrypoint /usr/bin/id "$SMCP_COD_LITE_WORKER" -g smcp)
sudo install -d -o "$SMCP_UID" -g "$SMCP_GID" -m 0700 /var/lib/smcp/models
docker run --rm --user "$SMCP_UID:$SMCP_GID" \
  --mount type=bind,src=/var/lib/smcp/models,dst=/var/lib/smcp/models \
  --entrypoint /opt/venv/bin/python "$SMCP_COD_LITE_WORKER" \
  -m smcp_worker.model_manifest fetch /opt/worker/model-manifests/catalog.json \
  cod-lite bpp-0.0312-hf-cfda8135320f --cache /var/lib/smcp/models
```

The fetcher downloads both `weights.bin` and `config.yaml` through private temporary files, checks their declared sizes and SHA-256 values, then installs them mode `0400` below a mode `0700` version directory. Running the fetch as the serving UID makes those files readable by `smcp` without granting write access during service operation. The adapter rechecks both hashes when the cache identity changes and refuses inference after any mismatch. User-namespace-remapped or rootless installations should map ownership to the effective container UID reported by their runtime.

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

## SNAC 24 kHz approval and runtime

The official `hubertsiuzdak/snac_24khz` checkpoint at immutable Hugging Face revision `d73ad176a12188fcf4f360ba3bf2c2fbbe8f58ec` declares MIT terms independently from the pinned MIT implementation. The catalog records the exact 79,488,254-byte weight hash and 300-byte configuration hash. The real adapter accepts canonical mono signed 16-bit PCM at 24 kHz up to 60 seconds and stores the three hierarchical 4096-entry codebooks in a bounded, versioned, canonical 12-bit token container; it never serializes tensors with pickle. Longer audio remains eligible for the Opus baseline in `ultra` mode and is not sent to the one-shot neural runtime.

`.github/workflows/snac-runtime.yml` builds the CPU-only, hash-locked runtime, explicitly fetches and verifies the external checkpoint after the build, exercises a real encode/decode round trip, scans the exact image and publishes it only on manual dispatch. Run `32649508981` published and attested the runtime as `ghcr.io/d590900/smcp-snac-runtime@sha256:1a21bda431cd81b45115819736b16f53bc12f35e7dc8e86b1c6470873292078c`; the catalog pins that immutable decoder contract.

Fetch the checkpoint into an external cache as the container UID, seal files read-only, then start the derived worker with the cache mounted read-only:

```console
docker run --rm --user root \
  --mount type=bind,source="$PWD/model-cache",target=/var/lib/smcp/models \
  --entrypoint /bin/sh \
  ghcr.io/d590900/smcp-worker-snac:snac-24khz \
  -c 'chown smcp:smcp /var/lib/smcp/models && chmod 0700 /var/lib/smcp/models'
docker run --rm \
  --mount type=bind,source="$PWD/model-cache",target=/var/lib/smcp/models \
  --entrypoint /opt/venv/bin/python \
  ghcr.io/d590900/smcp-worker-snac:snac-24khz \
  -m smcp_worker.model_manifest fetch \
  /opt/worker/model-manifests/catalog.json snac 24khz-hf-d73ad176a121 \
  --cache /var/lib/smcp/models
docker run --rm \
  --mount type=bind,source="$PWD/model-cache",target=/var/lib/smcp/models,readonly \
  ghcr.io/d590900/smcp-worker-snac:snac-24khz
```

Production deployments must replace the convenience worker tag with the digest emitted by the `snac-worker` workflow artifact. The catalog pins the smaller runtime digest because it is the immutable decoding contract shared by derived workers.

## Mimi 24 kHz approval and runtime

The official `kyutai/mimi` checkpoint at immutable Hugging Face revision `89091b3e466eb6a9d11e537bf26b144f194978f7` declares CC-BY-4.0 terms. Its real adapter uses the Apache-2.0 Transformers 5.5.0 implementation pinned to commit `c1c34249fa27deefbd4a377dfbf883a39baf5c6d`, accepts canonical mono signed 16-bit PCM at 24 kHz up to 30 seconds, and stores eight 2048-entry codebooks at 12.5 Hz in a bounded, versioned, canonical 11-bit token container. It loads the exact 384,649,828-byte `safetensors` checkpoint without pickle.

The CPU-only runtime has a hash-locked dependency graph and keeps the checkpoint external. Local Linux/amd64 validation verified both declared artifact hashes, deterministic double encoding, a real decode to exactly 24 kHz mono with the original 0.5-second duration, and a 99-byte canonical token payload for a 24,078-byte PCM test input. `.github/workflows/mimi-runtime.yml` repeats these gates and scans the exact image. Run `32652654491` published and attested `ghcr.io/d590900/smcp-mimi-runtime@sha256:e053c39c169accd02b775e46b6b1e344449b8207ff5c175741fc6dce69b7a8ff`; the catalog pins that immutable decoder contract.

Fetch the checkpoint into an external cache as the container UID, seal files read-only, then start the derived worker with the cache mounted read-only:

```console
docker run --rm --user root \
  --mount type=bind,source="$PWD/model-cache",target=/var/lib/smcp/models \
  --entrypoint /bin/sh \
  ghcr.io/d590900/smcp-worker-mimi:mimi-24khz \
  -c 'chown smcp:smcp /var/lib/smcp/models && chmod 0700 /var/lib/smcp/models'
docker run --rm \
  --mount type=bind,source="$PWD/model-cache",target=/var/lib/smcp/models \
  --entrypoint /opt/venv/bin/python \
  ghcr.io/d590900/smcp-worker-mimi:mimi-24khz \
  -m smcp_worker.model_manifest fetch \
  /opt/worker/model-manifests/catalog.json mimi 24khz-hf-89091b3e466e \
  --cache /var/lib/smcp/models
docker run --rm \
  --mount type=bind,source="$PWD/model-cache",target=/var/lib/smcp/models,readonly \
  ghcr.io/d590900/smcp-worker-mimi:mimi-24khz
```

Production deployments must replace the convenience worker tag with the digest emitted by the `mimi-worker` workflow artifact. The catalog pins the smaller runtime digest because it is the immutable decoding contract shared by derived workers.
