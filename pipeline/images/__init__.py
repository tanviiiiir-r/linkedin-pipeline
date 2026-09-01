"""Image pipeline package.

Re-exports the main image generation API while the refactor is in progress.
New code should import from pipeline.images; legacy imports from
pipeline.image_engine continue to work.
"""
from pipeline.image_engine import (
    AI_CANDIDATES,
    FAL_MODEL,
    IMAGE_PROVIDER,
    NON_AI_CANDIDATES,
    _build_style,
    _build_visual_scene,
    _dhash_image,
    _extract_pexels_query,
    _extract_visual_keywords,
    _is_usable_size,
    _score_candidate,
    _search_pexels,
    _visual_anchor,
    _visual_brief,
    available_providers,
    candidates_for_post,
    extract_article_images,
    image_for_post,
    prompt_for_post,
)

__all__ = [
    "AI_CANDIDATES",
    "FAL_MODEL",
    "IMAGE_PROVIDER",
    "NON_AI_CANDIDATES",
    "_build_style",
    "_build_visual_scene",
    "_dhash_image",
    "_extract_pexels_query",
    "_extract_visual_keywords",
    "_is_usable_size",
    "_score_candidate",
    "_search_pexels",
    "_visual_anchor",
    "_visual_brief",
    "available_providers",
    "candidates_for_post",
    "extract_article_images",
    "image_for_post",
    "prompt_for_post",
]
