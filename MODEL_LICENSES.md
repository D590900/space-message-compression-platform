# Model licenses

No model weights are stored in this repository or downloaded implicitly.

Each optional neural adapter remains disabled until its manifest records an official source, immutable code revision, weights checksum, configuration checksum, code license, **separately verified weights license**, input contract and decoder image digest. `UNKNOWN`, absent or non-redistributable weight terms block packaging and release.

| Adapter family | Code license | Weights license | Default state |
| --- | --- | --- | --- |
| CompressAI | To verify at pinned revision | To verify per checkpoint | Disabled |
| CoD-Lite / GenCodec | To verify at pinned revision | To verify per checkpoint | Disabled |
| SNAC | To verify at pinned revision | To verify per checkpoint | Disabled |
| Mimi | To verify at pinned revision | To verify per checkpoint | Disabled |
| EnCodec | To verify at pinned revision | To verify per checkpoint | Disabled |
| MLVC / DCVC | To verify at pinned revision | To verify per checkpoint | Disabled |
| Talking-head motion model | To verify at pinned revision | To verify per checkpoint | Disabled |

Verification evidence belongs in `services/compression-worker/model-manifests/`; release CI validates checksums and rejects placeholders.

