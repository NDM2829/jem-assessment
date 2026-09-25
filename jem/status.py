"""Stage status exposed to the Streamlit shell.

This module deliberately contains no data loading, hours, or prediction logic.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ProjectStatus:
    stage: str
    shell_ready: bool
    ingestion_ready: bool
    predictions_ready: bool
    note_classification_ready: bool


CURRENT_STATUS = ProjectStatus(
    stage="Step 1 — runnable shell",
    shell_ready=True,
    ingestion_ready=False,
    predictions_ready=False,
    note_classification_ready=False,
)

