from smcp_worker.models import QualityReport
from smcp_worker.quality_policy import apply_quality_policy


def report(metrics: dict[str, float | None]) -> QualityReport:
    return QualityReport(
        exact_round_trip=False,
        original_sha256="a" * 64,
        decoded_sha256="b" * 64,
        quality_gate_passed=True,
        metrics=metrics,
    )


def test_stricter_image_policy_rejects_default_passing_candidate() -> None:
    updated = apply_quality_policy(
        "IMAGE",
        report({"ms_ssim": 0.94}),
        {"image": {"ms_ssim_min": 0.95}},
    )

    assert not updated.quality_gate_passed
    assert updated.gate_failures == ("project_ms_ssim_below_minimum",)


def test_audio_and_video_thresholds_are_content_specific() -> None:
    audio = apply_quality_policy(
        "AUDIO",
        report({"duration_delta_seconds": 0.015, "clipping_ratio": 0.0005}),
        {
            "audio": {
                "duration_delta_max_seconds": 0.01,
                "clipping_ratio_max": 0.0008,
            }
        },
    )
    video = apply_quality_policy(
        "VIDEO",
        report(
            {
                "vmaf": None,
                "ssim": 0.91,
                "duration_delta_seconds": 0.02,
            }
        ),
        {
            "video": {
                "vmaf_min": 80,
                "ssim_fallback_min": 0.92,
                "duration_delta_max_seconds": 0.03,
            }
        },
    )

    assert audio.gate_failures == ("project_duration_delta_above_maximum",)
    assert video.gate_failures == ("project_ssim_below_minimum",)


def test_invalid_persisted_values_cannot_weaken_platform_floors() -> None:
    updated = apply_quality_policy(
        "IMAGE",
        report({"ms_ssim": 0.89}),
        {"image": {"ms_ssim_min": 0.1}},
    )

    assert not updated.quality_gate_passed
