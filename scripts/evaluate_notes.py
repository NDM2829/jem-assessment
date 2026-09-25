"""Score only completed human review against matching original notes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jem.io import demo_sources
from jem.note_evaluation import evaluate_review
from jem.notes import classify_bundle
from jem.pipeline import ingest


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate blind human note review")
    parser.add_argument("--review", type=Path, default=ROOT / "note_validation_review.csv")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data" / "demo")
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON metrics path")
    args = parser.parse_args()
    sources = demo_sources(ROOT) if args.data_dir == ROOT / "data" / "demo" else {
        path.name: path for path in args.data_dir.glob("*.csv")}
    result = ingest(sources)
    if not result.accepted or "shift_notes.csv" not in result.bundle.tables:
        raise SystemExit("Cannot evaluate notes: a valid bundle with shift_notes.csv is required.")
    report = evaluate_review(args.review.read_bytes(), classify_bundle(result))
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
