# EDT-03 receipt

```yaml
worker: edt-03
branch: edt-03-worker
base_commit: 182e36818eeac4595200a6f5d464e07efcb94ea9
base_tree: 0d78ae4cf5fe2889de356bf079891897a240d7ba
implementation_commit: 6eeb3b7da6920e0871acb0036da92b0ebb2f9841
implementation_tree: 0720353cf741e6893911f269f30bf6eb8119e126
source_manifest_sha256: 742fed428923c7702001865407d3d8897ba9685b5fcfd473076fc7edb3ee563a
compileall_exit: 0
unittest_exit: 0
unittest_count: 68
wheel_or_install_metadata: absent
direct_source_import: observed_with_PYTHONPATH_src
astrid_runtime_installed_origin: unproven
edt04_gap: true
edt05_gap: true
edt06_gap: true
```

Source checkout observations used:

- Runtime `dirfd.py` blob `4f936bebd4dae78c09c33603596431627e8409c6`: exact read/hash/write and parent/inode validation observations in lines 129–172, 185–210, 241–299, 398–424, 492–560.
- Runtime `cas.py` blob `d0c3bf4b4d3d81176cfb87c10bf08133f9e2e12a`: SHA-256 exact-byte mechanics in lines 11–79.
- Runtime `service.py` blob `2a62a312f2e9e81adc9fbefe050904d917c42e8d`: transaction/replay/staging observations in lines 189–205, 756–844, 2674–3135.
- Astrid `atomic_io.py` blob `bc07c6f341f69028343ab0a26cd6566b27cb6948`: narrow atomic byte write observations in lines 37–156; test blob `00220d8107b400a0494687bbff36ffa29a6a8dd7`, lines 46–235.

The source manifest path and SHA-256 are recorded in `work/edt-03-result.md`; no source checkout is treated as installed-origin proof.
