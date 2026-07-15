"""Phase-agnostic combat mathematics for The Old World.

The engine below the phases: the attack walk, the roll-target charts, rule
compilation, characteristic tests, casualty folding, and armour value. These
know nothing of the on-field :class:`~avelorn.tow.contingent.Contingent`, of a
phase, or of a result type — they operate on profiles and numbers. The
per-phase resolution (:mod:`avelorn.tow.phases`) is built on top of them.
"""
