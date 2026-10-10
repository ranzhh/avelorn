"""Fielded sides, made of parts."""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import NamedTuple

from avelorn.core.graph import Source
from avelorn.tow.contingent import Contingent
from avelorn.tow.kernels import BEST_ARMOUR_VALUE, UNARMOURED, Standing, Standings
from avelorn.tow.schema.armour import Armour
from avelorn.tow.schema.reference import RuleRef, slugified
from avelorn.tow.schema.troop_type import TroopTypeProfile
from avelorn.tow.schema.unit import Characteristic, Profile, ProfileRole, TroopType
from avelorn.tow.schema.weapon import Weapon, WeaponProfile
from avelorn.tow.traits import Carries

SHIELD = "shield"


class Held(frozenset[str]):
    """What a model fights with in hand, by slug: a weapon, and the shield when it uses one."""

    def __str__(self) -> str:
        """The slugs joined by ``+``, the weapon first.

        Returns:
            The slugs, sorted with the shield last.
        """
        return "+".join(sorted(self, key=lambda slug: (slug == SHIELD, slug)))


@dataclass(frozen=True, eq=False)
class Part:
    """The models of a side that share a profile row and a loadout.

    ``weapons`` are the weapons they carry that fight in combat, and ``worn``
    the armour they wear. A mount names the ``rider`` part whose models it
    carries: it fights beside them with its own row and weapon, and stands and
    falls with them.
    """

    id: str
    row: Profile
    count: int
    weapon: WeaponProfile | None = None
    wielded: Weapon | None = None
    weapons: tuple[Weapon, ...] = ()
    worn: tuple[Armour, ...] = ()
    armour: int | None = None
    ward: int | None = None
    carried: tuple[tuple[RuleRef, Source], ...] = ()
    rider: str | None = None

    @property
    def holdings(self) -> tuple[Held, ...]:
        """Each way the models can fight: a weapon they carry, alone or with the shield they wear.

        The weapons come in the order carried, each alone and then with the shield.
        """
        shielded = any(piece.id == SHIELD for piece in self.worn)
        holdings = []
        for weapon in self.weapons:
            holdings.append(Held({weapon.id}))
            if shielded:
                holdings.append(Held({weapon.id, SHIELD}))
        return tuple(holdings)

    def weapon_with(self, held: Held) -> WeaponProfile:
        """The combat profile of the weapon in ``held``; a mount's own, whatever is held.

        Returns:
            The profile.

        Raises:
            ValueError: ``held`` holds no weapon the models carry, or more than one.
        """
        if self.rider is not None and self.weapon is not None:
            return self.weapon
        match [each.combat_profile for each in self.weapons if each.id in held]:
            case [WeaponProfile() as profile]:
                return profile
        raise ValueError(f"{self.id} holds {held}, not one weapon it carries")

    def armour_with(self, held: Held) -> int | None:
        """The armour value folded from the pieces in use with ``held``: a shield only when held.

        Returns:
            The armour value, or None when unarmoured.
        """
        return defender_armour(
            [piece for piece in self.worn if piece.id != SHIELD or SHIELD in held]
        )

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


class PerPart(NamedTuple):
    """A number for each part of a side, in the side's part order."""

    parts: tuple[tuple[str, int], ...]

    @property
    def total(self) -> int:
        """Every part's number together."""
        return sum(count for _, count in self.parts)

    def of(self, part: str) -> int:
        """One part's number.

        Returns:
            Its number.
        """
        return dict(self.parts)[part]

    def __str__(self) -> str:
        """Each part's number, as text.

        Returns:
            The number per part.
        """
        return ", ".join(f"{part} {count}" for part, count in self.parts)


class Shots(PerPart):
    """The shots each part fires."""


class Attacks(PerPart):
    """The attacks each part makes."""


class Initiatives(PerPart):
    """The Initiative each part strikes at."""


class Hits(PerPart):
    """The automatic hits each part makes."""


@dataclass(frozen=True, eq=False)
class Fielding:
    """A side on the table, of one troop type: its parts in placement order, front to back."""

    unit: str
    troop: TroopTypeProfile
    parts: tuple[Part, ...]
    frontage: int
    mounts: tuple[Part, ...] = ()

    def __post_init__(self) -> None:
        """Refuse a fielding that cannot stand.

        Raises:
            ValueError: the fielding has no rank-and-file part, repeats a part, has no
                frontage, or has a mount that carries no part.
        """
        ids = [part.id for part in self.fighters]
        if len(set(ids)) != len(ids):
            raise ValueError(f"{self.unit} fields a part twice")
        if not any(part.row.role is ProfileRole.RANK_AND_FILE for part in self.parts):
            raise ValueError(f"{self.unit} fields no rank and file")
        if self.frontage < 1:
            raise ValueError(f"{self.unit} stands with no frontage")
        riders = {part.id for part in self.parts}
        if any(mount.rider not in riders for mount in self.mounts):
            raise ValueError(f"{self.unit} fields a mount that carries none of its parts")

    @property
    def fighters(self) -> tuple[Part, ...]:
        """Every part that strikes in combat: the models, then the mounts carrying them."""
        return (*self.parts, *self.mounts)

    @property
    def troop_type(self) -> TroopType:
        """The side's troop type."""
        return TroopType(self.troop.name)

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
        """The rules the side carries, with what gives each; every part carries the same.

        Yields:
            The reference, and its source.

        Raises:
            ValueError: the parts carry different rules.
        """
        first, *rest = self.parts
        carried = set(first.sources())
        for part in rest:
            if set(part.sources()) != carried:
                raise ValueError(f"{self.unit}: {part.id} carries rules {first.id} does not")
        yield from first.sources()

    @property
    def removal(self) -> tuple[tuple[str, int], ...]:
        """Each part with its Wounds per model, in the order casualties come off.

        Casualties come off the back of the placement, and a champion falls last.
        """
        rank_and_file = [part for part in self.parts if part.row.role is not ProfileRole.CHAMPION]
        champions = [part for part in self.parts if part.row.role is ProfileRole.CHAMPION]
        return tuple(
            (part.id, self._wounds(part))
            for part in (*reversed(rank_and_file), *reversed(champions))
        )

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

    def wounds_left(self, standings: Standings) -> int:
        """The Wounds the side's standing models have left.

        Returns:
            Their Wounds, less those a damaged model has lost.
        """
        return sum(
            standings.of(part.id).models * self._wounds(part) - standings.of(part.id).wounds_lost
            for part in self.parts
        )

    def rank_bonus(self, standings: Standings) -> int:
        """The Rank Bonus the models standing claim (the-combat-phase/rank-bonus).

        Each rank behind the first counts, an incomplete one only when it holds
        the troop type's models per rank, up to the troop type's maximum. A side
        narrower than a counting rank, or of a troop type that does not rank
        up, claims none.

        Returns:
            The Rank Bonus.
        """
        per_rank = self.troop.models_per_rank
        if per_rank is None or self.frontage < per_rank:
            return 0
        full, remainder = divmod(standings.models, self.frontage)
        behind = full + int(remainder >= per_rank) - 1
        return min(max(behind, 0), self.troop.max_rank_bonus)

    def unit_strength(self, standings: Standings) -> int:
        """The Unit Strength of the models standing, by the troop type's strength per model.

        Returns:
            The Unit Strength.
        """
        return sum(
            standings.of(part.id).models
            * self.troop.unit_strength_per_model(part.characteristic(Characteristic.WOUNDS))
            for part in self.parts
        )

    def _wounds(self, part: Part) -> int:
        wounds = part.characteristic(Characteristic.WOUNDS)
        if wounds is None:
            raise ValueError(f"{part.id} prints no Wounds")
        return wounds

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
        cls,
        contingent: Contingent,
        weapon: str | None = None,
        options: tuple[str, ...] = (),
        *,
        combat: bool = False,
    ) -> "Fielding":
        """Field a contingent as its rank and file, with a champion part for each champion bought.

        ``options`` are the ids of the options the contingent was mustered with.
        A champion stands in the front rank, so its part is placed first
        (command-groups/position-within-the-unit). Every part carries the unit's
        equipment and rules. The armour value folds from the armour worn. A ward
        comes only from rules, so a part fielded from the corpus has none. A part
        carries the rules of its datasheet, its troop type, and the profile its
        weapon shoots with. In ``combat`` it fixes no weapon, since the side
        chooses at Step 1.1, and carries the rules of each weapon's combat
        profile; a mount fights beside each part with the weapon its row
        carries (troop-types-in-detail/split-profile-cavalry). A round of combat
        reads each part's count as its models at the start of the round.

        Returns:
            The fielded side.

        Raises:
            ValueError: ``weapon`` has no profile to shoot with, an option is not
                offered, a side fielded for combat names a weapon, or a mount
                carries a weapon its unit does not.
        """
        unit = contingent.unit
        if combat and weapon is not None:
            raise ValueError(f"{unit.id} chooses its weapon at Step 1.1, not when fielded")
        carriers: tuple[Carries, ...] = (unit, unit.rank_and_file)
        carried = [pair for carrier in carriers for pair in carrier.sources()]
        weapons = tuple(w for w in contingent.loadout.weapons if w.combat_profile is not None)
        wielded = profile = None
        if weapon is not None:
            wielded = contingent.loadout.weapon(weapon)
            profile = wielded.missile_profile
            if profile is None:
                raise ValueError(f"{weapon} has no missile profile; it cannot shoot")
            shot = profile.name or wielded.name
            carried += [pair for pair in wielded.sources() if pair[1].profile == shot]
        if combat:
            carried += [pair for each in weapons for pair in _fought(each)]
        offered = {option.id: option for option in unit.options}
        unknown = [chosen for chosen in options if chosen not in offered]
        if unknown:
            raise ValueError(f"{unit.id} offers no option {', '.join(unknown)}")
        rows = {row.name: row for row in unit.profiles}
        champions = [
            rows[profile_name]
            for chosen in options
            if (profile_name := offered[chosen].profile) is not None
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
                weapons=weapons,
                worn=contingent.loadout.armour,
                armour=armour,
                carried=tuple(carried),
            )
            for row, count in counts
        )
        mounts = () if not combat else _mounted(contingent, parts)
        return cls(unit.id, unit.rank_and_file, parts, contingent.frontage, mounts)


def defender_armour(worn: Sequence[Armour]) -> int | None:
    """Fold worn armour into one armour value (the-shooting-phase/determining-armour-value).

    The best suit worn, improved by every stacking bonus (a shield's +1), floored at 2+.

    Returns:
        The armour value, or None when the model is effectively unarmoured.
    """
    suit = UNARMOURED
    improvement = 0
    for piece in worn:
        if piece.armour_value is not None:
            suit = min(suit, piece.armour_value)
        elif piece.armour_value_improvement is not None:
            improvement += piece.armour_value_improvement
    value = max(suit - improvement, BEST_ARMOUR_VALUE)
    return value if value < UNARMOURED else None


def _mounted(contingent: Contingent, riders: tuple[Part, ...]) -> tuple[Part, ...]:
    rows = [row for row in contingent.unit.profiles if row.role is ProfileRole.MOUNT]
    if not rows:
        return ()
    (row,) = rows
    match row.equipment:
        case [name]:
            weapon = contingent.loadout.weapon(name)
        case names:
            raise ValueError(f"{row.name} fights with {len(names)} weapons, not one")
    return tuple(
        Part(
            id=f"{rider.id}-{slugified(row.name)}",
            row=row,
            count=rider.count,
            weapon=weapon.combat_profile,
            weapons=(weapon,),
            carried=rider.carried,
            rider=rider.id,
        )
        for rider in riders
    )


def _fought(weapon: Weapon) -> list[tuple[RuleRef, Source]]:
    profile = weapon.combat_profile
    if profile is None:
        raise ValueError(f"{weapon.name} has no combat profile")
    fights = profile.name or weapon.name
    return [pair for pair in weapon.sources() if pair[1].profile == fights]
