"""Every corpus volley on both engines."""

from collections.abc import Hashable, Mapping
from typing import NamedTuple

import pytest

from avelorn.core.distribution import Distribution, Probability
from avelorn.tow.contingent import Contingent, Movement
from avelorn.tow.coverage import fieldings
from avelorn.tow.data import TOWRepository
from avelorn.tow.game import TOWGame
from avelorn.tow.kernels import Standing
from avelorn.tow.phases.shooting import make_panic_tests, shoot_unit
from avelorn.tow.programs import VOLLEY, load_program
from avelorn.tow.schema.phase import Phase
from avelorn.tow.steps import Fielded, Retreat

REPO = TOWRepository()
IN_PLAY = TOWGame.assemble(REPO).in_play[Phase.SHOOTING]
VOLLEY_PROGRAM = load_program(VOLLEY, REPO.rules)


class Outcome(NamedTuple):
    """What one volley ends in, as both engines report it."""

    shots: int
    unsaved: Mapping[int, Probability]
    casualties: Mapping[int, Probability]
    tested: Probability
    retreat: Mapping[Retreat, Probability]


def _kept[T: Hashable](mass: Mapping[T, Probability]) -> dict[T, Probability]:
    return {value: p for value, p in mass.items() if p}


def _fielded(fielded: Fielded, models: int) -> str:
    parts = (fielded.part, fielded.row, fielded.frontage, fielded.weapon, fielded.armour)
    return repr((*parts, fielded.ward, fielded.wielded, fielded.carried, models))


def _name(slug: str, options: tuple[str, ...]) -> str:
    return "+".join((slug, *(option.lower().replace(" ", "-") for option in options)))


def _sizes(contingent: Contingent, options: tuple[str, ...]) -> tuple[Contingent, ...]:
    size = contingent.unit.unit_size
    if size.max is not None and size.max < 2 * size.min:
        return (contingent,)
    return contingent, Contingent.deploy(contingent.unit.id, 2 * size.min, options, data=REPO)


def _distinct() -> tuple[dict[str, Contingent], dict[str, Contingent]]:
    shooters: dict[str, tuple[str, Contingent]] = {}
    targets: dict[str, tuple[str, Contingent]] = {}
    for options, contingent in fieldings(REPO):
        name = _name(contingent.unit.id, options)
        targets.setdefault(_fielded(Fielded.of(contingent), contingent.models), (name, contingent))
        for fielding in _sizes(contingent, options):
            for weapon in fielding.loadout.weapons:
                if weapon.missile_profile is not None:
                    armed = fielding.wielding(weapon.name)
                    fielded = Fielded.of(armed, weapon.name)
                    shooters.setdefault(
                        _fielded(fielded, armed.models),
                        (f"{name}/{weapon.id}/{armed.models}", armed),
                    )
    return dict(shooters.values()), dict(targets.values())


SHOOTERS, TARGETS = _distinct()


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


def _graph(attacker: Contingent, target: Contingent, distance: int) -> Outcome:
    assert attacker.weapon is not None
    lanes = VOLLEY_PROGRAM.evaluate(
        {
            "attacker/fielded": Fielded.of(attacker, attacker.weapon.name),
            "target/fielded": Fielded.of(target),
            "distance": distance,
            "can-shoot": True,
            "line-of-sight": True,
            "attacker/moved": attacker.movement.moved,
            "attacker/standing": Standing(attacker.models, 0),
            "target/standing": Standing(target.models, 0),
            "target/models-at-start-of-phase": target.models,
            "target/battle-strength": target.models,
        }
    )
    (taken,) = (
        evaluated
        for evaluated in lanes
        if all(
            evaluated.lane.choices[toggle] for toggle in evaluated.lane.program.toggles.values()
        )
    )
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
    disagreements = []
    for name, target in TARGETS.items():
        for moved in (False, True):
            attacker = SHOOTERS[shooter]
            if moved:
                attacker = attacker.after(Movement.march())
            profile = attacker.shooting_weapon().missile_profile
            assert profile is not None
            assert isinstance(profile.range, int)
            for distance in (profile.range // 2, profile.range):
                legacy = _legacy(attacker, target, distance)
                graph = _graph(attacker, target, distance)
                if graph != legacy:
                    scenario = f'{name} at {distance}"{" after moving" if moved else ""}'
                    disagreements.append(f"{scenario}: graph {graph}, legacy {legacy}")

    assert not disagreements, "\n".join(disagreements)
