from __future__ import annotations

import json
import os
import subprocess


def _extract_json_object(text: str) -> dict | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except Exception:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(raw[start : end + 1])
            return data if isinstance(data, dict) else None
        except Exception:
            return None
    return None


class LLMIntentParser:
    def __init__(self, command: str | None = None) -> None:
        self.command = command or os.environ.get("OPM_NL_INTENT_LLM_COMMAND", "").strip()

    @property
    def enabled(self) -> bool:
        return bool(self.command)

    def parse(self, normalized_query: str, hints: dict | None = None) -> dict | None:
        if not self.enabled:
            return None
        payload = {
            "task": "opm_intent_slot_fill",
            "query": str(normalized_query or ""),
            "hints": hints or {},
        }
        try:
            proc = subprocess.run(
                self.command,
                input=json.dumps(payload, ensure_ascii=False),
                text=True,
                shell=True,
                check=False,
                capture_output=True,
                timeout=20,
            )
        except Exception:
            return None
        if proc.returncode != 0:
            return None
        return _extract_json_object(proc.stdout)


def maybe_parse_with_local_llm(normalized_query: str, hints: dict | None = None) -> dict | None:
    parser = LLMIntentParser()
    return parser.parse(normalized_query, hints=hints)

