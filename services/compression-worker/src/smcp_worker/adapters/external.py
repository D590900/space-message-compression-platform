from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

COMMAND_TIMEOUT_SECONDS = 300


def executable(name: str) -> str | None:
    return shutil.which(name)


def version_line(command: Sequence[str]) -> str:
    completed = subprocess.run(  # noqa: S603 - argv-only trusted codec commands
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    output = completed.stdout or completed.stderr
    return output.splitlines()[0].strip()


def run(
    command: Sequence[str], *, timeout: int = COMMAND_TIMEOUT_SECONDS, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - never invokes a shell
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd,
    )


def transform(
    payload: bytes,
    input_suffix: str,
    output_suffix: str,
    command: Sequence[str],
) -> bytes:
    with tempfile.TemporaryDirectory(prefix="smcp-codec-") as directory:
        root = Path(directory)
        source = root / f"input{input_suffix}"
        output = root / f"output{output_suffix}"
        source.write_bytes(payload)
        resolved = [
            part.replace("{input}", str(source)).replace("{output}", str(output))
            for part in command
        ]
        run(resolved)
        result = output.read_bytes()
        if not result:
            raise ValueError("codec produced an empty output")
        return result


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def numeric_metric(metrics: Mapping[str, object], key: str) -> float:
    value = metrics.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"quality metric {key} is not numeric")
    return float(value)


def pareto_frontier_per_codec[Candidate, Report](
    candidates: list[tuple[Candidate, Report]],
    *,
    codec_id: Callable[[Candidate], str],
    payload_size: Callable[[Candidate], int],
    quality: Callable[[Report], tuple[float, ...]],
    stable_config: Callable[[Candidate], str],
) -> list[tuple[Candidate, Report]]:
    """Keep deterministic byte/quality non-dominated configurations per codec."""

    def dominates(left: tuple[Candidate, Report], right: tuple[Candidate, Report]) -> bool:
        left_candidate, left_report = left
        right_candidate, right_report = right
        if codec_id(left_candidate) != codec_id(right_candidate):
            return False
        left_quality = quality(left_report)
        right_quality = quality(right_report)
        if len(left_quality) != len(right_quality):
            raise ValueError("quality vectors must have a stable dimension")
        no_worse = payload_size(left_candidate) <= payload_size(right_candidate) and all(
            left_value >= right_value
            for left_value, right_value in zip(left_quality, right_quality, strict=True)
        )
        if not no_worse:
            return False
        strictly_better = payload_size(left_candidate) < payload_size(right_candidate) or any(
            left_value > right_value
            for left_value, right_value in zip(left_quality, right_quality, strict=True)
        )
        if strictly_better:
            return True
        return stable_config(left_candidate) < stable_config(right_candidate)

    frontier = [
        item
        for index, item in enumerate(candidates)
        if not any(
            dominates(other, item)
            for other_index, other in enumerate(candidates)
            if other_index != index
        )
    ]
    return sorted(
        frontier,
        key=lambda item: (
            payload_size(item[0]),
            codec_id(item[0]),
            stable_config(item[0]),
        ),
    )
