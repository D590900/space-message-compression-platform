from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Sequence
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
    command: Sequence[str], *, timeout: int = COMMAND_TIMEOUT_SECONDS
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - never invokes a shell
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
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


def pareto_smallest_per_codec[Candidate, Report](
    candidates: list[tuple[Candidate, Report]],
    *,
    codec_id: Callable[[Candidate], str],
    payload_size: Callable[[Candidate], int],
    stable_config: Callable[[Candidate], str],
) -> list[tuple[Candidate, Report]]:
    smallest: dict[str, tuple[Candidate, Report]] = {}
    for item in candidates:
        candidate = item[0]
        key = codec_id(candidate)
        previous = smallest.get(key)
        candidate_key = (payload_size(candidate), stable_config(candidate))
        previous_key = (payload_size(previous[0]), stable_config(previous[0])) if previous else None
        if previous_key is None or candidate_key < previous_key:
            smallest[key] = item
    return sorted(smallest.values(), key=lambda item: (payload_size(item[0]), codec_id(item[0])))
