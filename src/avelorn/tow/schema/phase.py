"""The turn sequence: the registry of the game's phases.

Phase names are taken verbatim from the printed turn sequence — four
phases, in declaration order. The values match the rules-page category
strings as the YAML prints them ("The Shooting Phase"), so a chapter
rule names its phase with no translation; like the other closed
rulebook vocabularies (stages, troop types) this lives in the schema
layer, so data can be validated against it at load.
"""

from enum import StrEnum


class Phase(StrEnum):
    """The turn's phases, named as the rulebook prints them, in order."""

    STRATEGY = "The Strategy Phase"
    MOVEMENT = "The Movement Phase"
    SHOOTING = "The Shooting Phase"
    COMBAT = "The Combat Phase"
