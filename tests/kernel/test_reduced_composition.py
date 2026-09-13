"""Fresh reduced-composition import proof for the neutral kernel/adapters."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest


OPTIONAL_MODULE_PREFIXES = (
    "herzchen.domains.work",
    "herzchen.domains.megado",
    "herzchen.domains.god",
    "herzchen.domains.shot",
    "herzchen.runtime",
    "herzchen.astrid",
    "herzchen.otto",
)


class ReducedCompositionTests(unittest.TestCase):
    def test_fresh_kernel_and_adapter_import_excludes_optional_domains(self) -> None:
        """FND-06 claim: neutral imports do not load optional domain modules."""

        child_env = dict(os.environ)
        script = """
import importlib.util
import json
import sys
import herzchen.kernel
import herzchen.adapters

optional_prefixes = %r
loaded = sorted(
    name for name in sys.modules
    if any(name == prefix or name.startswith(prefix + ".") for prefix in optional_prefixes)
)
origins = {
    name: (importlib.util.find_spec(name).origin if importlib.util.find_spec(name) else None)
    for name in ("herzchen", "herzchen.contracts", "herzchen.kernel", "herzchen.adapters")
}
print(json.dumps({"loaded_optional": loaded, "origins": origins}, sort_keys=True))
""" % (OPTIONAL_MODULE_PREFIXES,)
        completed = subprocess.run(
            [sys.executable, "-B", "-c", script],
            check=False,
            capture_output=True,
            text=True,
            env=child_env,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        observation = json.loads(completed.stdout)
        self.assertEqual(observation["loaded_optional"], [])
        self.assertTrue(all(observation["origins"].values()))


if __name__ == "__main__":
    unittest.main()
