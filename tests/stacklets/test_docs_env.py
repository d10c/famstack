"""Docs OCR configuration rendered for Paperless."""

import importlib.util
import shutil
from pathlib import Path


REPO = Path(__file__).parent.parent.parent
MODULE_PATH = REPO / "stacklets" / "docs" / "env.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("docs_env", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_unset_ocr_languages_preserve_the_existing_default():
    env = _load_module().render({}, {})

    assert env["PAPERLESS_OCR_LANGUAGE"] == "deu+eng"
    assert env["PAPERLESS_OCR_LANGUAGES"] == ""


def test_configured_languages_select_ocr_and_install_extra_packs():
    config = {
        "docs": {
            "ocr_languages": ["deu", "eng", "nld", "srp", "srp_latn", "urd"],
        },
    }

    env = _load_module().render(config, {})

    assert env["PAPERLESS_OCR_LANGUAGE"] == "deu+eng+nld+srp+srp_latn+urd"
    assert env["PAPERLESS_OCR_LANGUAGES"] == "nld srp srp-latn urd"


def test_invalid_ocr_language_code_is_rejected():
    config = {"docs": {"ocr_languages": ["eng", "not a code"]}}

    try:
        _load_module().render(config, {})
    except ValueError as exc:
        assert "not a code" in str(exc)
    else:
        raise AssertionError("invalid OCR language was accepted")


def test_stack_env_uses_the_docs_owned_renderer(tmp_path):
    from stack import Stack

    (tmp_path / "stacklets").mkdir()
    shutil.copytree(REPO / "stacklets" / "docs", tmp_path / "stacklets" / "docs")
    (tmp_path / ".stack").mkdir()
    (tmp_path / ".stack" / "secrets.toml").write_text("")
    (tmp_path / "users.toml").write_text("")
    (tmp_path / "stack.toml").write_text(f"""
[core]
data_dir = "{tmp_path / 'data'}"
timezone = "UTC"
language = "en"

[docs]
ocr_languages = ["eng", "nld", "urd"]
""")

    env = Stack(root=tmp_path, data=tmp_path / "data").env("docs")

    assert env["PAPERLESS_OCR_LANGUAGE"] == "eng+nld+urd"
    assert env["PAPERLESS_OCR_LANGUAGES"] == "nld urd"
