"""Run Brain sync and require QMD retrieval of the expected artifact."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import subprocess
from typing import Any


class VerificationPending(RuntimeError):
    pass


@dataclass(frozen=True)
class VerificationResult:
    brain_sync: str
    qmd_index: str
    retrieval_query: str
    retrieved_paths: list[str]
    content_hashes: dict[str, str]


class SystemRunner:
    def __init__(self, brain_root: str | Path = "/Users/agent/obsidian-brain"):
        self.brain_root = Path(brain_root).resolve()

    def sync(self) -> None:
        subprocess.run(["/Users/agent/.hermes/scripts/obsidian_brain_sync.sh"], check=True, capture_output=True, text=True, timeout=300)

    def query(self, query: str) -> list[str]:
        completed = subprocess.run(["qmd", "query", query, "-c", "obsidian-brain", "--json", "--no-rerank"], check=True, capture_output=True, text=True, timeout=300)
        value: Any = json.loads(completed.stdout)
        rows = value if isinstance(value, list) else value.get("results", [])
        return [
            str(row.get("path") or row.get("file"))
            for row in rows
            if isinstance(row, dict) and (row.get("path") or row.get("file"))
        ]


def _normalized_qmd_path(value: str) -> str:
    path = value.replace("\\", "/")
    if path.startswith("qmd://"):
        path = path.split("/", 3)[-1]
    return "/".join(
        re.sub(r"[^a-z0-9.]+", "-", part.lower()).strip("-")
        for part in path.strip("/").split("/")
    )


def sync_and_verify(result: Any, runner: Any | None = None) -> VerificationResult:
    runner = runner or SystemRunner()
    try:
        runner.sync()
    except Exception as exc:
        raise VerificationPending("brain sync failed") from exc
    try:
        paths = runner.query(result.retrieval_query)
    except Exception as exc:
        raise VerificationPending("qmd indexing/query failed") from exc
    expected = result.capture_note.replace("\\", "/")
    # QMD commonly returns a vault-relative path while the deterministic writer
    # holds an absolute disposable-Brain path. Match only exact path boundaries.
    matched = [
        path for path in paths
        if path.replace("\\", "/") == expected
        or path.replace("\\", "/").endswith(expected)
        or expected.endswith("/" + path.replace("\\", "/").lstrip("/"))
        or _normalized_qmd_path(path) == _normalized_qmd_path(expected)
    ]
    if not matched:
        raise VerificationPending("expected artifact was not retrievable")
    return VerificationResult("passed", "passed", result.retrieval_query, matched, {expected: result.content_hash})
