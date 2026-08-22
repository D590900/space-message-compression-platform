//! Command-line interface for deterministic capsule operations.

use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::time::Instant;

use anyhow::{Context, Result, bail};
use clap::{Parser, Subcommand};
use serde::Serialize;
use sha2::{Digest, Sha256};
use smcp_capsule_format::{
    BuildOptions, ParsedSection, Section, SectionKind, build, parse, verify,
};
use tempfile::NamedTempFile;
use uuid::Uuid;

#[derive(Debug, Parser)]
#[command(name = "smcp-capsule", version, about)]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Debug, Subcommand)]
enum Command {
    /// Build a canonical capsule atomically.
    Build {
        /// Output file.
        #[arg(long)]
        output: PathBuf,
        /// Strict total budget including all overhead.
        #[arg(long, default_value_t = 2_000_000)]
        budget: u64,
        /// Stable UUID; defaults to nil for reproducible local builds.
        #[arg(long, default_value = "00000000-0000-0000-0000-000000000000")]
        capsule_id: Uuid,
        /// Reed–Solomon parity percentage.
        #[arg(long, default_value_t = 0)]
        ecc_percent: u8,
        /// Pad the result to exactly the declared budget when possible.
        #[arg(long)]
        pad: bool,
        /// Repeated `kind=path` input, in canonical order.
        #[arg(long = "section", required = true)]
        sections: Vec<String>,
    },
    /// Print verified capsule metadata as JSON.
    Inspect { input: PathBuf },
    /// Verify integrity, ECC and strict budget.
    Verify { input: PathBuf },
    /// Extract one verified section.
    Extract {
        input: PathBuf,
        #[arg(long)]
        kind: String,
        #[arg(long)]
        output: PathBuf,
    },
    /// Measure verification throughput on this machine.
    Benchmark {
        input: PathBuf,
        #[arg(long, default_value_t = 100)]
        iterations: u32,
    },
}

#[derive(Serialize)]
struct SectionView {
    kind: String,
    bytes: usize,
    crc32c: u32,
    sha256: String,
}

#[derive(Serialize)]
struct InspectView {
    capsule_id: String,
    actual_bytes: u64,
    budget_bytes: u64,
    sections: Vec<SectionView>,
}

fn main() -> Result<()> {
    match Cli::parse().command {
        Command::Build {
            output,
            budget,
            capsule_id,
            ecc_percent,
            pad,
            sections,
        } => command_build(&output, budget, capsule_id, ecc_percent, pad, &sections),
        Command::Inspect { input } => command_inspect(&input),
        Command::Verify { input } => command_verify(&input),
        Command::Extract {
            input,
            kind,
            output,
        } => command_extract(&input, &kind, &output),
        Command::Benchmark { input, iterations } => command_benchmark(&input, iterations),
    }
}

fn command_build(
    output: &Path,
    budget: u64,
    capsule_id: Uuid,
    ecc_percent: u8,
    pad: bool,
    section_args: &[String],
) -> Result<()> {
    let sections = section_args
        .iter()
        .map(|argument| {
            let (kind, path) = argument
                .split_once('=')
                .context("section must use kind=path")?;
            Ok(Section {
                kind: parse_kind(kind)?,
                flags: 0,
                payload: fs::read(path).with_context(|| format!("read section payload {path}"))?,
            })
        })
        .collect::<Result<Vec<_>>>()?;
    let encoded = build(
        &sections,
        &BuildOptions {
            budget_bytes: budget,
            capsule_id,
            ecc_percent,
            pad_to_budget: pad,
        },
    )?;
    verify(&encoded)?;
    atomic_write(output, &encoded)?;
    println!(
        "{}",
        serde_json::json!({
            "output": output,
            "actual_bytes": encoded.len(),
            "budget_bytes": budget,
            "sha256": hex::encode(Sha256::digest(&encoded)),
        })
    );
    Ok(())
}

fn command_inspect(input: &Path) -> Result<()> {
    let bytes = fs::read(input).with_context(|| format!("read {}", input.display()))?;
    let parsed = parse(&bytes)?;
    let view = InspectView {
        capsule_id: parsed.capsule_id.to_string(),
        actual_bytes: parsed.total_bytes,
        budget_bytes: parsed.budget_bytes,
        sections: parsed.sections.iter().map(section_view).collect(),
    };
    println!("{}", serde_json::to_string_pretty(&view)?);
    Ok(())
}

fn command_verify(input: &Path) -> Result<()> {
    let bytes = fs::read(input).with_context(|| format!("read {}", input.display()))?;
    let report = verify(&bytes)?;
    println!(
        "{}",
        serde_json::json!({
            "valid": true,
            "actual_bytes": report.actual_bytes,
            "budget_bytes": report.budget_bytes,
            "section_count": report.section_count,
            "merkle_root": hex::encode(report.merkle_root),
            "ecc_verified": report.ecc_verified,
        })
    );
    Ok(())
}

fn command_extract(input: &Path, kind: &str, output: &Path) -> Result<()> {
    let bytes = fs::read(input).with_context(|| format!("read {}", input.display()))?;
    let parsed = parse(&bytes)?;
    let expected = parse_kind(kind)?;
    let section = parsed
        .sections
        .iter()
        .find(|section| section.kind == expected)
        .with_context(|| format!("section {kind} not present"))?;
    atomic_write(output, section.payload)
}

fn command_benchmark(input: &Path, iterations: u32) -> Result<()> {
    if iterations == 0 {
        bail!("iterations must be positive");
    }
    let bytes = fs::read(input).with_context(|| format!("read {}", input.display()))?;
    let started = Instant::now();
    for _ in 0..iterations {
        verify(&bytes)?;
    }
    let elapsed = started.elapsed();
    println!(
        "{}",
        serde_json::json!({
            "iterations": iterations,
            "input_bytes": bytes.len(),
            "elapsed_ns": elapsed.as_nanos(),
            "average_ns": elapsed.as_nanos() / u128::from(iterations),
        })
    );
    Ok(())
}

fn section_view(section: &ParsedSection<'_>) -> SectionView {
    SectionView {
        kind: format!("{:?}", section.kind),
        bytes: section.payload.len(),
        crc32c: section.crc32c,
        sha256: hex::encode(section.sha256),
    }
}

fn parse_kind(value: &str) -> Result<SectionKind> {
    Ok(match value {
        "codec-registry" => SectionKind::CodecRegistry,
        "model-registry" => SectionKind::ModelRegistry,
        "text" => SectionKind::TextStream,
        "image" => SectionKind::ImageStream,
        "audio" => SectionKind::AudioStream,
        "motion" => SectionKind::MotionStream,
        "video" => SectionKind::GenericVideoStream,
        "index" => SectionKind::RecordIndex,
        "manifest-digest" => SectionKind::ManifestDigest,
        _ => bail!("unknown or derived section kind {value}"),
    })
}

fn atomic_write(output: &Path, bytes: &[u8]) -> Result<()> {
    let parent = output.parent().unwrap_or_else(|| Path::new("."));
    let mut temporary = NamedTempFile::new_in(parent)
        .with_context(|| format!("create temporary output in {}", parent.display()))?;
    temporary.write_all(bytes)?;
    temporary.as_file().sync_all()?;
    temporary
        .persist(output)
        .map_err(|error| error.error)
        .with_context(|| format!("persist output to {}", output.display()))?;
    Ok(())
}
