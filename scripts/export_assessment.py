"""Produce both required assessment CSVs from one processed source bundle."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jem.exports import source_hashes, write_manifest
from jem.io import FILES, demo_sources
from jem.pipeline import ingest
from jem.predictors.base import ProcessingError
from jem.workflow import load_policy, process_bundle


def export_assessment(data_dir: Path, output_dir: Path, as_of: str | None = None) -> tuple[int, int]:
    sources = demo_sources(ROOT) if data_dir == ROOT / "data" / "demo" else {
        name: path for name in FILES if (path := data_dir / name).is_file()}
    # Payroll is accepted by ingestion but unused. Keep it out of this run's
    # inputs and manifest even when a local raw original happens to exist.
    sources.pop("payroll_details.csv", None)
    ingestion = ingest(sources, as_of=as_of)
    if not ingestion.accepted:
        raise ProcessingError("Input bundle rejected; inspect structured ingestion issues before exporting.")
    if "shift_notes.csv" not in ingestion.bundle.tables or any(
            message.startswith("Note classification unavailable") for message in ingestion.unavailable_outputs):
        raise ProcessingError("A valid shift_notes.csv is required for both assessment outputs.")
    policy = load_policy(ROOT / "config" / "prediction_policy.toml")
    processed = process_bundle(ingestion, policy)
    forecasts = tuple(entry.forecast for entry in processed.queue)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "predictions.csv").write_bytes(processed.predictions_csv)
    (output_dir / "note_classifications.csv").write_bytes(processed.note_classifications_csv)
    with (ROOT / "config" / "prediction_policy.toml").open("rb") as handle:
        import tomli
        deployment = tomli.load(handle)["deployment"]
    write_manifest(output_dir / "predictions_manifest.json", forecasts=forecasts,
                   input_hashes=source_hashes(sources), policy_version=policy.config.policy_version,
                   threshold_rule=deployment["threshold_rule"],
                   threshold_source_weeks=deployment["threshold_source_weeks"],
                   threshold_source_eligible_rows=deployment["threshold_source_eligible_rows"],
                   reporting_mode=ingestion.reporting.mode)
    return len(forecasts), len(processed.note_classifications)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export both required assessment CSVs from one bundle")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data" / "demo")
    parser.add_argument("--output-dir", type=Path, default=ROOT)
    parser.add_argument("--as-of", default=None, help="Selected reporting date, YYYY-MM-DD")
    args = parser.parse_args()
    employees, notes = export_assessment(args.data_dir, args.output_dir, args.as_of)
    print(f"Exported {employees} employee predictions and {notes} source note classifications.")


if __name__ == "__main__":
    try:
        main()
    except ProcessingError as exc:
        raise SystemExit(f"Cannot process export: {exc}") from None
