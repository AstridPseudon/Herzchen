# C33 current 76-port adaptation

P01 current matrix basis is the FND candidate that removes exactly one unsupported mutation port:

- Candidate commit: `8235d9aacbe7357e8f72cec8342eca77aab0cb58`
- Candidate tree: `c69702a8b42420159dbcdb4b0d572c0e8f9dfffa`
- Removed port: `work.v1|work.revise|work.project|work.parent-linked`
- Reason: `WorkGraph` rejects project parents and exposes no valid project-parent mutation path; the descriptor port was unsupported.

The C33 harness now derives the current accepted set from the candidate descriptors, asserts the removed port is absent, and requires exactly 76 unique current ports. It writes a versioned current matrix with `historical_row_count: 77` and the removed-port reason. The prior 77-port matrix is preserved at `work/c33-persisted-port-matrix-77-historical-20260914.json` with SHA256 `4c5cb78ec497c58300bbc8d68e5c7571c563194717fc65bd7f3f4d00d8fcf766`.

The previous same-key parent fixture correction remains in this branch. No product implementation is changed by this adaptation.
