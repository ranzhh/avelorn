"""The engine's own error vocabulary.

One family, so callers can catch engine errors as a class apart from
Python's own. The tenet behind ``UnmodelledRuleError``: where leaving a
rule out would resolve the *wrong game*, a whole action that never
happened, the engine refuses loudly instead.
"""


class AvelornError(Exception):
    """Base of the engine's own errors."""


class UnmodelledRuleError(AvelornError):
    """A printed rule, reaction, or option the engine recognises but has not modelled.

    Raised at the point of use: the vocabulary declares the printed
    member (a closed vocabulary is supplied exhaustively), and asking
    the engine to resolve it is refused until it is modelled.
    """
