"""Create a blind, non-overwriting review sample from source notes."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
import random
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jem.io import demo_sources
from jem.pipeline import ingest


CHALLENGE = re.compile(r"client|klient|centre|manager|mgmt|approv|signed|relief|cover|aflos|masjien|oorhandiging|akezanga", re.I)
COLUMNS = ("sample_id", "sample_split", "shift_id", "note", "human_category", "reviewer", "review_comment")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a fresh blind note review sheet")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data" / "demo")
    parser.add_argument("--output", type=Path, default=ROOT / "note_validation_review.csv")
    parser.add_argument("--exclude-review", type=Path, action="append", default=[],
                        help="Previously reviewed CSV whose shift IDs must be excluded")
    parser.add_argument("--exclude-ids", type=Path, help="Optional newline-separated prior sample shift IDs")
    parser.add_argument("--seed", type=int, default=506)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("Review sheet already exists; keep existing human work and choose a new output path.")
    sources = demo_sources(ROOT) if args.data_dir == ROOT / "data" / "demo" else {
        path.name: path for path in args.data_dir.glob("*.csv")}
    result = ingest(sources)
    if not result.accepted or "shift_notes.csv" not in result.bundle.tables:
        raise SystemExit("A valid bundle with shift_notes.csv is required.")
    excluded = set(args.exclude_ids.read_text(encoding="utf-8").splitlines()) if args.exclude_ids else set()
    for path in args.exclude_review:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            excluded.update(row["shift_id"] for row in csv.DictReader(handle))
    counts = {}
    for row in result.notes:
        counts[row.get("shift_id", "")] = counts.get(row.get("shift_id", ""), 0) + 1
    available = [row for row in result.notes if row.get("shift_id") and counts[row["shift_id"]] == 1
                 and row["shift_id"] not in excluded]
    randomizer = random.Random(args.seed)
    if len(available) < 120:
        raise SystemExit("Fewer than 120 unique unreviewed source notes are available.")
    random_rows = randomizer.sample(available, 100)
    chosen = {row["shift_id"] for row in random_rows}
    challenge_pool = [row for row in available if row["shift_id"] not in chosen and CHALLENGE.search(row.get("note", ""))]
    if len(challenge_pool) < 20:
        raise SystemExit("Fewer than 20 fresh targeted challenge notes are available.")
    challenge_rows = randomizer.sample(challenge_pool, 20)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        for index, (split, row) in enumerate(
            [("random_validation", row) for row in random_rows] +
            [("targeted_challenge", row) for row in challenge_rows], start=1):
            writer.writerow({"sample_id": f"N{index:03d}", "sample_split": split,
                             "shift_id": row["shift_id"], "note": row.get("note", ""),
                             "human_category": "", "reviewer": "", "review_comment": ""})
    print("Created blind review sheet: 100 random, 20 targeted; human fields blank.")


if __name__ == "__main__":
    main()
