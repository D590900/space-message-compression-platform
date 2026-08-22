//! Capsule format integration, property and corruption tests.

use proptest::prelude::*;
use smcp_capsule_format::{
    BuildOptions, CapsuleError, MAGIC, Section, SectionKind, build, parse, verify,
};
use uuid::Uuid;

const fn options(budget: u64) -> BuildOptions {
    BuildOptions {
        budget_bytes: budget,
        capsule_id: Uuid::from_bytes([0x11; 16]),
        ecc_percent: 20,
        pad_to_budget: false,
    }
}

fn sections() -> Vec<Section> {
    vec![
        Section {
            kind: SectionKind::CodecRegistry,
            flags: 0,
            payload: b"\x01\x0btext.brotli\x05".to_vec(),
        },
        Section {
            kind: SectionKind::TextStream,
            flags: 0,
            payload: b"deterministic payload".to_vec(),
        },
        Section {
            kind: SectionKind::RecordIndex,
            flags: 0,
            payload: vec![0, 1, 0, 21],
        },
        Section {
            kind: SectionKind::ManifestDigest,
            flags: 0,
            payload: vec![0xA5; 32],
        },
    ]
}

#[test]
fn deterministic_round_trip_with_ecc() {
    let first = build(&sections(), &options(2_000_000)).unwrap();
    let second = build(&sections(), &options(2_000_000)).unwrap();
    assert_eq!(first, second);
    assert_eq!(&first[..8], &MAGIC);
    let parsed = parse(&first).unwrap();
    assert_eq!(parsed.capsule_id, Uuid::from_bytes([0x11; 16]));
    assert!(verify(&first).unwrap().ecc_verified);
}

#[test]
fn hard_budget_is_never_exceeded() {
    let error = build(&sections(), &options(128)).unwrap_err();
    assert!(matches!(error, CapsuleError::BudgetExceeded { .. }));
}

#[test]
fn exact_padding_respects_budget() {
    let mut config = options(2_000);
    config.ecc_percent = 0;
    config.pad_to_budget = true;
    let encoded = build(&sections(), &config).unwrap();
    assert_eq!(encoded.len(), 2_000);
    assert_eq!(parse(&encoded).unwrap().total_bytes, 2_000);
}

#[test]
fn corrupt_payload_is_rejected() {
    let mut encoded = build(&sections(), &options(2_000_000)).unwrap();
    let last = encoded.len() - 1;
    encoded[last] ^= 1;
    assert!(matches!(
        parse(&encoded),
        Err(CapsuleError::SectionChecksumMismatch(_))
    ));
}

#[test]
fn truncated_inputs_never_panic() {
    let encoded = build(&sections(), &options(2_000_000)).unwrap();
    for length in 0..encoded.len() {
        assert!(parse(&encoded[..length]).is_err());
    }
}

proptest! {
    #[test]
    fn arbitrary_input_never_panics(input in prop::collection::vec(any::<u8>(), 0..8192)) {
        let _ = parse(&input);
    }

    #[test]
    fn successful_build_always_within_budget(
        payload in prop::collection::vec(any::<u8>(), 0..4096),
        budget in 256_u64..8192,
        ecc in 0_u8..=50,
    ) {
        let sections = vec![
            Section {
                kind: SectionKind::CodecRegistry,
                flags: 0,
                payload: vec![1, 0],
            },
            Section {
                kind: SectionKind::TextStream,
                flags: 0,
                payload,
            },
            Section {
                kind: SectionKind::RecordIndex,
                flags: 0,
                payload: vec![0, 0],
            },
            Section {
                kind: SectionKind::ManifestDigest,
                flags: 0,
                payload: vec![0; 32],
            },
        ];
        let config = BuildOptions {
            budget_bytes: budget,
            capsule_id: Uuid::nil(),
            ecc_percent: ecc,
            pad_to_budget: false,
        };
        if let Ok(encoded) = build(&sections, &config) {
            prop_assert!(encoded.len() as u64 <= budget);
            prop_assert!(parse(&encoded).is_ok());
        }
    }
}
