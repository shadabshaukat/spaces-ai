from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from functools import lru_cache
from typing import Optional

from .config import settings

logger = logging.getLogger(__name__)


class CaptionModelUnavailable(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _load_caption_model():
    try:
        import torch  # type: ignore
        from transformers import AutoProcessor, LlavaForConditionalGeneration, BlipForConditionalGeneration  # type: ignore
    except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency
        raise CaptionModelUnavailable(
            "LLaVA captioning dependencies are not installed. Install extras with `uv sync --extra caption` or `pip install .[caption]`."
        ) from exc

    model_name = settings.image_caption_model_small if settings.image_caption_use_small else settings.image_caption_model
    device = settings.image_caption_device
    torch_dtype = torch.float16 if device != "cpu" else torch.float32

    processor = AutoProcessor.from_pretrained(model_name)
    if settings.image_caption_use_small:
        model = BlipForConditionalGeneration.from_pretrained(
            model_name,
            torch_dtype=torch_dtype,
            low_cpu_mem_usage=True,
        )
    else:
        model = LlavaForConditionalGeneration.from_pretrained(
            model_name,
            torch_dtype=torch_dtype,
            low_cpu_mem_usage=True,
        )
    model.to(device)
    model.eval()
    logger.info("Loaded image captioning model %s on %s", model_name, device)
    return model, processor


def captioning_ready(preload_model: bool = False) -> tuple[bool, str | None]:
    if not settings.enable_image_captioning:
        return False, "captioning disabled"
    try:
        if preload_model:
            _load_caption_model()
    except CaptionModelUnavailable as exc:
        return False, str(exc)
    except Exception as exc:  # pragma: no cover
        return False, f"captioning init failed: {exc}"
    return True, None


def _build_prompt(processor, prompt: str) -> str:
    if hasattr(processor, "apply_chat_template"):
        return processor.apply_chat_template(
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image"},
                    ],
                }
            ],
            tokenize=False,
            add_generation_prompt=True,
        )
    return f"USER: <image>\n{prompt}\nASSISTANT:"


def generate_caption(image) -> Optional[str]:
    if not settings.enable_image_captioning:
        return None

    def _run() -> Optional[str]:
        model, processor = _load_caption_model()
        prompt = settings.image_caption_prompt
        if settings.image_caption_use_small:
            inputs = processor(images=image, return_tensors="pt")
        else:
            prompt = _build_prompt(processor, prompt)
            inputs = processor(images=image, text=prompt, return_tensors="pt")
        device = settings.image_caption_device
        for key in inputs:
            inputs[key] = inputs[key].to(device)
        output = model.generate(**inputs, max_new_tokens=settings.image_caption_max_tokens)
        decoded = processor.decode(output[0], skip_special_tokens=True).strip()
        if "ASSISTANT:" in decoded:
            decoded = decoded.split("ASSISTANT:", 1)[-1].strip()
        return decoded or None

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_run)
            return future.result(timeout=settings.image_caption_timeout_s)
    except TimeoutError:
        logger.warning("Image captioning timed out after %ss", settings.image_caption_timeout_s)
        return None
    except CaptionModelUnavailable as exc:
        logger.warning("Caption model unavailable: %s", exc)
        return None
    except Exception as exc:
        logger.warning("Image captioning failed: %s", exc)
        return None