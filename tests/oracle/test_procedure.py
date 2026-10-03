"""The oracle against the rulebook's own examples and rules no engine models yet."""

import ast
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

from .procedure import Attack, Order, Phase, ReRoll, one_attack, remove_casualties, removed

# S10 against T1 wounds on 2+ and nothing saves, so an attack's odds read off its hit.
SURE_WOUND = Fraction(5, 6)


def test_the_oracle_imports_no_engine() -> None:
    """Independence is the point: only core math may be imported from avelorn."""
    tree = ast.parse(Path(__file__).with_name("procedure.py").read_text())
    imported = [
        name
        for node in ast.walk(tree)
        for name in (
            [node.module or ""]
            if isinstance(node, ast.ImportFrom)
            else [alias.name for alias in node.names]
            if isinstance(node, ast.Import)
            else []
        )
    ]
    allowed = {"avelorn.core.dice", "avelorn.core.distribution"}
    assert not {name for name in imported if name.startswith("avelorn")} - allowed


def test_seven_plus_to_hit_confirms_a_natural_six() -> None:
    """The printed example: BS2 at -2 needs a 7, so a natural 6 is rolled again and hits on 4+."""
    attack = Attack(Phase.SHOOTING, skill=2, strength=10, toughness=1, hit_modifier=-2)
    assert one_attack(attack).unsaved == Fraction(1, 6) * Fraction(1, 2) * SURE_WOUND


def test_ten_plus_to_hit_is_impossible() -> None:
    """The 7+ table prints 10 as "Impossible!"."""
    attack = Attack(Phase.SHOOTING, skill=1, strength=10, toughness=1, hit_modifier=-4)
    assert one_attack(attack).unsaved == 0


def test_ballistic_skill_seven_re_rolls_a_miss_at_five_plus() -> None:
    """BS of 6 or Higher prints 2+/5+ for BS7: 5/6, then the miss re-rolled at 5+."""
    attack = Attack(Phase.SHOOTING, skill=7, strength=10, toughness=1)
    assert one_attack(attack).unsaved == (Fraction(5, 6) + Fraction(1, 6) * Fraction(2, 6)) * (
        SURE_WOUND
    )


def test_a_natural_six_always_hits_in_combat() -> None:
    """WS1 against WS10 at -3 needs an 8, yet the natural 6 still hits."""
    attack = Attack(
        Phase.COMBAT, skill=1, strength=10, toughness=1, foe_weapon_skill=10, hit_modifier=-3
    )
    assert one_attack(attack).unsaved == Fraction(1, 6) * SURE_WOUND


def test_poisoned_attacks_add_two_to_wound_on_a_natural_six_to_hit() -> None:
    """WS4 v WS4 hits on 4+, S3 v T5 wounds on 6+; the natural 6 To Hit wounds on 4+ instead."""
    attack = Attack(Phase.COMBAT, skill=4, strength=3, toughness=5, foe_weapon_skill=4)
    plain = Fraction(3, 6) * Fraction(1, 6)
    poisoned = Fraction(2, 6) * Fraction(1, 6) + Fraction(1, 6) * Fraction(3, 6)
    assert one_attack(attack).unsaved == plain
    assert one_attack(replace(attack, poisoned=True)).unsaved == poisoned


def test_poisoned_attacks_cannot_be_used_when_the_hit_needed_seven_plus() -> None:
    """At -3 the hit needs a 7: the natural 6 still hits in combat, but wounds on the plain 6+."""
    attack = Attack(
        Phase.COMBAT,
        skill=4,
        strength=3,
        toughness=5,
        foe_weapon_skill=4,
        hit_modifier=-3,
        poisoned=True,
    )
    assert one_attack(attack).unsaved == Fraction(1, 6) * Fraction(1, 6)


def test_a_killing_blow_skips_the_armour_save_but_not_the_ward() -> None:
    """WS4 v WS4, S3 v T3, 2+ armour, 5+ ward: the natural 6 To Wound is a Killing Blow."""
    attack = Attack(
        Phase.COMBAT,
        skill=4,
        strength=3,
        toughness=3,
        foe_weapon_skill=4,
        armour_value=2,
        ward=5,
        killing_blow=True,
        save_re_rolls=frozenset({ReRoll.ONES}),
    )
    odds = one_attack(attack)
    ward_fails = Fraction(4, 6)
    armour_fails = Fraction(1, 6) * Fraction(1, 6)  # only a natural 1, re-rolled into another
    assert odds.kill == Fraction(1, 2) * Fraction(1, 6) * ward_fails
    assert odds.wound == Fraction(1, 2) * Fraction(2, 6) * armour_fails * ward_fails


def test_a_cleaving_blow_skips_the_armour_save_without_slaying() -> None:
    """Cleaving Blow denies armour as Killing Blow does, but scores a plain wound."""
    attack = Attack(
        Phase.COMBAT, skill=4, strength=3, toughness=3, foe_weapon_skill=4, armour_value=2
    )
    cleaving = one_attack(replace(attack, cleaving_blow=True))
    assert cleaving.kill == 0
    assert cleaving.wound == one_attack(replace(attack, killing_blow=True)).unsaved


def test_wounds_are_lost_one_model_at_a_time() -> None:
    """The printed Ogre example: W3 Ogres losing five Wounds lose one model."""
    assert removed([1] * 5, models=3, wounds=3) == 1


def test_excess_wounds_do_not_spill_over() -> None:
    """Multiple Wounds (3) twice on W2 models: each fells one, the excess is lost."""
    assert removed([3, 3], models=3, wounds=2) == 2
    assert removed([2, 2], models=3, wounds=3) == 1


def test_a_killing_blow_takes_the_wounded_models_remaining_wounds() -> None:
    """Two Wounds on a W3 model, then a Killing Blow: that model goes, the next is fresh."""
    assert removed([1, 1, None, 1, 1], models=3, wounds=3) == 1
    assert removed([None, 1, 1, 1, 1], models=3, wounds=3) == 2


def test_the_monte_carlo_is_seeded() -> None:
    """The same seed gives the same histogram, so a sized tolerance is a fixed verdict."""
    odds = one_attack(Attack(Phase.SHOOTING, skill=4, strength=3, toughness=3))

    def run() -> dict[int, float]:
        return remove_casualties(
            10, odds, models=3, wounds=2, order=Order.AS_ROLLED, trials=500, seed=3
        )

    assert run() == run()


def test_ballistic_skill_six_applies_a_modifier_to_the_first_roll_only() -> None:
    """BS6 at -1 hits on 3+, and a miss is re-rolled at the unmodified 6+."""
    attack = Attack(Phase.SHOOTING, skill=6, strength=10, toughness=1, hit_modifier=-1)
    assert one_attack(attack).unsaved == (Fraction(4, 6) + Fraction(2, 6) * Fraction(1, 6)) * (
        SURE_WOUND
    )
