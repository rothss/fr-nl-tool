from __future__ import annotations


def render_answer_text(query_result: dict) -> str | None:
    answer_text = query_result.get("answer_text")
    if answer_text is None:
        return None
    return str(answer_text)

