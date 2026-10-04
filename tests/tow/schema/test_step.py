"""The printed step vocabulary against the steps the engine registers."""

from avelorn.tow.schema.step import Step, StepKind
from avelorn.tow.steps import STEPS


def test_every_registered_step_is_printed_in_its_sequence() -> None:
    """A registered step is a printed step of the sequence it is filed under, of its kind."""
    for (sequence, name), spec in STEPS.items():
        printed = Step(name)
        assert sequence in printed.sequences, f"{name} is not printed in {sequence}"
        assert printed.kind == StepKind(spec.kind), f"{name} is printed as a {printed.kind}"
