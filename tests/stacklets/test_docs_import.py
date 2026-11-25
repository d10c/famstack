"""Resumable document imports enter through the Matrix documents room."""

import importlib.util
import json
from pathlib import Path


REPO = Path(__file__).parent.parent.parent
MODULE_PATH = REPO / "stacklets" / "docs" / "cli" / "import.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("docs_import", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeStack:
    def __init__(self, results=None):
        self.results = list(results or [])
        self.calls = []

    def run_cli_command(self, stacklet, command, args):
        self.calls.append((stacklet, command, args))
        if self.results:
            return self.results.pop(0)
        return {"ok": True, "event_id": "$event"}


def _config(tmp_path, stack):
    return {
        "data_dir": str(tmp_path / "data"),
        "stack_instance": stack,
    }


def _state_path(module, tmp_path, source):
    root = tmp_path / "data" / "docs" / "import"
    return module._source_dir(root, source) / "state.json"


def test_source_scan_recurses_and_queues_only_document_formats(tmp_path):
    module = _load_module()
    source = tmp_path / "archive"
    (source / "letters").mkdir(parents=True)
    (source / "letters" / "scan.pdf").write_bytes(b"pdf")
    (source / "invoice.docx").write_bytes(b"office")
    (source / "notes.md").write_text("# structured text")
    (source / "clip.mp4").write_bytes(b"video")

    result = module.run(
        ["--source", str(source)],
        {},
        _config(tmp_path, FakeStack()),
    )

    assert result == {"ok": True, "queued": 2}
    state = json.loads(_state_path(module, tmp_path, source).read_text())
    assert state["cursor"] == 0
    manifest = (
        _state_path(module, tmp_path, source).parent / "manifest.txt"
    ).read_text().splitlines()
    assert manifest == ["invoice.docx", "letters/scan.pdf"]


def test_dry_run_does_not_upload_or_advance_cursor(tmp_path):
    module = _load_module()
    source = tmp_path / "archive"
    source.mkdir()
    (source / "one.pdf").write_bytes(b"one")
    stack = FakeStack()
    config = _config(tmp_path, stack)

    module.run(["--source", str(source)], {}, config)
    result = module.run(["--proceed", "1", "--dry-run"], {}, config)

    assert result == {"ok": True, "would_upload": 1, "remaining": 1}
    assert stack.calls == []
    state = json.loads(_state_path(module, tmp_path, source).read_text())
    assert state["cursor"] == 0


def test_status_reports_saved_progress(tmp_path, capsys):
    module = _load_module()
    source = tmp_path / "archive"
    source.mkdir()
    (source / "one.pdf").write_bytes(b"one")
    config = _config(tmp_path, FakeStack())

    module.run(["--source", str(source)], {}, config)
    result = module.run(["--status"], {}, config)

    assert result == {"ok": True, "sources": 1}
    assert f"{source.resolve()}: 0/1 filed, 1 remaining" in capsys.readouterr().err


def test_successful_uploads_delegate_to_messages_with_attribution(tmp_path):
    module = _load_module()
    source = tmp_path / "archive"
    source.mkdir()
    (source / "one.pdf").write_bytes(b"one")
    stack = FakeStack()
    config = _config(tmp_path, stack)

    module.run(["--source", str(source)], {}, config)
    result = module.run(["--proceed", "1", "--as", "marge"], {}, config)

    assert result == {"ok": True, "uploaded": 1, "remaining": 0}
    assert stack.calls == [
        (
            "messages",
            "upload",
            ["documents", str(source / "one.pdf"), "--as", "marge"],
        ),
    ]
    state = json.loads(_state_path(module, tmp_path, source).read_text())
    assert state["cursor"] == 1


def test_failed_file_stays_at_cursor_for_resume(tmp_path):
    module = _load_module()
    source = tmp_path / "archive"
    source.mkdir()
    (source / "a.pdf").write_bytes(b"a")
    (source / "b.pdf").write_bytes(b"b")
    (source / "c.pdf").write_bytes(b"c")
    stack = FakeStack([
        {"ok": True, "event_id": "$a"},
        {"error": "Matrix rejected b.pdf"},
    ])
    config = _config(tmp_path, stack)

    module.run(["--source", str(source)], {}, config)
    result = module.run(["--proceed", "3"], {}, config)

    assert result["error"] == "Upload failed for b.pdf: Matrix rejected b.pdf"
    assert result["uploaded"] == 1
    assert result["remaining"] == 2
    assert len(stack.calls) == 2
    state = json.loads(_state_path(module, tmp_path, source).read_text())
    assert state["cursor"] == 1
