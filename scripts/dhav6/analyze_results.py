#!/usr/bin/env python3
"""Aggregate harbor job results into a summary table.

Usage:
    python analyze_results.py results/
    python analyze_results.py results/baselines_qwen3.5-35b-a3b results/dhav6_qwen3.5-35b-a3b
"""

import json
import sys
from pathlib import Path


def score_job(job_dir: Path) -> dict:
    """Score a single harbor job directory."""
    results = list(job_dir.rglob("*/result.json"))
    # Filter out the top-level result.json (harbor summary)
    results = [r for r in results if r.parent != job_dir and r.parent.parent != job_dir
               or "__" in r.parent.name]
    # Actually just look for task-level results (dirs with __ in name)
    task_results = []
    for ts_dir in job_dir.iterdir():
        if not ts_dir.is_dir() or not ts_dir.name.startswith("2026"):
            continue
        for task_dir in ts_dir.iterdir():
            rf = task_dir / "result.json"
            if rf.exists():
                task_results.append(rf)

    if not task_results:
        # Try flat layout
        for task_dir in job_dir.iterdir():
            if task_dir.is_dir() and "__" in task_dir.name:
                rf = task_dir / "result.json"
                if rf.exists():
                    task_results.append(rf)

    total = len(task_results)
    passed = 0
    errors = 0
    for rf in task_results:
        try:
            d = json.loads(rf.read_text())
            vr = d.get("verifier_result", {})
            if isinstance(vr, dict):
                reward = vr.get("rewards", {}).get("reward", 0)
                if reward > 0:
                    passed += 1
            ar = d.get("agent_result", {})
            if isinstance(ar, dict):
                ei = ar.get("exception_info", {})
                if isinstance(ei, dict) and ei.get("type"):
                    errors += 1
        except Exception:
            errors += 1

    return {
        "total": total,
        "passed": passed,
        "errors": errors,
        "rate": f"{passed/total*100:.1f}%" if total else "N/A",
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: python analyze_results.py <results_dir> [results_dir2 ...]")
        sys.exit(1)

    rows = []
    for arg in sys.argv[1:]:
        base = Path(arg)
        if not base.exists():
            print(f"Warning: {base} does not exist, skipping")
            continue
        # Each subdirectory is a job
        for job_dir in sorted(base.iterdir()):
            if not job_dir.is_dir():
                continue
            scores = score_job(job_dir)
            if scores["total"] == 0:
                continue
            rows.append({
                "job": f"{base.name}/{job_dir.name}",
                **scores,
            })

    if not rows:
        print("No results found.")
        sys.exit(0)

    # Print table
    hdr = f"{'Job':<50} {'Passed':>8} {'Total':>8} {'Errors':>8} {'Rate':>8}"
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        print(f"{r['job']:<50} {r['passed']:>8} {r['total']:>8} {r['errors']:>8} {r['rate']:>8}")

    # CSV
    csv_path = Path(sys.argv[1]).parent / "results_summary.csv"
    with open(csv_path, "w") as f:
        f.write("job,passed,total,errors,rate\n")
        for r in rows:
            f.write(f"{r['job']},{r['passed']},{r['total']},{r['errors']},{r['rate']}\n")
    print(f"\nCSV saved to {csv_path}")


if __name__ == "__main__":
    main()
