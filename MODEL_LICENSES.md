# Model licenses

No model weights are stored in this repository or downloaded implicitly.

Each optional neural adapter remains disabled until its manifest records an official source, immutable code revision, weights checksum, configuration checksum, code license, **separately verified weights license**, input contract and decoder image digest. `UNKNOWN`, absent or non-redistributable weight terms block packaging and release.

| Adapter family      | Pinned code revision                       | Verified code license | Weights license                                            | State          |
| ------------------- | ------------------------------------------ | --------------------- | ---------------------------------------------------------- | -------------- |
| CompressAI          | `1c9e3eee83a8f4c8162d38b52f78f5b0c40de175` | BSD-3-Clause          | UNKNOWN — checkpoint-specific verification required        | Disabled       |
| CoD-Lite / GenCodec | `c49eb0d643cc75e6c732cbc311a508627b54cf06` | MIT                   | MIT — 0.0312-bpp checkpoint at HF revision `cfda8135…`     | Enabled (CUDA) |
| SNAC                | `8f79a718f1ad71f94f79999f0071348227aff22e` | MIT                   | MIT — 24 kHz checkpoint at HF revision `d73ad176…`         | Enabled (CPU)  |
| Mimi / Moshi        | `e6a55d2722a65870ef52a6c9f6ecfc0e90f38362` | Apache-2.0            | UNKNOWN — model-card verification required                 | Disabled       |
| EnCodec             | `0e2d0aed29362c8e8f52494baf3e6f99056b214f` | MIT                   | UNKNOWN — production/redistribution approval required      | Disabled       |
| MLVC                | `f5b90b9abc4595f8790615b532f795b4582322f2` | MIT                   | UNKNOWN — checkpoint-specific verification required        | Disabled       |
| DCVC                | `819c219b24db34310bbd15c51a720aaaf5eb2e7d` | MIT                   | UNKNOWN — checkpoint-specific verification required        | Disabled       |
| LivePortrait        | `9b294b3d0536135442ea73cb01e6cb3ca7029dd3` | MIT                   | UNKNOWN — every transitive detector/model must be reviewed | Disabled       |

Pinned evidence URLs and exact disable reasons are in `services/compression-worker/model-manifests/catalog.json`. The validator rejects unknown weight terms, missing hashes, mutable decoder references or incomplete input contracts for any entry marked enabled. CoD-Lite and SNAC have immutable decoder digests recorded in the catalog and keep weights external. Every other unregistered family still fails closed if toggled on without implementation work.
