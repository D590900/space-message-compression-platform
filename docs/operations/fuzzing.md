# Capsule parser fuzzing

The `parse` target sends arbitrary byte slices directly to the bounded, unsafe-free Capsule Format v1 parser. Its lockfile and minimized seed corpus are committed; crash artifacts and build products are not.

Install and run the pinned toolchain from the repository root:

```console
rustup toolchain install nightly-2026-08-15 --profile minimal
cargo +nightly-2026-08-15 install cargo-fuzz --version 0.13.2 --locked
cargo +nightly-2026-08-15 fuzz run parse \
  --fuzz-dir crates/capsule-format/fuzz -- \
  -max_total_time=30 -rss_limit_mb=2048 -print_final_stats=1
```

The 2026-08-22 macOS arm64 smoke run executed 33,725,554 inputs in 31 seconds, reached 64 coverage features, peaked at 487 MB RSS, and found no crash. This bounded run is regression evidence, not a proof that the parser is vulnerability-free. CI repeats a 15-second smoke; longer scheduled campaigns should retain and triage every artifact before adding it to the corpus.
