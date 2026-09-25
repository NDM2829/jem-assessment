"""Write the assessment note CSV from the same bundle rules used by the app."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jem.io import demo_sources
from jem.notes import RULES_VERSION, classify_bundle, note_classifications_csv_bytes, note_evidence_csv_bytes
from jem.pipeline import ingest


def main() -> None:
    parser = argparse.ArgumentParser(description="Export all source note classifications")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data" / "demo")
    parser.add_argument("--output", type=Path, default=ROOT / "note_classifications.csv")
    parser.add_argument("--evidence-output", type=Path, default=None,
                        help="Optional separate internal evidence CSV path")
    args = parser.parse_args()
    sources = demo_sources(ROOT) if args.data_dir == ROOT / "data" / "demo" else {
        path.name: path for path in args.data_dir.glob("*.csv")}
    result = ingest(sources)
    if not result.accepted or "shift_notes.csv" not in result.bundle.tables or any(
        item.startswith("Note classification unavailable") for item in result.unavailable_outputs):
        raise SystemExit("Cannot export notes: correct the bundle or supply a valid shift_notes.csv.")
    rows = classify_bundle(result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(note_classifications_csv_bytes(rows))
    if args.evidence_output:
        args.evidence_output.parent.mkdir(parents=True, exist_ok=True)
        args.evidence_output.write_bytes(note_evidence_csv_bytes(rows))
    print(f"Exported {len(rows)} source note classifications using {RULES_VERSION}.")


if __name__ == "__main__":
    main()
