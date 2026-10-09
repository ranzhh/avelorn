"""Every corpus volley on both engines."""

from collections.abc import Hashable, Mapping
from dataclasses import replace
from typing import NamedTuple

import pytest
from pins.corrections import corrections

from avelorn.core.distribution import Distribution, Probability
from avelorn.tow.contingent import Contingent, Movement
from avelorn.tow.coverage import fieldings
from avelorn.tow.data import TOWRepository
from avelorn.tow.fielding import Fielding
from avelorn.tow.game import TOWGame
from avelorn.tow.phases.shooting import make_panic_tests, shoot_unit
from avelorn.tow.programs import VOLLEY, Built, Evaluated, load_program
from avelorn.tow.schema.phase import Phase
from avelorn.tow.schema.stage import Side
from avelorn.tow.schema.unit import Characteristic
from avelorn.tow.steps import Retreat

REPO = TOWRepository()
IN_PLAY = TOWGame.assemble(REPO).in_play[Phase.SHOOTING]
VOLLEY_PROGRAM = load_program(VOLLEY, REPO.rules)
CORRECTIONS = corrections()


class Outcome(NamedTuple):
    """What one volley ends in, as both engines report it."""

    shots: int
    unsaved: Mapping[int, Probability]
    casualties: Mapping[int, Probability]
    tested: Probability
    retreat: Mapping[Retreat, Probability]


def _kept[T: Hashable](mass: Mapping[T, Probability]) -> dict[T, Probability]:
    return {value: p for value, p in mass.items() if p}


def _fielded(fielded: Fielding, models: int) -> str:
    parts = tuple(
        (part.id, part.row, part.count, part.weapon, part.armour, part.ward, part.wielded)
        for part in fielded.parts
    )
    return repr((parts, tuple(fielded.sources()), fielded.frontage, models))


def _name(slug: str, options: tuple[str, ...]) -> str:
    return "+".join((slug, *(option.lower().replace(" ", "-") for option in options)))


def _sizes(contingent: Contingent, options: tuple[str, ...]) -> tuple[Contingent, ...]:
    size = contingent.unit.unit_size
    if size.max is not None and size.max < 2 * size.min:
        return (contingent,)
    return contingent, Contingent.deploy(contingent.unit.id, 2 * size.min, options, data=REPO)


type Fielded = tuple[tuple[str, ...], Contingent]


def _distinct() -> tuple[dict[str, Fielded], dict[str, Fielded]]:
    shooters: dict[str, tuple[str, Fielded]] = {}
    targets: dict[str, tuple[str, Fielded]] = {}
    for options, contingent in fieldings(REPO):
        name = _name(contingent.unit.id, options)
        target = Fielding.of(contingent, options=options)
        targets.setdefault(_fielded(target, contingent.models), (name, (options, contingent)))
        for fielding in _sizes(contingent, options):
            for weapon in fielding.loadout.weapons:
                if weapon.missile_profile is not None:
                    armed = fielding.wielding(weapon.name)
                    fielded = Fielding.of(armed, weapon.name, options)
                    shooters.setdefault(
                        _fielded(fielded, armed.models),
                        (f"{name}/{weapon.id}/{armed.models}", (options, armed)),
                    )
    return dict(shooters.values()), dict(targets.values())


SHOOTERS, TARGETS = _distinct()


def _skilled(fielding: Fielding) -> bool:
    printed = fielding.hit.characteristic(Characteristic.BALLISTIC_SKILL)
    return any(
        part.characteristic(Characteristic.BALLISTIC_SKILL) != printed for part in fielding.parts
    )


def _unit_skill(fielding: Fielding) -> Fielding:
    skill = fielding.hit.characteristic(Characteristic.BALLISTIC_SKILL)
    parts = tuple(
        replace(
            part,
            row=part.row.model_copy(
                update={
                    "characteristics": {
                        **part.row.characteristics,
                        Characteristic.BALLISTIC_SKILL: skill,
                    }
                }
            ),
        )
        for part in fielding.parts
    )
    return replace(fielding, parts=parts)


def _legacy(attacker: Contingent, target: Contingent, distance: int) -> Outcome:
    volley = shoot_unit(attacker, target, phase_rules=IN_PLAY, distance=distance)
    panic = make_panic_tests(volley, target)
    retreat = {
        Retreat.HOLDS: panic.p_holds,
        Retreat.FALLS_BACK_IN_GOOD_ORDER: panic.p_falls_back,
        Retreat.FLEES: panic.p_flees,
        Retreat.DESTROYED: panic.p_destroyed,
    }
    return Outcome(
        volley.shots,
        _kept(Distribution.from_counts(volley.distribution).mass),
        _kept(Distribution.from_counts(volley.casualties).mass),
        panic.p_test,
        _kept(retreat),
    )


def _taken(built: Built, attacker: Contingent, target: Contingent, distance: int) -> Evaluated:
    lanes = built.evaluate(
        {
            "distance": distance,
            "can-shoot": True,
            "line-of-sight": True,
            "attacker/moved": attacker.movement.moved,
            "attacker/standing": built.fielded[Side.ATTACKER].standing(attacker.models),
            "target/standing": built.fielded[Side.TARGET].standing(target.models),
            "target/models-at-start-of-phase": target.models,
            "target/battle-strength": target.models,
        }
    )
    (taken,) = (evaluated for evaluated in lanes if not evaluated.lane.out)
    return taken


def _graph(built: Built, attacker: Contingent, target: Contingent, distance: int) -> Outcome:
    taken = _taken(built, attacker, target, distance)
    (shots,) = taken.at("volley/how-many-shots").read("shots").mass
    removed = taken.at("volley/remove-casualties")
    return Outcome(
        shots,
        _kept(removed.read("unsaved").mass),
        _kept(removed.read("models").map(lambda left: target.models - left).mass),
        taken.at("volley/heavy-casualties").read("tested").mass.get(True, 0),
        _kept(taken.at("volley/fall-back-or-flee").read("retreat").mass),
    )


@pytest.mark.parametrize("shooter", list(SHOOTERS))
def test_every_volley_agrees_with_legacy(shooter: str) -> None:
    """A champion shooting at its own Ballistic Skill is read at the unit's, as legacy is."""
    options, shooting = SHOOTERS[shooter]
    assert shooting.weapon is not None
    fielded = Fielding.of(shooting, shooting.weapon.name, options)
    if _skilled(fielded):
        fielded = _unit_skill(fielded)
    disagreements = []
    for name, (bought, target) in TARGETS.items():
        targeted = Fielding.of(target, options=bought)
        built = VOLLEY_PROGRAM.built({Side.ATTACKER: fielded, Side.TARGET: targeted})
        for moved in (False, True):
            attacker = shooting.after(Movement.march()) if moved else shooting
            profile = attacker.shooting_weapon().missile_profile
            assert profile is not None
            assert isinstance(profile.range, int)
            for distance in (profile.range // 2, profile.range):
                legacy = _legacy(attacker, target, distance)
                graph = _graph(built, attacker, target, distance)
                if graph != legacy:
                    scenario = f'{name} at {distance}"{" after moving" if moved else ""}'
                    disagreements.append(f"{scenario}: graph {graph}, legacy {legacy}")

    assert not disagreements, "\n".join(disagreements)


CHAMPIONS = [
    shooter
    for shooter, (options, shooting) in SHOOTERS.items()
    if shooting.models == shooting.unit.unit_size.min
    and shooting.weapon is not None
    and _skilled(Fielding.of(shooting, shooting.weapon.name, options))
]


@pytest.mark.parametrize("shooter", CHAMPIONS)
def test_a_champion_shoots_at_its_own_ballistic_skill(
    shooter: str, request: pytest.FixtureRequest
) -> None:
    """The champion's chance to hit bare Elven Spearmen at half range, standing still."""
    options, shooting = SHOOTERS[shooter]
    assert shooting.weapon is not None
    fielded = Fielding.of(shooting, shooting.weapon.name, options)
    (champion,) = (part for part in fielded.parts if part is not fielded.hit)
    _, spearmen = TARGETS["elven-spearmen"]
    profile = shooting.shooting_weapon().missile_profile
    assert profile is not None
    assert isinstance(profile.range, int)
    distance = profile.range // 2
    legacy = shoot_unit(shooting, spearmen, phase_rules=IN_PLAY, distance=distance)
    built = VOLLEY_PROGRAM.built({Side.ATTACKER: fielded, Side.TARGET: Fielding.of(spearmen)})
    taken = _taken(built, shooting, spearmen, distance)
    hits = taken.at(f"volley/attacker/attack/{champion.id}/roll-to-hit").read("hits").mass
    correction = CORRECTIONS[request.node.nodeid]

    assert set(hits) == {0, 1}
    assert (legacy.p_hit, hits[1]) == (correction.old, correction.new)
    assert correction.old != correction.new


def test_every_correction_pins_a_champion(request: pytest.FixtureRequest) -> None:
    module = request.node.nodeid.split("::")[0]
    test = test_a_champion_shoots_at_its_own_ballistic_skill.__name__
    pinned = {pin for pin in CORRECTIONS if pin.startswith(f"{module}::")}

    assert pinned == {f"{module}::{test}[{shooter}]" for shooter in CHAMPIONS}
