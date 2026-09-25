from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_shell_renders_without_analytical_claims() -> None:
    entrypoint = Path(__file__).parents[1] / "app.py"
    app = AppTest.from_file(entrypoint).run(timeout=10)

    assert not app.exception
    assert app.title[0].value == "Jem overtime early warning"
    assert "first correlated-hours predictor" in app.info[0].value
    rendered_text = "\n".join(element.value for element in app.markdown)
    assert "dashboard does not yet display hours" in rendered_text
