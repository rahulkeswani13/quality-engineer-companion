from __future__ import annotations

import json
import os
import re

from companion.models import Chunk
from companion.rag.embed import GeminiQuotaError

TOPIC_HINTS = ("torque", "ncr", "hold", "qms", "procedure", "capa", "lot", "containment", "wrench")


def local_topic_labels(query: str, chunks: list[Chunk]) -> dict[str, str]:
    q = set(re.findall(r"[a-z0-9]+", query.lower()))
    labels: dict[str, str] = {}
    query_is_procedure = bool(q & {h for h in TOPIC_HINTS})
    for chunk in chunks:
        blob = set(re.findall(r"[a-z0-9]+", f"{chunk.doc_id} {chunk.heading} {chunk.text}".lower()))
        overlap = q & blob
        topical = bool(overlap & {h for h in TOPIC_HINTS}) or ("torque" in blob and "torque" in q)
        if query_is_procedure and topical:
            labels[chunk.chunk_id] = "relevant"
        else:
            labels[chunk.chunk_id] = "off_topic"
    return labels


def local_rewrite(query: str, plant: str) -> str:
    return f"{query} current revision plant {plant}"


def local_explanation(
    query: str,
    sop_ids: list[str],
    lot_id: str,
    serials: list[str] | None = None,
) -> str:
    # Do not echo the raw query: it can mention a serial from another lot
    # (calibration_escape cites SN-4419 while planning L-8820) and fail B1.
    del query  # kept in the signature so call sites stay uniform with gemini_*
    cited = ", ".join(sop_ids) if sop_ids else "(none)"
    text = f"Lot {lot_id} requires a lot hold per {cited}."
    if serials:
        text += f" Exceptions: {', '.join(serials)}."
    text += " Shipped serials are exceptions, not WIP hold targets."
    return text


def gemini_json(prompt: str, model: str = "gemini-2.5-flash") -> dict:
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise GeminiQuotaError("gemini_missing_key")
    client = genai.Client(api_key=api_key)
    last_exc: Exception | None = None
    for name in (model, "gemini-2.0-flash"):
        try:
            response = client.models.generate_content(
                model=name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0,
                    response_mime_type="application/json",
                ),
            )
            return json.loads(response.text)
        except GeminiQuotaError:
            raise
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            text = str(exc).lower()
            if "429" in text or "quota" in text:
                raise GeminiQuotaError("gemini_429") from exc
            if "timeout" in text or "deadline" in text or "timed out" in text:
                raise GeminiQuotaError("gemini_timeout") from exc
            continue
    raise GeminiQuotaError("gemini_timeout") from last_exc


def gemini_topic_labels(query: str, chunks: list[Chunk]) -> dict[str, str]:
    payload = [
        {"id": c.chunk_id, "doc_id": c.doc_id, "heading": c.heading, "text": c.text[:800]}
        for c in chunks
    ]
    prompt = (
        "Grade each chunk as relevant or off_topic for the quality query. "
        "Do not judge revision or plant — code does that. "
        f"Query: {query}\nChunks: {json.dumps(payload)}\n"
        'Return JSON {"grades": [{"id": "...", "label": "relevant"|"off_topic"}]}'
    )
    try:
        data = gemini_json(prompt)
    except GeminiQuotaError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise GeminiQuotaError("gemini_timeout") from exc
    out: dict[str, str] = {}
    for row in data.get("grades", []):
        label = row.get("label", "off_topic")
        if label not in ("relevant", "off_topic"):
            label = "off_topic"
        out[row["id"]] = label
    return out


def gemini_rewrite(query: str, plant: str) -> str:
    try:
        data = gemini_json(
            "Rewrite this quality query to target the current revision procedure "
            f"at plant {plant}. Keep the original defect; do not invent a defect. "
            'Return JSON {"query": "..."}.\n'
            f"Original: {query}"
        )
    except GeminiQuotaError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise GeminiQuotaError("gemini_timeout") from exc
    return str(data.get("query") or local_rewrite(query, plant))


def gemini_explanation(
    query: str,
    sop_ids: list[str],
    lot_id: str,
    snippets: list[str],
    serials: list[str] | None = None,
) -> str:
    allowed = {
        "sop_ids": sop_ids,
        "lot_id": lot_id,
        "serials": serials or [],
    }
    try:
        data = gemini_json(
            "Write a short cited containment explanation. Cite only these identifiers; "
            "do not mention any other SOP, lot, or serial. "
            f"Allowed: {json.dumps(allowed)}. Query: {query}. "
            f"Snippets: {snippets[:4]}. Return JSON {{\"explanation\": \"...\"}}."
        )
    except GeminiQuotaError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise GeminiQuotaError("gemini_timeout") from exc
    return str(data.get("explanation") or local_explanation(query, sop_ids, lot_id, serials))
