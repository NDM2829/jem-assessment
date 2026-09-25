from dataclasses import replace
from datetime import date
from pathlib import Path
from shutil import copyfile

from streamlit.testing.v1 import AppTest

from jem.io import FILES, demo_sources
from jem.pipeline import ingest
from jem.workflow import input_fingerprint, load_policy, process_bundle, source_fingerprint


ROOT = Path(__file__).parents[1]


def test_input_fingerprint_tracks_source_asof_and_policy():
    sources = demo_sources(ROOT)
    policy = load_policy(ROOT / "config" / "prediction_policy.toml")
    baseline = input_fingerprint(sources, date(2026, 8, 12), policy)
    assert source_fingerprint(sources) == source_fingerprint(dict(sources))
    assert baseline != input_fingerprint(sources, date(2026, 8, 5), policy)
    assert baseline != input_fingerprint(sources, date(2026, 8, 12), replace(policy, digest="changed"))
    changed = dict(sources)
    changed["shift_notes.csv"] = b"shift_id,note\nA,replacement\n"
    assert baseline != input_fingerprint(changed, date(2026, 8, 12), policy)


def test_bundled_demo_processes_without_unused_payroll_file(tmp_path):
    demo_dir = tmp_path / "data" / "demo"
    demo_dir.mkdir(parents=True)
    for name in FILES:
        if name != "payroll_details.csv":
            copyfile(ROOT / "data" / "demo" / name, demo_dir / name)
    sources = demo_sources(tmp_path)
    assert "payroll_details.csv" not in sources
    ingestion = ingest(sources)
    assert ingestion.accepted
    assert not any(issue.file == "payroll_details.csv" for issue in ingestion.issues)
    processed = process_bundle(ingestion, load_policy(ROOT / "config" / "prediction_policy.toml"))
    assert len(processed.queue) == 213
    assert processed.predictions_csv == (ROOT / "predictions.csv").read_bytes()
    copyfile(ROOT / "app.py", tmp_path / "app.py")
    (tmp_path / "config").mkdir()
    copyfile(ROOT / "config" / "prediction_policy.toml", tmp_path / "config" / "prediction_policy.toml")
    app = AppTest.from_file(tmp_path / "app.py").run(timeout=30)
    assert not app.exception
    assert app.metric[0].value == "213"
