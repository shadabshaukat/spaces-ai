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


def vision_dependencies_ready(preload_model: bool = False) -> tuple[bool, str | None]:
    """Return whether Pillow/OpenCLIP dependencies are ready along with an optional detail string."""
    try:
        import PIL  # type: ignore  # noqa: F401
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on extras
        return False, "Pillow is not installed. Install extras with `uv sync --extra image` or `pip install .[image]`."
    try:
        if preload_model:
            _get_clip_model()
    except VisionModelUnavailable as e:
        return False, str(e)
    except Exception as e:  # pragma: no cover - safety net for model issues
        return False, f"Vision model initialization failed: {e}"
    return True, None


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
        try:
            tokens = tokenizer(texts)
        except TypeError as exc:
            msg = str(exc)
            if "Unexpected type" not in msg:
                raise
            logger.debug("Tokenizer does not support batched input; tokenizing %d texts individually", len(texts))
            single_tokens = []
            for text in texts:
                tok = tokenizer(text)
                if hasattr(tok, "unsqueeze"):
                    single_tokens.append(tok.unsqueeze(0))
                    continue
                if isinstance(tok, (list, tuple)):
                    tok = torch.tensor(tok)
                    single_tokens.append(tok.unsqueeze(0))
                    continue
                if isinstance(tok, dict) and tok.get("input_ids") is not None:
                    tensor = tok["input_ids"]
                    if hasattr(tensor, "unsqueeze"):
                        single_tokens.append(tensor.unsqueeze(0))
                        continue
                raise TypeError("Tokenizer output unsupported for batching") from exc
            tokens = torch.cat(single_tokens, dim=0)
        tokens = tokens.to(device)
        vecs = model.encode_text(tokens)
        vecs /= vecs.norm(dim=-1, keepdim=True)
    return vecs.cpu().tolist()