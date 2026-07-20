"""The troop-type table: each troop type's rank-and-file data.

One entry per troop type from the rulebook's troop-type table
(troop-types-at-a-glance/troop-type-table), hand-authored under
``data/tow/troop-types/`` and loaded into a registry keyed by troop type.
The :class:`~avelorn.tow.schema.unit.TroopType` enum is the closed
vocabulary a datasheet is validated against; this is the data hanging off
each member — how it ranks up, the special rules it confers, and its base
size in time.
"""

from pydantic import BaseModel, ConfigDict, Field


class TroopTypeProfile(BaseModel):
    """A troop type's rank-and-file data, and how it ranks up.

    ``models_per_rank`` is how many models a rank must hold to count
    toward the Rank Bonus, or None for a troop type that does not rank up
    (Swarm, Heavy Chariot, the monsters and war machines that fight as
    single models); ``max_rank_bonus`` is the most extra ranks it may
    claim. ``special_rules`` are the rules the troop type confers on every
    unit of it (Regular Infantry's Press of Battle, say), as printed
    display-name strings — the type's own rules, held apart from the
    datasheet's ``special_rules`` because their owner is the troop type,
    not the unit.
    """

    model_config = ConfigDict(extra="forbid")

    id: str  # stable slug, e.g. "regular-infantry"
    name: str  # display name, matching the TroopType value ("Regular Infantry")
    models_per_rank: int | None = Field(default=None, ge=1)
    max_rank_bonus: int = Field(default=0, ge=0)
    special_rules: tuple[str, ...] = ()

    def default_frontage(self, models: int) -> int:
        """The width this troop type ranks up at when none is chosen.

        Its minimum rankable width, so a unit is wide enough to claim a
        Rank Bonus; a troop type that does not rank up stands in a single
        rank of all its models.

        Returns:
            The default formation width in models.
        """
        return self.models_per_rank if self.models_per_rank is not None else max(models, 1)
