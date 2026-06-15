"""
Artifact management for page-export verification.

Manages the directory structure and file I/O for storing test artifacts:
  - page_snapshot.json
  - export_snapshot.json
  - compare_result.json
  - export.xlsx
  - page_before_export.png
  - trace.zip
  - browser_console.log
  - network.har
  - manifest.json
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ArtifactManager:
    """Manages artifact storage for a verification run."""

    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)

    def ensure_dirs(self) -> None:
        """Create the artifact directory structure."""
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def path(self, filename: str) -> Path:
        """Get full path for an artifact file."""
        return self.base_dir / filename

    def save_json(self, filename: str, data: dict | list) -> Path:
        """Save data as JSON artifact."""
        p = self.path(filename)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        return p

    def save_text(self, filename: str, text: str) -> Path:
        """Save text artifact."""
        p = self.path(filename)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def save_bytes(self, filename: str, data: bytes) -> Path:
        """Save binary artifact."""
        p = self.path(filename)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return p

    def read_json(self, filename: str) -> dict | list | None:
        """Read a JSON artifact."""
        p = self.path(filename)
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    def list_artifacts(self) -> list[str]:
        """List all artifact files."""
        if not self.base_dir.exists():
            return []
        return [f.name for f in self.base_dir.iterdir() if f.is_file()]
