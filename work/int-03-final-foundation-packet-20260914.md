# INT-03 foundation packet preparation

This is an evidence packet for root’s later gate decision. It does not claim acceptance, qualification, publication, or a gate verdict.

The tested implementation candidate is source commit `046b9acfdc9ba541faff65ff3713961890684303`, tree `047a43ba687f45c298139b595756dac84ab729da`. The disposable installed wheel is `herzchen_contracts-0.1.0-py3-none-any.whl`, SHA-256 `4a6dc658fd3b71e9d9d64323bd6539a2feef2521cc5e2e9b472daf2bf3dfbb2f`, run with Python `3.11.16`, pytest `9.1.1`, and `PYTHONPATH`/`PYTHONHOME` unset. The pinned Astrid dependency is source `96e5664237eb35adeb4cad08bddd8cd6df0a2ae1`, tree `19f7539a266618a797559eedbda48e2752b30fa3`, temporary wheel SHA-256 `1da76f252f96e7db84c31a387704e8a6ecdf22333098528139b3db83c8fda67a`.

Accepted source pins are FND-06 `9e15ad908c4a9773ce27e7ff8e03e3dfca274c9b` / `db08184a5bf81a74c1970db7ac741f97cc192cda`, final DAT-06 `2f4dd05e624be2fd228886977be093b386d6f94b` / `e64232672f3e8acbc845369ce68176dccb490455`, PKG correction `1735eadcbf0c5a447a7c74e9ab213b225e4e5ed8` / `fc8c13750d8bb1a7c3d1247d86d6233e1818e64d`, WRK-06 `b036bbbe11e93811a62b95150338a192b5fd6806` / `304cfefe37c5c6c284ac667f2a7b8043aa9031f2`, EDT-06 test evidence `77bd75e4b4047d3ca32550f299d2b9cf2305dbfa` / `61f2f9a6141a38c4ac3706f8842838993ec930df`, and accepted S-NEW-01 correction `acd9ae3666574add8b9289d368a9b9f6f74b694a7` / `793c435567261ad077f093ac4a7f5ba30bcd05a7`. The static blank resource remained unchanged at SHA-256 `5675a02cc9a34bf90de0d5e91dc0617965fe15b133ab1b0cb4b0340bb19af31b`.

The prior frozen campaign remains preserved: **249 tests and 80 subtests** with pinned Astrid, transcript `work/int-03-final-installed-run-20260914.txt`, SHA-256 `5b4b47bb010d0694da7c249864f20f3731a11314ff37a0d23294f59c32d67892`. After the accepted S-NEW-01 correction, the affected installed campaign passed **154 tests with zero skips**, using the pinned Astrid loader and its required disposable dependencies. Transcript: `work/int-03-snew01-installed-affected-run-20260914.txt`, SHA-256 `5fdf6e0dee5b340f5e76718c5798958153af362be54fb4bccab3a81a74b457ca`.

The refreshed direct C38/S-NEW-01 probe passed six checks. JSON evidence: `work/int-03-c38-foundation-probe-20260914.json`, SHA-256 `3eb6d389dbfa5431d7ab587edea3f59cb25a974cee1a56688d68f56495875f88`; transcript: `work/int-03-c38-foundation-probe-20260914.txt`, SHA-256 `72aa2e09e0242f0dd378d116ce3e717bc8b1adaf1276e9b813c43f4e92c95724`; reproducible script: `work/int-03-c38-foundation-probe.py`, SHA-256 `61527f89f5ecd7073a260f8cd28c6df45138cb3b17c2d0c940ee01a25da75891`.

The probe used only installed public APIs and a disposable SQLite store. It exercised:

- immediate blank pending creation, fresh identity read, empty outcome/tasklist, curator, and the committed WRK/DAT/association receipts;
- same-key replay with unchanged event count and changed-argument rejection;
- pending edit, fresh query, pinned document attachment, and retention of `why_pending`, revisit, and curator metadata;
- typed revisit/wait plus readiness observation as attention only, with no admission or dispatch;
- explicit manager admission as a separate operation, still with dispatch false;
- built-in `work.blank_project` dynamic initial-spec composition: the initial DAT document/ref, active `project.documents/specification` association, empty initial revision, rendered template revision, and all three creation receipts are read before optional authoring open;
- untouched idle close retaining the project/specification/revision/association while removing only the registered checkout file and creating no task or content revision.

The accepted correction uses `_blank_dat_seed` and `composition_seed` in `src/herzchen/packs/templates.py`; the shipped static seed stays sparse. It composes the DAT document and project association in the supplied FND transaction from the shared rendered projection, without SQL, a private writer, or generic `{}` content.

`C38` and `S-NEW-01` are `supported_by_current_candidate` in `evidence/foundation-coverage.json`. `C39` is recorded as a supported foundation slice with the later host action pending: shared candidate/decision primitives are covered by the retained REWORK/correction/approval, exact candidate/criterion, stale/unknown/allowance, and non-dispatch manager-choice tests. A real manager next action through a supported host remains a later consumer journey and is not pulled into this foundation packet.

The 49 original scenario records remain lossless: the mechanical comparison of `id`, `name`, `required_proof`, `state`, `produced_by`, and `criteria` is `PASS`, with all original seed values preserved. Six records absent from `validation/area-contracts.json` remain explicitly proposed under `integration_release/INT`; no immutable seed or area file was changed. The final canonical extraction-map SHA-256 is `e273cb7b7e9c26f83a8e1002753c835863333b77e9bfce5b5a3909b1801dbbd5`.

Correction history is retained. Before PKG correction, candidate `50da2534d436d88d40a66c6cd9b51b4bae3848cf` / tree `b3db8dc506a2c1a186deae31af5e217fb2274548` produced 233 passed and one failure because the older TemplateEngine did not expose `seed.work` local refs; accepted PKG commits restored the 249/80 campaign. The subsequent S-NEW-01 correction lineage is `87dde21` → `e81405e` → `acd9ae3`, integrated as `becafe9`, `d5e4892`, and `046b9ac`. The accepted worker result SHA is `8466b6eea9434e2b6451a205622ccd255923d83883b6f885a32c03f8fc1fea55`; manager supplement SHA is `5b7a08a6ec1fefc38ad08ba68e37d6d1c030c25260b1f161eb8edf42ccd64940`.

The earlier duplicate WRK06 launch was terminated without a commit; the canonical worker’s final audit touched only its three owned paths. No review/oracle call, product qualification, remote promotion, or control mutation was performed by this packet step.
