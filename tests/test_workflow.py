from dataclasses import replace
from datetime import date
from pathlib import Path

from jem.io import demo_sources
from jem.workflow import input_fingerprint, load_policy, source_fingerprint


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
