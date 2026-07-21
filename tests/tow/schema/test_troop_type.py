"""TroopTypeProfile: how a troop type resolves its per-model Unit Strength."""

import pytest

from avelorn.tow.data import TOWRepository
from avelorn.tow.schema.troop_type import TroopTypeProfile

REPO = TOWRepository()


def test_fixed_unit_strength_ignores_wounds() -> None:
    """A fixed Unit Strength is returned whatever the model's Wounds."""
    infantry = REPO.troop_types.by_name("Regular Infantry")  # US 1
    assert infantry.unit_strength_per_model(1) == 1
    assert infantry.unit_strength_per_model(4) == 1  # Wounds do not move a fixed US


def test_as_starting_wounds_reads_the_models_wounds() -> None:
    """An "As Starting Wounds" troop type takes the model's Wounds as its US."""
    monster = REPO.troop_types.by_name("Monstrous Creature")
    assert monster.unit_strength_per_model(6) == 6
    assert monster.unit_strength_per_model(None) == 1  # no printed Wounds counts as one


@pytest.mark.parametrize("profile", list(REPO.troop_types.values()), ids=lambda p: p.id)
def test_every_troop_type_resolves_a_positive_unit_strength(profile: TroopTypeProfile) -> None:
    """Every troop type's data yields a positive per-model Unit Strength."""
    assert profile.unit_strength_per_model(3) >= 1
