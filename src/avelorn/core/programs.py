"""Small graph programs used to exercise the graph surface."""

from fractions import Fraction

from avelorn.core.distribution import Distribution, Monoid
from avelorn.core.graph import (
    Bearer,
    Consequence,
    Decision,
    Landing,
    Lanes,
    Measurement,
    Program,
    Projection,
    Repeat,
    Roll,
    RuleNode,
    Scalar,
    Side,
    Verdict,
)


def volley_program() -> dict[str, object]:
    """Build and evaluate the small volley shown by the graph frontend.

    This is deliberately hand-authored while program loading is still a later
    layer. It exercises the same graph contract as a loaded program: a count,
    a repeated attack, a decision lane, readings, and rule landings.

    Returns:
        The evaluated graph in the frontend's JSON-compatible shape.
    """

    def d6(_range: str) -> Distribution[int]:
        return Distribution({face: Fraction(1, 6) for face in range(1, 7)})

    def wound(hit: int) -> Distribution[int]:
        return Distribution.pure(int(hit >= 4))

    def casualties(range_band: str) -> Distribution[int]:
        return Distribution.pure(1 if range_band == "close" else 0)

    shots = Measurement[int](
        name="shots", side=Side.THIS_MODEL, kernel=lambda: Distribution.pure(3)
    )
    range_band = Decision[str](
        name="choose-range", side=Side.THIS_MODEL, options=("close", "long")
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
        inputs=(range_band,),
        kernel=casualties,
    )

    hit.show(
        Projection(
            "hits",
            lambda world: int(world.of(hit) >= 4),
            Monoid(0),
        )
    )
    wound_roll.show(wound_roll.output("wounds", Monoid(0)))
    remove.show(Scalar("models", 5))

    program = Program.build(
        "volley",
        {
            Side.THIS_MODEL: "the archers",
            Side.THE_ENEMY: "the spearmen",
        },
        (
            shots,
            range_band,
            # The group retains one attack's joint distribution and the
            # reading stacks it three times when the edge is read.
            Repeat(name="attack", times=shots, items=(hit, wound_roll)),
            Lanes(name="aftermath", decision=range_band, items=(remove,)),
        ),
    )
    program.attach(
        RuleNode(
            rule="volley-fire",
            name="Volley Fire",
            bearer=Bearer.THIS_MODEL,
            landings=(Landing(hit, Verdict.APPLIED), Landing(remove, Verdict.HONOURED)),
        )
    )

    (lane,) = program.evaluate(choices={range_band: "close"})
    return lane.to_view()
