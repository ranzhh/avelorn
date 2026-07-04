"""The charge sequence: Stand & Shoot reaction, hand-checked from the charts."""

from pathlib import Path

import pytest

from avelorn.core.loading import load_yaml, load_yaml_dir
from avelorn.tow.combat.charge import stand_and_shoot
from avelorn.tow.combat.melee import Charge, ChargeArc, Contingent, combat_result, fight
from avelorn.tow.combat.shooting import shoot_unit
from avelorn.tow.schema.armour import Armour
from avelorn.tow.schema.rule import Rule
from avelorn.tow.schema.unit import Unit
from avelorn.tow.schema.weapon import Weapon

DATA_DIR = Path(__file__).parents[3] / "data"

ARMOURY = {a.name: a for a in load_yaml_dir(DATA_DIR / "tow/armour", Armour)}
RULES = {r.name: r for r in load_yaml_dir(DATA_DIR / "tow/rules", Rule)}


def load_unit(slug: str) -> Unit:
    """Load an Elven unit from the data/ tree.

    Returns:
        The parsed unit model.
    """
    return load_yaml(DATA_DIR / f"tow/armies/high-elf-realms/units/{slug}.yaml", Unit)


def load_weapon(slug: str) -> Weapon:
    """Load a weapon from the data/ tree.

    Returns:
        The parsed weapon model.
    """
    return load_yaml(DATA_DIR / f"tow/weapons/{slug}.yaml", Weapon)


def test_stand_and_shoot_applies_the_minus_one_to_hit() -> None:
    """Archers standing and shooting hit at -1: BS4 (3+) becomes 4+."""
    archers, spearmen = load_unit("elven-archers"), load_unit("elven-spearmen")
    plain = shoot_unit(archers, spearmen, 10, load_weapon("longbow"), armoury=ARMOURY, rules=RULES)
    reaction = stand_and_shoot(
        Contingent(archers, 10),
        Contingent(spearmen, 10),
        load_weapon("longbow"),
        armoury=ARMOURY,
        rules=RULES,
    )
    assert plain.hit_target == 3
    assert reaction.hit_target == 4  # -1 To Hit for Standing and Shooting


def test_stand_and_shoot_is_exempt_from_firing_at_long_range() -> None:
    """The reaction never carries a Firing at Long Range note: the rule is a no-op.

    A plain volley with no distance leaves the range band unknown, so the
    rule is reported unfactored; the reaction asserts the exemption, so it
    is honoured silently instead.
    """
    archers, spearmen = load_unit("elven-archers"), load_unit("elven-spearmen")
    plain = shoot_unit(archers, spearmen, 10, load_weapon("longbow"), armoury=ARMOURY, rules=RULES)
    reaction = stand_and_shoot(
        Contingent(archers, 10),
        Contingent(spearmen, 10),
        load_weapon("longbow"),
        armoury=ARMOURY,
        rules=RULES,
    )
    assert any("Firing at Long Range" in note for note in plain.notes)
    assert not any("Firing at Long Range" in note for note in reaction.notes)


def test_stand_and_shoot_caps_casualties_at_the_charging_unit_size() -> None:
    """A volley cannot fell more chargers than the charging unit contains."""
    archers, spearmen = load_unit("elven-archers"), load_unit("elven-spearmen")
    reaction = stand_and_shoot(
        Contingent(archers, 20),
        Contingent(spearmen, 5),
        load_weapon("longbow"),
        armoury=ARMOURY,
        rules=RULES,
    )
    assert reaction.target_models == 5
    assert len(reaction.casualties) == 6  # 0..5
    assert sum(reaction.casualties) == pytest.approx(1.0)


# --- The whole sequence: Stand & Shoot feeding the composed melee ---


def test_charge_sequence_matches_mixing_the_survivor_fights_by_hand() -> None:
    """fight() over the reaction pmf equals summing P(k) x the N-k survivor fight.

    The Archers Stand & Shoot the charging Spearmen; feeding that casualty
    pmf to fight() as ``a_prior_losses`` must reproduce, exactly, a by-hand
    mixture over each number ``k`` of Spearmen felled before contact.
    """
    archers, spearmen = load_unit("elven-archers"), load_unit("elven-spearmen")
    spear, hand = load_weapon("thrusting-spear"), load_weapon("hand-weapon")
    charge = Charge(6, ChargeArc.FRONT)
    models = 3
    charger = Contingent(spearmen, models, charge=charge)
    defender = Contingent(archers, 3)
    reaction = stand_and_shoot(
        defender, charger, load_weapon("longbow"), armoury=ARMOURY, rules=RULES
    )

    composed = fight(
        charger,
        defender,
        a_weapon=spear,
        b_weapon=hand,
        a_prior_losses=reaction.casualties,
        armoury=ARMOURY,
        rules=RULES,
    )

    manual = [[0.0] * (defender.models + 1) for _ in range(models + 1)]
    for felled, p_felled in enumerate(reaction.casualties):
        survivors = fight(
            Contingent(spearmen, models - felled, charge=charge),
            defender,
            a_weapon=spear,
            b_weapon=hand,
            armoury=ARMOURY,
            rules=RULES,
        )
        for a_lost, row in enumerate(survivors.losses):
            for b_lost, mass in enumerate(row):
                manual[a_lost][b_lost] += p_felled * mass

    for composed_row, manual_row in zip(composed.losses, manual, strict=True):
        assert composed_row == pytest.approx(manual_row)
    assert composed.first_striker is charger  # the charge still strikes first


def test_stand_and_shoot_erodes_the_chargers_combat_result() -> None:
    """Softening the chargers first lowers their combat-result win chance.

    A charge met by Stand & Shoot brings fewer Spearmen to the melee, so
    they inflict fewer wounds and win the combat less often than an un-shot
    charge of the same size would.
    """
    archers, spearmen = load_unit("elven-archers"), load_unit("elven-spearmen")
    spear, hand = load_weapon("thrusting-spear"), load_weapon("hand-weapon")
    charger = Contingent(spearmen, 10, charge=Charge(8, ChargeArc.FRONT))
    defender = Contingent(archers, 10)
    reaction = stand_and_shoot(
        defender, charger, load_weapon("longbow"), armoury=ARMOURY, rules=RULES
    )

    unshot = combat_result(
        fight(charger, defender, a_weapon=spear, b_weapon=hand, armoury=ARMOURY, rules=RULES)
    )
    shot = combat_result(
        fight(
            charger,
            defender,
            a_weapon=spear,
            b_weapon=hand,
            a_prior_losses=reaction.casualties,
            armoury=ARMOURY,
            rules=RULES,
        )
    )
    assert shot.p_a_wins < unshot.p_a_wins


def test_force_short_range_honours_long_range_as_a_no_op() -> None:
    """shoot_unit's force_short_range treats the shot as within half range."""
    archers, spearmen = load_unit("elven-archers"), load_unit("elven-spearmen")
    forced = shoot_unit(
        archers,
        spearmen,
        10,
        load_weapon("longbow"),
        armoury=ARMOURY,
        rules=RULES,
        force_short_range=True,
    )
    assert not any("Firing at Long Range" in note for note in forced.notes)
