//! Generate the committed deterministic Capsule Format v1 golden vector.

use std::fs;
use std::path::Path;

use sha2::{Digest, Sha256};
use smcp_capsule_format::{BuildOptions, Section, SectionKind, build, verify};
use uuid::Uuid;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let manifest = include_bytes!("../../../packages/test-vectors/capsules/v1-manifest.txt");
    let sections = vec![
        Section {
            kind: SectionKind::CodecRegistry,
            flags: 0,
            payload: b"\x01\x00\x0btext.brotli\x05BITEX".to_vec(),
        },
        Section {
            kind: SectionKind::TextStream,
            flags: 0,
            payload: b"golden deterministic message".to_vec(),
        },
        Section {
            kind: SectionKind::RecordIndex,
            flags: 0,
            payload: vec![1, 0, 0, 28],
        },
        Section {
            kind: SectionKind::ManifestDigest,
            flags: 0,
            payload: Sha256::digest(manifest).to_vec(),
        },
    ];
    let capsule = build(
        &sections,
        &BuildOptions {
            budget_bytes: 4_096,
            capsule_id: Uuid::from_bytes([0x42; 16]),
            ecc_percent: 20,
            pad_to_budget: false,
        },
    )?;
    verify(&capsule)?;
    let directory = Path::new("packages/test-vectors/capsules");
    fs::create_dir_all(directory)?;
    fs::write(directory.join("v1-golden.capsule"), &capsule)?;
    fs::write(
        directory.join("v1-golden.capsule.sha256"),
        format!(
            "{:x}  packages/test-vectors/capsules/v1-golden.capsule\n",
            Sha256::digest(&capsule)
        ),
    )?;
    Ok(())
}
