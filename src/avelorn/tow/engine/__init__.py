"""Phase-agnostic combat mathematics for The Old World.

The engine below the phases: the attack walk, rule compilation, casualty
folding, and armour value, on top of the pure dice mechanics in
:mod:`avelorn.tow.kernels`. These know nothing of the on-field
:class:`~avelorn.tow.contingent.Contingent`, of a phase, or of a result type —
they operate on profiles and numbers. The per-phase resolution
(:mod:`avelorn.tow.phases`) is built on top of them.
"""
