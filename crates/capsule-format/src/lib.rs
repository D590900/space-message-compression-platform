//! SMCP Capsule Format v1.
//!
//! The encoder is canonical and deterministic. It never emits a byte vector larger
//! than the declared budget, and the parser performs all bounds checks before slicing.

use std::collections::BTreeSet;

use crc32c::crc32c;
use reed_solomon_erasure::galois_8::ReedSolomon;
use sha2::{Digest, Sha256};
use thiserror::Error;
use uuid::Uuid;

/// Fixed format magic, including its terminating zero byte.
pub const MAGIC: [u8; 8] = *b"SMCPCAP\0";
/// Encoded header size.
pub const HEADER_BYTES: usize = 64;
const HEADER_BYTES_U32: u32 = 64;
/// Encoded section-table entry size.
pub const SECTION_ENTRY_BYTES: usize = 64;
/// Maximum accepted section count.
pub const MAX_SECTIONS: usize = 4_096;
/// Maximum accepted capsule size (4 GiB).
pub const MAX_CAPSULE_BYTES: usize = 4 * 1024 * 1024 * 1024;

/// Semantic type of a capsule section.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
#[repr(u16)]
pub enum SectionKind {
    /// Deduplicated codec registry.
    CodecRegistry = 1,
    /// Deduplicated model registry.
    ModelRegistry = 2,
    /// Lossless or semantic text stream.
    TextStream = 10,
    /// Image stream.
    ImageStream = 11,
    /// Audio stream.
    AudioStream = 12,
    /// Talking-head motion stream.
    MotionStream = 13,
    /// Generic video stream.
    GenericVideoStream = 14,
    /// Delta-coded record index.
    RecordIndex = 20,
    /// SHA-256 digest of the external reconstruction manifest.
    ManifestDigest = 30,
    /// Merkle root over every preceding protected section.
    MerkleRoot = 31,
    /// Reed–Solomon parity data.
    Ecc = 40,
    /// Optional zero padding.
    Padding = 255,
}

impl TryFrom<u16> for SectionKind {
    type Error = CapsuleError;

    fn try_from(value: u16) -> Result<Self, Self::Error> {
        Ok(match value {
            1 => Self::CodecRegistry,
            2 => Self::ModelRegistry,
            10 => Self::TextStream,
            11 => Self::ImageStream,
            12 => Self::AudioStream,
            13 => Self::MotionStream,
            14 => Self::GenericVideoStream,
            20 => Self::RecordIndex,
            30 => Self::ManifestDigest,
            31 => Self::MerkleRoot,
            40 => Self::Ecc,
            255 => Self::Padding,
            other => return Err(CapsuleError::UnknownSectionKind(other)),
        })
    }
}

/// Input section passed to the canonical builder.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Section {
    /// Section type.
    pub kind: SectionKind,
    /// Section flags; v1 requires zero for all known sections.
    pub flags: u16,
    /// Raw binary payload.
    pub payload: Vec<u8>,
}

/// Builder configuration.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BuildOptions {
    /// Hard maximum size including every header, table entry, parity byte and padding byte.
    pub budget_bytes: u64,
    /// Stable capsule identifier. Callers choose it; no randomness occurs inside the builder.
    pub capsule_id: Uuid,
    /// Reed–Solomon parity percentage in the inclusive range 0..=50.
    pub ecc_percent: u8,
    /// If true, append zero padding until the exact budget is reached.
    pub pad_to_budget: bool,
}

/// Parsed section metadata and borrowed payload.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ParsedSection<'a> {
    /// Section kind.
    pub kind: SectionKind,
    /// Section flags.
    pub flags: u16,
    /// Borrowed payload.
    pub payload: &'a [u8],
    /// Stored CRC32C.
    pub crc32c: u32,
    /// Stored SHA-256.
    pub sha256: [u8; 32],
}

/// Successfully parsed capsule.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ParsedCapsule<'a> {
    /// Declared strict budget.
    pub budget_bytes: u64,
    /// Capsule identifier.
    pub capsule_id: Uuid,
    /// All canonical sections.
    pub sections: Vec<ParsedSection<'a>>,
    /// Total encoded length.
    pub total_bytes: u64,
}

/// Verification summary.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerificationReport {
    /// Total bytes observed.
    pub actual_bytes: u64,
    /// Declared budget.
    pub budget_bytes: u64,
    /// Number of sections.
    pub section_count: usize,
    /// Verified Merkle root.
    pub merkle_root: [u8; 32],
    /// Whether Reed–Solomon parity is present and verified.
    pub ecc_verified: bool,
}

/// Capsule build or parse failure.
#[derive(Debug, Error, Eq, PartialEq)]
pub enum CapsuleError {
    /// Budget is outside supported limits.
    #[error("invalid capsule budget {0}")]
    InvalidBudget(u64),
    /// ECC percentage is outside the supported range.
    #[error("ECC percentage must be between 0 and 50")]
    InvalidEccPercent,
    /// Input sections violate canonical ordering or uniqueness.
    #[error("sections are not canonical: {0}")]
    NonCanonicalSections(&'static str),
    /// The fully serialized capsule would exceed its strict budget.
    #[error("capsule requires {actual} bytes but budget is {budget}")]
    BudgetExceeded {
        /// Actual required bytes.
        actual: u64,
        /// Declared maximum.
        budget: u64,
    },
    /// Input is truncated.
    #[error("truncated capsule")]
    Truncated,
    /// Magic does not identify SMCP.
    #[error("invalid capsule magic")]
    InvalidMagic,
    /// Unsupported major/minor version.
    #[error("unsupported capsule version {major}.{minor}")]
    UnsupportedVersion {
        /// Major version.
        major: u16,
        /// Minor version.
        minor: u16,
    },
    /// Header or section-table checksum mismatch.
    #[error("section table checksum mismatch")]
    TableChecksumMismatch,
    /// Unsupported required header/section flags.
    #[error("unsupported flags {0:#x}")]
    UnsupportedFlags(u32),
    /// Section type is not recognized.
    #[error("unknown section kind {0}")]
    UnknownSectionKind(u16),
    /// Section offsets overlap or are not canonical.
    #[error("invalid section layout")]
    InvalidLayout,
    /// Section payload checksum mismatch.
    #[error("section checksum mismatch for kind {0:?}")]
    SectionChecksumMismatch(SectionKind),
    /// Stored Merkle root is absent or incorrect.
    #[error("Merkle root mismatch")]
    MerkleMismatch,
    /// Reed–Solomon metadata or parity is invalid.
    #[error("ECC verification failed")]
    EccMismatch,
    /// Integer conversion or arithmetic overflow.
    #[error("integer overflow")]
    Overflow,
}

#[derive(Clone, Debug)]
struct EncodedEntry {
    kind: SectionKind,
    flags: u16,
    offset: u64,
    length: u64,
    crc32c: u32,
    sha256: [u8; 32],
}

/// Build a canonical capsule.
///
/// # Errors
///
/// Returns [`CapsuleError`] for invalid options or section ordering, arithmetic
/// overflow, ECC failure, or when the complete encoded result exceeds the budget.
pub fn build(sections: &[Section], options: &BuildOptions) -> Result<Vec<u8>, CapsuleError> {
    validate_options(options)?;
    validate_input_sections(sections)?;

    let mut canonical = sections.to_vec();
    let protected_root = merkle_root(&canonical);
    canonical.push(Section {
        kind: SectionKind::MerkleRoot,
        flags: 0,
        payload: protected_root.to_vec(),
    });

    if options.ecc_percent > 0 {
        let protected = concat_protected_payloads(&canonical);
        canonical.push(Section {
            kind: SectionKind::Ecc,
            flags: 0,
            payload: encode_ecc(&protected, options.ecc_percent)?,
        });
    }

    let unpadded_len = encoded_len(&canonical)?;
    if unpadded_len > options.budget_bytes {
        return Err(CapsuleError::BudgetExceeded {
            actual: unpadded_len,
            budget: options.budget_bytes,
        });
    }
    if options.pad_to_budget && unpadded_len < options.budget_bytes {
        // Adding a section costs a table entry. Only pad if room remains after that cost.
        let with_entry = unpadded_len
            .checked_add(SECTION_ENTRY_BYTES as u64)
            .ok_or(CapsuleError::Overflow)?;
        if with_entry <= options.budget_bytes {
            canonical.push(Section {
                kind: SectionKind::Padding,
                flags: 0,
                payload: vec![
                    0;
                    usize::try_from(options.budget_bytes - with_entry)
                        .map_err(|_| CapsuleError::Overflow)?
                ],
            });
        }
    }
    encode_capsule(&canonical, options)
}

const fn validate_options(options: &BuildOptions) -> Result<(), CapsuleError> {
    if options.budget_bytes < HEADER_BYTES as u64 || options.budget_bytes > MAX_CAPSULE_BYTES as u64
    {
        return Err(CapsuleError::InvalidBudget(options.budget_bytes));
    }
    if options.ecc_percent > 50 {
        return Err(CapsuleError::InvalidEccPercent);
    }
    Ok(())
}

fn validate_input_sections(sections: &[Section]) -> Result<(), CapsuleError> {
    if sections.len() + 2 > MAX_SECTIONS {
        return Err(CapsuleError::NonCanonicalSections("too many sections"));
    }
    let mut seen = BTreeSet::new();
    let mut previous = None;
    for section in sections {
        if matches!(
            section.kind,
            SectionKind::MerkleRoot | SectionKind::Ecc | SectionKind::Padding
        ) {
            return Err(CapsuleError::NonCanonicalSections(
                "derived section supplied by caller",
            ));
        }
        if section.flags != 0 {
            return Err(CapsuleError::NonCanonicalSections("non-zero section flags"));
        }
        if previous.is_some_and(|kind| kind >= section.kind) || !seen.insert(section.kind) {
            return Err(CapsuleError::NonCanonicalSections(
                "sections must be strictly ordered and unique",
            ));
        }
        previous = Some(section.kind);
    }
    if !seen.contains(&SectionKind::CodecRegistry)
        || !seen.contains(&SectionKind::RecordIndex)
        || !seen.contains(&SectionKind::ManifestDigest)
    {
        return Err(CapsuleError::NonCanonicalSections(
            "codec registry, record index and manifest digest are required",
        ));
    }
    if sections
        .iter()
        .find(|section| section.kind == SectionKind::ManifestDigest)
        .is_none_or(|section| section.payload.len() != 32)
    {
        return Err(CapsuleError::NonCanonicalSections(
            "manifest digest must contain exactly 32 bytes",
        ));
    }
    Ok(())
}

fn encoded_len(sections: &[Section]) -> Result<u64, CapsuleError> {
    let table = (sections.len() as u64)
        .checked_mul(SECTION_ENTRY_BYTES as u64)
        .ok_or(CapsuleError::Overflow)?;
    sections.iter().try_fold(
        (HEADER_BYTES as u64)
            .checked_add(table)
            .ok_or(CapsuleError::Overflow)?,
        |sum, section| {
            sum.checked_add(
                u64::try_from(section.payload.len()).map_err(|_| CapsuleError::Overflow)?,
            )
            .ok_or(CapsuleError::Overflow)
        },
    )
}

fn encode_capsule(sections: &[Section], options: &BuildOptions) -> Result<Vec<u8>, CapsuleError> {
    let total_len = encoded_len(sections)?;
    if total_len > options.budget_bytes {
        return Err(CapsuleError::BudgetExceeded {
            actual: total_len,
            budget: options.budget_bytes,
        });
    }
    let total_usize = usize::try_from(total_len).map_err(|_| CapsuleError::Overflow)?;
    let table_bytes = sections
        .len()
        .checked_mul(SECTION_ENTRY_BYTES)
        .ok_or(CapsuleError::Overflow)?;
    let mut offset = HEADER_BYTES
        .checked_add(table_bytes)
        .ok_or(CapsuleError::Overflow)?;
    let mut entries = Vec::with_capacity(sections.len());
    for section in sections {
        entries.push(EncodedEntry {
            kind: section.kind,
            flags: section.flags,
            offset: u64::try_from(offset).map_err(|_| CapsuleError::Overflow)?,
            length: u64::try_from(section.payload.len()).map_err(|_| CapsuleError::Overflow)?,
            crc32c: crc32c(&section.payload),
            sha256: sha256(&section.payload),
        });
        offset = offset
            .checked_add(section.payload.len())
            .ok_or(CapsuleError::Overflow)?;
    }

    let mut table = Vec::with_capacity(table_bytes);
    for entry in &entries {
        table.extend_from_slice(&(entry.kind as u16).to_le_bytes());
        table.extend_from_slice(&entry.flags.to_le_bytes());
        table.extend_from_slice(&entry.offset.to_le_bytes());
        table.extend_from_slice(&entry.length.to_le_bytes());
        table.extend_from_slice(&entry.crc32c.to_le_bytes());
        table.extend_from_slice(&0_u32.to_le_bytes());
        table.extend_from_slice(&entry.sha256);
        table.extend_from_slice(&0_u32.to_le_bytes());
    }
    debug_assert_eq!(table.len(), table_bytes);

    let mut output = Vec::with_capacity(total_usize);
    output.extend_from_slice(&MAGIC);
    output.extend_from_slice(&1_u16.to_le_bytes());
    output.extend_from_slice(&0_u16.to_le_bytes());
    output.extend_from_slice(&0_u32.to_le_bytes());
    output.extend_from_slice(&options.budget_bytes.to_le_bytes());
    output.extend_from_slice(options.capsule_id.as_bytes());
    output.extend_from_slice(
        &u32::try_from(sections.len())
            .map_err(|_| CapsuleError::Overflow)?
            .to_le_bytes(),
    );
    output.extend_from_slice(&HEADER_BYTES_U32.to_le_bytes());
    output.extend_from_slice(&total_len.to_le_bytes());
    output.extend_from_slice(&crc32c(&table).to_le_bytes());
    output.extend_from_slice(&0_u32.to_le_bytes());
    debug_assert_eq!(output.len(), HEADER_BYTES);
    output.extend_from_slice(&table);
    for section in sections {
        output.extend_from_slice(&section.payload);
    }
    debug_assert_eq!(output.len(), total_usize);
    Ok(output)
}

/// Parse and fully verify a capsule.
///
/// # Errors
///
/// Returns [`CapsuleError`] for any malformed, non-canonical, truncated, corrupt,
/// unsupported, over-budget or integrity-invalid input.
pub fn parse(input: &[u8]) -> Result<ParsedCapsule<'_>, CapsuleError> {
    if input.len() < HEADER_BYTES {
        return Err(CapsuleError::Truncated);
    }
    if input[..8] != MAGIC {
        return Err(CapsuleError::InvalidMagic);
    }
    let major = read_u16(input, 8)?;
    let minor = read_u16(input, 10)?;
    if (major, minor) != (1, 0) {
        return Err(CapsuleError::UnsupportedVersion { major, minor });
    }
    let flags = read_u32(input, 12)?;
    if flags != 0 {
        return Err(CapsuleError::UnsupportedFlags(flags));
    }
    let budget = read_u64(input, 16)?;
    let capsule_id = Uuid::from_bytes(
        input[24..40]
            .try_into()
            .map_err(|_| CapsuleError::Truncated)?,
    );
    let count = usize::try_from(read_u32(input, 40)?).map_err(|_| CapsuleError::Overflow)?;
    if count == 0 || count > MAX_SECTIONS {
        return Err(CapsuleError::InvalidLayout);
    }
    if read_u32(input, 44)? != HEADER_BYTES_U32 {
        return Err(CapsuleError::InvalidLayout);
    }
    let total = read_u64(input, 48)?;
    if total != input.len() as u64 || total > budget || input.len() > MAX_CAPSULE_BYTES {
        return Err(CapsuleError::InvalidLayout);
    }
    let table_len = count
        .checked_mul(SECTION_ENTRY_BYTES)
        .ok_or(CapsuleError::Overflow)?;
    let table_end = HEADER_BYTES
        .checked_add(table_len)
        .ok_or(CapsuleError::Overflow)?;
    let table = input
        .get(HEADER_BYTES..table_end)
        .ok_or(CapsuleError::Truncated)?;
    if crc32c(table) != read_u32(input, 56)? {
        return Err(CapsuleError::TableChecksumMismatch);
    }

    let mut parsed = Vec::with_capacity(count);
    let mut expected_offset = table_end;
    let mut previous = None;
    for index in 0..count {
        let base = index
            .checked_mul(SECTION_ENTRY_BYTES)
            .ok_or(CapsuleError::Overflow)?;
        let kind = SectionKind::try_from(read_u16(table, base)?)?;
        let section_flags = read_u16(table, base + 2)?;
        if section_flags != 0 {
            return Err(CapsuleError::UnsupportedFlags(u32::from(section_flags)));
        }
        if previous.is_some_and(|prior| prior >= kind) {
            return Err(CapsuleError::InvalidLayout);
        }
        previous = Some(kind);
        let offset =
            usize::try_from(read_u64(table, base + 4)?).map_err(|_| CapsuleError::Overflow)?;
        let length =
            usize::try_from(read_u64(table, base + 12)?).map_err(|_| CapsuleError::Overflow)?;
        if offset != expected_offset {
            return Err(CapsuleError::InvalidLayout);
        }
        let end = offset.checked_add(length).ok_or(CapsuleError::Overflow)?;
        let payload = input.get(offset..end).ok_or(CapsuleError::Truncated)?;
        expected_offset = end;
        let stored_crc = read_u32(table, base + 20)?;
        let stored_hash: [u8; 32] = table
            .get(base + 28..base + 60)
            .ok_or(CapsuleError::Truncated)?
            .try_into()
            .map_err(|_| CapsuleError::Truncated)?;
        if crc32c(payload) != stored_crc || sha256(payload) != stored_hash {
            return Err(CapsuleError::SectionChecksumMismatch(kind));
        }
        parsed.push(ParsedSection {
            kind,
            flags: section_flags,
            payload,
            crc32c: stored_crc,
            sha256: stored_hash,
        });
    }
    if expected_offset != input.len() {
        return Err(CapsuleError::InvalidLayout);
    }
    validate_parsed_sections(&parsed)?;
    verify_derived_sections(&parsed)?;
    Ok(ParsedCapsule {
        budget_bytes: budget,
        capsule_id,
        sections: parsed,
        total_bytes: total,
    })
}

fn validate_parsed_sections(sections: &[ParsedSection<'_>]) -> Result<(), CapsuleError> {
    let codec_index = sections
        .iter()
        .position(|section| section.kind == SectionKind::CodecRegistry);
    let record_index = sections
        .iter()
        .position(|section| section.kind == SectionKind::RecordIndex);
    let manifest_index = sections
        .iter()
        .position(|section| section.kind == SectionKind::ManifestDigest);
    let merkle_index = sections
        .iter()
        .position(|section| section.kind == SectionKind::MerkleRoot);
    if codec_index.is_none() || record_index.is_none() || manifest_index.is_none() {
        return Err(CapsuleError::NonCanonicalSections(
            "codec registry, record index and manifest digest are required",
        ));
    }
    let manifest_index = manifest_index.expect("checked above");
    if sections[manifest_index].payload.len() != 32 {
        return Err(CapsuleError::NonCanonicalSections(
            "manifest digest must contain exactly 32 bytes",
        ));
    }
    if merkle_index != Some(manifest_index + 1) {
        return Err(CapsuleError::NonCanonicalSections(
            "Merkle root must immediately follow the manifest digest",
        ));
    }
    Ok(())
}

/// Parse a capsule and return its integrity summary.
///
/// # Errors
///
/// Returns [`CapsuleError`] when full parsing, checksum, Merkle, ECC or budget
/// verification fails.
pub fn verify(input: &[u8]) -> Result<VerificationReport, CapsuleError> {
    let parsed = parse(input)?;
    let merkle = parsed
        .sections
        .iter()
        .find(|section| section.kind == SectionKind::MerkleRoot)
        .ok_or(CapsuleError::MerkleMismatch)?;
    Ok(VerificationReport {
        actual_bytes: parsed.total_bytes,
        budget_bytes: parsed.budget_bytes,
        section_count: parsed.sections.len(),
        merkle_root: merkle
            .payload
            .try_into()
            .map_err(|_| CapsuleError::MerkleMismatch)?,
        ecc_verified: parsed
            .sections
            .iter()
            .any(|section| section.kind == SectionKind::Ecc),
    })
}

fn verify_derived_sections(sections: &[ParsedSection<'_>]) -> Result<(), CapsuleError> {
    let merkle_index = sections
        .iter()
        .position(|section| section.kind == SectionKind::MerkleRoot)
        .ok_or(CapsuleError::MerkleMismatch)?;
    let leaves: Vec<Section> = sections[..merkle_index]
        .iter()
        .map(|section| Section {
            kind: section.kind,
            flags: section.flags,
            payload: section.payload.to_vec(),
        })
        .collect();
    if sections[merkle_index].payload != merkle_root(&leaves) {
        return Err(CapsuleError::MerkleMismatch);
    }
    if let Some(ecc) = sections
        .iter()
        .find(|section| section.kind == SectionKind::Ecc)
    {
        let protected: Vec<u8> = sections[..=merkle_index]
            .iter()
            .flat_map(|section| section.payload.iter().copied())
            .collect();
        verify_ecc(&protected, ecc.payload)?;
    }
    if let Some(padding) = sections
        .iter()
        .find(|section| section.kind == SectionKind::Padding)
        && padding.payload.iter().any(|byte| *byte != 0)
    {
        return Err(CapsuleError::InvalidLayout);
    }
    Ok(())
}

fn merkle_root(sections: &[Section]) -> [u8; 32] {
    let mut level: Vec<[u8; 32]> = sections
        .iter()
        .map(|section| {
            let mut hasher = Sha256::new();
            hasher.update((section.kind as u16).to_le_bytes());
            hasher.update(section.flags.to_le_bytes());
            hasher.update(&section.payload);
            hasher.finalize().into()
        })
        .collect();
    if level.is_empty() {
        return sha256(&[]);
    }
    while level.len() > 1 {
        if level.len() % 2 == 1 {
            level.push(*level.last().expect("non-empty Merkle level"));
        }
        let (pairs, remainder) = level.as_chunks::<2>();
        debug_assert!(remainder.is_empty());
        level = pairs
            .iter()
            .map(|pair| {
                let mut hasher = Sha256::new();
                hasher.update(pair[0]);
                hasher.update(pair[1]);
                hasher.finalize().into()
            })
            .collect();
    }
    level[0]
}

fn concat_protected_payloads(sections: &[Section]) -> Vec<u8> {
    sections
        .iter()
        .flat_map(|section| section.payload.iter().copied())
        .collect()
}

fn encode_ecc(protected: &[u8], ecc_percent: u8) -> Result<Vec<u8>, CapsuleError> {
    let data_shards = 10_usize;
    let parity_shards = usize::from(ecc_percent)
        .checked_mul(data_shards)
        .ok_or(CapsuleError::Overflow)?
        .div_ceil(100)
        .max(1);
    let shard_len = protected.len().div_ceil(data_shards).max(1);
    let mut shards = vec![vec![0_u8; shard_len]; data_shards + parity_shards];
    for (index, byte) in protected.iter().enumerate() {
        shards[index / shard_len][index % shard_len] = *byte;
    }
    ReedSolomon::new(data_shards, parity_shards)
        .map_err(|_| CapsuleError::EccMismatch)?
        .encode(&mut shards)
        .map_err(|_| CapsuleError::EccMismatch)?;
    let mut payload = Vec::with_capacity(12 + parity_shards * shard_len);
    payload.extend_from_slice(
        &u16::try_from(data_shards)
            .map_err(|_| CapsuleError::Overflow)?
            .to_le_bytes(),
    );
    payload.extend_from_slice(
        &u16::try_from(parity_shards)
            .map_err(|_| CapsuleError::Overflow)?
            .to_le_bytes(),
    );
    payload.extend_from_slice(
        &u32::try_from(shard_len)
            .map_err(|_| CapsuleError::Overflow)?
            .to_le_bytes(),
    );
    payload.extend_from_slice(
        &u32::try_from(protected.len())
            .map_err(|_| CapsuleError::Overflow)?
            .to_le_bytes(),
    );
    for shard in &shards[data_shards..] {
        payload.extend_from_slice(shard);
    }
    Ok(payload)
}

fn verify_ecc(protected: &[u8], payload: &[u8]) -> Result<(), CapsuleError> {
    if payload.len() < 12 {
        return Err(CapsuleError::EccMismatch);
    }
    let data_shards = usize::from(read_u16(payload, 0)?);
    let parity_shards = usize::from(read_u16(payload, 2)?);
    let shard_len = usize::try_from(read_u32(payload, 4)?).map_err(|_| CapsuleError::Overflow)?;
    let protected_len =
        usize::try_from(read_u32(payload, 8)?).map_err(|_| CapsuleError::Overflow)?;
    if data_shards == 0
        || parity_shards == 0
        || protected_len != protected.len()
        || payload.len() != 12 + parity_shards * shard_len
    {
        return Err(CapsuleError::EccMismatch);
    }
    let mut shards = vec![vec![0_u8; shard_len]; data_shards + parity_shards];
    for (index, byte) in protected.iter().enumerate() {
        let shard = index / shard_len;
        if shard >= data_shards {
            return Err(CapsuleError::EccMismatch);
        }
        shards[shard][index % shard_len] = *byte;
    }
    for parity_index in 0..parity_shards {
        let start = 12 + parity_index * shard_len;
        shards[data_shards + parity_index].copy_from_slice(&payload[start..start + shard_len]);
    }
    ReedSolomon::new(data_shards, parity_shards)
        .map_err(|_| CapsuleError::EccMismatch)?
        .verify(&shards)
        .map_err(|_| CapsuleError::EccMismatch)?
        .then_some(())
        .ok_or(CapsuleError::EccMismatch)
}

fn sha256(input: &[u8]) -> [u8; 32] {
    Sha256::digest(input).into()
}

fn read_u16(input: &[u8], offset: usize) -> Result<u16, CapsuleError> {
    Ok(u16::from_le_bytes(
        input
            .get(offset..offset + 2)
            .ok_or(CapsuleError::Truncated)?
            .try_into()
            .map_err(|_| CapsuleError::Truncated)?,
    ))
}

fn read_u32(input: &[u8], offset: usize) -> Result<u32, CapsuleError> {
    Ok(u32::from_le_bytes(
        input
            .get(offset..offset + 4)
            .ok_or(CapsuleError::Truncated)?
            .try_into()
            .map_err(|_| CapsuleError::Truncated)?,
    ))
}

fn read_u64(input: &[u8], offset: usize) -> Result<u64, CapsuleError> {
    Ok(u64::from_le_bytes(
        input
            .get(offset..offset + 8)
            .ok_or(CapsuleError::Truncated)?
            .try_into()
            .map_err(|_| CapsuleError::Truncated)?,
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parser_rejects_self_consistent_capsule_without_required_sections() {
        let sections = vec![Section {
            kind: SectionKind::MerkleRoot,
            flags: 0,
            payload: sha256(&[]).to_vec(),
        }];
        let options = BuildOptions {
            budget_bytes: 1_024,
            capsule_id: Uuid::nil(),
            ecc_percent: 0,
            pad_to_budget: false,
        };
        let encoded = encode_capsule(&sections, &options).expect("test capsule encodes");

        assert!(matches!(
            parse(&encoded),
            Err(CapsuleError::NonCanonicalSections(
                "codec registry, record index and manifest digest are required"
            ))
        ));
    }
}
