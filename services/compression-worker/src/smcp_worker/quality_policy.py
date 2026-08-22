from __future__ import annotations

from dataclasses import replace
from typing import Any

from smcp_worker.models import QualityReport


def _number(
    policy: dict[str, Any],
    section: str,
    key: str,
    default: float,
    *,
    minimum: float,
    maximum: float,
) -> float:
    section_value = policy.get(section)
    if not isinstance(section_value, dict):
        return default
    value = section_value.get(key, default)
    if not isinstance(value, int | float) or isinstance(value, bool):
        return default
    numeric = float(value)
    if not minimum <= numeric <= maximum:
        return default
    return numeric


def apply_quality_policy(
    content_type: str,
    report: QualityReport,
    policy: dict[str, Any] | None,
) -> QualityReport:
    """Apply project thresholds without allowing weaker platform safety floors."""
    configured = policy if isinstance(policy, dict) else {}
    failures = list(report.gate_failures)

    if content_type == "IMAGE":
        threshold = _number(configured, "image", "ms_ssim_min", 0.90, minimum=0.90, maximum=1.0)
        value = report.metrics.get("ms_ssim")
        if isinstance(value, int | float) and float(value) < threshold:
            failures.append("project_ms_ssim_below_minimum")
    elif content_type == "AUDIO":
        duration_max = _number(
            configured,
            "audio",
            "duration_delta_max_seconds",
            0.02,
            minimum=0.0,
            maximum=0.02,
        )
        clipping_max = _number(
            configured,
            "audio",
            "clipping_ratio_max",
            0.001,
            minimum=0.0,
            maximum=0.001,
        )
        duration = report.metrics.get("duration_delta_seconds")
        clipping = report.metrics.get("clipping_ratio")
        if isinstance(duration, int | float) and float(duration) > duration_max:
            failures.append("project_duration_delta_above_maximum")
        if isinstance(clipping, int | float) and float(clipping) > clipping_max:
            failures.append("project_clipping_ratio_above_maximum")
    elif content_type == "VIDEO":
        vmaf_min = _number(configured, "video", "vmaf_min", 70.0, minimum=70.0, maximum=100.0)
        ssim_min = _number(
            configured,
            "video",
            "ssim_fallback_min",
            0.85,
            minimum=0.85,
            maximum=1.0,
        )
        duration_max = _number(
            configured,
            "video",
            "duration_delta_max_seconds",
            0.05,
            minimum=0.0,
            maximum=0.05,
        )
        vmaf = report.metrics.get("vmaf")
        ssim = report.metrics.get("ssim")
        duration = report.metrics.get("duration_delta_seconds")
        if isinstance(vmaf, int | float):
            if float(vmaf) < vmaf_min:
                failures.append("project_vmaf_below_minimum")
        elif isinstance(ssim, int | float) and float(ssim) < ssim_min:
            failures.append("project_ssim_below_minimum")
        if isinstance(duration, int | float) and float(duration) > duration_max:
            failures.append("project_duration_delta_above_maximum")

    unique_failures = tuple(dict.fromkeys(failures))
    return replace(
        report,
        quality_gate_passed=not unique_failures,
        gate_failures=unique_failures,
    )
