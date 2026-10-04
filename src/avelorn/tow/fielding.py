"""Fielded sides, made of parts."""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import NamedTuple

from avelorn.core.graph import Source
from avelorn.tow.contingent import Contingent
from avelorn.tow.engine.armour import defender_armour
from avelorn.tow.kernels import Standing, Standings
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
            The reference, and its source, in the first part's order.
        """
        first, *rest = self.parts
        shared = [set(part.sources()) for part in rest]
        for pair in first.sources():
            if all(pair in each for each in shared):
                yield pair

    @property
    def removal(self) -> tuple[tuple[str, int], ...]:
        """Each part with its Wounds per model, in the order casualties come off.

        Casualties come off the back of the placement, and a champion falls last.

        Raises:
            ValueError: a part prints no Wounds.
        """
        rank_and_file = [part for part in self.parts if part.row.role is not ProfileRole.CHAMPION]
        champions = [part for part in self.parts if part.row.role is ProfileRole.CHAMPION]
        order = []
        for part in (*reversed(rank_and_file), *reversed(champions)):
            wounds = part.characteristic(Characteristic.WOUNDS)
            if wounds is None:
                raise ValueError(f"{part.id} prints no Wounds")
            order.append((part.id, wounds))
        return tuple(order)

    def standing(self, models: int) -> Standings:
        """The side with ``models`` standing, the rest taken off as casualties fall.

        Returns:
            Each part's standing.

        Raises:
            ValueError: more models stand than the side fields.
        """
        fielded = sum(part.count for part in self.parts)
        if models > fielded:
            raise ValueError(f"{self.unit} fields {fielded} models, not {models}")
        counts = {part.id: part.count for part in self.parts}
        lost = fielded - models
        for part, _ in self.removal:
            taken = min(lost, counts[part])
            counts[part] -= taken
            lost -= taken
        return Standings(tuple((part.id, Standing(counts[part.id], 0)) for part in self.parts))

    def highest(self, c: Characteristic, standings: Standings) -> int | None:
        """The highest value of a characteristic among the parts still standing.

        Returns:
            The highest printed value, or None when every standing part prints "-".
        """
        values = [
            value
            for part in self.parts
            if standings.of(part.id).models and (value := part.characteristic(c)) is not None
        ]
        return max(values, default=None)

    @classmethod
    def of(
        cls, contingent: Contingent, weapon: str | None = None, options: tuple[str, ...] = ()
    ) -> "Fielding":
        """Field a contingent as its rank and file, with a champion part for each champion bought.

        ``options`` are the options the contingent was mustered with. A champion
        stands in the front rank, so its part is placed first
        (command-groups/position-within-the-unit). Every part carries the unit's
        equipment and rules. The armour value folds from the armour worn. A ward
        comes only from rules, so a part fielded from the corpus has none. A part
        carries the rules of its datasheet, its troop type, and the profile its
        weapon shoots with.

        Returns:
            The fielded side.

        Raises:
            ValueError: ``weapon`` has no missile profile, or an option is not offered.
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
        offered = {option.name: option for option in unit.options}
        unknown = [name for name in options if name not in offered]
        if unknown:
            raise ValueError(f"{unit.id} offers no option {', '.join(unknown)}")
        rows = {row.name: row for row in unit.profiles}
        champions = [
            rows[profile_name]
            for name in options
            if (profile_name := offered[name].profile) is not None
        ]
        armour = defender_armour(contingent.loadout.armour)
        counts = [(row, 1) for row in champions]
        counts.append((unit.main, contingent.models - len(champions)))
        parts = tuple(
            Part(
                id=slugified(row.name),
                row=row,
                count=count,
                weapon=profile,
                wielded=wielded,
                armour=armour,
                carried=tuple(carried),
            )
            for row, count in counts
        )
        return cls(unit.id, parts, contingent.frontage)
