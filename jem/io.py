"""Lossless CSV bundle loading for demo files, uploads, and export scripts."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Mapping


FILES = (
    "employees.csv", "shifts.csv", "sites.csv", "shift_notes.csv",
    "public_holidays.csv", "weekly_summary.csv", "payroll_details.csv",
)
CORE_FILES = frozenset(("employees.csv", "shifts.csv", "sites.csv"))
REQUIRED_COLUMNS = {
    "employees.csv": frozenset(("employee_id", "full_name", "primary_site_id", "contract_ordinary_hours")),
    "shifts.csv": frozenset(("shift_id", "employee_id", "site_id", "shift_date", "clock_in_time", "clock_out_time")),
    "sites.csv": frozenset(("site_id", "site_name")),
    "shift_notes.csv": frozenset(("shift_id", "note")),
    "public_holidays.csv": frozenset(("date", "name")),
    "weekly_summary.csv": frozenset(("employee_id", "week_starting", "total_hours", "overtime_hours", "breached")),
    # This file is accepted but never parsed into the analytical bundle.
    "payroll_details.csv": frozenset(),
}


@dataclass(frozen=True)
class Issue:
    file: str
    row: int | None
    key: str | None
    severity: str
    issue: str
    suggested_correction: str


@dataclass(frozen=True)
class RawTable:
    columns: tuple[str, ...]
    rows: tuple[dict[str, str], ...]


@dataclass(frozen=True)
class LoadedBundle:
    tables: dict[str, RawTable]
    issues: tuple[Issue, ...]
    row_counts: dict[str, int]


def _bytes(source: bytes | str | Path | BinaryIO) -> bytes:
    if isinstance(source, bytes):
        return source
    if isinstance(source, (str, Path)):
        return Path(source).read_bytes()
    # Streamlit UploadedFile and ordinary binary file handles support read/seek.
    if hasattr(source, "seek"):
        source.seek(0)
    data = source.read()
    return data.encode("utf-8") if isinstance(data, str) else data


def load_bundle(sources: Mapping[str, bytes | str | Path | BinaryIO]) -> LoadedBundle:
    """Load one complete bundle. Each invocation starts with empty tables.

    Values may be paths, bytes, or browser upload file objects. Never inspect
    payroll row contents: payroll is unused and may contain sensitive fields.
    """
    tables: dict[str, RawTable] = {}
    issues: list[Issue] = []
    row_counts: dict[str, int] = {}
    for name in sources:
        if name not in FILES:
            issues.append(Issue(name, None, None, "warning", "Unexpected file ignored", "Use one of the seven supported CSV names."))
    for name in FILES:
        if name not in sources:
            if name == "payroll_details.csv":
                continue
            level = "error" if name in CORE_FILES else "warning"
            issues.append(Issue(name, None, None, level, "File missing", "Include this CSV in the replacement bundle." if level == "error" else "Include this CSV to enable its dependent output."))
            continue
        if name == "payroll_details.csv":
            # Deliberately no reading, parsing, diagnostic, or retained values.
            continue
        try:
            decoded = _bytes(sources[name]).decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(decoded, newline=""), restkey="__extra__", restval="")
            columns = tuple(reader.fieldnames or ())
            if not columns:
                raise ValueError("CSV header is missing")
            if len(columns) != len(set(columns)):
                issues.append(Issue(name, 1, None, "error" if name in CORE_FILES else "warning", "Duplicate column names", "Give each CSV column one distinct name."))
            missing = REQUIRED_COLUMNS[name].difference(columns)
            if missing:
                level = "error" if name in CORE_FILES else "warning"
                issues.append(Issue(name, 1, None, level, "Missing required columns: " + ", ".join(sorted(missing)), "Export this file with the required header columns."))
            rows = []
            for row_number, raw in enumerate(reader, start=2):
                if "__extra__" in raw:
                    issues.append(Issue(name, row_number, None, "warning", "Extra CSV fields", "Check quoting and column alignment in this row."))
                rows.append({column: raw.get(column, "") or "" for column in columns})
            tables[name] = RawTable(columns, tuple(rows))
            row_counts[name] = len(rows)
        except (OSError, UnicodeError, csv.Error, ValueError) as exc:
            # Exception messages may contain source text; report only the type.
            issues.append(Issue(name, None, None, "error" if name in CORE_FILES else "warning", "CSV could not be read (" + type(exc).__name__ + ")", "Supply a UTF-8 CSV with a header row."))
    return LoadedBundle(tables, tuple(issues), row_counts)


def demo_sources(root: str | Path) -> dict[str, Path]:
    """Paths for the bundled demo; accepted by the same loader as uploads."""
    directory = Path(root) / "data" / "demo"
    return {name: directory / name for name in FILES if (directory / name).is_file()}
