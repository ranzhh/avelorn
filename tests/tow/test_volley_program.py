"""Volley program."""

from collections.abc import Hashable, Mapping
from itertools import product

import pytest
from oracle.procedure import NO_ARMOUR, Attack, Phase, one_attack
from pins.corrections import corrections

from avelorn.core.distribution import Distribution, Monoid, Probability
from avelorn.tow.contingent import Contingent
from avelorn.tow.data import TOWRepository
from avelorn.tow.kernels import Standing, save_probability
from avelorn.tow.phases.shooting import make_panic_tests, shoot
from avelorn.tow.programs import VOLLEY, Evaluated, load_program
from avelorn.tow.schema.stage import Side
from avelorn.tow.schema.unit import Characteristic
from avelorn.tow.schema.weapon import WeaponStrength
from avelorn.tow.steps import Band, Fielded, Retreat
from avelorn.tow.traits import Operand

REPO = TOWRepository()
VOLLEY_PROGRAM = load_program(VOLLEY, REPO.rules)
ARCHERS = REPO.units["elven-archers"]
SPEARMEN = REPO.units["elven-spearmen"]
LONGBOW = REPO.weapons["longbow"].missile_profile
CORRECTIONS = corrections()


def _shooter(shots: int, ballistic_skill: int, strength: int, armour_piercing: int) -> Fielded:
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
    return Fielded("archers", row, shots, bow)


def _target(toughness: int, wounds: int, armour: int | None, ward: int | None) -> Fielded:
    row = SPEARMEN.main.model_copy(
        update={
            "characteristics": {
                **SPEARMEN.main.characteristics,
                Characteristic.TOUGHNESS: toughness,
                Characteristic.WOUNDS: wounds,
            }
        }
    )
    return Fielded("spearmen", row, 5, armour=armour, ward=ward)


def _volley(
    attacker: Fielded,
    target: Fielded,
    *,
    shooters: int,
    models: int,
    battle_strength: int,
    distance: int = 12,
    who_can_shoot: bool = True,
    line_of_sight: bool = True,
) -> Evaluated:
    knowns: dict[str, Hashable] = {
        "attacker/fielded": attacker,
        "target/fielded": target,
        "distance": distance,
        "who-can-shoot": who_can_shoot,
        "line-of-sight": line_of_sight,
        "attacker/standing": Standing(shooters, 0),
        "target/standing": Standing(models, 0),
        "target/models-at-start-of-phase": models,
        "target/battle-strength": battle_strength,
    }
    (evaluated,) = VOLLEY_PROGRAM.evaluate(knowns)
    return evaluated


def _landed(shots: int, p: Probability) -> Mapping[int, Probability]:
    once = Distribution({landed: mass for landed, mass in ((1, p), (0, 1 - p)) if mass})
    return once.repeat(shots, Monoid(0)).mass


def _read(evaluated: Evaluated, path: str, reading: str) -> Mapping[Hashable, Probability]:
    return {value: mass for value, mass in evaluated.at(path).read(reading).mass.items() if mass}


def _casualties(evaluated: Evaluated, models: int) -> Distribution[int]:
    return evaluated.at("volley/remove-casualties").read("models").map(lambda left: models - left)


def _per_shot(evaluated: Evaluated, path: str, reading: str, shots: int) -> Probability:
    return evaluated.at(path).read(reading).expect(lambda count: count) / shots


def _assert_matches_legacy(
    pin: str,
    shots: int,
    ballistic_skill: int,
    strength: int,
    toughness: int,
    armour: int | None,
    armour_piercing: int,
    ward: int | None,
    models: int,
    wounds: int,
) -> None:
    legacy = shoot(
        shots,
        ballistic_skill,
        strength,
        toughness,
        armour_value=armour,
        armour_piercing=armour_piercing,
        ward_target=ward,
        wounds_per_model=wounds,
        targets=models,
    )
    evaluated = _volley(
        _shooter(shots, ballistic_skill, strength, armour_piercing),
        _target(toughness, wounds, armour, ward),
        shooters=shots,
        models=models,
        battle_strength=models,
    )

    correction = CORRECTIONS.get(pin)
    if correction is not None:
        attack = Attack(
            Phase.SHOOTING,
            skill=ballistic_skill,
            strength=strength,
            toughness=toughness,
            armour_value=NO_ARMOUR if armour is None else armour,
            armour_piercing=armour_piercing,
            ward=ward,
        )
        hit = _per_shot(evaluated, "volley/attack/roll-to-hit", "hits", shots)
        unsaved = _per_shot(evaluated, "volley/remove-casualties", "unsaved", shots)
        assert hit != legacy.p_hit
        assert (legacy.p_hit, hit) == (correction.old, correction.new)
        assert unsaved == one_attack(attack).unsaved
        return

    hit_and_wounded = legacy.p_hit * legacy.p_wound
    assert _read(evaluated, "volley/attack/roll-to-hit", "hits") == _landed(shots, legacy.p_hit)
    assert _read(evaluated, "volley/attack/roll-to-wound", "wounds") == _landed(
        shots, hit_and_wounded
    )
    assert _read(evaluated, "volley/attack/make-armour-saves", "saves") == _landed(
        shots, hit_and_wounded * save_probability(legacy.save_target)
    )
    unsaved = evaluated.at("volley/remove-casualties").read("unsaved")
    assert unsaved.mass == Distribution.from_counts(legacy.distribution).mass
    assert _casualties(evaluated, models).mass == Distribution.from_counts(legacy.casualties).mass


_SCENARIOS = [
    pytest.param(3, 4, 3, 3, 5, None, 3, 1, id="golden-chain"),
    pytest.param(1, 4, 3, 3, None, 4, 1, 1, id="ward-save"),
    pytest.param(10, 5, 1, 7, None, None, 10, 1, id="impossible-wound"),
    pytest.param(10, 4, 3, 3, None, None, 2, 1, id="casualties-capped"),
    pytest.param(6, 4, 3, 3, None, None, 6, 3, id="multi-wound-fold"),
    pytest.param(1, 6, 10, 1, None, None, 1, 1, id="bs6"),
]


@pytest.mark.parametrize(
    ("shots", "ballistic_skill", "strength", "toughness", "armour", "ward", "models", "wounds"),
    _SCENARIOS,
)
def test_the_shooting_scenarios_match_legacy_shoot(
    request: pytest.FixtureRequest,
    shots: int,
    ballistic_skill: int,
    strength: int,
    toughness: int,
    armour: int | None,
    ward: int | None,
    models: int,
    wounds: int,
) -> None:
    _assert_matches_legacy(
        request.node.nodeid,
        shots,
        ballistic_skill,
        strength,
        toughness,
        armour,
        0,
        ward,
        models,
        wounds,
    )


def test_every_correction_pins_a_shooting_scenario(request: pytest.FixtureRequest) -> None:
    module = request.node.nodeid.split("::")[0]
    test = test_the_shooting_scenarios_match_legacy_shoot.__name__

    assert set(CORRECTIONS) <= {f"{module}::{test}[{each.id}]" for each in _SCENARIOS}


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
def test_the_sweep_matches_legacy_shoot(
    request: pytest.FixtureRequest,
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
    _assert_matches_legacy(
        request.node.nodeid,
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


@pytest.mark.parametrize(
    ("shots", "models", "battle_strength"),
    [
        pytest.param(10, 5, 5, id="small-unit-may-be-destroyed"),
        pytest.param(10, 8, 20, id="already-below-half"),
        pytest.param(20, 10, 12, id="falls-back-or-flees"),
        pytest.param(3, 20, 20, id="rarely-tests"),
    ],
)
def test_the_panic_steps_match_legacy_make_panic_tests(
    shots: int, models: int, battle_strength: int
) -> None:
    legacy_volley = shoot(shots, 4, 3, 3, armour_value=5, targets=models)
    ruleless = SPEARMEN.model_copy(update={"special_rules": []})
    legacy = make_panic_tests(
        legacy_volley,
        Contingent.field(ruleless, models, data=REPO),
        battle_strength=battle_strength,
    )
    evaluated = _volley(
        _shooter(shots, 4, 3, 0),
        _target(3, 1, 5, None),
        shooters=shots,
        models=models,
        battle_strength=battle_strength,
    )

    tested = evaluated.at("volley/heavy-casualties").read("tested").mass.get(True, 0)
    retreat = evaluated.at("volley/fall-back-or-flee").read("retreat").mass
    assert legacy.reroll_from is None
    assert tested == legacy.p_test
    assert retreat.get(Retreat.DESTROYED, 0) == legacy.p_destroyed
    assert retreat.get(Retreat.HOLDS, 0) == legacy.p_holds
    assert retreat.get(Retreat.FALLS_BACK_IN_GOOD_ORDER, 0) == legacy.p_falls_back
    assert retreat.get(Retreat.FLEES, 0) == legacy.p_flees


def _corpus_volley(
    distance: int, shooters: int = 10, who_can_shoot: bool = True, line_of_sight: bool = True
) -> Evaluated:
    archers = Contingent.deploy("elven-archers", 10, data=REPO, frontage=5)
    spearmen = Contingent.deploy("elven-spearmen", 20, data=REPO, frontage=5)
    return _volley(
        Fielded.of(archers, "Longbow"),
        Fielded.of(spearmen),
        shooters=shooters,
        models=20,
        battle_strength=20,
        distance=distance,
        who_can_shoot=who_can_shoot,
        line_of_sight=line_of_sight,
    )


def test_a_part_at_a_step_reads_its_characteristic_as_an_operand() -> None:
    at = _corpus_volley(12).at("volley/attack/roll-to-wound")

    assert at.part(Side.TARGET, "elven-spearmen").characteristic(
        Characteristic.TOUGHNESS
    ) == Operand(Distribution.pure(3), 3)


def test_a_shooter_wounds_at_its_weapon_strength() -> None:
    volley = _volley(
        _shooter(5, 4, 5, 0), _target(3, 1, None, None), shooters=5, models=5, battle_strength=5
    )

    archers = volley.at("volley/attack/roll-to-wound").part(Side.ATTACKER, "archers")
    assert archers.characteristic(Characteristic.STRENGTH) == Operand(Distribution.pure(5), 3)


def test_each_side_of_a_mirror_match_reads_its_own_part() -> None:
    archers = Contingent.deploy("elven-archers", 10, data=REPO, frontage=5)
    volley = _volley(
        Fielded.of(archers, "Longbow"),
        Fielded.of(archers),
        shooters=10,
        models=10,
        battle_strength=10,
    )

    at = volley.at("volley/attack/roll-to-wound")
    assert at.part(Side.ATTACKER, "elven-archers").characteristic(
        Characteristic.STRENGTH
    ) == Operand(Distribution.pure(3), 3)
    assert at.part(Side.TARGET, "elven-archers").characteristic(
        Characteristic.TOUGHNESS
    ) == Operand(Distribution.pure(3), 3)


@pytest.mark.parametrize(
    ("distance", "shooters", "who_can_shoot", "line_of_sight", "band", "shots"),
    [
        pytest.param(15, 10, True, True, Band.SHORT, 5, id="short-range-at-half-range"),
        pytest.param(30, 10, True, True, Band.LONG, 5, id="long-range-at-maximum-range"),
        pytest.param(31, 10, True, True, Band.OUT_OF_RANGE, 0, id="out-of-range"),
        pytest.param(12, 3, True, True, Band.SHORT, 3, id="fewer-shooters-than-the-frontage"),
        pytest.param(12, 10, False, True, Band.SHORT, 0, id="nobody-can-shoot"),
        pytest.param(12, 10, True, False, Band.SHORT, 0, id="no-line-of-sight"),
    ],
)
def test_the_volley_counts_its_shots(
    distance: int,
    shooters: int,
    who_can_shoot: bool,
    line_of_sight: bool,
    band: Band,
    shots: int,
) -> None:
    volley = _corpus_volley(distance, shooters, who_can_shoot, line_of_sight)

    assert volley.at("volley/check-range").read("band").mass == {band: 1}
    assert volley.at("volley/how-many-shots").read("shots").mass == {shots: 1}
