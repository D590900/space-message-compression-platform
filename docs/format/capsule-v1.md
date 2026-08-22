# SMCP Capsule Format v1

All integers are little-endian. Encoders must produce canonical section ordering and decoders must reject non-canonical layouts. The strict budget includes the fixed header, section table, every payload, Merkle root, ECC and optional padding.

## Fixed header (64 bytes)

| Offset | Bytes | Field                                |
| -----: | ----: | ------------------------------------ |
|      0 |     8 | Magic `SMCPCAP\0`                    |
|      8 |     2 | Major version (`1`)                  |
|     10 |     2 | Minor version (`0`)                  |
|     12 |     4 | Required flags (zero in v1)          |
|     16 |     8 | Declared budget                      |
|     24 |    16 | Capsule UUID bytes                   |
|     40 |     4 | Section count                        |
|     44 |     4 | Header size (`64`)                   |
|     48 |     8 | Exact total encoded bytes            |
|     56 |     4 | CRC32C of the complete section table |
|     60 |     4 | Reserved zero                        |

## Section table

Each 64-byte entry contains: kind `u16`, flags `u16`, offset `u64`, length `u64`, payload CRC32C `u32`, reserved `u32`, payload SHA-256 `[u8;32]`, reserved `u32`. Payloads are contiguous in table order; gaps, overlaps, duplicate kinds and trailing bytes are invalid.

Kinds are codec registry (1), model registry (2), text/image/audio/motion/generic-video streams (10–14), record index (20), manifest digest (30), Merkle root (31), Reed–Solomon ECC (40), and zero padding (255). JSON and Base64 are not valid stream or registry encodings.

## Caller-supplied binary payloads

Unsigned integers inside caller-supplied sections use canonical unsigned LEB128. Strings and byte strings are `length varint || bytes`.

The codec registry is `codec_count varint` followed by lexicographically sorted, unique pairs of length-prefixed UTF-8 codec ID and version. Each content stream is a sequence of `payload_length varint || compressed_payload`; the record index points to the payload byte after its length prefix.

The record index is `record_count varint` followed by records in plan-selection order. Each record is job UUID `[u8;16]`, candidate UUID `[u8;16]`, content kind `u8` (`1` text, `2` image, `3` audio, `4` video), stream payload offset varint, payload length varint, and payload SHA-256 `[u8;32]`.

The reconstruction manifest remains external and tenant-scoped in PostgreSQL. Its capsule binding is SHA-256 over the canonical binary sequence: capsule UUID, declared budget `u64`, then for every selected entry its artifact UUID, candidate UUID, utility `i64`, and payload SHA-256. Only that 32-byte digest is embedded in the capsule.

## Integrity

Each section has CRC32C for quick corruption detection and SHA-256 for strong identity. Merkle leaves hash `kind || flags || payload`; an odd node is duplicated at each level. The root covers all preceding caller-supplied sections.

ECC protects the concatenation of protected section payloads through fixed ten-data-shard Reed–Solomon encoding. Its binary header is data shard count `u16`, parity shard count `u16`, shard length `u32`, protected length `u32`, followed by parity shards. Parity count is the configured percentage rounded upward and clamped to at least one when enabled.

The reference implementation validates every conversion and slice boundary before access, caps section count and total bytes, contains no `unsafe`, and emits no output when the serialized result exceeds the declared budget.
