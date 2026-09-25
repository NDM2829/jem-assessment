"""Reproduce the four-method shared-code comparison without changing deployment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tomli

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jem.comparison import STATISTICAL, evaluate
from jem.features import build_history, source_shifts
from jem.io import FILES, demo_sources
from jem.pipeline import ingest
from jem.workflow import load_policy


def main() -> None:
    parser = argparse.ArgumentParser(description="Chronological comparison of three statistical candidates and naive")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data" / "demo")
    parser.add_argument("--output", type=Path, default=ROOT / "analysis" / "evidence" / "step8_comparison.json")
    args = parser.parse_args()
    sources = demo_sources(ROOT) if args.data_dir == ROOT / "data" / "demo" else {
        name: path for name in FILES if (path := args.data_dir / name).is_file()}
    sources.pop("payroll_details.csv", None)
    declared = tomli.loads((ROOT / "config" / "prediction_policy.toml").read_text())["comparison"]
    if (tuple(declared["statistical_candidates"]) != STATISTICAL or declared["baseline"] != "naive"
        or declared["primary_metric"] != "pooled_chronological_f2"
        or declared["tie_break"]["order"] != ["higher_recall", "fewer_false_alerts", "fewer_total_alerts", "method_name"]
        or declared["parameter_search"] or declared["new_model_families"]):
        raise SystemExit("The declared Step 1 comparison policy differs from the implemented fixed rule.")
    ingested = ingest(sources)
    if not ingested.accepted or ingested.reporting.week_start is None:
        raise SystemExit("Bundle rejected; fix the structured ingestion issues before evaluating.")
    history = build_history(source_shifts(ingested), ingested.employees_by_id, ingested.reporting.week_start)
    report = evaluate(history, load_policy(ROOT / "config" / "prediction_policy.toml").config,
                      ingested.reporting.week_start)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("Main evaluation weeks:", ", ".join(report["weeks"]["main"]))
    for method, row in report["summary"].items():
        print(f"{method}: TP={row['TP']} FP={row['FP']} FN={row['FN']} F2={row['F2']:.4f} all_alerts={row['all_review_alerts']}")
    print("Selected:", report["selected"]["method"], "threshold:", report["selected"]["deployment_threshold"])
    print("Report:", args.output)


if __name__ == "__main__":
    main()
