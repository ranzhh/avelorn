"""Small graph programs used to exercise the graph surface."""

from fractions import Fraction

from avelorn.core.distribution import Distribution, Monoid
from avelorn.core.graph import (
    Bearer,
    Consequence,
    Landing,
    Measurement,
    Program,
    Projection,
    Repeat,
    Roll,
    RuleNode,
    Scalar,
    Sequence,
    Side,
    Verdict,
)


def volley_program() -> dict[str, object]:
    """Build and evaluate the small volley shown by the graph frontend.

    This is deliberately hand-authored while program loading is still a later
    layer. It exercises the graph contract with explicit measurements for the
    units, formation, distance, and weapon range. The shooting rules remain
    placeholders rather than the production volley resolver.

    Returns:
        The evaluated graph in the frontend's JSON-compatible shape.
    """

    def certain(value: int) -> Distribution[int]:
        return Distribution.pure(value)

    def check_range(distance: int, weapon_range: int) -> Distribution[str]:
        return Distribution.pure("long" if distance > weapon_range / 2 else "close")

    def how_many_shots(models: int, frontage: int) -> Distribution[int]:
        return Distribution.pure(min(models, frontage))

    def d6(_range: str) -> Distribution[int]:
        return Distribution({face: Fraction(1, 6) for face in range(1, 7)})

    def wound(hit: int) -> Distribution[int]:
        return Distribution.pure(int(hit >= 4))

    def casualties(range_band: str, target_models: int) -> Distribution[int]:
        return Distribution.pure(int(range_band == "close" and target_models > 0))

    def panic(removed: int) -> Distribution[str]:
        return Distribution.pure("flight" if removed else "holds")

    attacker_models = Measurement[int](
        name="models", side=Side.THIS_MODEL, kernel=lambda: certain(10)
    )
    attacker_frontage = Measurement[int](
        name="frontage", side=Side.THIS_MODEL, kernel=lambda: certain(5)
    )
    target_models = Measurement[int](
        name="target-models", side=Side.THE_ENEMY, kernel=lambda: certain(20)
    )
    distance = Measurement[int](name="distance", side=Side.THIS_MODEL, kernel=lambda: certain(12))
    weapon_range = Measurement[int](
        name="weapon-range", side=Side.THIS_MODEL, kernel=lambda: certain(24)
    )
    range_band = Measurement[str](
        name="range",
        side=Side.THIS_MODEL,
        inputs=(distance, weapon_range),
        kernel=check_range,
    )
    shots = Measurement[int](
        name="shots",
        side=Side.THIS_MODEL,
        inputs=(attacker_models, attacker_frontage),
        kernel=how_many_shots,
    )
    hit = Roll[int](
        name="roll-to-hit",
        side=Side.THIS_MODEL,
        inputs=(range_band,),
        kernel=d6,
        target=Scalar("to hit", 4),
    )
    wound_roll = Roll[int](
        name="roll-to-wound",
        side=Side.THIS_MODEL,
        inputs=(hit,),
        kernel=wound,
        target=Scalar("to wound", 4),
    )
    remove = Consequence[int](
        name="remove-casualties",
        side=Side.THE_ENEMY,
        inputs=(range_band, target_models),
        kernel=casualties,
    )
    flight = Consequence[str](
        name="panic-flight",
        side=Side.THE_ENEMY,
        inputs=(remove,),
        kernel=panic,
    )

    attacker_models.show(attacker_models.output("models", Monoid(0)))
    attacker_frontage.show(attacker_frontage.output("frontage", Monoid(0)))
    target_models.show(target_models.output("target", Monoid(0)))
    distance.show(distance.output("distance", Monoid(0)))
    weapon_range.show(weapon_range.output("range", Monoid(0)))
    range_band.show(Projection("range", lambda world: world.of(range_band), Monoid("unknown")))
    shots.show(shots.output("shots", Monoid(0)))
    hit.show(
        Projection(
            "hits",
            lambda world: int(world.of(hit) >= 4),
            Monoid(0),
        )
    )
    wound_roll.show(wound_roll.output("wounds", Monoid(0)))
    remove.show(remove.output("casualties", Monoid(0)))
    flight.show(flight.output("panic", Monoid("unknown")))

    program = Program.build(
        "volley",
        {
            Side.THIS_MODEL: "Archers",
            Side.THE_ENEMY: "Spearmen",
        },
        (
            Sequence(
                name="pre-volley",
                items=(
                    attacker_models,
                    attacker_frontage,
                    target_models,
                    distance,
                    weapon_range,
                    range_band,
                    shots,
                ),
            ),
            Sequence(
                name="volley",
                items=(Repeat(name="attack", times=shots, items=(hit, wound_roll)),),
            ),
            Sequence(name="result", items=(remove, flight)),
        ),
    )
    program.attach(
        RuleNode(
            rule="volley-fire",
            name="Volley Fire (mock metadata only)",
            bearer=Bearer.THIS_MODEL,
            landings=(Landing(shots, Verdict.HELD),),
        )
    )

    (lane,) = program.evaluate()
    return lane.to_view()
