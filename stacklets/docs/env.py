"""Render docs configuration into Paperless environment variables."""

from __future__ import annotations

import re


DEFAULT_OCR_LANGUAGES = ["deu", "eng"]
PAPERLESS_BUNDLED_LANGUAGES = {"deu", "eng", "fra", "ita", "spa"}
LANGUAGE_CODE = re.compile(r"^[a-z]{3}(?:_[a-z0-9]+)?$")


def render(config: dict, env: dict) -> dict:
    languages = config.get("docs", {}).get(
        "ocr_languages", DEFAULT_OCR_LANGUAGES
    )
    if not isinstance(languages, list) or not languages:
        raise ValueError("[docs].ocr_languages must be a non-empty TOML list")

    invalid = [
        language
        for language in languages
        if not isinstance(language, str) or not LANGUAGE_CODE.fullmatch(language)
    ]
    if invalid:
        raise ValueError(
            "Invalid [docs].ocr_languages code(s): "
            + ", ".join(repr(language) for language in invalid)
        )

    rendered = dict(env)
    rendered["PAPERLESS_OCR_LANGUAGE"] = "+".join(languages)
    rendered["PAPERLESS_OCR_LANGUAGES"] = " ".join(
        language.replace("_", "-")
        for language in languages
        if language not in PAPERLESS_BUNDLED_LANGUAGES
    )
    return rendered
