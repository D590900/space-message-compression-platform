from dataclasses import dataclass

from smcp_worker.adapters.external import pareto_frontier_per_codec


@dataclass(frozen=True)
class Candidate:
    codec: str
    size: int
    config: str


def test_keeps_real_byte_quality_tradeoffs_and_removes_dominated_points() -> None:
    candidates = [
        (Candidate("codec-a", 100, "low"), (0.91,)),
        (Candidate("codec-a", 140, "high"), (0.98,)),
        (Candidate("codec-a", 150, "dominated"), (0.97,)),
        (Candidate("codec-b", 160, "independent"), (0.90,)),
    ]

    frontier = pareto_frontier_per_codec(
        candidates,
        codec_id=lambda candidate: candidate.codec,
        payload_size=lambda candidate: candidate.size,
        quality=lambda report: report,
        stable_config=lambda candidate: candidate.config,
    )

    assert [candidate.config for candidate, _ in frontier] == [
        "low",
        "high",
        "independent",
    ]


def test_equal_objectives_use_stable_configuration_tie_break() -> None:
    candidates = [
        (Candidate("codec-a", 100, "z-config"), (0.95, 40.0)),
        (Candidate("codec-a", 100, "a-config"), (0.95, 40.0)),
    ]

    frontier = pareto_frontier_per_codec(
        candidates,
        codec_id=lambda candidate: candidate.codec,
        payload_size=lambda candidate: candidate.size,
        quality=lambda report: report,
        stable_config=lambda candidate: candidate.config,
    )

    assert [candidate.config for candidate, _ in frontier] == ["a-config"]
