"""（长上下文的单价跃升场景）为长上下文的单价跃升选哪个基线才不会被误导？用延迟与分位统计比较至少两个基线在同一输入上的差异。

测量：延迟与分位统计（p95_latency_ms）；协议：对照实验。
仅依赖 Python 标准库。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any

SEP = '\t'
MEASURE_FIELD = 'p95_latency_ms'
FAILURE_MODE = '资源预算不足'


def _read_rows(path: str, limit: int = 0) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            if SEP and SEP in line:
                label, _, payload = line.partition(SEP)
                rows.append((label.strip(), payload.strip()))
            else:
                rows.append(("", line.strip()))
            if limit and len(rows) >= limit:
                break
    return rows


def _nums(values: list[str]) -> list[float]:
    out: list[float] = []
    for v in values:
        try:
            out.append(float(v))
        except ValueError:
            continue
    return out


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    frac = pos - lo
    return ordered[lo] * (1 - frac) + ordered[hi] * frac



def measure_latency(rows: list[tuple[str, str]]) -> dict:
    """延迟测量：按标签分桶，报告 p50/p95/p99 与退化判定。"""
    buckets: dict[str, list[float]] = {}
    for label, payload in rows:
        buckets.setdefault(label or "all", []).extend(_nums([payload]))
    out: dict = {"metric": "latency", "unit": "ms"}
    per_label: dict[str, dict] = {}
    for label, values in sorted(buckets.items()):
        if not values:
            continue
        p50 = _percentile(values, 0.50)
        p95 = _percentile(values, 0.95)
        p99 = _percentile(values, 0.99)
        per_label[label] = {"n": len(values), "p50": p50, "p95": p95, "p99": p99}
    if per_label:
        baselines = [v["p95"] for v in per_label.values() if v["p95"] is not None]
        if len(baselines) > 1:
            base = min(baselines)
            worst = max(baselines)
            ratio = round(worst / base, 3) if base else None
            out["p95_latency_ms"] = worst
            out["regression_ratio"] = ratio
            out["regressed"] = bool(ratio and ratio > 1.5)
    out["per_label"] = per_label
    return out



def measure(rows: list[tuple[str, str]]) -> dict:
    """按测量族分派到具体测量函数。"""
    return measure_latency(rows)



def run_protocol(measure, rows: list[tuple[str, str]], args: argparse.Namespace) -> dict:
    """对照实验：按标签分组测量，并列出组间差异。"""
    buckets: dict[str, list[tuple[str, str]]] = {}
    for label, payload in rows:
        buckets.setdefault(label or "all", []).append((label, payload))
    groups = {name: measure(items) for name, items in sorted(buckets.items())}
    result = {"protocol": "controlled_comparison", "groups": groups,
              "group_count": len(groups)}
    values = [g.get('p95_latency_ms') for g in groups.values()
              if isinstance(g.get('p95_latency_ms'), (int, float))]
    if len(values) > 1:
        result["spread"] = round(max(values) - min(values), 6)
        result["max_group"] = max(groups, key=lambda k: groups[k].get('p95_latency_ms', 0))
    return result



def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="（长上下文的单价跃升场景）为长上下文的单价跃升选哪个基线才不会被误导？用延迟与分位统计比较至少两个基线在同一输入上的差异。")
    ap.add_argument("--input", help="输入文件路径")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 行")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    ap.add_argument("--threshold", type=float, default=0.0, help="判定阈值")
    ap.add_argument("--budget", type=int, default=50, help="预算条数")
    ap.add_argument("--bins", type=int, default=10, help="分桶数量")
    ap.add_argument("--components", default="", help="组件列表（逗号分隔）")
    args = ap.parse_args(argv)

    if not args.input:
        ap.print_help()
        return 0

    t0 = time.time()
    try:
        rows = _read_rows(args.input, args.limit)
    except OSError as exc:
        print(f"读取失败：{exc}", file=sys.stderr)
        return 2

    measured = measure(rows)
    result = run_protocol(measure, rows, args)
    result["measure"] = measured
    result["row_count"] = len(rows)
    result["failure_mode"] = FAILURE_MODE
    result["elapsed_seconds"] = round(time.time() - t0, 4)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        value = measured.get(MEASURE_FIELD)
        print(f"读取 1 个文件，共 {result['row_count']} 条记录")
        print(f"{MEASURE_FIELD} = {value}")
        print(f"处理完成，耗时 {result['elapsed_seconds']}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
