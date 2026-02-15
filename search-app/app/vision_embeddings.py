from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Iterable, List

from .config import settings

logger = logging.getLogger(__name__)


class VisionModelUnavailable(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _get_clip_model():
    try:
        import open_clip  # type: ignore
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on extras
        raise VisionModelUnavailable(
            "open_clip is not installed. Install extras with `uv sync --extra image` or `pip install .[image]`"
        ) from exc
    model_name = settings.image_embed_model
    cache_dir = Path(settings.model_cache_dir) / "vision"
    cache_dir.mkdir(parents=True, exist_ok=True)
    pretrained = "openai" if "openclip" in model_name else "laion2b_s34b_b79k"
    model, preprocess, tokenizer = open_clip.create_model_and_transforms(
        model_name.split("/")[-1],
        pretrained=pretrained,
        cache_dir=str(cache_dir),
        device=settings.image_embed_device,
    )
    logger.info("Loaded image embedding model %s on %s", model_name, settings.image_embed_device)
    return model, preprocess, tokenizer


def embed_image_paths(paths: Iterable[str]) -> List[List[float]]:
    paths = list(paths)
    if not paths:
        return []
    model, preprocess, _ = _get_clip_model()
    import torch  # type: ignore
    from PIL import Image  # type: ignore

    device = settings.image_embed_device
    model.eval()
    embeddings: List[List[float]] = []
    with torch.no_grad():
        for path in paths:
            img = Image.open(path).convert("RGB")
            tensor = preprocess(img).unsqueeze(0).to(device)
            vec = model.encode_image(tensor)
            vec /= vec.norm(dim=-1, keepdim=True)
            embeddings.append(vec.squeeze(0).cpu().tolist())
    return embeddings


def embed_image_texts(texts: Iterable[str]) -> List[List[float]]:
    texts = [t.strip() for t in texts if t and t.strip()]
    if not texts:
        return []
    model, _preprocess, tokenizer = _get_clip_model()
    import torch  # type: ignore

    device = settings.image_embed_device
    model.eval()
    with torch.no_grad():
        tokens = tokenizer(texts)
        tokens = tokens.to(device)
        vecs = model.encode_text(tokens)
        vecs /= vecs.norm(dim=-1, keepdim=True)
    return vecs.cpu().tolist()