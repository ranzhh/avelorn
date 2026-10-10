"""One volley of shooting, resolved on the graph."""

from collections.abc import Hashable
from dataclasses import dataclass
from fractions import Fraction

from avelorn.core.distribution import Distribution, Probability
from avelorn.core.graph import Verdict
from avelorn.tow.contingent import Contingent
from avelorn.tow.fielding import Fielding
from avelorn.tow.kernels import Standings
from avelorn.tow.programs import Evaluated, Loaded
from avelorn.tow.schema.side import Side
from avelorn.tow.steps import NO_ROLL, Retreat


@dataclass(frozen=True)
class Volley:
    """A volley's lane in which every rule the players may decline is taken."""

    evaluated: Evaluated
    shooter: Fielding
    target_models: int

    def _read(self, path: str, reading: str) -> Distribution[Hashable]:
        return self.evaluated.at(f"{self.evaluated.lane.program.name}/{path}").read(reading)

    def _fired(self, step: str) -> str:
        return f"attacker/attack/{self.shooter.hit.id}/{step}"

    @property
    def shots(self) -> int:
        """The shots fired."""
        (shots,) = self._read("how-many-shots", "shots").mass
        return _count(shots)

    @property
    def unsaved(self) -> Distribution[int]:
        """The unsaved wounds."""
        return self._read("remove-casualties", "unsaved").map(_count)

    @property
    def casualties(self) -> Distribution[int]:
        """The models removed."""
        left = self._read("remove-casualties", "models").map(_count)
        return left.map(lambda standing: self.target_models - standing)

    @property
    def standing(self) -> Distribution[Standings]:
        """What is left of each part of the target, as a Stand & Shoot shows it."""
        return self._read("remove-casualties", "standing").map(_standings)

    @property
    def p_unsaved(self) -> Probability:
        """The chance one shot wounds and goes unsaved."""
        if self.shots == 0:
            return Fraction(0)
        return self.unsaved.expect(Fraction) / self.shots

    @property
    def tested(self) -> Probability:
        """The chance the target takes a Panic test."""
        return self._read("heavy-casualties", "tested").mass.get(True, Fraction(0))

    @property
    def retreat(self) -> Distribution[Retreat]:
        """What the target does after its Panic test."""
        return self._read("fall-back-or-flee", "retreat").map(_retreat)

    def needed(self, step: str) -> str:
        """The score the rank and file's roll needs at a step, across the volley.

        Returns:
            Each score in force, joined with "or".
        """
        mass = self._read(self._fired(step), "needed").mass
        shown = {score for value in mass for score in str(value).split(" or ")}
        return " or ".join(sorted(shown, key=lambda score: (score == NO_ROLL, score)))

    def applied(self, path: str) -> tuple[str, ...]:
        """The rules applied at a step in some world of the volley.

        Returns:
            Their names, sorted.
        """
        lane = self.evaluated.lane
        at = self.evaluated.at(path).step
        return tuple(
            sorted(
                node.name
                for node in lane.program.rules.values()
                if any(landing.at is at for landing in node.landings)
                and lane.verdicts(node.id, at).mass.get(Verdict.APPLIED)
            )
        )

    @property
    def held(self) -> tuple[str, ...]:
        """The rules the volley holds without applying: no landing, or held at every one."""
        return self.evaluated.held


def _count(value: Hashable) -> int:
    if not isinstance(value, int):
        raise TypeError(f"{value!r} is no count")
    return value


def _retreat(value: Hashable) -> Retreat:
    if not isinstance(value, Retreat):
        raise TypeError(f"{value!r} is no retreat")
    return value


def _standings(value: Hashable) -> Standings:
    if not isinstance(value, Standings):
        raise TypeError(f"{value!r} is no standing")
    return value


def fire(
    loaded: Loaded,
    shooter: Contingent,
    target: Contingent,
    *,
    distance: int,
    shooter_options: tuple[str, ...] = (),
    target_options: tuple[str, ...] = (),
    battle_strength: int | None = None,
) -> Volley:
    """Shoot one contingent at another with the weapon in hand.

    The shooter moved when its movement says so. ``battle_strength`` is the
    target's size at the start of the battle; it defaults to the size it is
    shot at.

    Returns:
        The volley's lane in which every rule the players may decline is taken.
    """
    weapon = shooter.shooting_weapon()
    fielded = {
        Side.ATTACKER: Fielding.of(shooter, weapon.name, shooter_options),
        Side.TARGET: Fielding.of(target, options=target_options),
    }
    built = loaded.built(fielded)
    lanes = built.evaluate(
        {
            "distance": distance,
            "can-shoot": True,
            "line-of-sight": True,
            "attacker/moved": shooter.movement.moved,
            "attacker/standing": fielded[Side.ATTACKER].standing(shooter.models),
            "target/standing": fielded[Side.TARGET].standing(target.models),
            "target/models-at-start-of-phase": target.models,
            "target/battle-strength": battle_strength or target.models,
        }
    )
    (taken,) = (evaluated for evaluated in lanes if not evaluated.lane.out)
    return Volley(taken, fielded[Side.ATTACKER], target.models)


def stand_and_shoot(loaded: Loaded, shooter: Contingent, charger: Contingent) -> Volley:
    """The charged unit shoots the charger as it closes, with the missile weapon it fires.

    The volley is at no range, and the charger is fielded as the round of
    combat will field it, so what is left of it starts the round.

    Returns:
        The volley's lane in which every rule the players may decline is taken.
    """
    weapon = shooter.shooting_weapon()
    fielded = {
        Side.ATTACKER: Fielding.of(shooter, weapon.name),
        Side.TARGET: Fielding.of(charger, combat=True),
    }
    lanes = loaded.built(fielded).evaluate(
        {
            "distance": 0,
            "can-shoot": True,
            "line-of-sight": True,
            "attacker/moved": shooter.movement.moved,
            "attacker/standing": fielded[Side.ATTACKER].standing(shooter.models),
            "target/standing": fielded[Side.TARGET].standing(charger.models),
        }
    )
    (taken,) = (evaluated for evaluated in lanes if not evaluated.lane.out)
    return Volley(taken, fielded[Side.ATTACKER], charger.models)
