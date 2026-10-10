"""Volley program."""

from collections.abc import Hashable, Mapping
from fractions import Fraction
from itertools import product

import pytest
from oracle.procedure import NO_ARMOUR, Attack, Phase, casualties, one_attack

from avelorn.core.distribution import Distribution, Monoid, Probability
from avelorn.tow.contingent import Contingent
from avelorn.tow.data import TOWRepository
from avelorn.tow.fielding import Fielding, Part
from avelorn.tow.programs import VOLLEY, Evaluated, load_program
from avelorn.tow.schema.stage import Side
from avelorn.tow.schema.unit import Characteristic
from avelorn.tow.schema.weapon import WeaponStrength
from avelorn.tow.steps import Band
from avelorn.tow.traits import Operand

REPO = TOWRepository()
VOLLEY_PROGRAM = load_program(VOLLEY, REPO.rules)
ARCHERS = REPO.units["elven-archers"]
SPEARMEN = REPO.units["elven-spearmen"]
LONGBOW = REPO.weapons["longbow"].missile_profile


def _shooter(shots: int, ballistic_skill: int, strength: int, armour_piercing: int) -> Fielding:
    assert LONGBOW is not None
    row = ARCHERS.main.model_copy(
        update={
            "characteristics": {
                **ARCHERS.main.characteristics,
                Characteristic.BALLISTIC_SKILL: ballistic_skill,
            }
        }
    )
    bow = LONGBOW.model_copy(
        update={"strength": WeaponStrength(base=strength), "armour_piercing": armour_piercing}
    )
    return Fielding(
        "archers", ARCHERS.rank_and_file, (Part("archers", row, shots, weapon=bow),), shots
    )


def _target(
    toughness: int, wounds: int, armour: int | None, ward: int | None, models: int
) -> Fielding:
    row = SPEARMEN.main.model_copy(
        update={
            "characteristics": {
                **SPEARMEN.main.characteristics,
                Characteristic.TOUGHNESS: toughness,
                Characteristic.WOUNDS: wounds,
            }
        }
    )
    part = Part("spearmen", row, models, armour=armour, ward=ward)
    return Fielding("spearmen", SPEARMEN.rank_and_file, (part,), 5)


def _volley(
    attacker: Fielding,
    target: Fielding,
    *,
    shooters: int,
    models: int,
    battle_strength: int,
    distance: int = 12,
    can_shoot: bool = True,
    line_of_sight: bool = True,
    moved: bool = False,
) -> Evaluated:
    knowns: dict[str, Hashable] = {
        "distance": distance,
        "can-shoot": can_shoot,
        "line-of-sight": line_of_sight,
        "attacker/moved": moved,
        "attacker/standing": attacker.standing(shooters),
        "target/standing": target.standing(models),
        "target/models-at-start-of-phase": models,
        "target/battle-strength": battle_strength,
    }
    built = VOLLEY_PROGRAM.built({Side.ATTACKER: attacker, Side.TARGET: target})
    (evaluated,) = built.evaluate(knowns)
    return evaluated


def _landed(shots: int, p: Probability) -> Mapping[int, Probability]:
    once = Distribution({landed: mass for landed, mass in ((1, p), (0, 1 - p)) if mass})
    return once.repeat(shots, Monoid(0)).mass


def _casualties(evaluated: Evaluated, models: int) -> Distribution[int]:
    return evaluated.at("volley/remove-casualties").read("models").map(lambda left: models - left)


def _assert_matches_the_oracle(
    shots: int,
    ballistic_skill: int,
    strength: int,
    toughness: int,
    armour: int | None,
    armour_piercing: int,
    ward: int | None,
    models: int,
    wounds: int,
    moved: bool = False,
) -> None:
    attack = Attack(
        Phase.SHOOTING,
        skill=ballistic_skill,
        strength=strength,
        toughness=toughness,
        armour_value=NO_ARMOUR if armour is None else armour,
        armour_piercing=armour_piercing,
        ward=ward,
        hit_modifier=-1 if moved else 0,
    )
    odds = one_attack(attack)
    evaluated = _volley(
        _shooter(shots, ballistic_skill, strength, armour_piercing),
        _target(toughness, wounds, armour, ward, models),
        shooters=shots,
        models=models,
        battle_strength=models,
        moved=moved,
    )

    unsaved = evaluated.at("volley/remove-casualties").read("unsaved").mass
    assert {count: p for count, p in unsaved.items() if p} == _landed(shots, odds.unsaved)
    removed = _casualties(evaluated, models).mass
    assert {count: p for count, p in removed.items() if p} == casualties(
        [odds] * shots, models=models, wounds=wounds
    )


_SCENARIOS = [
    pytest.param(3, 4, 3, 3, 5, None, 3, 1, False, id="golden-chain"),
    pytest.param(1, 4, 3, 3, None, 4, 1, 1, False, id="ward-save"),
    pytest.param(10, 5, 1, 7, None, None, 10, 1, False, id="impossible-wound"),
    pytest.param(10, 4, 3, 3, None, None, 2, 1, False, id="casualties-capped"),
    pytest.param(6, 4, 3, 3, None, None, 6, 3, False, id="multi-wound-fold"),
    pytest.param(1, 6, 10, 1, None, None, 1, 1, False, id="bs6"),
    pytest.param(1, 6, 10, 1, None, None, 1, 1, True, id="bs6-moved"),
]


@pytest.mark.parametrize(
    (
        "shots",
        "ballistic_skill",
        "strength",
        "toughness",
        "armour",
        "ward",
        "models",
        "wounds",
        "moved",
    ),
    _SCENARIOS,
)
def test_the_shooting_scenarios_match_the_oracle(
    shots: int,
    ballistic_skill: int,
    strength: int,
    toughness: int,
    armour: int | None,
    ward: int | None,
    models: int,
    wounds: int,
    moved: bool,
) -> None:
    _assert_matches_the_oracle(
        shots, ballistic_skill, strength, toughness, armour, 0, ward, models, wounds, moved
    )


_SWEEP = list(
    product(
        (1, 3, 5),
        ((1, 7), (2, 4), (3, 3), (5, 3), (4, 6)),
        (None, 3, 6),
        (0, -2),
        (None, 4),
        (1, 7),
        ((7, 1), (3, 3)),
    )
)


@pytest.mark.parametrize(
    (
        "ballistic_skill",
        "strength_toughness",
        "armour",
        "armour_piercing",
        "ward",
        "shots",
        "unit",
    ),
    _SWEEP,
    ids=[
        f"bs{bs}-s{s}-t{t}-av{av}-ap{ap}-ward{ward}-shots{shots}-models{models}-w{wounds}"
        for bs, (s, t), av, ap, ward, shots, (models, wounds) in _SWEEP
    ],
)
def test_the_sweep_matches_the_oracle(
    ballistic_skill: int,
    strength_toughness: tuple[int, int],
    armour: int | None,
    armour_piercing: int,
    ward: int | None,
    shots: int,
    unit: tuple[int, int],
) -> None:
    strength, toughness = strength_toughness
    models, wounds = unit
    _assert_matches_the_oracle(
        shots,
        ballistic_skill,
        strength,
        toughness,
        armour,
        armour_piercing,
        ward,
        models,
        wounds,
    )


def _corpus_volley(
    distance: int, shooters: int = 10, can_shoot: bool = True, line_of_sight: bool = True
) -> Evaluated:
    archers = Contingent.deploy("elven-archers", 10, data=REPO, frontage=5)
    spearmen = Contingent.deploy("elven-spearmen", 20, data=REPO, frontage=5)
    return _volley(
        Fielding.of(archers, "Longbow"),
        Fielding.of(spearmen),
        shooters=shooters,
        models=20,
        battle_strength=20,
        distance=distance,
        can_shoot=can_shoot,
        line_of_sight=line_of_sight,
    )


def test_ballistic_skill_6_shows_its_chart_target_moved_by_the_rules_in_force() -> None:
    volley = _volley(
        _shooter(1, 6, 3, 0),
        _target(3, 1, None, None, 1),
        shooters=1,
        models=1,
        battle_strength=1,
        moved=True,
    )

    hit = volley.at("volley/attacker/attack/archers/roll-to-hit")
    assert (hit.read("printed").mass, hit.read("needed").mass) == (
        {"2+ then 6+": 1},
        {"3+ then 6+": 1},
    )


def test_a_save_shows_every_target_armour_bane_leaves_in_force() -> None:
    sisters = Contingent.deploy("sisters-of-avelorn", 5, data=REPO, frontage=5)
    spearmen = Contingent.deploy("elven-spearmen", 10, data=REPO)
    volley = _volley(
        Fielding.of(sisters, "Bow of Avelorn"),
        Fielding.of(spearmen),
        shooters=5,
        models=10,
        battle_strength=10,
    )
    every_six, no_save_at_all = Fraction(31, 36) ** 5, Fraction(5, 36) ** 5

    saves = volley.at("volley/attacker/attack/sister-of-avelorn/make-armour-saves")
    assert saves.read("printed").mass == {"5+": 1}
    assert saves.read("needed").mass == {
        "6+": every_six,
        "6+ or -": 1 - every_six - no_save_at_all,
        "-": no_save_at_all,
    }


def test_a_part_at_a_step_reads_its_characteristic_as_an_operand() -> None:
    at = _corpus_volley(12).at("volley/attacker/attack/elven-archer/roll-to-wound")

    assert at.part(Side.TARGET, "elven-spearman").characteristic(
        Characteristic.TOUGHNESS
    ) == Operand(Distribution.pure(3), 3)


def test_a_shooter_wounds_at_its_weapon_strength() -> None:
    volley = _volley(
        _shooter(5, 4, 5, 0), _target(3, 1, None, None, 5), shooters=5, models=5, battle_strength=5
    )

    archers = volley.at("volley/attacker/attack/archers/roll-to-wound").part(
        Side.ATTACKER, "archers"
    )
    assert archers.characteristic(Characteristic.STRENGTH) == Operand(Distribution.pure(5), 3)


def test_each_side_of_a_mirror_match_reads_its_own_part() -> None:
    archers = Contingent.deploy("elven-archers", 10, data=REPO, frontage=5)
    volley = _volley(
        Fielding.of(archers, "Longbow"),
        Fielding.of(archers),
        shooters=10,
        models=10,
        battle_strength=10,
    )

    at = volley.at("volley/attacker/attack/elven-archer/roll-to-wound")
    assert at.part(Side.ATTACKER, "elven-archer").characteristic(
        Characteristic.STRENGTH
    ) == Operand(Distribution.pure(3), 3)
    assert at.part(Side.TARGET, "elven-archer").characteristic(
        Characteristic.TOUGHNESS
    ) == Operand(Distribution.pure(3), 3)


@pytest.mark.parametrize(
    ("distance", "shooters", "can_shoot", "line_of_sight", "band", "shots"),
    [
        pytest.param(15, 10, True, True, Band.SHORT, 8, id="short-range-at-half-range"),
        pytest.param(30, 10, True, True, Band.LONG, 8, id="long-range-at-maximum-range"),
        pytest.param(31, 10, True, True, Band.OUT_OF_RANGE, 0, id="out-of-range"),
        pytest.param(12, 3, True, True, Band.SHORT, 3, id="fewer-shooters-than-the-frontage"),
        pytest.param(12, 10, False, True, Band.SHORT, 0, id="nobody-can-shoot"),
        pytest.param(12, 10, True, False, Band.SHORT, 0, id="no-line-of-sight"),
    ],
)
def test_the_volley_counts_its_shots(
    distance: int,
    shooters: int,
    can_shoot: bool,
    line_of_sight: bool,
    band: Band,
    shots: int,
) -> None:
    volley = _corpus_volley(distance, shooters, can_shoot, line_of_sight)

    assert volley.at("volley/check-range").read("band").mass == {band: 1}
    assert volley.at("volley/how-many-shots").read("shots").mass == {shots: 1}


@pytest.mark.parametrize(
    ("moved", "standing", "parts"),
    [
        pytest.param(False, 10, "sentinel 1, elven-archer 7", id="volley-fire"),
        pytest.param(True, 10, "sentinel 1, elven-archer 4", id="after-moving"),
        pytest.param(False, 7, "sentinel 1, elven-archer 5", id="three-lost-off-the-back"),
    ],
)
def test_a_champion_shoots_from_the_front_rank(moved: bool, standing: int, parts: str) -> None:
    """Ten Archers five wide with a Sentinel: the Sentinel fires from the front rank."""
    archers = Contingent.deploy("elven-archers", 10, ("Sentinel",), data=REPO, frontage=5)
    spearmen = Contingent.deploy("elven-spearmen", 20, data=REPO, frontage=5)
    volley = _volley(
        Fielding.of(archers, "Longbow", ("Sentinel",)),
        Fielding.of(spearmen),
        shooters=standing,
        models=20,
        battle_strength=20,
        moved=moved,
    )

    assert volley.at("volley/how-many-shots").read("parts").mass == {parts: 1}


def test_a_champion_shoots_at_its_own_ballistic_skill() -> None:
    """The Sentinel hits on 2+ at its own BS 5, where the Archers at BS 4 need 3+."""
    archers = Contingent.deploy("elven-archers", 10, ("Sentinel",), data=REPO, frontage=5)
    spearmen = Contingent.deploy("elven-spearmen", 20, data=REPO, frontage=5)
    volley = _volley(
        Fielding.of(archers, "Longbow", ("Sentinel",)),
        Fielding.of(spearmen),
        shooters=10,
        models=20,
        battle_strength=20,
    )

    hits = volley.at("volley/attacker/attack/sentinel/roll-to-hit").read("hits").mass
    assert {count: p for count, p in hits.items() if p} == {0: Fraction(1, 6), 1: Fraction(5, 6)}
