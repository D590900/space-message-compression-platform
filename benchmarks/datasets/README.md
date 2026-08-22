# Synthetic benchmark corpus

Every fixture is generated from source in [`generate.py`](generate.py), is covered by the repository's Apache-2.0 license, and contains no personal or third-party data. The manifest pins byte length and SHA-256 for every committed fixture.

Regenerate and verify from the repository root:

```console
python benchmarks/datasets/generate.py
python benchmarks/datasets/generate.py --verify
```

Generation requires Python 3.12 and FFmpeg. The video is a two-second geometric talking-head proxy with synthetic audio; it is useful for deterministic pipeline smoke tests, not for substantiating human identity or lip-sync quality claims.
