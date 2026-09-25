# Same-format replacement upload check

This is a **synthetic test fixture**, not a real later client export or new performance evidence. `tests/test_app.py::test_upload_replacement_and_failure_clear_old_results` drives the Streamlit app with two same-format CSV bundles and needs no edits to the app or policy between uploads.

| Check | First bundle | Replacement bundle |
|---|---|---|
| Detected week start | 2026-09-07 | 2026-09-14 |
| Employee IDs | A1, A2 | B1, B2 |
| Source note | `A1 replacement note` | `B1 replacement note` |
| Outputs | Predictions for A1/A2 and first note | Predictions for B1/B2 and second note; neither contains the earlier roster/note |

The test also selects an earlier as-of date, confirms that an incomplete replacement cannot load, and checks that clearing an upload clears the active result. An attempted overwrite of a processed upload is rejected until **Choose another export** is used. The app downloads come from the active processed bundle; the original root CSVs are regenerated separately from `data/demo/` after this check.
