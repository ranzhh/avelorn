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

from avelorn.tow.schema.unit_strength import UnitStrength


class TroopTypeProfile(BaseModel):
    """A troop type's rank-and-file data, and how it ranks up.

    ``models_per_rank`` is how many models a rank must hold to count
    toward the Rank Bonus, or None for a troop type that does not rank up
    (Swarm, Heavy Chariot, the monsters and war machines that fight as
    single models); ``max_rank_bonus`` is the most extra ranks it may
    claim. ``unit_strength`` is each model's Unit Strength as the
    troop-type table prints it — a fixed count, or "As Starting Wounds"
    for the troop types whose strength scales with the model.
    ``special_rules`` are the rules the troop type confers on every
    unit of it (Regular Infantry's Press of Battle, say), as printed
    display-name strings — the type's own rules, held apart from the
    datasheet's ``special_rules`` because their owner is the troop type,
    not the unit.
    """

    model_config = ConfigDict(extra="forbid")

    id: str  # stable slug, e.g. "regular-infantry"
    name: str  # display name, matching the TroopType value ("Regular Infantry")
    unit_strength: UnitStrength
    models_per_rank: int | None = Field(default=None, ge=1)
    max_rank_bonus: int = Field(default=0, ge=0)
    special_rules: tuple[str, ...] = ()

    def unit_strength_per_model(self, wounds: int | None) -> int:
        """This troop type's Unit Strength for one model of ``wounds`` Wounds.

        A fixed count for most troop types; the model's starting Wounds for
        the ones the table prints as "As Starting Wounds" (Monstrous
        Creatures, Behemoths, War Machines) — where a profile with no
        printed Wounds counts as one, as the wound rules treat it.

        Returns:
            The per-model Unit Strength.
        """
        if isinstance(self.unit_strength, int):
            return self.unit_strength
        return wounds or 1  # AS_STARTING_WOUNDS

    def default_frontage(self, models: int) -> int:
        """The width this troop type ranks up at when none is chosen.

        Its minimum rankable width, so a unit is wide enough to claim a
        Rank Bonus; a troop type that does not rank up stands in a single
        rank of all its models.

        Returns:
            The default formation width in models.
        """
        return self.models_per_rank if self.models_per_rank is not None else max(models, 1)
