"""Conservative, versioned supervisor-note rules; no notebook runtime dependency."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from difflib import get_close_matches
import io
import re
import unicodedata

from jem.pipeline import IngestionResult


RULES_VERSION = "notes-1.0"
CATEGORIES = ("client_requested", "absence_cover", "relief_problem", "equipment_failure",
              "late_handover", "cover_unspecified", "unclear_or_mixed", "no_useful_information")
CAUSE_PILES = {name: ("client_requested" if name == "client_requested" else
                      "operational_associated" if name in CATEGORIES[1:5] else "unknown")
               for name in CATEGORIES}
ABBREVIATIONS = {"agn": "again", "hrs": "hours", "mgr": "manager", "mgmt": "management",
                 "pls": "please", "bc": "because"}
VOCABULARY = set("""client klient centre manager management requested request asked wanted
approved approval signed office extra relief replacement handover oorhandiging
waiting waited delayed paperwork nobody never arrived supposed machine scrubber
buffer generator motor failed fault manually broken stocktake covering covered
absent clinic responsibility leave sick akezanga akafikanga aflos opgedaag
stukkend masjien sleutels gevra gedek gemeld normal incidents nothing report""".split())
ROUTINE = {"", "n a", "na", "ntr", "ok", "fine", "sharp", "quiet shift", "all quiet",
           "all good", "all fine", "nothing to report", "no incidents", "no issues on site",
           "as per normal", "akukho lutho", "niks om te rapporteer nie"}


@dataclass(frozen=True)
class NoteClassification:
    shift_id: str
    note: str
    category: str
    cause_pile: str
    source_row: int | None
    linked_shift_id: str | None
    normalised_note: str
    typo_corrections: tuple[str, ...]
    matched_evidence: str
    explicit_client_request: bool
    approval_status: str
    language_review_needed: bool
    needs_review: bool
    rules_version: str = RULES_VERSION


def normalise_note(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    plain = plain.replace("'", "").replace("’", "")
    return " ".join(ABBREVIATIONS.get(word, word) for word in re.sub(r"[^a-z0-9\s]", " ", plain).split())


def correct_domain_typos(text: str) -> tuple[str, tuple[str, ...]]:
    corrected, changes = [], []
    for word in text.split():
        if word not in VOCABULARY and len(word) >= 5 and word.isalpha():
            matches = get_close_matches(word, sorted(VOCABULARY), n=2, cutoff=0.88)
            if len(matches) == 1:
                corrected.append(matches[0])
                changes.append(f"{word}→{matches[0]}")
                continue
        corrected.append(word)
    return " ".join(corrected), tuple(changes)


def classify_note(text: str, *, shift_id: str = "", source_row: int | None = None,
                  linked_shift_id: str | None = None) -> NoteClassification:
    original = normalise_note(text)
    clean, corrections = correct_domain_typos(original)

    def has(pattern: str) -> bool:
        return re.search(pattern, clean) is not None

    language_flag = any(ord(char) > 127 for char in text) or has(
        r"\b(aflos|oorhandiging|masjien|stukkend|klient|akezanga|akafikanga|ngimele|ngicela|gedek|siek|akukho|niks)\b")
    explicit_client = has(r"\b(client|klient)\b") and has(
        r"\b(asked|requested|wanted|gevra)\b|\b(client|klient)\s+says?\s+stay")
    uncertain_approval = has(r"dont know|do not know|not sure|awaiting approval|not approved|no approval")
    confirmed_approval = has(r"\bapproved\b|\bsigned\s+(off|for)\b|\bokd\b")
    approval = "unconfirmed" if uncertain_approval else "confirmed_in_note" if confirmed_approval else "not_stated"

    matches = []
    relief = has(r"\brelief\b|no replacement|next shift|\baflos\b")
    if relief and has(r"\b(no|never|nobody|late|delayed|did not|didnt|only arrived|still on site|supposed|akafikanga|stayed|coming)\b|nie opgedaag"):
        matches.append("relief_problem")
    if has(r"\babsent\b|off sick|at the clinic|family responsibility leave|\bon leave\b|\bsick\b|didnt come|did not come|no show no call|\bakezanga\b|siek gemeld") and not relief:
        matches.append("absence_cover")
    equipment = has(r"\b(machine|scrubber|buffer|generator|masjien)\b|gate motor|\blift\b")
    failure = has(r"\b(broke|broken|down|fault|failed|kaput|stukkend)\b|out of order|by hand|manually")
    if equipment and failure and not has(r"not broken|no fault|no equipment problems"):
        matches.append("equipment_failure")
    if has(r"\bhandover\b|\boorhandiging\b|keys missing|ob book not signed") and has(r"late|delayed|wait|\blaat\b"):
        matches.append("late_handover")
    cover = has(r"stood in for|covered for|\bcovering\b|shift as well|2 posts 1 guard")

    if not text.strip() or (not clean and not language_flag) or (bool(original) and original in ROUTINE) or (bool(clean) and clean in ROUTINE):
        category, evidence = "no_useful_information", "empty/placeholder/routine statement"
    elif len(matches) > 1:
        category, evidence = "unclear_or_mixed", "multiple operational signals: " + ", ".join(matches)
    elif len(matches) == 1:
        if explicit_client and not has(r"real reason|\bbecause\b"):
            category, evidence = "unclear_or_mixed", "explicit client request and operational cause"
        else:
            category, evidence = matches[0], "explicit operational cause; approval kept separate"
    elif explicit_client:
        category, evidence = "client_requested", "identified client explicitly requested extra work"
    elif cover:
        category, evidence = "cover_unspecified", "cover stated without a specific cause"
    else:
        category, evidence = "unclear_or_mixed", "no sufficiently specific cause or identified client request"
    review = category in {"unclear_or_mixed", "cover_unspecified"} or bool(corrections) or bool(language_flag)
    return NoteClassification(shift_id, text, category, CAUSE_PILES[category], source_row,
                              linked_shift_id, clean, corrections, evidence, bool(explicit_client),
                              approval, bool(language_flag), review)


def classify_bundle(result: IngestionResult) -> tuple[NoteClassification, ...]:
    """Reclassify all source rows in order, including unmatched and duplicate notes."""
    return tuple(classify_note(row.get("note", ""), shift_id=row.get("shift_id", ""),
                               source_row=index + 2, linked_shift_id=result.note_links[index])
                 for index, row in enumerate(result.notes))


def note_classifications_csv_bytes(rows: tuple[NoteClassification, ...]) -> bytes:
    handle = io.StringIO(newline="")
    writer = csv.writer(handle)
    writer.writerow(("shift_id", "category", "note"))
    for row in rows:
        writer.writerow((row.shift_id, row.category, row.note))
    return handle.getvalue().encode("utf-8")


def note_evidence_csv_bytes(rows: tuple[NoteClassification, ...]) -> bytes:
    """Separate audit table; assessment submission columns remain untouched."""
    columns = ("source_row", "shift_id", "note", "category", "cause_pile", "linked_shift_id",
               "normalised_note", "typo_corrections", "matched_evidence", "explicit_client_request",
               "approval_status", "language_review_needed", "needs_review", "rules_version")
    handle = io.StringIO(newline="")
    writer = csv.DictWriter(handle, fieldnames=columns)
    writer.writeheader()
    for row in rows:
        writer.writerow({"source_row": row.source_row, "shift_id": row.shift_id, "note": row.note,
                         "category": row.category, "cause_pile": row.cause_pile,
                         "linked_shift_id": row.linked_shift_id, "normalised_note": row.normalised_note,
                         "typo_corrections": "; ".join(row.typo_corrections),
                         "matched_evidence": row.matched_evidence,
                         "explicit_client_request": row.explicit_client_request,
                         "approval_status": row.approval_status,
                         "language_review_needed": row.language_review_needed,
                         "needs_review": row.needs_review, "rules_version": row.rules_version})
    return handle.getvalue().encode("utf-8")
