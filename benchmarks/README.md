# Benchmarks

The benchmark corpus is synthetic, redistributable and hash-pinned. Baseline runs record successful and failed attempts without hiding unavailable capabilities, and produce JSON, CSV and Markdown from one execution.

```console
python benchmarks/datasets/generate.py --verify
cd services/compression-worker
uv run python ../../benchmarks/runners/run_baselines.py \
  --output ../../benchmark-results/local
```

Results under `benchmarks/reports/` are committed evidence from named environments. `benchmark-results/` is ignored scratch output. Compare like-for-like environments and fixture manifest hashes; timing across unlike hardware is not a regression signal.
