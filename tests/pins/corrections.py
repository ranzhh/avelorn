"""The numbers the graph moves away from legacy, each with the page that moves it."""

from fractions import Fraction
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, TypeAdapter

CORRECTIONS = Path(__file__).with_name("corrections.yaml")


class Correction(BaseModel):
    """A pinned number that legacy gives as ``old`` and the graph as ``new``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    pin: str
    old: Fraction
    new: Fraction
    page: str
    reason: str


def corrections() -> dict[str, Correction]:
    """Every correction, by the pin it moves.

    Returns:
        The corrections, keyed by pin.

    Raises:
        ValueError: two entries name one pin.
    """
    read: dict[str, Correction] = {}
    entries = yaml.safe_load(CORRECTIONS.read_text())
    for correction in TypeAdapter(list[Correction]).validate_python(entries):
        if correction.pin in read:
            raise ValueError(f"{correction.pin} is corrected twice")
        read[correction.pin] = correction
    return read
