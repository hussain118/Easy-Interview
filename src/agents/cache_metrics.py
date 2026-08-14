"""Prompt-cache observability for GPT calls. Records only non-sensitive
numeric/metadata fields — never candidate answers, PII, or prompt text.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

METRICS_LOG_PATH = Path(__file__).resolve().parent.parent.parent / "output" / "cache_metrics.jsonl"


@dataclass
class CacheMetric:
    timestamp_ms: int
    model: str
    purpose: str
    input_tokens: int
    cached_tokens: int
    output_tokens: int
    cache_hit_ratio: float


def record(
    *,
    model: str,
    purpose: str,
    input_tokens: int,
    cached_tokens: int,
    output_tokens: int,
    log_to_file: bool = True,
) -> CacheMetric:
    """cache_hit_ratio = cached_tokens / input_tokens when input_tokens > 0, else 0."""
    ratio = (cached_tokens / input_tokens) if input_tokens > 0 else 0.0
    metric = CacheMetric(
        timestamp_ms=int(time.time() * 1000),
        model=model,
        purpose=purpose,
        input_tokens=input_tokens,
        cached_tokens=cached_tokens,
        output_tokens=output_tokens,
        cache_hit_ratio=round(ratio, 4),
    )
    if log_to_file:
        METRICS_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with METRICS_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(metric)) + "\n")
    return metric


def summarize(path: Path = METRICS_LOG_PATH) -> dict:
    """Aggregate stats across all recorded metrics — used to report REAL
    measured cache behavior in ARCHITECTURE.md, never an invented number.
    """
    if not path.exists():
        return {"count": 0}
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        return {"count": 0}
    total_input = sum(r["input_tokens"] for r in rows)
    total_cached = sum(r["cached_tokens"] for r in rows)
    return {
        "count": len(rows),
        "total_input_tokens": total_input,
        "total_cached_tokens": total_cached,
        "overall_cache_hit_ratio": round(total_cached / total_input, 4) if total_input > 0 else 0.0,
    }
