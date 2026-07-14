"""The fielded unit: Contingent.deploy and the Charge bonus."""

from dataclasses import replace

import pytest

from avelorn.tow.combat.contingent import Charge, ChargeArc, Contingent, Formation, Loadout
from avelorn.tow.data import TOWRepository
from avelorn.tow.muster import Complement
from avelorn.tow.schema.rule import ModifierEffect
from avelorn.tow.schema.unit import Unit

REPO = TOWRepository()


@pytest.fixture
def spearmen_unit() -> Unit:
    """The Elven Spearmen datasheet, whose options a Complement is built from.

    Returns:
        The validated unit model.
    """
    return REPO.units["elven-spearmen"]


def _fielded(unit: Unit, models: int, frontage: int | None = None) -> Contingent:
    # Field at the optionless loadout, optionally at a chosen frontage.
    return Contingent.field(
        unit,
        models,
        weapons=REPO.weapons,
        armoury=REPO.armoury,
        rules=REPO.rules,
        frontage=frontage,
    )


def test_deploy_fields_complement_size_and_loadout(spearmen_unit: Unit) -> None:
    """Contingent.deploy carries the complement's size and chosen loadout."""
    mustered = Complement(unit=spearmen_unit, size=18, options=["Shieldwall"])

    contingent = Contingent.deploy(
        mustered, weapons=REPO.weapons, armoury=REPO.armoury, rules=REPO.rules
    )

    assert contingent.models == 18
    # The chosen option's rule is what the engine reads, not the printed profile.
    assert "Shieldwall" in contingent.unit.special_rules
    assert "Shieldwall" not in spearmen_unit.special_rules


def test_deploy_without_options_matches_the_datasheet(spearmen_unit: Unit) -> None:
    """With no options, the fielded loadout equals the printed datasheet."""
    contingent = Contingent.deploy(
        Complement(unit=spearmen_unit, size=10),
        weapons=REPO.weapons,
        armoury=REPO.armoury,
        rules=REPO.rules,
    )

    assert contingent.unit.equipment == spearmen_unit.equipment
    assert contingent.unit.special_rules == spearmen_unit.special_rules


def test_each_arc_carries_its_initiative_cap() -> None:
    """+3 into the front arc, +4 into the flank or rear."""
    assert ChargeArc.FRONT.initiative_cap == 3
    assert ChargeArc.FLANK.initiative_cap == 4
    assert ChargeArc.REAR.initiative_cap == 4


def test_charge_rejects_a_negative_distance() -> None:
    """A negative charge distance is a programming error, not a zero bonus."""
    with pytest.raises(ValueError, match="negative distance"):
        Charge(-1, ChargeArc.FRONT)


def test_deploy_resolves_equipment_into_the_loadout(spearmen_unit: Unit) -> None:
    """Fielding resolves printed equipment names to weapon and armour entries.

    Spearmen carry Hand Weapon and Thrusting Spear (weapons) plus Light
    Armour and Shield (armour); the loadout partitions them resolved, in
    equipment order.
    """
    contingent = Contingent.deploy(
        Complement(unit=spearmen_unit, size=10),
        weapons=REPO.weapons,
        armoury=REPO.armoury,
        rules=REPO.rules,
    )
    assert contingent.loadout == Loadout(
        weapons=(REPO.weapons["hand-weapon"], REPO.weapons["thrusting-spear"]),
        armour=(REPO.armoury["light-armour"], REPO.armoury["shield"]),
        rules=(REPO.rules["elven-reflexes"], REPO.rules["valour-of-ages"]),
        unresolved_rules=(
            "Close Order",
            "Martial Prowess",
            "Regimental Unit",
        ),
    )


def test_deploy_resolves_option_granted_equipment() -> None:
    """Equipment added by a chosen option reaches the resolved loadout."""
    archers = REPO.units["elven-archers"]
    mustered = Complement(unit=archers, size=10, options=["Light Armour"])
    contingent = Contingent.deploy(
        mustered, weapons=REPO.weapons, armoury=REPO.armoury, rules=REPO.rules
    )
    assert contingent.loadout is not None
    assert REPO.armoury["light-armour"] in contingent.loadout.armour


def test_deploy_rejects_unresolvable_equipment(spearmen_unit: Unit) -> None:
    """A typo'd equipment name fails the deploy, naming the miss.

    The data covers every unit-referenced item, so at this seam a miss is
    an error to the list-builder, not a per-volley note.
    """
    typo = spearmen_unit.model_copy(update={"equipment": ["Hand Weapon", "Shjeld"]})
    with pytest.raises(ValueError, match=r"matches no weapon or armour: \['Shjeld'\]"):
        Contingent.deploy(
            Complement(unit=typo, size=10),
            weapons=REPO.weapons,
            armoury=REPO.armoury,
            rules=REPO.rules,
        )


def test_field_gives_the_printed_optionless_loadout(spearmen_unit: Unit) -> None:
    """field() is the per-unit default: the printed lists resolved, no options.

    Any model count is allowed — a what-if body needs no legal list
    size — and the loadout equals what deploying an optionless
    complement resolves.
    """
    fielded = Contingent.field(
        spearmen_unit, 1, weapons=REPO.weapons, armoury=REPO.armoury, rules=REPO.rules
    )
    deployed = Contingent.deploy(
        Complement(unit=spearmen_unit, size=10),
        weapons=REPO.weapons,
        armoury=REPO.armoury,
        rules=REPO.rules,
    )
    assert fielded.models == 1
    assert fielded.loadout == deployed.loadout


def test_a_remnant_keeps_its_loadout(spearmen_unit: Unit) -> None:
    """A post-casualty remnant is the same body, thinned: replace the count."""
    fielded = Contingent.field(
        spearmen_unit, 10, weapons=REPO.weapons, armoury=REPO.armoury, rules=REPO.rules
    )
    remnant = replace(fielded, models=7)
    assert remnant.models == 7
    assert remnant.loadout is fielded.loadout
    assert remnant.unit is fielded.unit


def test_deploy_tolerates_rules_without_entries(spearmen_unit: Unit) -> None:
    """A special rule with no entry is the norm: carried printed, not lost.

    Option-granted rules resolve on the same terms — Shieldwall has no
    entry under data/tow/rules/, so it joins the printed remainder that
    keeps feeding the "not factored" notes.
    """
    mustered = Complement(unit=spearmen_unit, size=10, options=["Shieldwall"])
    contingent = Contingent.deploy(
        mustered, weapons=REPO.weapons, armoury=REPO.armoury, rules=REPO.rules
    )
    assert contingent.loadout is not None
    assert [rule.id for rule in contingent.loadout.rules] == ["elven-reflexes", "valour-of-ages"]
    assert "Shieldwall" in contingent.loadout.unresolved_rules


def test_deploy_substitutes_rule_parameters_as_printed(spearmen_unit: Unit) -> None:
    """A parameterised unit rule arrives as the rule printed on the unit.

    No unit in data/ prints one yet, so a doctored datasheet exercises
    the path: "Armour Bane (2)" resolves to the (X) entry with the 2
    substituted into its effects, symmetric with the weapons and armour
    beside it.
    """
    doctored = spearmen_unit.model_copy(update={"special_rules": ["Armour Bane (2)"]})
    contingent = Contingent.deploy(
        Complement(unit=doctored, size=10),
        weapons=REPO.weapons,
        armoury=REPO.armoury,
        rules=REPO.rules,
    )
    assert contingent.loadout is not None
    (rule,) = contingent.loadout.rules
    assert rule.name == "Armour Bane (2)"
    effect = rule.effects[0]
    assert isinstance(effect, ModifierEffect)
    assert effect.then == {"armour-piercing": 2}


def test_loadout_answers_the_weapon_choice_by_printed_name(spearmen_unit: Unit) -> None:
    """The per-action choice picks a carried weapon by its printed name."""
    fielded = Contingent.field(
        spearmen_unit, 10, weapons=REPO.weapons, armoury=REPO.armoury, rules=REPO.rules
    )
    assert fielded.loadout.weapon("Thrusting Spear") is REPO.weapons["thrusting-spear"]
    with pytest.raises(ValueError, match="no 'Longbow' in this loadout; carried: Hand Weapon"):
        fielded.loadout.weapon("Longbow")


def test_loadout_resolves_the_carried_weapons_rules(spearmen_unit: Unit) -> None:
    """Weapon-rule names with entries resolve into the loadout's index.

    The archers' longbow prints Armour Bane (1) and Volley Fire: the
    first has an entry and resolves as printed; the second has none and
    is simply absent — the per-action compile reports it unfactored.
    """
    archers = Contingent.field(
        REPO.units["elven-archers"],
        10,
        weapons=REPO.weapons,
        armoury=REPO.armoury,
        rules=REPO.rules,
    )
    index = archers.loadout.weapon_rules
    assert set(index) == {"Armour Bane (1)"}
    assert index["Armour Bane (1)"].name == "Armour Bane (1)"


def test_an_uncarried_weapon_cannot_be_fought_with(spearmen_unit: Unit) -> None:
    """Every action's weapon choice is confirmed against the loadout."""
    fielded = Contingent.field(
        spearmen_unit, 10, weapons=REPO.weapons, armoury=REPO.armoury, rules=REPO.rules
    )
    assert fielded.wields(REPO.weapons["thrusting-spear"]) is REPO.weapons["thrusting-spear"]
    with pytest.raises(ValueError, match="does not carry 'Longbow'"):
        fielded.wields(REPO.weapons["longbow"])


# --- Formation: the geometry of ranks and files ---


def test_formation_geometry() -> None:
    """files, ranks, full_ranks and remainder over a five-wide formation."""
    full = Formation(models=10, frontage=5)  # two complete ranks
    assert (full.files, full.full_ranks, full.remainder, full.ranks) == (5, 2, 0, 2)

    ragged = Formation(models=12, frontage=5)  # 5 + 5 + a rear rank of 2
    assert (ragged.files, ragged.full_ranks, ragged.remainder, ragged.ranks) == (5, 2, 2, 3)

    thin = Formation(models=3, frontage=5)  # one incomplete rank
    assert (thin.files, thin.full_ranks, thin.remainder, thin.ranks) == (3, 0, 3, 1)


# --- frontage: the formation's width ---


def test_a_fielded_contingent_has_a_concrete_frontage(spearmen_unit: Unit) -> None:
    """A unit on the table is in a formation, so its frontage is always a width.

    With no width chosen, fielding lays the unit out in a single rank.
    """
    fielded = _fielded(spearmen_unit, 10)
    assert fielded.frontage == 10
    assert fielded.formation == Formation(models=10, frontage=10)


def test_a_chosen_frontage_is_kept(spearmen_unit: Unit) -> None:
    """A width given at fielding is the contingent's frontage."""
    assert _fielded(spearmen_unit, 10, frontage=5).frontage == 5


def test_frontage_must_be_a_positive_width(spearmen_unit: Unit) -> None:
    """A frontage below one model wide is a programming error, not a zero."""
    with pytest.raises(ValueError, match="at least 1 model wide"):
        _fielded(spearmen_unit, 10, frontage=0)
