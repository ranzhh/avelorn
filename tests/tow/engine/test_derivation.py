"""The To Hit ledger: that its lines name what moved the roll, and that they sum."""

from avelorn.tow.engine.attack import Modifier
from avelorn.tow.engine.derivation import hit_derivation
from avelorn.tow.schema.rule import NaturalRoll
from avelorn.tow.schema.stage import Stage


def _to_hit(move: int, source: str | None = None, trigger: NaturalRoll | None = None) -> Modifier:
    # A compiled record landing on the To Hit roll, as the rules compiler emits it.
    return Modifier(lands_on=Stage.ROLL_TO_HIT, move=move, trigger=trigger, source=source)


def _ledger(reported: int, situational: int = 0, *modifiers: Modifier):
    # The archers' chart value throughout: BS 4 gives 3+.
    return hit_derivation(
        base=3, basis="BS 4", reported=reported, situational=situational, modifiers=modifiers
    )


def test_no_modifier_leaves_the_chart_value_standing() -> None:
    """Nothing moved the roll, so the ledger has no steps to show."""
    ledger = _ledger(3)
    assert ledger.steps == ()
    assert ledger.target == ledger.base == 3


def test_the_callers_own_modifier_leads_the_ledger() -> None:
    """Cover is folded into the chart lookup before the walk runs, so it is step one."""
    ledger = _ledger(5, -1, _to_hit(1, "Firing at Long Range"))
    assert [(step.source, step.modifier, step.target) for step in ledger.steps] == [
        ("situational", -1, 4),
        ("Firing at Long Range", -1, 5),
    ]


def test_a_step_reads_in_the_printed_sign_convention() -> None:
    """A record raising the target by one is a printed -1 To Hit."""
    ledger = _ledger(4, 0, _to_hit(1, "Moving and Shooting"))
    assert ledger.steps[0].modifier == -1
    assert ledger.steps[0].target == 4


def test_a_modifier_riding_a_natural_face_is_left_out() -> None:
    """It applies on that face alone, so it is no part of the printed target."""
    trigger = NaturalRoll(roll=Stage.ROLL_TO_WOUND, face=6)
    assert _ledger(3, 0, _to_hit(1, "Armour Bane", trigger=trigger)).steps == ()


def test_a_target_the_steps_do_not_reach_becomes_an_unattributed_step() -> None:
    """A bespoke hook moved the roll; the ledger says so rather than not summing."""
    ledger = _ledger(5)
    assert [(step.source, step.modifier) for step in ledger.steps] == [(None, -2)]
    assert ledger.steps[-1].target == ledger.target == 5


def test_every_ledger_ends_on_the_target_it_explains() -> None:
    """Whatever the mix of steps, the last line is the number the ledger is for."""
    cases = (
        (3, 0, ()),
        (5, -2, ()),
        (5, -1, (_to_hit(1, "Firing at Long Range"),)),
        (5, 0, (_to_hit(1, "a"), _to_hit(1, "b"))),
    )
    for reported, situational, records in cases:
        ledger = _ledger(reported, situational, *records)
        standing = ledger.steps[-1].target if ledger.steps else ledger.base
        assert standing == reported
