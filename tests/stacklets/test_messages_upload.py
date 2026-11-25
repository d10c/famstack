"""The messages upload plugin accepts delegated CLI arguments."""

import importlib.util
from pathlib import Path


REPO = Path(__file__).parent.parent.parent
MODULE_PATH = REPO / "stacklets" / "messages" / "cli" / "upload.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("messages_upload", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeClient:
    def __init__(self, *args):
        pass

    def login(self, username, password):
        return True

    def join(self, room):
        return True

    def upload_media(self, data, mime, filename):
        return "mxc://home/file"

    def send_file(self, room, mxc, filename, mime, **kwargs):
        return True, "$event"


def test_run_uses_passed_arguments_for_cross_stacklet_upload(tmp_path, monkeypatch):
    module = _load_module()
    document = tmp_path / "letter.pdf"
    document.write_bytes(b"pdf")
    monkeypatch.setattr(module, "MatrixClient", FakeClient)
    config = {
        "is_healthy": lambda: True,
        "instance_dir": str(tmp_path),
        "stack": {"messages": {"server_name": "home"}},
        "secrets": {"global__USER_MARGE_PASSWORD": "secret"},
        "manifest": {"ports": {"synapse": 42031}},
    }

    result = module.run(
        ["documents", str(document), "--as", "marge"],
        {},
        config,
    )

    assert result["ok"] is True
    assert result["room"] == "documents"
    assert result["as"] == "marge"
