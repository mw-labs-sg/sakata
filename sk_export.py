"""Provider-neutral briefing export for ChatGPT, Claude and other LLMs.

The JSON snapshot is canonical. Markdown wraps the same snapshot in a short
analysis instruction and preserves its structure in fenced JSON blocks, which
gives an LLM readable context without weakening types or numeric precision.
Chart-only series are deliberately removed: the computed levels, rankings and
tables are the output; thousands of SVG coordinates and OHLC points are not.
"""
import datetime as dt
import json
import math


SCHEMA = "sakata.briefing.v1"
CHART_KEYS = {"t", "o", "h", "l", "c", "ph", "pl", "md", "vb", "vs",
              "charts"}


def clean(value):
    """Return a JSON-safe copy while dropping chart-only payloads."""
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()
                if k not in CHART_KEYS}
    if isinstance(value, (list, tuple, set)):
        return [clean(v) for v in value]
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    # numpy scalars expose item(); keep this module independent of numpy.
    try:
        return clean(value.item())
    except (AttributeError, ValueError):
        return str(value)


def snapshot(sections: dict, selections: dict, mode: str,
             generated=None) -> dict:
    generated = generated or dt.datetime.now(dt.timezone.utc)
    return clean({
        "schema": SCHEMA,
        "generated_utc": generated,
        "mode": mode.lower(),
        "selections": selections,
        "sections": sections,
    })


def as_json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False)


def as_markdown(data: dict) -> str:
    """A readable prompt envelope around the exact structured snapshot."""
    lines = [
        "# Sakata Market Briefing",
        "",
        f"Generated: {data.get('generated_utc', '—')}",
        f"Mode: {str(data.get('mode', 'focused')).title()}",
        f"Schema: `{data.get('schema', SCHEMA)}`",
        "",
        "## Analysis task",
        "",
        "Act as a cross-asset futures strategist. Analyse only the supplied ",
        "snapshot. Identify the market regime, cross-asset agreement and ",
        "divergences, strongest opportunities, volatility/margin/carry/event ",
        "risks, and clear invalidation conditions. Separate observations from ",
        "interpretations. Do not invent missing data, and flag stale, partial ",
        "or conflicting inputs.",
        "",
        "## Active selections",
        "",
        "```json",
        json.dumps(data.get("selections", {}), ensure_ascii=False, indent=2),
        "```",
    ]
    for name, section in data.get("sections", {}).items():
        lines += ["", f"## {name.replace('_', ' ').title()}", "", "```json",
                  json.dumps(section, ensure_ascii=False, indent=2), "```"]
    lines += ["", "---", "", "End of Sakata briefing.", ""]
    return "\n".join(lines)
