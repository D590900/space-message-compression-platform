from __future__ import annotations

from pathlib import Path

from smcp_worker.adapters.audio import MimiAudioAdapter, OpusAudioAdapter, SnacAudioAdapter
from smcp_worker.adapters.image import AvifImageAdapter, CodLiteImageAdapter, JpegXlImageAdapter
from smcp_worker.adapters.text import BrotliTextAdapter, ZstandardTextAdapter
from smcp_worker.adapters.video import Av1VideoAdapter
from smcp_worker.model_manifest import load_catalog
from smcp_worker.models import CodecCapabilities, Profile

MODEL_CATALOG = Path(__file__).resolve().parents[2] / "model-manifests" / "catalog.json"


def _model_capabilities() -> tuple[CodecCapabilities, ...]:
    catalog = load_catalog(MODEL_CATALOG)
    capabilities: list[CodecCapabilities] = []
    for model in catalog.models:
        if model.id == "cod-lite":
            capabilities.append(CodLiteImageAdapter(manifest=model).capabilities())
            continue
        if model.id == "snac":
            capabilities.append(SnacAudioAdapter(manifest=model).capabilities())
            continue
        if model.id == "mimi":
            capabilities.append(MimiAudioAdapter(manifest=model).capabilities())
            continue
        if model.enabled:
            raise RuntimeError(
                f"{model.codec_id} is marked enabled but no neural pipeline is registered"
            )
        content_type = model.codec_id.partition(".")[0].upper()
        capabilities.append(
            CodecCapabilities(
                codec_id=model.codec_id,
                codec_version=model.version,
                content_types=(content_type,),
                profiles=(Profile.ULTRA, Profile.SEMANTIC),
                enabled=False,
                deterministic=False,
                disabled_reason=model.disabled_reason,
                install_hint=model.install_hint,
            )
        )
    return tuple(capabilities)


def all_capabilities() -> tuple[CodecCapabilities, ...]:
    cpu = (
        BrotliTextAdapter().capabilities(),
        ZstandardTextAdapter().capabilities(),
        AvifImageAdapter().capabilities(),
        JpegXlImageAdapter().capabilities(),
        OpusAudioAdapter().capabilities(),
        Av1VideoAdapter().capabilities(),
    )
    return cpu + _model_capabilities()
