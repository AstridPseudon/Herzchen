# INT-03 foundation packet preparation

This is an evidence packet for root’s later gate decision. It does not claim acceptance, qualification, publication, or a gate verdict.

The tested implementation candidate is source commit `c7156360ab601533a38710b8957887e582db669e`, tree `f547137f5804c0d8958d68d08633b35698aa2e43`. The disposable installed wheel is `herzchen_contracts-0.1.0-py3-none-any.whl`, SHA-256 `7b44a33a187dc8a23bc0f1b768ba2052df02e2bddbeceb8aede748dda8927567`, run with Python `3.11.16`, pytest `9.1.1`, and `PYTHONPATH`/`PYTHONHOME` unset. The pinned Astrid dependency is source `96e5664237eb35adeb4cad08bddd8cd6df0a2ae1`, tree `19f7539a266618a797559eedbda48e2752b30fa3`, temporary wheel SHA-256 `1da76f252f96e7db84c31a387704e8a6ecdf22333098528139b3db83c8fda67a`.

Accepted source pins are FND-06 `9e15ad908c4a9773ce27e7ff8e03e3dfca274c9b` / `db08184a5bf81a74c1970db7ac741f97cc192cda`, final DAT-06 `2f4dd05e624be2fd228886977be093b386d6f94b` / `e64232672f3e8acbc845369ce68176dccb490455`, PKG correction `1735eadcbf0c5a447a7c74e9ab213b225e4e5ed8` / `fc8c13750d8bb1a7c3d1247d86d6233e1818e64d`, WRK-06 `b036bbbe11e93811a62b95150338a192b5fd6806` / `304cfefe37c5c6c284ac667f2a7b8043aa9031f2`, and EDT-06 test evidence `77bd75e4b4047d3ca32550f299d2b9cf2305dbfa` / `61f2f9a6141a38c4ac3706f8842838993ec930df`.

The final built-artifact campaign passed **249 tests and 80 subtests** with pinned Astrid installed. Transcript: `work/int-03-final-installed-run-20260914.txt`, SHA-256 `5b4b47bb010d0694da7c249864f20f3731a11314ff37a0d23294f59c32d67892`. The existing bounded API probe passed 1 test; transcript: `work/int-03-final-public-api-probe-run-20260914.txt`, SHA-256 `d2f31c46add23a7712adc7adfd29bbcf276b8e1f0c9aece1fdbef9bdd8ace104`. The new direct C38/S-NEW-01 probe passed six checks; JSON evidence: `work/int-03-c38-foundation-probe-20260914.json`, SHA-256 `601f9bda5bd5b48bb73b1d9c36ab1dae34c4aafb2f828eefa8af8f98fc8ebc5d`; transcript: `work/int-03-c38-foundation-probe-20260914.txt`, SHA-256 `d3094839a1d533d6860799a76ac5762bd01332c2355c61fae95ed57966b23d98`.

The probe used only installed public APIs and a disposable SQLite store. It exercised:

- immediate blank pending creation, fresh identity read, empty outcome/tasklist, curator, and committed creation receipt;
- same-key replay with no new event and changed-argument rejection;
- pending edit, fresh query, pinned initial-spec document attachment, and retention of `why_pending`, revisit, and curator metadata;
- typed revisit/wait plus readiness observation as attention only, with no admission or dispatch;
- explicit manager admission as a separate operation, still with dispatch false;
- built-in `work.blank_project` template rendering, initial empty authoring content, fresh receipt/read, and untouched idle close retaining the same project revision while removing only the registered checkout file.

The C38 named foundation boundary is therefore supported by the current candidate. The remaining S-NEW-01 atomic initial-spec creation gap is explicit. The remaining C39 boundary is explicit: shared candidate/decision primitives are covered by the retained REWORK/correction/approval, exact candidate/criterion, stale/unknown/allowance, and non-dispatch manager-choice tests; a real manager next action through a supported host remains a later consumer journey and is not pulled into this foundation packet.

`C38` is `supported_by_current_candidate` in `evidence/foundation-coverage.json`. `C39` is recorded as a supported foundation slice with the later host action pending. `S-NEW-01` remains `partial_pending_followup`: the direct probe proves blank template rendering, fresh project receipt/read, initial empty authoring bytes, replay/invalid rejection, and untouched close, but the owning public creation path does not yet persist an initial-spec document/ref/receipt atomically with the blank project before optional open. The packet is not gate-ready while that exact owner gap remains. The bounded owner brief is sealed at `work/int-03-snew01-gap-brief.md`. Other criteria retain their exact `partial_pending_followup` status and evidence references in the JSON coverage artifact; C17 is supported for packaged artifact identity.

The 49 original scenario records remain lossless: the mechanical comparison of `id`, `name`, `required_proof`, `state`, `produced_by`, and `criteria` is `PASS`, with all original seed values preserved. Six records absent from `validation/area-contracts.json` remain explicitly proposed under `integration_release/INT`; no immutable seed or area file was changed.

Correction history is retained. Before PKG correction, candidate `50da2534d436d88d40a66c6cd9b51b4bae3848cf` / tree `b3db8dc506a2c1a186deae31af5e217fb2274548` produced 233 passed and one failure because the older TemplateEngine did not expose `seed.work` local refs. Accepted correction commits `18b8dad`, `d04fd77`, `601ad73`, and `c715636` supplied the required shipped-seed/DAT relation behavior; the rebuilt candidate produced 249/80.

The earlier duplicate WRK06 launch was terminated without a commit; the canonical worker’s final audit touched only its three owned paths. The accepted manager supplement records the duplicate PID/thread, timing, no commit, and no mixed handoff state. No review/oracle call, product qualification, remote promotion, or control mutation was performed by this packet step.
