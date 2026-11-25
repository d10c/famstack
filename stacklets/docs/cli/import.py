"""
stack docs import - resumably file documents through the Matrix front door.

The source is scanned recursively into state under the configured famstack
data directory. Each successful file upload advances the cursor immediately,
so an interruption or failed upload resumes at the first unfiled document.

Usage:
  stack docs import --source /Volumes/archive/documents
  stack docs import --status
  stack docs import --proceed 100
  stack docs import --proceed 10 --dry-run
  stack docs import --source /Volumes/archive/documents --proceed 100 --as marge
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


HELP = "Import documents resumably through the archivist"

DOCUMENT_EXTENSIONS = {
    ".pdf",
    ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff",
    ".doc", ".docx", ".odt",
    ".xls", ".xlsx", ".ods",
    ".ppt", ".pptx", ".odp",
}
IMPORT_DIR = "docs/import"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _import_root(config: dict) -> Path:
    data_dir = Path(config.get("data_dir", config.get("repo_root", ".")))
    return data_dir / IMPORT_DIR


def _source_slug(source_path: Path) -> str:
    return re.sub(
        r"[^a-zA-Z0-9]+", "-", str(source_path.resolve())
    ).strip("-").lower()


def _source_dir(import_root: Path, source_path: Path) -> Path:
    return import_root / "sources" / _source_slug(source_path)


def _load_state(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n")


def _load_manifest(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line for line in path.read_text().splitlines() if line]


def _save_manifest(path: Path, files: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(files) + "\n")


def _scan_documents(root: Path) -> list[str]:
    files = []
    for dirpath, _, filenames in os.walk(root):
        for filename in filenames:
            if Path(filename).suffix.lower() not in DOCUMENT_EXTENSIONS:
                continue
            path = Path(dirpath) / filename
            files.append(str(path.relative_to(root)))
    return sorted(files)


def _all_sources(import_root: Path) -> list[tuple[Path, dict, list[str]]]:
    sources_dir = import_root / "sources"
    if not sources_dir.exists():
        return []
    sources = []
    for source_dir in sources_dir.iterdir():
        state = _load_state(source_dir / "state.json")
        if state:
            sources.append((
                source_dir,
                state,
                _load_manifest(source_dir / "manifest.txt"),
            ))
    return sources


def _active_source(import_root: Path) -> tuple[Path, dict] | None:
    active = []
    for source_dir, state, manifest in _all_sources(import_root):
        if state.get("cursor", 0) < len(manifest):
            active.append((state.get("last_used", ""), source_dir, state))
    if not active:
        return None
    active.sort(key=lambda item: item[0], reverse=True)
    _, source_dir, state = active[0]
    return source_dir, state


def _parse_args(argv: list[str]):
    parser = argparse.ArgumentParser(
        prog="stack docs import", description=HELP
    )
    parser.add_argument("--source", type=Path)
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--proceed", type=int, metavar="N")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--as", dest="sender", metavar="USER")
    return parser.parse_args(argv)


def _scan_source(source: Path, import_root: Path) -> dict:
    if not source.is_dir():
        return {"error": f"Source path does not exist: {source}"}

    source_dir = _source_dir(import_root, source)
    state_path = source_dir / "state.json"
    existing = _load_state(state_path)
    if existing:
        manifest = _load_manifest(source_dir / "manifest.txt")
        remaining = len(manifest) - existing.get("cursor", 0)
        if remaining > 0:
            existing["last_used"] = _now()
            _save_state(state_path, existing)
            return {"ok": True, "resumed": True, "remaining": remaining}

    files = _scan_documents(source)
    if not files:
        return {"error": f"No supported document files found in {source}"}

    _save_manifest(source_dir / "manifest.txt", files)
    now = _now()
    _save_state(state_path, {
        "source": str(source.resolve()),
        "cursor": 0,
        "uploaded": 0,
        "total": len(files),
        "created": now,
        "last_used": now,
    })
    print(
        f"  Queued {len(files)} documents from {source}.\n"
        "  Run 'stack docs import --proceed N' to start filing.",
        file=sys.stderr,
    )
    return {"ok": True, "queued": len(files)}


def _status(import_root: Path, source: Path | None = None) -> dict:
    sources = _all_sources(import_root)
    if source:
        source_dir = _source_dir(import_root, source)
        sources = [item for item in sources if item[0] == source_dir]
    if not sources:
        print("  No document imports found.", file=sys.stderr)
        return {"ok": True, "active": False}

    for _, state, manifest in sorted(
        sources, key=lambda item: item[1].get("source", "")
    ):
        cursor = state.get("cursor", 0)
        print(
            f"  {state['source']}: {cursor}/{len(manifest)} filed, "
            f"{len(manifest) - cursor} remaining",
            file=sys.stderr,
        )
    return {"ok": True, "sources": len(sources)}


def _proceed(
    count: int,
    import_root: Path,
    config: dict,
    source: Path | None = None,
    dry_run: bool = False,
    sender: str | None = None,
) -> dict:
    if count <= 0:
        return {"error": "--proceed must be greater than zero"}

    if source:
        source_dir = _source_dir(import_root, source)
    else:
        active = _active_source(import_root)
        if not active:
            return {"error": "No active import. Run --source first."}
        source_dir, _ = active

    state_path = source_dir / "state.json"
    state = _load_state(state_path)
    if not state:
        return {"error": "No import found for this source. Run --source first."}

    manifest = _load_manifest(source_dir / "manifest.txt")
    cursor = state.get("cursor", 0)
    remaining = len(manifest) - cursor
    if remaining <= 0:
        return {"ok": True, "uploaded": 0, "remaining": 0}

    source_root = Path(state["source"])
    if not source_root.is_dir():
        return {"error": f"Source not accessible: {source_root}"}

    batch = manifest[cursor:cursor + count]
    if dry_run:
        for relative in batch:
            print(f"  {relative}", file=sys.stderr)
        return {
            "ok": True,
            "would_upload": len(batch),
            "remaining": remaining,
        }

    stack = config.get("stack_instance")
    if stack is None:
        return {"error": "Stack command runner unavailable"}

    uploaded = 0
    for relative in batch:
        path = source_root / relative
        if not path.is_file():
            error = f"Source file missing: {relative}"
            print(f"  ! {error}", file=sys.stderr)
            return {
                "error": error,
                "uploaded": uploaded,
                "remaining": len(manifest) - state["cursor"],
            }

        args = ["documents", str(path)]
        if sender:
            args.extend(["--as", sender])
        result = stack.run_cli_command("messages", "upload", args) or {
            "error": "No result returned"
        }
        if "error" in result:
            error = f"Upload failed for {relative}: {result['error']}"
            print(f"  ! {error}", file=sys.stderr)
            return {
                "error": error,
                "uploaded": uploaded,
                "remaining": len(manifest) - state["cursor"],
            }

        uploaded += 1
        state["cursor"] += 1
        state["uploaded"] = state.get("uploaded", 0) + 1
        state["last_used"] = _now()
        _save_state(state_path, state)
        print(f"  + {relative}", file=sys.stderr)

    return {
        "ok": True,
        "uploaded": uploaded,
        "remaining": len(manifest) - state["cursor"],
    }


def run(args, stacklet, config):
    options = _parse_args(args)
    import_root = _import_root(config)

    if options.source and options.proceed:
        scanned = _scan_source(options.source, import_root)
        if "error" in scanned:
            return scanned
        return _proceed(
            options.proceed,
            import_root,
            config,
            source=options.source,
            dry_run=options.dry_run,
            sender=options.sender,
        )
    if options.source and options.status:
        return _status(import_root, options.source)
    if options.source:
        return _scan_source(options.source, import_root)
    if options.status:
        return _status(import_root)
    if options.proceed:
        return _proceed(
            options.proceed,
            import_root,
            config,
            dry_run=options.dry_run,
            sender=options.sender,
        )
    return {
        "error": "No action specified. Use --source, --status, or --proceed."
    }
