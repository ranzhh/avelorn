"""Fielded sides, made of parts."""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import NamedTuple

from avelorn.core.graph import Source
from avelorn.tow.contingent import Contingent
from avelorn.tow.engine.armour import defender_armour
from avelorn.tow.schema.reference import RuleRef, slugified
from avelorn.tow.schema.unit import Characteristic, Profile, ProfileRole
from avelorn.tow.schema.weapon import Weapon, WeaponProfile
from avelorn.tow.traits import Carries


@dataclass(frozen=True, eq=False)
class Part:
    """The models of a side that share a profile row and a loadout."""

    id: str
    row: Profile
    count: int
    weapon: WeaponProfile | None = None
    wielded: Weapon | None = None
    armour: int | None = None
    ward: int | None = None
    carried: tuple[tuple[RuleRef, Source], ...] = ()

    def characteristic(self, c: Characteristic) -> int | None:
        """The part's printed value for a characteristic.

        Returns:
            The printed value, or None for a printed "-".
        """
        return self.row.characteristic(c)

    def sources(self) -> Iterator[tuple[RuleRef, Source]]:
        """The rules the part carries, with what gives each.

        Yields:
            The reference, and its source.
        """
        yield from self.carried


class Shots(NamedTuple):
    """The shots each part fires."""

    parts: tuple[tuple[str, int], ...]

    @property
    def total(self) -> int:
        """Every part's shots together."""
        return sum(count for _, count in self.parts)

    def of(self, part: str) -> int:
        """The shots one part fires.

        Returns:
            Its shots.
        """
        return dict(self.parts)[part]

    def __str__(self) -> str:
        """Each part's shots, as text.

        Returns:
            The shots per part.
        """
        return ", ".join(f"{part} {count}" for part, count in self.parts)


@dataclass(frozen=True, eq=False)
class Fielding:
    """A side on the table: its parts in placement order, front to back."""

    unit: str
    parts: tuple[Part, ...]
    frontage: int

    def __post_init__(self) -> None:
        """Refuse a fielding that cannot stand.

        Raises:
            ValueError: the fielding has no rank-and-file part, repeats a part, or has no frontage.
        """
        ids = [part.id for part in self.parts]
        if len(set(ids)) != len(ids):
            raise ValueError(f"{self.unit} fields a part twice")
        if not any(part.row.role is ProfileRole.RANK_AND_FILE for part in self.parts):
            raise ValueError(f"{self.unit} fields no rank and file")
        if self.frontage < 1:
            raise ValueError(f"{self.unit} stands with no frontage")

    @property
    def hit(self) -> Part:
        """The part a model hit belongs to: the first rank and file in placement order."""
        return next(part for part in self.parts if part.row.role is ProfileRole.RANK_AND_FILE)

    def part(self, id: str) -> Part:
        """The part with an id.

        Returns:
            The part.

        Raises:
            KeyError: no part has that id.
        """
        for part in self.parts:
            if part.id == id:
                return part
        raise KeyError(f"{self.unit} fields no part {id}")

    def sources(self) -> Iterator[tuple[RuleRef, Source]]:
        """The rules every part of the side carries, with what gives each.

        Yields:
            The reference, and its source.
        """
        for part in self.parts:
            yield from part.sources()

    def standing(self, models: int) -> tuple[tuple[Part, int], ...]:
        """Each part's models still standing, casualties taken off the back.

        Returns:
            Each part with its standing models, in placement order.
        """
        lost = sum(part.count for part in self.parts) - models
        left: list[tuple[Part, int]] = []
        for part in reversed(self.parts):
            taken = min(lost, part.count)
            lost -= taken
            left.append((part, part.count - taken))
        return tuple(reversed(left))

    def highest(self, c: Characteristic, models: int) -> int | None:
        """The highest value of a characteristic among the parts still standing.

        Returns:
            The highest printed value, or None when every standing part prints "-".
        """
        values = [
            value
            for part, count in self.standing(models)
            if count and (value := part.characteristic(c)) is not None
        ]
        return max(values, default=None)

    @classmethod
    def of(cls, contingent: Contingent, weapon: str | None = None) -> "Fielding":
        """Field a contingent as its rank and file.

        The armour value folds from the armour worn. A ward comes only from rules,
        so a part fielded from the corpus has none. The part carries the rules of
        its datasheet, its troop type, and the profile its weapon shoots with.

        Returns:
            The fielded side.

        Raises:
            ValueError: ``weapon`` has no missile profile.
        """
        unit = contingent.unit
        carriers: tuple[Carries, ...] = (unit, unit.rank_and_file)
        carried = [pair for carrier in carriers for pair in carrier.sources()]
        wielded = profile = None
        if weapon is not None:
            wielded = contingent.loadout.weapon(weapon)
            profile = wielded.missile_profile
            if profile is None:
                raise ValueError(f"{weapon} has no missile profile; it cannot shoot")
            shot = profile.name or wielded.name
            carried += [pair for pair in wielded.sources() if pair[1].profile == shot]
        part = Part(
            id=slugified(unit.main.name),
            row=unit.main,
            count=contingent.models,
            weapon=profile,
            wielded=wielded,
            armour=defender_armour(contingent.loadout.armour),
            carried=tuple(carried),
        )
        return cls(unit.id, (part,), contingent.frontage)
