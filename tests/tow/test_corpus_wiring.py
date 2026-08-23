"""The corpus wired up: printed rules reaching the maths on real datasheets.

`tests/tow/phases/test_combat_spec.py` pins what the rules *mean*, using
stripped synthetic bodies so every figure is exact. This file asks the other
question: do the datasheets actually connect? A rule can be authored, tested
against a doctored unit, and still never fire for the unit that prints it --
the name misspelled, the gate unanswerable from that seat, the entry filed
where nothing looks. Nothing above catches that.

Each test below strips one rule from a real unit and compares, so the only
difference is the rule under test. Exact amounts stay in the spec; what is
asserted here is that the real datasheet reaches them.
"""

from fractions import Fraction

from avelorn.tow.data import TOWRepository
from avelorn.tow.game import TOWGame
from avelorn.tow.phases.combat import CombatResult, break_test, strike_unit
from avelorn.tow.phases.shooting import shoot_unit
from avelorn.tow.schema.unit import Unit
from avelorn.tow.views import unmodelled_rules

REPO = TOWRepository()
GAME = TOWGame.load_data()

# The rules each recently imported datasheet prints that have no entry, so the
# engine cannot apply them. Pinned per unit rather than corpus-wide: this set
# should shrink as gaps close, where a corpus-wide list grows with every import
# and would fail on work unrelated to these units. Everything else each unit
# prints resolves.
UNMODELLED = {
    "war-lions": {"Fear", "Move Through Cover", "Open Order", "Swiftstride", "Vanguard"},
    "merwyrm": {"Close Order", "Large Target"},
    "great-eagle": {"Close Order", "Fear", "Fly (10)", "Swiftstride"},
    "frostheart-phoenix": {"Close Order", "Fear", "Fly (9)", "Large Target", "Swiftstride"},
    "flamespyre-phoenix": {
        "Close Order",
        "Fear",
        "Fly (10)",
        "From the Ashes",
        "Large Target",
        "Swiftstride",
        "Wake of Fire",
    },
}


def _without(unit: Unit, rule: str) -> Unit:
    # The same datasheet with one printed rule struck out, so a comparison
    # isolates that rule and nothing else about the unit.
    assert rule in unit.special_rules, f"{unit.name} does not print {rule}"
    return unit.model_copy(update={"special_rules": [r for r in unit.special_rules if r != rule]})


def test_each_datasheet_models_everything_but_the_named_rules() -> None:
    """Per unit, exactly the listed rules lack an entry. The rest reach the maths."""
    report = unmodelled_rules(REPO)
    for slug, expected in UNMODELLED.items():
        assert {rule.name for rule in report if slug in rule.units} == expected, slug


def test_blizzard_aura_makes_a_foe_of_the_frostheart_strike_last() -> None:
    """The Frostheart's foe strikes at Initiative 1, however quick it prints.

    Swordmasters print I6, the highest in the corpus. Fighting the Frostheart
    they strike at 1 -- Strike Last conferred on the enemy, which is the whole
    point of an enemy-subject set, and the rule is claimed for the Phoenix that
    carries it rather than for them.
    """
    frostheart = REPO.units["frostheart-phoenix"]
    swordmasters = GAME.field(REPO.units["swordmasters-of-hoeth"], 5).wielding("Hand Weapon")

    with GAME.turn().combat() as combat:
        chilled = combat.fight(swordmasters, GAME.field(frostheart, 1).wielding("Wicked Claws"))
        bare = combat.fight(
            swordmasters,
            GAME.field(_without(frostheart, "Blizzard Aura"), 1).wielding("Wicked Claws"),
        )

    assert chilled.a_initiative.value == 1
    assert bare.a_initiative.value == 6
    assert chilled.a_initiative.foe_factored == ("Blizzard Aura",)


def test_enfeebling_cold_costs_a_foe_of_the_merwyrm_a_point_of_strength() -> None:
    """Striking the Merwyrm is one step harder to wound than its Toughness alone.

    White Lions swing a Chracian Great Blade at S5 into T6: a 4+ to wound. The
    Merwyrm's aura drops them to S4 and the roll to a 5+. Comparing against the
    same Merwyrm without the rule keeps Toughness out of it.
    """
    merwyrm = REPO.units["merwyrm"]
    lions = GAME.field(REPO.units["white-lions-of-chrace"], 5).wielding("Chracian Great Blade")

    chilled = strike_unit(lions, GAME.field(merwyrm, 1).wielding("Lashing Talons"))
    bare = strike_unit(
        lions, GAME.field(_without(merwyrm, "Enfeebling Cold"), 1).wielding("Lashing Talons")
    )

    assert (bare.wound_target, chilled.wound_target) == (4, 5)


def test_terror_costs_the_loser_a_point_of_break_leadership() -> None:
    """Breaking from the Merwyrm is tested at one less Leadership.

    Swordmasters print Ld8. Losing a round by 2 they Break on a natural over
    their Leadership: 9-12, ten of the thirty-six. Terror tests them at 7
    instead, so 8-12 Breaks -- fifteen of thirty-six.
    """
    merwyrm = REPO.units["merwyrm"]
    swordmasters = GAME.field(REPO.units["swordmasters-of-hoeth"], 5).wielding("Hand Weapon")
    lost_by_two = CombatResult(
        p_a_wins=Fraction(1), p_draw=Fraction(0), p_b_wins=Fraction(0), margin={2: Fraction(1)}
    )

    feared = break_test(
        lost_by_two, GAME.field(merwyrm, 1).wielding("Lashing Talons"), swordmasters
    ).b
    bare = break_test(
        lost_by_two,
        GAME.field(_without(merwyrm, "Terror"), 1).wielding("Lashing Talons"),
        swordmasters,
    ).b

    assert bare.p_breaks == Fraction(10, 36)
    assert feared.p_breaks == Fraction(15, 36)


def test_abyssal_cloak_deepens_the_merwyrms_long_range_penalty() -> None:
    """Shooting the Merwyrm at long range is one point harder than the usual -1.

    Forced to short range the cloak is a known no-op, honoured by not applying
    rather than reported unfactored.
    """
    merwyrm = REPO.units["merwyrm"]
    bare_sheet = _without(merwyrm, "Abyssal Cloak")
    archers = GAME.field(REPO.units["elven-archers"], 5).wielding("Longbow")

    far = shoot_unit(archers, GAME.field(merwyrm, 1), distance=20)
    far_bare = shoot_unit(archers, GAME.field(bare_sheet, 1), distance=20)
    assert far.hit_target == far_bare.hit_target + 1

    near = shoot_unit(archers, GAME.field(merwyrm, 1), force_short_range=True)
    near_bare = shoot_unit(archers, GAME.field(bare_sheet, 1), force_short_range=True)
    assert near.hit_target == near_bare.hit_target
    assert not any("not factored: Abyssal Cloak" in note for note in near.notes)


def test_the_great_eagles_maw_multiplies_the_wounds_it_inflicts() -> None:
    """Multiple Wounds (2) on a printed weapon fells a 3-Wound body it otherwise could not.

    The Serrated Maw's own rules are claimed, and against a Great Eagle's own W3
    the doubled wounds remove models where its Wicked Claws, at the same
    Strength, cannot. The multiplier's arithmetic is pinned in the combat spec;
    what this asserts is that the printed weapon reaches it.
    """
    eagle = REPO.units["great-eagle"]
    target = GAME.field(eagle, 3).wielding("Wicked Claws")
    maw = strike_unit(GAME.field(eagle, 3).wielding("Serrated Maw"), target)
    claws = strike_unit(GAME.field(eagle, 3).wielding("Wicked Claws"), target)

    assert not any("not factored: Multiple Wounds" in note for note in maw.notes)
    assert not any("not factored: Armour Bane" in note for note in maw.notes)
    felled = lambda result: sum(k * p for k, p in enumerate(result.casualties))  # noqa: E731
    assert felled(maw) > felled(claws)


def test_stomp_attacks_are_claimed_by_every_behemoth_that_prints_them() -> None:
    """The closing automatic hits fire for the real datasheets, not just a fixture.

    Each of these prints Stomp Attacks and the Merwyrm prints Impact Hits too;
    both land outside the Initiative order, so a round must claim them rather
    than report them unapplied.
    """
    foe = GAME.field(REPO.units["swordmasters-of-hoeth"], 5).wielding("Hand Weapon")
    for slug, weapon in (
        ("merwyrm", "Lashing Talons"),
        ("frostheart-phoenix", "Wicked Claws"),
        ("flamespyre-phoenix", "Wicked Claws"),
        ("great-eagle", "Serrated Maw"),
    ):
        with GAME.turn().combat() as combat:
            fought = combat.fight(GAME.field(REPO.units[slug], 1).wielding(weapon), foe)
        unapplied = [
            note
            for note in fought.notes
            if "not factored" in note and ("Stomp Attacks" in note or "Impact Hits" in note)
        ]
        assert not unapplied, f"{slug}: {unapplied}"
