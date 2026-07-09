"""The engine's error family."""

from avelorn.core.errors import AvelornError, UnmodelledRuleError
from avelorn.core.registry import UnknownNameError


def test_engine_errors_are_one_family() -> None:
    """Every engine error is catchable as AvelornError.

    UnknownNameError keeps LookupError for its callers; the family
    membership is additional, not a replacement.
    """
    assert issubclass(UnmodelledRuleError, AvelornError)
    assert issubclass(UnknownNameError, AvelornError)
    assert issubclass(UnknownNameError, LookupError)
