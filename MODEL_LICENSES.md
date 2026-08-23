# Model licenses

No model weights are stored in this repository or downloaded implicitly.

Each optional neural adapter remains disabled until its manifest records an official source, immutable code revision, code license, parameter origin, input contract and decoder image digest. External checkpoints additionally require immutable URLs, checksums and separately verified weight terms. Per-asset models must prove that the encoder creates every parameter from the input and embeds it in the authenticated bitstream. `UNKNOWN`, absent or non-redistributable terms block packaging and release.

| Adapter family         | Pinned code revision                       | Verified code license | Weights license                                            | State           |
| ---------------------- | ------------------------------------------ | --------------------- | ---------------------------------------------------------- | --------------- |
| Cool-Chic image        | `a6fe38a414dd098b39c41636bd6e423626402f7e` | BSD-3-Clause          | BSD-3-Clause — generated per image; no checkpoint          | Runtime pending |
| CoD-Lite / GenCodec    | `c49eb0d643cc75e6c732cbc311a508627b54cf06` | MIT                   | MIT — 0.0312-bpp checkpoint at HF revision `cfda8135…`     | Enabled (CUDA)  |
| SNAC                   | `8f79a718f1ad71f94f79999f0071348227aff22e` | MIT                   | MIT — 24 kHz checkpoint at HF revision `d73ad176…`         | Enabled (CPU)   |
| Mimi / Transformers    | `c1c34249fa27deefbd4a377dfbf883a39baf5c6d` | Apache-2.0            | CC-BY-4.0 — official model card at HF revision `89091b3e…` | Enabled (CPU)   |
| EnCodec / Transformers | `c1c34249fa27deefbd4a377dfbf883a39baf5c6d` | Apache-2.0            | MIT — official 48 kHz model at HF revision `c3def8e7…`     | Enabled (CPU)   |
| Cool-Chic video        | `a6fe38a414dd098b39c41636bd6e423626402f7e` | BSD-3-Clause          | BSD-3-Clause — generated per frame; no checkpoint          | Runtime pending |
| HiNeRV video           | `fdb92ec22492246f800621dfd454f6a5c62ab75b` | MIT                   | MIT — trained per video; no checkpoint                     | Runtime pending |
| LivePortrait           | `9b294b3d0536135442ea73cb01e6cb3ca7029dd3` | MIT                   | MIT — detector-free core at HF revision `82a4fa67…`        | Enabled (CPU)   |

Pinned evidence URLs and exact disable reasons are in `services/compression-worker/model-manifests/catalog.json`. The validator rejects unknown terms, missing external-artifact hashes, mutable decoder references or incomplete input contracts for any entry marked enabled. CoD-Lite, SNAC, Mimi, EnCodec and LivePortrait have immutable decoder digests recorded in the catalog and keep weights external. LivePortrait pins only its four MIT core checkpoints and deliberately excludes the non-commercial InsightFace models. Cool-Chic image/video and HiNeRV use only per-asset parameters covered by their pinned implementation licenses; publication of their audited decoder images is the remaining activation gate.
