import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "pin_demos.py"
spec = importlib.util.spec_from_file_location("pin_demos", SCRIPT)
assert spec is not None
assert spec.loader is not None
pin_demos = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pin_demos)


@pytest.mark.parametrize("name", pin_demos.DEMOS)
def test_demo_output_matches_its_pin(name: str) -> None:
    diff = pin_demos.diff_against_pin(name)
    assert not diff, diff
