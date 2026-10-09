"""Changes a rule lands on a step."""

from avelorn.tow.changes import Gate, Granted, Operated, Sources
from avelorn.tow.data import TOWRepository
from avelorn.tow.schema.effect import Cancels, Effect, Operation
from avelorn.tow.schema.quantity import Quantity

REPO = TOWRepository()


def _effect(rule: str, index: int) -> Effect:
    graph = REPO.rules[rule].graph
    assert graph is not None
    return graph.effects[index]


def _operated(rule: str, effect: Effect, key: Quantity | None) -> Operated:
    return Operated(rule, effect, key, None, Gate(), Sources((Granted(None, None),)), None)


def test_a_cancel_of_one_quantity_spares_the_rest_of_an_add() -> None:
    added = {Quantity.ARMOUR_PIERCING: 1, Quantity.ARMOUR_VALUE: 1}
    both = _effect("arrows-of-isha", 0).model_copy(update={"add": added})
    named = Cancels(op=Operation.ADD, quantity=Quantity.ARMOUR_VALUE)
    cancel = _effect("abyssal-cloak", 1).model_copy(update={"cancels": named})
    canceller = _operated("abyssal-cloak", cancel, None)

    assert {key: canceller.cancels(_operated("arrows-of-isha", both, key)) for key in added} == {
        Quantity.ARMOUR_PIERCING: False,
        Quantity.ARMOUR_VALUE: True,
    }
