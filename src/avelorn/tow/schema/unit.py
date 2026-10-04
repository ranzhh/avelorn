"""Unit models for Warhammer: The Old World.

Profile rows are written flat under the rulebook headers (M, WS, BS,
...) so hand-authored YAML reads like the printed stat line; a
validator gathers those keys into the row's ``characteristics``
mapping, and Python code reads them through :class:`Characteristic`.
"""

from collections.abc import Iterator
from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.functional_validators import BeforeValidator

from avelorn.core.graph import Carrier, Source
from avelorn.core.registry import Registry
from avelorn.tow.schema.reference import RuleRef
from avelorn.tow.schema.troop_type import TroopTypeProfile


def _dash_to_none(value: object) -> object:
    if value == "-":
        return None
    return value


# A profile characteristic; "-" in source material means not applicable.
Stat = Annotated[int | None, BeforeValidator(_dash_to_none)]


class Characteristic(StrEnum):
    """The profile characteristics; values are the printed abbreviations.

    The single declaration of the vocabulary: profile rows are keyed by
    it, tests match on it, and rule effects will name it.
    """

    MOVEMENT = "M"
    WEAPON_SKILL = "WS"
    BALLISTIC_SKILL = "BS"
    STRENGTH = "S"
    TOUGHNESS = "T"
    WOUNDS = "W"
    INITIATIVE = "I"
    ATTACKS = "A"
    LEADERSHIP = "Ld"


class ProfileRole(StrEnum):
    """What a profile row is a row *of*.

    A datasheet's rows are not alternatives; they are the parts a model is made
    of. A Silver Helm prints three: the rider, the champion who replaces one
    rider, and the Barded Elven Steed every rider sits on. Reading any one of
    them as "the unit's profile" drops the others.

    The distinction is not cosmetic. A champion is one model of the unit
    fighting at its own line (#46); a mount is carried by *every* model and
    fights alongside it, contributing its own attacks and lending the ridden
    model its Movement. Which row is which cannot be inferred safely at the
    point of use -- a mount is recognisable only by the shape of its dashes --
    so it is recorded here, once, when the datasheet is written.
    """

    RANK_AND_FILE = "rank-and-file"
    CHAMPION = "champion"
    MOUNT = "mount"


class Profile(BaseModel):
    """One row of a characteristic profile, keyed by the printed abbreviations.

    A unit may have several rows, e.g. rank-and-file plus champion. The
    row is written flat in the printed form ({ name: ..., M: 5, ... });
    a validator gathers the abbreviation keys into ``characteristics``,
    so the vocabulary is declared once, on :class:`Characteristic`.

    ``role`` says which part of the model the row describes
    (:class:`ProfileRole`). Every row states it.

    A mount row lists its own weapons in ``equipment``. The unit's list
    holds the other rows' equipment and the mount's armour, such as barding.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    role: ProfileRole
    characteristics: dict[Characteristic, Stat]
    equipment: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _gather_printed_row(cls, data: object) -> object:
        if isinstance(data, dict) and "characteristics" not in data:
            data = dict(data)
            data["characteristics"] = {
                key: data.pop(key) for key in list(data) if key in Characteristic
            }
        return data

    @model_validator(mode="after")
    def _complete_row(self) -> Self:
        missing = [c.value for c in Characteristic if c not in self.characteristics]
        if missing:
            raise ValueError(f"profile row is missing characteristics: {missing}")
        return self

    @model_validator(mode="after")
    def _only_a_mount_lists_equipment(self) -> Self:
        if self.equipment and self.role is not ProfileRole.MOUNT:
            raise ValueError(f"{self.name}: only a mount row lists equipment")
        return self

    def __getitem__(self, characteristic: Characteristic) -> int | None:
        """The row's value for a characteristic.

        Returns:
            The characteristic's value, or None for a printed "-".
        """
        return self.characteristics[characteristic]

    def characteristic(self, c: Characteristic) -> int | None:
        """The printed value of a characteristic, as the ``Profiled`` trait reads it.

        Returns:
            The printed value, or None for a printed "-".
        """
        return self.characteristics[c]


class UnitSize(BaseModel):
    """Allowed model count for a unit."""

    model_config = ConfigDict(extra="forbid")

    min: int = Field(ge=1)
    max: int | None = Field(default=None, ge=1)  # None = no upper limit

    @model_validator(mode="after")
    def _max_not_below_min(self) -> Self:
        if self.max is not None and self.max < self.min:
            raise ValueError(f"max ({self.max}) must be >= min ({self.min})")
        return self


class BaseSize(BaseModel):
    """Base footprint of a single model, in millimetres."""

    model_config = ConfigDict(extra="forbid")

    width_mm: int = Field(ge=1)
    depth_mm: int = Field(ge=1)


class TroopType(StrEnum):
    """Closed set from the rulebook's troop-type table."""

    REGULAR_INFANTRY = "Regular Infantry"
    HEAVY_INFANTRY = "Heavy Infantry"
    MONSTROUS_INFANTRY = "Monstrous Infantry"
    SWARM = "Swarm"
    LIGHT_CAVALRY = "Light Cavalry"
    HEAVY_CAVALRY = "Heavy Cavalry"
    MONSTROUS_CAVALRY = "Monstrous Cavalry"
    WAR_BEAST = "War Beast"
    LIGHT_CHARIOT = "Light Chariot"
    HEAVY_CHARIOT = "Heavy Chariot"
    MONSTROUS_CREATURE = "Monstrous Creature"
    BEHEMOTH = "Behemoth"
    WAR_MACHINE = "War Machine"


class OptionKind(StrEnum):
    """Coarse category of a unit option."""

    CHAMPION = "champion"
    STANDARD_BEARER = "standard_bearer"
    MUSICIAN = "musician"
    EQUIPMENT = "equipment"
    SPECIAL_RULE = "special_rule"
    MAGIC_STANDARD = "magic_standard"
    OTHER = "other"


class OptionScope(StrEnum):
    """Who takes an option: the whole unit, or models of it."""

    UNIT = "unit"
    MODEL = "model"


class UnitOption(BaseModel):
    """A purchasable upgrade.

    Exactly one cost shape applies: a flat `points` cost (per unit, or per
    model when `per_model` is set) or a `points_budget` to spend up to
    (e.g. magic standards).

    `scope` says who takes the option, as the printed line's subject does.
    A champion option names its profile row in `profile`.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    kind: OptionKind = OptionKind.OTHER
    scope: OptionScope
    profile: str | None = None
    # The model the option attaches to, named as its profile row prints it
    # ("An Ironbeard may take Cinderblast Bombs" -> "Ironbeard"). None is
    # the whole unit. The Unit validator checks the name against the
    # profiles, so an option cannot attach to a model that is not there.
    applies_to: str | None = None
    points: int | None = Field(default=None, ge=0)
    per_model: bool = False
    points_budget: int | None = Field(default=None, ge=1)
    adds_rules: list[RuleRef] = Field(default_factory=list)
    removes_rules: list[RuleRef] = Field(default_factory=list)
    adds_equipment: list[str] = Field(default_factory=list)
    removes_equipment: list[str] = Field(default_factory=list)
    # Availability restriction, free text for now (e.g. "0-1 unit per
    # 1000 points"); becomes structured when the validation engine needs it.
    limit: str | None = None

    # Interim guard until cost shapes become a discriminated union.
    @model_validator(mode="after")
    def _exactly_one_cost_shape(self) -> Self:
        if (self.points is None) == (self.points_budget is None):
            raise ValueError("exactly one of points or points_budget must be set")
        if self.per_model and self.points is None:
            raise ValueError("per_model applies to points, not points_budget")
        return self

    @model_validator(mode="after")
    def _champion_names_its_row(self) -> Self:
        if (self.kind is OptionKind.CHAMPION) != (self.profile is not None):
            raise ValueError(
                f"{self.name}: only a champion option names a profile row, "
                "and every champion option must"
            )
        return self

    @model_validator(mode="after")
    def _named_model_takes_model_scope(self) -> Self:
        if self.applies_to is not None and self.scope is not OptionScope.MODEL:
            raise ValueError(f"{self.name}: an option for {self.applies_to} must have model scope")
        return self


class Unit(BaseModel):
    """A unit entry as printed in an army's list."""

    model_config = ConfigDict(extra="forbid")

    id: str  # stable slug, e.g. "elven-spearmen"
    name: str
    points: int = Field(ge=0)  # per model
    unit_size: UnitSize
    troop_type: TroopType
    # The troop type's data, resolved from the troop-type registry when the
    # repository loads the datasheet — None on a datasheet validated in
    # isolation (a raw file, the importer), where only the printed enum is
    # known. See TOWRepository.units.
    troop_type_profile: TroopTypeProfile | None = None
    base_size: BaseSize | None = None
    profiles: list[Profile] = Field(min_length=1)
    equipment: list[str] = Field(default_factory=list)
    special_rules: list[RuleRef] = Field(default_factory=list)
    options: list[UnitOption] = Field(default_factory=list)

    # An option attached to a named model needs that model's profile row:
    # "An Ironbeard may ..." is only meaningful on a datasheet printing an
    # Ironbeard.
    @model_validator(mode="after")
    def _options_attach_to_a_printed_model(self) -> Self:
        printed = {profile.name for profile in self.profiles}
        unknown = sorted(
            {
                option.applies_to
                for option in self.options
                if option.applies_to is not None and option.applies_to not in printed
            }
        )
        if unknown:
            raise ValueError(f"options attach to models with no profile: {unknown}")
        return self

    @model_validator(mode="after")
    def _one_rank_and_file_row(self) -> Self:
        roles = [p.role for p in self.profiles]
        if (count := roles.count(ProfileRole.RANK_AND_FILE)) != 1:
            raise ValueError(f"{self.name}: needs one rank-and-file row, has {count}")
        if (count := roles.count(ProfileRole.MOUNT)) > 1:
            raise ValueError(f"{self.name}: may have one mount row, has {count}")
        return self

    @model_validator(mode="after")
    def _champion_options_name_champion_rows(self) -> Self:
        champions = {p.name for p in self.profiles if p.role is ProfileRole.CHAMPION}
        named = {option.profile for option in self.options if option.profile is not None}
        if unknown := sorted(named - champions):
            raise ValueError(f"champion options name no champion row: {unknown}")
        if unnamed := sorted(champions - named):
            raise ValueError(f"no option names the champion rows: {unnamed}")
        return self

    @property
    def rank_and_file(self) -> TroopTypeProfile:
        """The troop type's data, resolved — how this unit ranks up.

        The repository attaches it when it loads the datasheet
        (:attr:`troop_type_profile`); a datasheet validated in isolation
        has none and cannot be fielded, since a body on the table must
        know how it forms ranks.

        Returns:
            The resolved troop-type profile.

        Raises:
            ValueError: the profile is unresolved — the datasheet was
                loaded outside the repository.
        """
        if self.troop_type_profile is None:
            raise ValueError(
                f"{self.name}: troop-type profile unresolved; "
                "load the datasheet through the repository"
            )
        return self.troop_type_profile

    @property
    def main(self) -> Profile:
        """The rank-and-file row -- the model the unit is bought by.

        For a single-row datasheet this is the one row; for a cavalry
        datasheet it is the rider, whose Toughness and Wounds the model
        uses, whose Weapon Skill enemy To Hit rolls are made against, and
        whose armour value the model saves on
        (troop-types-in-detail/split-profile-cavalry). Champion and mount
        rows are other parts of the unit, reached by their own accessors.

        Returns:
            The rank-and-file profile row.
        """
        return next(p for p in self.profiles if p.role is ProfileRole.RANK_AND_FILE)

    @property
    def mount(self) -> Profile | None:
        """The row for the creature every model of this unit rides, if any.

        A cavalry unit's steed: the model on the table is the rider *and*
        this. The mount supplies the model's Movement and fights beside the
        rider with its own Weapon Skill, Strength, Initiative and Attacks
        (troop-types-in-detail/split-profile-cavalry); the fight folds it in
        as a second attack batch.

        Returns:
            The mount row, or None for a unit that rides nothing.
        """
        return next((p for p in self.profiles if p.role is ProfileRole.MOUNT), None)

    @property
    def unread_rows(self) -> list[Profile]:
        """The rows the engine never reads: all but :attr:`main` and :attr:`mount`.

        Those two accessors are how the engine reads a datasheet's rows, so a
        new one (a champion's, #46) shrinks this list beside it. Characteristic
        tests read every row's Leadership (:meth:`highest`) and do not count.

        Returns:
            The profile rows nothing fights with, in printed order.
        """
        return [p for p in self.profiles if p is not self.main and p is not self.mount]

    def with_troop_type(self, troop_types: Registry[TroopTypeProfile]) -> "Unit":
        """This datasheet with its troop-type profile resolved from the registry.

        The repository calls this as it loads a unit, so the datasheet
        carries how it ranks up without a registry in hand later.

        Returns:
            A copy carrying the resolved :attr:`troop_type_profile`.
        """
        return self.model_copy(update={"troop_type_profile": troop_types.by_name(self.troop_type)})

    def sources(self) -> Iterator[tuple[RuleRef, Source]]:
        """The rules the datasheet prints, each carried by the model.

        Yields:
            The reference, and its source.
        """
        for reference in self.special_rules:
            yield reference, Source(Carrier.MODEL)

    def highest(self, characteristic: Characteristic) -> int | None:
        """The unit's highest value for a characteristic.

        The printed selection rule for tests: "where a model (or unit)
        has more than one value for the same characteristic, use the
        highest value" (model-profiles/characteristic-tests; stated for
        Leadership too).

        Returns:
            The highest value across the unit's profiles, or None when
            no profile has one.
        """
        values = [value for p in self.profiles if (value := p[characteristic]) is not None]
        return max(values) if values else None
