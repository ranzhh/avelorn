"""The engine's own error vocabulary.

One family, so callers can catch engine errors as a class apart from
Python's own. The tenet behind ``UnmodelledRuleError``: where degrading
to an unfactored note would resolve the *wrong game*, the engine
refuses loudly instead — a note can honestly report a modifier the
math skipped, but not a whole action that never happened.
"""


class AvelornError(Exception):
    """Base of the engine's own errors."""


class UnmodelledRuleError(AvelornError):
    """A printed rule, reaction, or option the engine recognises but has not modelled.

    Raised at the point of use: the vocabulary declares the printed
    member (a closed vocabulary is supplied exhaustively), and asking
    the engine to resolve it is refused until it is modelled.
    """
