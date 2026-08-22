from smcp_worker.capabilities import all_capabilities
from smcp_worker.models import Profile


def test_optional_models_are_explicitly_disabled_without_verified_weights() -> None:
    capabilities = all_capabilities()
    by_id = {capability.codec_id: capability for capability in capabilities}

    for codec_id in (
        "image.compressai",
        "image.cod-lite",
        "audio.snac",
        "audio.mimi",
        "audio.encodec",
        "video.mlvc",
        "video.dcvc",
        "video.liveportrait",
    ):
        capability = by_id[codec_id]
        assert not capability.enabled
        assert capability.disabled_reason
        assert capability.install_hint


def test_each_content_type_has_a_real_enabled_cpu_codec() -> None:
    enabled_types = {
        content_type
        for capability in all_capabilities()
        if capability.enabled
        for content_type in capability.content_types
    }
    assert enabled_types == {"TEXT", "IMAGE", "AUDIO", "VIDEO"}


def test_semantic_profile_is_not_advertised_by_an_enabled_codec() -> None:
    assert all(
        Profile.SEMANTIC not in capability.profiles
        for capability in all_capabilities()
        if capability.enabled
    )
