# INT-03 API-probe evidence metadata repair

The historical API-probe receipt and its 11 observations remain unchanged. The final candidate map had three dangling observation references: `INT03-FND-002`, `INT03-DAT-002`, and `INT03-WRK-002`; none exists in the observation array. The map now removes those IDs and points each criterion row to exact installed test functions, retaining actual observation IDs `INT03-FND-001`, `INT03-CURSOR-001`, `INT03-DAT-001`, `INT03-DAT-003`, `INT03-PKG-001..003`, and `INT03-WRK-001` only where they are present and applicable.

Validation:

- observation IDs are read from the 11 entries in `work/int-03-api-probe-evidence.json`;
- no `INT03-FND-002`, `INT03-DAT-002`, or `INT03-WRK-002` remains in the candidate map;
- this is metadata correction only; no source or test files changed.
