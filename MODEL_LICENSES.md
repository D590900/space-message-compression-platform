# Model licenses

No model weights are stored in this repository or downloaded implicitly.

Each optional neural adapter remains disabled until its manifest records an official source, immutable code revision, weights checksum, configuration checksum, code license, **separately verified weights license**, input contract and decoder image digest. `UNKNOWN`, absent or non-redistributable weight terms block packaging and release.

| Adapter family         | Pinned code revision                       | Verified code license | Weights license                                            | State           |
| ---------------------- | ------------------------------------------ | --------------------- | ---------------------------------------------------------- | --------------- |
| CompressAI             | `1c9e3eee83a8f4c8162d38b52f78f5b0c40de175` | BSD-3-Clause          | UNKNOWN — checkpoint-specific verification required        | Disabled        |
| CoD-Lite / GenCodec    | `c49eb0d643cc75e6c732cbc311a508627b54cf06` | MIT                   | MIT — 0.0312-bpp checkpoint at HF revision `cfda8135…`     | Enabled (CUDA)  |
| SNAC                   | `8f79a718f1ad71f94f79999f0071348227aff22e` | MIT                   | MIT — 24 kHz checkpoint at HF revision `d73ad176…`         | Enabled (CPU)   |
| Mimi / Transformers    | `c1c34249fa27deefbd4a377dfbf883a39baf5c6d` | Apache-2.0            | CC-BY-4.0 — official model card at HF revision `89091b3e…` | Enabled (CPU)   |
| EnCodec / Transformers | `c1c34249fa27deefbd4a377dfbf883a39baf5c6d` | Apache-2.0            | MIT — official 48 kHz model at HF revision `c3def8e7…`     | Enabled (CPU)   |
| MLVC                   | `f5b90b9abc4595f8790615b532f795b4582322f2` | MIT                   | UNKNOWN — checkpoint-specific verification required        | Disabled        |
| DCVC                   | `819c219b24db34310bbd15c51a720aaaf5eb2e7d` | MIT                   | UNKNOWN — checkpoint-specific verification required        | Disabled        |
| LivePortrait           | `9b294b3d0536135442ea73cb01e6cb3ca7029dd3` | MIT                   | MIT — detector-free core at HF revision `82a4fa67…`        | Runtime pending |

Pinned evidence URLs and exact disable reasons are in `services/compression-worker/model-manifests/catalog.json`. The validator rejects unknown weight terms, missing hashes, mutable decoder references or incomplete input contracts for any entry marked enabled. CoD-Lite, SNAC, Mimi and EnCodec have immutable decoder digests recorded in the catalog and keep weights external. LivePortrait pins only its four MIT core checkpoints and deliberately excludes the non-commercial InsightFace models; it remains fail-closed until its detector-free runtime is published. CompressAI, MLVC and DCVC still have `UNKNOWN` checkpoint terms.
