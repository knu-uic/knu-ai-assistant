from __future__ import annotations

from typing import Any, Dict, List


def _append_budget(parts: list[str], text: str, remaining: int) -> int:
    if remaining <= 0 or not text:
        return remaining
    if len(text) <= remaining:
        parts.append(text)
        return remaining - len(text)
    note = f"\n... [컨텍스트 길이 제한으로 이후 {len(text) - remaining}자 제외]"
    if remaining <= len(note):
        parts.append(text[:remaining].rstrip())
    else:
        keep = remaining - len(note)
        parts.append(text[:keep].rstrip() + note)
    return 0


def _context_header(c: Dict[str, Any]) -> str:
    sd = c.get("start_date")
    ed = c.get("end_date")
    date_line = ""
    if sd or ed:
        date_line = f"\n접수기간: {sd or '미상'} ~ {ed or '미상'}"
    return f"[{c['title']}]({c['url']}){date_line}"


def _format_context_with_budget(c: Dict[str, Any], budget: int) -> str:
    header = _context_header(c)
    body = (c.get("body_content") or c.get("snippet") or "").strip()
    matched_chunk = (c.get("matched_chunk") or "").strip()
    attachment_names = c.get("attachment_names") or []

    full = f"{header}\n{body}"
    if len(full) <= budget:
        parts = [full]
        if attachment_names:
            parts.append("\n[첨부파일명]")
            parts.extend(f"- {name}" for name in attachment_names)
        return "\n".join(parts)

    parts = [header]
    remaining = budget - len(header)

    if body and remaining > 0:
        heading = "\n[본문]"
        parts.append(heading)
        remaining -= len(heading)
        body_budget = max(0, int(remaining * 0.8))
        body_parts: list[str] = []
        _append_budget(body_parts, body, body_budget)
        body_text = "\n".join(body_parts)
        parts.append(body_text)
        remaining -= len(body_text)

    if matched_chunk and remaining > 0:
        heading = "\n[검색 매칭 청크]"
        parts.append(heading)
        remaining -= len(heading)
        remaining = _append_budget(parts, matched_chunk, remaining)

    if attachment_names and remaining > 0:
        heading = "\n[첨부파일명]"
        parts.append(heading)
        remaining -= len(heading)
        attachment_text = "\n".join(f"- {name}" for name in attachment_names)
        remaining = _append_budget(parts, attachment_text, remaining)

    return "\n".join(part for part in parts if part)


def _format_support_context(c: Dict[str, Any], budget: int) -> str:
    header = _context_header(c)
    body = (c.get("body_content") or c.get("snippet") or "").strip()
    matched_chunk = (c.get("matched_chunk") or "").strip()
    summary = (c.get("summary") or "").strip()
    attachment_names = c.get("attachment_names") or []

    parts = [header]
    remaining = budget - len(header)

    if summary and remaining > 0:
        heading = "\n[요약]"
        parts.append(heading)
        remaining -= len(heading)
        remaining = _append_budget(parts, summary, remaining)

    if matched_chunk and remaining > 0:
        heading = "\n[검색 매칭 청크]"
        parts.append(heading)
        remaining -= len(heading)
        remaining = _append_budget(parts, matched_chunk, remaining)

    if body and remaining > 0:
        heading = "\n[본문 일부]"
        parts.append(heading)
        remaining -= len(heading)
        body_budget = max(0, int(remaining * 0.5))
        body_parts: list[str] = []
        _append_budget(body_parts, body, body_budget)
        body_text = "\n".join(body_parts)
        parts.append(body_text)
        remaining -= len(body_text)

    if attachment_names and remaining > 0:
        heading = "\n[첨부파일명]"
        parts.append(heading)
        remaining -= len(heading)
        attachment_text = "\n".join(f"- {name}" for name in attachment_names)
        remaining = _append_budget(parts, attachment_text, remaining)

    return "\n".join(part for part in parts if part)


def _format_broad_context(contexts: List[Dict[str, Any]], budget: int) -> str:
    if not contexts:
        return "(컨텍스트 없음)"

    parts: list[str] = []
    remaining = budget

    for c in contexts:
        if remaining <= 0:
            break

        header = _context_header(c)
        summary = (c.get("summary") or "").strip() or (c.get("matched_chunk") or "").strip()
        card = header
        if summary:
            card += f"\n요약: {summary}"

        block = ("\n\n" if parts else "") + card
        before = len("".join(parts))
        remaining = _append_budget(parts, block, remaining)
        if len("".join(parts)) == before:
            break

    return "".join(parts).strip()


def _pack_evidence_chunks(evidence_chunks: List[Dict[str, Any]], budget: int) -> str:
    if not evidence_chunks or budget <= 0:
        return ""

    parts: list[str] = ["# 핵심 검색 청크"]
    remaining = budget - len(parts[0])

    for idx, ev in enumerate(evidence_chunks, 1):
        if remaining <= 0:
            break

        block = (
            f"\n\n[{idx}] {ev['title']}\n"
            f"URL: {ev['url']}\n"
            f"{ev['chunk']}"
        )

        before = len("".join(parts))
        remaining = _append_budget(parts, block, remaining)
        if len("".join(parts)) == before:
            break

    return "".join(parts).strip()


def pack_contexts(
    contexts: List[Dict[str, Any]],
    evidence_chunks: List[Dict[str, Any]] | None = None,
    budget: int = 6000,
) -> str:
    if not contexts and not evidence_chunks:
        return "(컨텍스트 없음)"
    if budget <= 0:
        budget = 6000

    packed: list[str] = []
    remaining = budget

    evidence_text = _pack_evidence_chunks(
        evidence_chunks or [],
        max(0, int(budget * 0.35)),
    )

    if evidence_text:
        packed.append(evidence_text)
        remaining -= len(evidence_text)

    for idx, context in enumerate(contexts):
        if remaining <= 0:
            break

        separator_cost = len("\n\n---\n\n") if packed else 0
        available = remaining - separator_cost
        if available <= 0:
            break

        if idx == 0:
            rendered = _format_context_with_budget(context, available)
        else:
            rendered = _format_support_context(context, available)

        packed.append(rendered)
        remaining -= separator_cost + len(rendered)

    return "\n\n---\n\n".join(packed)


__all__ = [
    "pack_contexts",
    "_format_broad_context",
]
