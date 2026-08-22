from __future__ import annotations

from smcp_worker.adapters.audio import OpusAudioAdapter
from smcp_worker.adapters.image import AvifImageAdapter, JpegXlImageAdapter
from smcp_worker.adapters.text import BrotliTextAdapter, ZstandardTextAdapter
from smcp_worker.adapters.video import Av1VideoAdapter
from smcp_worker.models import CodecCapabilities, Profile


def _model_capability(codec_id: str, content_type: str, model_name: str) -> CodecCapabilities:
    return CodecCapabilities(
        codec_id=codec_id,
        codec_version="unavailable",
        content_types=(content_type,),
        profiles=(Profile.ULTRA, Profile.SEMANTIC),
        enabled=False,
        deterministic=False,
        disabled_reason=f"no licensed, checksum-verified {model_name} weights are installed",
        install_hint=(
            "Add an immutable manifest under services/compression-worker/model-manifests, "
            "record code and weights licenses, then explicitly enable the model."
        ),
    )


def all_capabilities() -> tuple[CodecCapabilities, ...]:
    cpu = (
        BrotliTextAdapter().capabilities(),
        ZstandardTextAdapter().capabilities(),
        AvifImageAdapter().capabilities(),
        JpegXlImageAdapter().capabilities(),
        OpusAudioAdapter().capabilities(),
        Av1VideoAdapter().capabilities(),
    )
    optional = (
        _model_capability("image.compressai", "IMAGE", "CompressAI"),
        _model_capability("image.cod-lite", "IMAGE", "CoD-Lite/GenCodec"),
        _model_capability("audio.snac", "AUDIO", "SNAC"),
        _model_capability("audio.mimi", "AUDIO", "Mimi"),
        _model_capability("audio.encodec", "AUDIO", "EnCodec"),
        _model_capability("video.mlvc", "VIDEO", "MLVC"),
        _model_capability("video.dcvc", "VIDEO", "DCVC"),
        _model_capability("video.liveportrait", "VIDEO", "LivePortrait/GFVC"),
    )
    return cpu + optional
