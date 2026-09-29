"""Hardware tests are opt-in ONLY.

Default `pytest` NEVER runs anything in this directory: every test here is
skipped unless the human operator sets JT4000M_HARDWARE_TEST=1 explicitly.

Even when enabled, these tests must only:
  * enumerate MIDI ports (safe discovery), and
  * run the OFFLINE experiment comparison on local fixture files.
They must never send unknown SysEx, never change synth parameters, and never
assert that the device behaved in any particular way.
"""
import os

import pytest

collect_ignore = []

if not os.environ.get("JT4000M_HARDWARE_TEST"):
    def pytest_collection_modifyitems(config, items):
        mark = pytest.mark.skip(
            reason="hardware test; set JT4000M_HARDWARE_TEST=1 to run "
                   "(requires the physical JT-4000M connected by a human)")
        for item in items:
            if "hardware" in str(item.fspath).replace("\\", "/"):
                item.add_marker(mark)
