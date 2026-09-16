import argparse
import difflib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PINS = ROOT / "tests" / "pins"
DEMOS = ("shooting", "melee", "turn", "soften_the_charge")


def run_demo(name: str) -> str:
    script = ROOT / "scripts" / f"{name}_demo.py"
    completed = subprocess.run(
        [sys.executable, str(script)], check=True, capture_output=True, text=True, cwd=ROOT
    )
    return completed.stdout


def pin_path(name: str) -> Path:
    return PINS / f"{name}.txt"


def diff_against_pin(name: str) -> str:
    pinned = pin_path(name).read_text().splitlines(keepends=True)
    actual = run_demo(name).splitlines(keepends=True)
    lines = difflib.unified_diff(
        pinned, actual, fromfile=f"tests/pins/{name}.txt", tofile=f"scripts/{name}_demo.py"
    )
    return "".join(lines)


def update_pins() -> None:
    for name in DEMOS:
        pin_path(name).write_text(run_demo(name))
        print(f"{name}: pin rewritten")


def check_pins() -> int:
    differing = 0
    for name in DEMOS:
        diff = diff_against_pin(name)
        if diff:
            differing += 1
            print(diff, end="")
        else:
            print(f"{name}: matches pin")
    return differing


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--update", action="store_true")
    if parser.parse_args().update:
        update_pins()
        return 0
    return 1 if check_pins() else 0


if __name__ == "__main__":
    sys.exit(main())
