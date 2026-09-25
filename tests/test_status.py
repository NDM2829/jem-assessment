from jem.status import CURRENT_STATUS


def test_step_one_status_is_honest() -> None:
    assert CURRENT_STATUS.shell_ready is True
    assert CURRENT_STATUS.ingestion_ready is False
    assert CURRENT_STATUS.predictions_ready is False
    assert CURRENT_STATUS.note_classification_ready is False

