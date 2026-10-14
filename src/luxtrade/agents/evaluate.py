"""Golden-set evaluation (SOLUTION_DESIGN §9): ``python -m luxtrade.agents.evaluate``.

Asks every variant (EN/FR/DE) of every golden question through the real LLM and scores:
spec accuracy, answer status, expected limitations and, on real data only, the key numbers
(rank order of the top 5 and values within tolerance). Writes ``data/runs/eval_<timestamp>.json``.
"""

import argparse
import json
import logging
import sys
from datetime import UTC, datetime

import yaml

from luxtrade import config
from luxtrade.agents.service import Assistant
from luxtrade.logging_setup import setup_logging

logger = logging.getLogger(__name__)
_FLOW_LISTS = {
    "top_exports": "export",
    "top_imports": "import",
    "top_total_trade": "total",
    "top_exports_hs2": "export",
    "top_imports_hs2": "import",
}


def _spec_score(expected: dict, actual: dict | None) -> tuple[int, int, list[str]]:
    if not actual:
        return 0, len(expected), list(expected)
    misses = [k for k, v in expected.items() if str(actual.get(k)) != str(v)]
    return len(expected) - len(misses), len(expected), misses


def _numbers(entry: dict, rec) -> list[str]:  # noqa: ANN001 - RunRecord
    """Compare top-5 rankings and values with the golden benchmark (real data only)."""
    problems = []
    main = rec.frame("main")
    tol = entry.get("tolerance", {}).get("value_meur", 0.1)
    for name, flow in _FLOW_LISTS.items():
        expected = entry.get("expected", {}).get(name)
        if not expected or main.empty:
            continue
        got = main[(main["flow"] == flow) & (main["kind"] == "item")].sort_values("rank")
        exp_codes = [str(row[0]) for row in expected[:5]]
        got_codes = list(got["key"].astype(str).head(5))
        if exp_codes != got_codes:
            problems.append(f"{name}: rank order {got_codes} != {exp_codes}")
        for code, meur, *_ in expected[:5]:
            row = got[got["key"].astype(str) == str(code)]
            if not row.empty and abs(row["value"].iloc[0] / 1e6 - meur) > tol:
                problems.append(f"{name}: {code} {row['value'].iloc[0] / 1e6:.1f} != {meur}")
    return problems


def evaluate(languages: tuple[str, ...] = ("en", "fr", "de")) -> dict:
    """Run the golden set and return the report."""
    entries = yaml.safe_load(config.GOLDEN_FILE.read_text(encoding="utf-8"))
    assistant = Assistant()
    if not assistant.online:
        raise SystemExit("The golden evaluation calls the LLM: set ANTHROPIC_API_KEY first.")
    placeholder = assistant.sem.coverage.is_placeholder
    rows = []
    for entry in entries:
        for lang, question in entry.get("variants", {}).items():
            if lang not in languages:
                continue
            rec = assistant.ask(question)
            hit, total, misses = _spec_score(entry.get("expected_spec", {}), rec.spec)
            want_lims = set(entry.get("expected_limitations", []))
            got_lims = {lim["key"] for lim in rec.limitations}
            numbers = [] if placeholder else _numbers(entry, rec)
            rows.append(
                {
                    "id": entry["id"],
                    "lang": lang,
                    "run_id": rec.run_id,
                    "status": rec.status,
                    "spec_score": f"{hit}/{total}",
                    "spec_misses": misses,
                    "missing_limitations": sorted(want_lims - got_lims),
                    "numbers": "skipped (placeholder data)" if placeholder else (numbers or "ok"),
                    "insight_source": rec.insight_source,
                }
            )
            logger.info("%s [%s] %s spec %d/%d", entry["id"], lang, rec.status, hit, total)
    spec_hits = sum(int(r["spec_score"].split("/")[0]) for r in rows)
    spec_total = sum(int(r["spec_score"].split("/")[1]) for r in rows)
    report = {
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "model": assistant.llm.model,
        "placeholder_data": placeholder,
        "questions": len(rows),
        "answered": sum(r["status"] == "answered" for r in rows),
        "spec_accuracy_pct": round(100 * spec_hits / spec_total, 1) if spec_total else None,
        "limitations_complete": sum(not r["missing_limitations"] for r in rows),
        "rows": rows,
    }
    out = config.RUNS_DIR / f"eval_{datetime.now(UTC):%Y%m%dT%H%M%S}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    report["file"] = str(out)
    return report


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Run the golden question set")
    parser.add_argument("--lang", nargs="*", default=["en", "fr", "de"])
    args = parser.parse_args()
    setup_logging(log_file="eval.log")
    report = evaluate(tuple(args.lang))
    summary = {k: v for k, v in report.items() if k != "rows"}
    json.dump(summary, sys.stdout, indent=1, ensure_ascii=False)
    print()
    for r in report["rows"]:
        print(
            f"{r['id']:<22} {r['lang']} {r['status']:<11} spec {r['spec_score']:<6} "
            f"lims-missing {r['missing_limitations']} numbers {r['numbers']}"
        )


if __name__ == "__main__":
    main()
