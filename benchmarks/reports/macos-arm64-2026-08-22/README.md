# Generated CPU baseline report

> This file is derived from `results.json`; target values are not copied into results.

- Commit: `cb44349aff8a52fcea2bac7d047b7851eec6ba51`
- Platform: `macOS-15.6.1-arm64-arm-64bit`
- Generated (UTC): `2026-08-22T13:41:49Z`

| Fixture                   | Codec          | Level |  Input | Payload |   Ratio | Encode ms | Decode ms | Gate |
| ------------------------- | -------------- | ----: | -----: | ------: | ------: | --------: | --------: | ---- |
| text-en.txt               | text.brotli    |     5 |    146 |     117 |   1.248 |     0.302 |     0.007 | pass |
| text-en.txt               | text.brotli    |     9 |    146 |     118 |   1.237 |     0.231 |     0.004 | pass |
| text-en.txt               | text.brotli    |    11 |    146 |     108 |   1.352 |     0.420 |     0.004 | pass |
| text-en.txt               | text.zstandard |     9 |    146 |     125 |   1.168 |     0.124 |     0.020 | pass |
| text-en.txt               | text.zstandard |    19 |    146 |     123 |   1.187 |     0.106 |     0.004 | pass |
| text-en.txt               | text.zstandard |    22 |    146 |     123 |   1.187 |     0.087 |     0.002 | pass |
| text-it.txt               | text.brotli    |     5 |    125 |     110 |   1.136 |     0.168 |     0.003 | pass |
| text-it.txt               | text.brotli    |     9 |    125 |     110 |   1.136 |     0.176 |     0.002 | pass |
| text-it.txt               | text.brotli    |    11 |    125 |     102 |   1.225 |     0.435 |     0.005 | pass |
| text-it.txt               | text.zstandard |     9 |    125 |     111 |   1.126 |     0.096 |     0.007 | pass |
| text-it.txt               | text.zstandard |    19 |    125 |     106 |   1.179 |     0.095 |     0.002 | pass |
| text-it.txt               | text.zstandard |    22 |    125 |     106 |   1.179 |     0.088 |     0.002 | pass |
| text-multilingual.txt     | text.brotli    |     5 |    183 |     177 |   1.034 |     0.154 |     0.004 | pass |
| text-multilingual.txt     | text.brotli    |     9 |    183 |     182 |   1.005 |     0.238 |     0.004 | pass |
| text-multilingual.txt     | text.brotli    |    11 |    183 |     163 |   1.123 |     0.529 |     0.005 | pass |
| text-multilingual.txt     | text.zstandard |     9 |    183 |     184 |   0.995 |     0.090 |     0.002 | pass |
| text-multilingual.txt     | text.zstandard |    19 |    183 |     180 |   1.017 |     0.094 |     0.003 | pass |
| text-multilingual.txt     | text.zstandard |    22 |    183 |     180 |   1.017 |     0.094 |     0.001 | pass |
| image-pattern-512.png     | image.avif     |    20 | 655658 |    8083 |  81.116 |    36.729 |    73.325 | pass |
| image-pattern-512.png     | image.avif     |    32 | 655658 |    6459 | 101.511 |    34.562 |    65.440 | pass |
| image-pattern-512.png     | image.avif     |    44 | 655658 |    4167 | 157.345 |    34.226 |    78.990 | pass |
| image-pattern-512.png     | image.jpeg-xl  |     5 | 655658 |   19217 |  34.119 |    93.300 |    19.113 | pass |
| image-pattern-512.png     | image.jpeg-xl  |    10 | 655658 |   22888 |  28.646 |   104.175 |    20.540 | pass |
| image-pattern-512.png     | image.jpeg-xl  |    20 | 655658 |   15096 |  43.433 |   102.616 |    20.385 | pass |
| audio-synthetic-2s.wav    | audio.opus     |    12 |  96044 |    3397 |  28.273 |    62.827 |    17.524 | pass |
| audio-synthetic-2s.wav    | audio.opus     |    20 |  96044 |    5825 |  16.488 |    60.922 |    17.270 | pass |
| audio-synthetic-2s.wav    | audio.opus     |    32 |  96044 |    7710 |  12.457 |    64.166 |    17.306 | pass |
| video-talking-head-2s.mkv | video.av1      |    28 | 162125 |   17402 |   9.316 |    79.496 |    21.716 | pass |
| video-talking-head-2s.mkv | video.av1      |    36 | 162125 |   16613 |   9.759 |    79.937 |    21.932 | pass |
| video-talking-head-2s.mkv | video.av1      |    44 | 162125 |   16390 |   9.892 |    78.505 |    21.322 | pass |

## Limitations

This synthetic corpus is a reproducibility smoke set, not a representative human media corpus. Neural quality metrics and identity, speaker, ASR, pose, and lip-sync models remain explicitly unavailable until separately licensed, hashed manifests are installed.
