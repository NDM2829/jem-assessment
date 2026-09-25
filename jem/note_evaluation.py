"""Metrics against blind human review only; never use AI reference labels as truth."""

from __future__ import annotations

from collections import Counter
import csv
import io

from jem.notes import CATEGORIES, CAUSE_PILES, NoteClassification, RULES_VERSION


REVIEW_COLUMNS = {"sample_id", "sample_split", "shift_id", "note", "human_category", "reviewer"}
PILE_LABELS = ("client_requested", "operational_associated", "unknown")


def _matrix(pairs: list[tuple[str, str]], labels: tuple[str, ...]) -> dict:
    counts = Counter(pairs)
    return {"labels": list(labels), "rows": [[counts[truth, predicted] for predicted in labels]
                                             for truth in labels]}


def _category_metrics(pairs: list[tuple[str, str]]) -> dict:
    counts = Counter(pairs)
    result = {}
    for label in CATEGORIES:
        tp = counts[label, label]
        support = sum(count for (truth, _), count in counts.items() if truth == label)
        predicted = sum(count for (_, prediction), count in counts.items() if prediction == label)
        precision = tp / predicted if predicted else 0.0
        recall = tp / support if support else 0.0
        result[label] = {"support": support, "precision": precision, "recall": recall,
                         "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0}
    return result


def evaluate_review(review_csv: bytes, classifications: tuple[NoteClassification, ...]) -> dict:
    reader = csv.DictReader(io.StringIO(review_csv.decode("utf-8-sig"), newline=""))
    if not REVIEW_COLUMNS.issubset(reader.fieldnames or ()):
        raise ValueError("Review CSV lacks required blind-review columns.")
    reviewed = list(reader)
    identifiers = [row["sample_id"] for row in reviewed]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("Review CSV has duplicate sample IDs.")
    shift_ids = [row["shift_id"] for row in reviewed]
    if len(set(shift_ids)) != len(shift_ids):
        raise ValueError("Review CSV has duplicate shift IDs.")
    by_key: dict[tuple[str, str], list[NoteClassification]] = {}
    for item in classifications:
        by_key.setdefault((item.shift_id, item.note), []).append(item)
    versions = {row.rules_version for row in classifications}
    if len(versions) > 1:
        raise ValueError("Classifications contain mixed rules versions.")
    splits = sorted({row["sample_split"] for row in reviewed})
    report = {"rules_version": next(iter(versions), RULES_VERSION), "status": "pending",
              "splits": {}, "validation_note": "Human review only. A reviewed sample used to revise rules requires a fresh sample for an independent check."}
    any_matched = False
    for split in splits:
        group = [row for row in reviewed if row["sample_split"] == split]
        pairs = []
        filled = stale = incomplete = 0
        for row in group:
            label = row["human_category"].strip()
            reviewer = row["reviewer"].strip()
            if not label and not reviewer:
                continue
            if not label or not reviewer:
                incomplete += 1
                continue
            filled += 1
            if label not in CATEGORIES:
                raise ValueError("Review CSV contains an unknown human category.")
            matches = by_key.get((row["shift_id"], row["note"]), ())
            if len(matches) != 1:
                stale += 1
                continue
            pairs.append((label, matches[0].category))
        any_matched |= bool(pairs)
        pile_pairs = [(CAUSE_PILES[truth], CAUSE_PILES[predicted]) for truth, predicted in pairs]
        report["splits"][split] = {
            "expected": len(group), "human_filled": filled, "matched_reviewed": len(pairs),
            "stale_or_ambiguous": stale, "incomplete_review": incomplete,
            "status": "pending" if not pairs else "partial" if len(pairs) < len(group) else "reviewed",
            "accuracy": sum(truth == predicted for truth, predicted in pairs) / len(pairs) if pairs else None,
            "per_category": _category_metrics(pairs) if pairs else None,
            "category_confusion": _matrix(pairs, CATEGORIES) if pairs else None,
            "cause_pile_confusion": _matrix(pile_pairs, PILE_LABELS) if pairs else None,
        }
    report["status"] = ("pending" if not any_matched else
                        "reviewed" if all(item["status"] == "reviewed" for item in report["splits"].values())
                        else "partial")
    return report
