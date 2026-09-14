"""Immutable local source files grouped by platform, period and ETL batch."""

import hashlib
import json
import shutil
import uuid
from pathlib import Path


def digest_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def platform_for(code):
    if code.startswith("orch_"):
        return "orchestration"
    if code == "terminal_material_names":
        return "integration"
    return code.split("_", 1)[0]


def archive_source(source, database, code, start, end, batch, role="import", root=None):
    source = Path(source).resolve()
    root = Path(root) if root else Path(database).resolve().parent / "raw"
    # Date strings and batch IDs must never become arbitrary path components.
    parts = [platform_for(code), code, f"{start or 'undated'}_{end or 'undated'}", batch]
    if any(not p or any(c in p for c in '/\\:') or p in {".", ".."} for p in parts):
        raise ValueError("Invalid source archive components")
    folder = root.joinpath(*parts)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{role}_{source.name}"
    digest = digest_file(source)
    if target.exists():
        if digest_file(target) != digest:
            raise ValueError("Refusing to overwrite an archived source")
    else:
        shutil.copy2(source, target)
    if digest_file(target) != digest:
        raise ValueError("Source changed during archive copy")
    manifest = {"dataset": code, "period_start": start, "period_end": end,
                "etl_run_id": batch, "role": role, "filename": target.name,
                "original_filename": source.name, "sha256": digest}
    (folder / f"{role}.manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return target.resolve()


def archive_download(source, database, code, start, end):
    return archive_source(source, database, code, start, end, "file_" + uuid.uuid4().hex, role="original")
