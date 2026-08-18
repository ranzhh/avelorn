"""Rule models for Warhammer: The Old World.

A rule entry carries the printed rule verbatim — name, flavour line,
and body paragraphs as displayed on the page — plus, optionally, its
executable ``effects``. Effects are hand-authored alongside the
imported text precisely so the structured form can be diffed against
what the rulebook actually says; a rule without effects is data the
engine recognises but cannot yet apply.

Most effects are **modifiers**: a change to one of the attack's
printed quantities, gated by a shared trigger vocabulary. The ``kind``
names the quantity in the rulebook's own modifier language ("To Hit
modifier", "the Armour Piercing characteristic ... is improved") and
implies where in the attack sequence the change lands; the triggers —
engagement facts (``when``) and a natural face on one stage's die
(``on_natural``) — say when it fires. What changes and when it fires
are separate halves of the sentence, and the YAML mirrors that split.
Other kinds are payloads consumed by their own seams (a re-roll
grant). Kinds are named after mechanics the rulebook itself names,
never after the rules that use them: a kind must serve any rule
sharing the mechanic, or the vocabulary degrades into per-rule scripts
in YAML dress — a rule too bespoke for any general kind belongs in a
code handler, as itself. Anything a rule needs that no kind expresses
stays unmodelled (and is reported by the engine) rather than
approximated.
"""

import re
from collections.abc import Mapping
from contextlib import suppress
from enum import StrEnum
from typing import Annotated, Literal, NamedTuple, assert_never

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from avelorn.tow.schema.psychology import Outcome, PanicCause
from avelorn.tow.schema.stage import Dice, Stage
from avelorn.tow.schema.unit import Characteristic, TroopType
from avelorn.tow.schema.weapon import WeaponType

# The printed convention for a parameterised rule: the name is filed
# under an "(X)" placeholder ("Armour Bane (X)"), and effects reference
# the parameter as the literal "X" ("the amount shown in brackets after
# the name of this special rule").
PARAMETER_SUFFIX = " (X)"

_DICE_QUANTITY = re.compile(r"^D(?P<sides>[36])(?:\+(?P<plus>\d+))?$")


class DiceQuantity(BaseModel):
    """A printed quantity decided by a dice roll: "D6", "D3", "D3+1".

    The dice form of a rule's bracketed parameter — "Often, this is
    determined by the roll of a dice" (Stomp Attacks, Impact Hits). One
    die plus a flat addend covers every printed instance; a wider form
    (2D6, say) joins when a rule prints one.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    sides: Literal[3, 6]
    plus: int = Field(default=0, ge=0)

    @classmethod
    def parse(cls, printed: str) -> "DiceQuantity | None":
        """Read a printed dice quantity off its text.

        Returns:
            The parsed quantity, or None when the text is not one.
        """
        match = _DICE_QUANTITY.match(printed)
        if match is None:
            return None
        sides: Literal[3, 6] = 3 if match.group("sides") == "3" else 6
        return cls(sides=sides, plus=int(match.group("plus") or 0))


class Seam(StrEnum):
    """Where an operation's quantity is consumed.

    A modifier's quantity lands in exactly one place, and the seam names it:
    the dice walk (roll quantities); the effective-characteristic query; the
    fighting-rank query; the combat-result fold; the armour fold, which
    improves the defender's armour value before its save; or the ward fold,
    which grants the defender the best warding value its rules confer.
    :meth:`ModifierEffect._ops_speak_to_one_seam` holds a single effect to
    one seam, so all-or-nothing reporting stays per consumer. The
    characteristic and armour seams are the two that honour a printed
    :class:`Bounded` amount — a ceiling on a characteristic, a floor (the
    best save) on the armour value.
    """

    ROLL = "roll"
    CHARACTERISTIC = "characteristic"
    RANK = "rank"
    COMBAT_RESULT = "combat-result"
    ARMOUR = "armour"
    WARD = "ward"


class Quantity(StrEnum):
    """A quantity a modifier can change, in the rulebook's own modifier vocabulary.

    The whole modifier vocabulary in one closed, append-only enum — a member
    joins when an imported rule needs it. Each member knows the :class:`Seam`
    that consumes it, so routing is the member's own knowledge, not a side
    table: ``to-hit`` and ``armour-piercing`` land on the dice walk,
    ``fighting-ranks`` / ``supporting-ranks`` on the fighting-rank query,
    ``combat-result`` on the combat-result fold, and ``armour-value`` on the
    armour fold (a defender improving its own save). A profile
    :class:`~avelorn.tow.schema.unit.Characteristic` is the one quantity kept
    apart — a stat vocabulary used far beyond modifiers — so an operation's
    key is a Quantity or a Characteristic.
    """

    TO_HIT = "to-hit"
    ARMOUR_PIERCING = "armour-piercing"
    FIGHTING_RANKS = "fighting-ranks"
    SUPPORTING_RANKS = "supporting-ranks"
    COMBAT_RESULT = "combat-result"
    ARMOUR_VALUE = "armour-value"
    WARD_SAVE = "ward-save"

    @property
    def seam(self) -> Seam:
        """The seam that consumes this quantity."""
        match self:
            case Quantity.TO_HIT | Quantity.ARMOUR_PIERCING:
                return Seam.ROLL
            case Quantity.FIGHTING_RANKS | Quantity.SUPPORTING_RANKS:
                return Seam.RANK
            case Quantity.COMBAT_RESULT:
                return Seam.COMBAT_RESULT
            case Quantity.ARMOUR_VALUE:
                return Seam.ARMOUR
            case Quantity.WARD_SAVE:
                return Seam.WARD
            case unhandled:
                assert_never(unhandled)


def seam_of(key: "Quantity | Characteristic") -> Seam:
    """The seam that consumes an operation's key.

    Returns:
        The quantity's own seam, or the characteristic seam for a profile
        characteristic (the quantity kept outside :class:`Quantity`).
    """
    return Seam.CHARACTERISTIC if isinstance(key, Characteristic) else key.seam


class NaturalRoll(BaseModel):
    """A natural face shown by one of the attack sequence's dice.

    The *event* half of the trigger vocabulary — "rolls a natural 6
    when making a roll To Wound". Where ``when`` gates on engagement
    state, known once before any die is cast (and possibly unknown),
    an event is decided branch by branch during resolution and is never
    unknown. ``roll`` must name a stage that rolls one die per attack —
    the stage's own :attr:`~avelorn.tow.schema.stage.Stage.dice` row,
    checked at data load.
    """

    model_config = ConfigDict(extra="forbid")

    face: int = Field(ge=1, le=6)
    roll: Stage

    @field_validator("roll")
    @classmethod
    def _a_die_is_rolled_there(cls, roll: Stage) -> Stage:
        if roll.dice is not Dice.D6_PER_ATTACK:
            raise ValueError(f"{roll} rolls no die per attack; no natural face is shown there")
        return roll


class Comparison(BaseModel):
    """A predicate on one numeric property of an event: exactly one comparator.

    The leaf of a gate path — ``charging.distance`` is constrained by
    ``{at_least: 3}``, ``{at_most: 6}`` or ``{equals: 8}``. The comparator
    vocabulary is closed and append-only, the same discipline as
    :class:`Quantity`; a new one joins when a rule needs it. Exactly one
    comparator is set — a leaf tests one thing.
    """

    model_config = ConfigDict(extra="forbid")

    equals: int | None = None
    at_least: int | None = None
    at_most: int | None = None

    @model_validator(mode="after")
    def _names_one_comparator(self) -> "Comparison":
        chosen = [c for c in ("equals", "at_least", "at_most") if getattr(self, c) is not None]
        if len(chosen) != 1:
            raise ValueError("a comparison names exactly one of: equals, at_least, at_most")
        return self

    def matches(self, value: int) -> bool:
        """Whether ``value`` satisfies this comparison.

        Returns:
            True if the property's value meets the comparator.
        """
        if self.equals is not None:
            return value == self.equals
        if self.at_least is not None:
            return value >= self.at_least
        assert self.at_most is not None  # the validator guarantees one is set
        return value <= self.at_most


class Gate(BaseModel):
    """Base for a branch of the gate tree — a subject or an event.

    A branch recurses: its fields are further gates (subjects, events) or leaf
    predicates. The evaluator tells a branch from a leaf by this base, so a
    :class:`Comparison` (a leaf predicate, not a subject) is deliberately *not*
    a Gate. ``extra=forbid`` is inherited, so every gate rejects an unknown
    property at load — path validation, structural.
    """

    model_config = ConfigDict(extra="forbid")


class MembershipGate(Gate):
    """Base for a gate satisfied by any one member of the collection it names.

    Most subjects are single — the combat a model is engaged in, the weapon in
    its hand — and a gate on one describes that one thing. A few are plural:
    armour is *several* pieces worn, and "equipped with a shield" asks whether
    some piece among them is a shield. Such a gate still describes one member
    (``worn: {name: Shield}``); what differs is the arity of the subject behind
    it, so the gate tested against every member and satisfied by any.

    The arity is declared here, in the schema, rather than read off the facts at
    evaluation, because it is needed exactly when there are no facts to read: a
    collection the producer never offered is unknown, and only the gate is left
    to say whether the missing subject was one thing or many.
    """


class ChargeGate(Gate):
    """A gate on the charge event — the model's own charge this turn.

    The typed home for "a turn in which it charged", carrying the charge's
    properties so a rule can constrain them: Furious Charge asks
    ``{distance: {at_least: 3}}``. A property name outside this model is a
    data error at load (``extra=forbid``), the same closed-vocabulary
    discipline the flat conditions have — load-time path validation falls out
    of the typed model. New properties (the arc, the number of enemy models
    charged) join here as rules need them.
    """

    distance: Comparison | None = None  # inches of the charge move

    @model_validator(mode="after")
    def _asks_something(self) -> "ChargeGate":
        if self.distance is None:
            raise ValueError("a charging gate must constrain a property (e.g. distance)")
        return self


class CombatGate(Gate):
    """A gate on the close combat the model is fighting.

    Facts of the combat itself, not the model: ``first_round`` (Elven Reflexes,
    Martial Prowess), ``outnumbers`` — whether this side's Unit Strength
    beats the foe's (Massed Infantry) — and ``was_charged``, whether the foe
    charged the bearer this turn (Shieldwall's "a turn in which it was
    charged"). Booleans today; the subject is where a round *number* or a
    flank/rear facing would join.
    """

    first_round: bool | None = None
    outnumbers: bool | None = None
    was_charged: bool | None = None


class MovementGate(Gate):
    """A gate on how the model moved this turn.

    ``moved`` is any move (Moving and Shooting's To Hit penalty); ``charge`` is
    the charge — ``false`` to require the model did not charge (Press of Battle,
    Fight in Extra Rank), or a :class:`ChargeGate` to constrain the charge's
    properties (Furious Charge's ``{distance: {at_least: 3}}``).
    """

    moved: bool | None = None
    charge: bool | ChargeGate | None = None


class ShootingGate(Gate):
    """A gate on the volley the model is firing.

    ``at_long_range`` is whether the target sits beyond half the weapon's
    maximum range (Firing at Long Range); ``stand_and_shoot`` whether the
    volley is a Stand & Shoot charge reaction (which Volley Fire forbids).
    The subject is where a range band or a cover fact would join.
    """

    at_long_range: bool | None = None
    stand_and_shoot: bool | None = None


class WeaponGate(Gate):
    """A gate on the weapon a model has in hand — by family or by name.

    The typed home for "wielding a bow" / "wielding this weapon": ``type`` names a
    weapon family (:class:`~avelorn.tow.schema.weapon.WeaponType`, the seam #107
    added), ``name`` a specific printed name. Arrows of Isha asks
    ``{type: bow}``; Parry's "a hand weapon" asks ``{name: Hand Weapon}``. Both
    may be set (a specific weapon of a family). At least one must be, or the gate
    constrains nothing (``extra=forbid`` keeps a stray property a load error).
    """

    type: WeaponType | None = None
    name: str | None = None

    @model_validator(mode="after")
    def _asks_something(self) -> "WeaponGate":
        if self.type is None and self.name is None:
            raise ValueError("a weapon gate must constrain type or name")
        return self


class ArmourGate(MembershipGate):
    """A gate on a piece of armour a model wears — by name, among all it wears.

    The ``worn`` peer of :class:`WeaponGate`, and the armour half of the
    equipment-in-use axis: Parry's "equipped with ... a shield" asks
    ``{name: Shield}``. Two things separate it from the weapon gate, and both
    come from the equipment itself. Armour has no family vocabulary — a piece is
    only ever its printed name — so ``name`` is the sole property; and a model
    wears *several* pieces at once where it holds one weapon, so this is a
    :class:`MembershipGate`, satisfied by any piece worn that matches.
    """

    name: str | None = None

    @model_validator(mode="after")
    def _asks_something(self) -> "ArmourGate":
        if self.name is None:
            raise ValueError("an armour gate must constrain name")
        return self


class AttackKind(StrEnum):
    """The kind of attack a model is the target of — a closed, append-only set.

    The rulebook names attacks by kind, and rules gate on the *positive* kind
    they care about: Lion Cloak on ``shooting``, Parry on being in close combat.
    "Not shooting" is not "close combat" — a spell is neither — so the kind is
    categorical, never a boolean. A member joins when a rule needs it (a spell
    ``magic`` kind when a magic-attack path exists).
    """

    CLOSE_COMBAT = "close_combat"
    SHOOTING = "shooting"


class AttackGate(Gate):
    """A gate on the attack a model is the target of.

    The incoming attack, from the defender's side: its ``kind`` (Lion Cloak
    fires only ``against ... shooting attacks``), whether it is ``magical``
    (Lion Cloak wants non-magical, the reason it does not help against a magical
    bow), and whether it is ``flaming`` — carries the Flaming Attacks rule.
    Orthogonal facts — a shooting or a close-combat attack may be either.
    """

    kind: AttackKind | None = None
    magical: bool | None = None
    flaming: bool | None = None


class FoeGate(Gate):
    """A gate on the foe of the attack the bearer is making.

    The mirror of :class:`AttackGate` — that subject describes the attack a
    model *suffers*, this one the model its own attack lands on. Killing
    Blow and Cleaving Blow read the foe's troop type ("enemy models whose
    troop type is infantry or cavalry ..."): ``troop_type`` is the printed
    list, satisfied by any member. A printed category expands to its
    sub-types when the entry is authored — the rulebook's own reading
    ("when the rules refer to Infantry units, Monstrous Infantry must also
    follow", troop-types-at-a-glance) — so the engine matches one closed
    vocabulary, never a category tree.
    """

    troop_type: tuple[TroopType, ...] | None = None

    @model_validator(mode="after")
    def _asks_something(self) -> "FoeGate":
        if not self.troop_type:
            raise ValueError("a foe gate must constrain a property (e.g. troop_type)")
        return self


class When(Gate):
    """An effect's gate: the facts that must hold for it to apply.

    A typed tree, one field per subject — the combat the model is engaged in,
    its movement, the volley it fires, the attack it is the target of — each
    carrying that subject's own facts, plus the ``natural`` dice event. A rule
    reads as ``subject -> property (-> comparator)``:
    ``{combat: {first_round: true}}``, ``{target_of: {kind: shooting}}``.

    ``combat`` and ``target_of`` are presence entities: ``combat: true`` gates
    on being engaged in a close combat (Parry's "whilst engaged in close
    combat"), a nested gate on being engaged *and* a property (Elven Reflexes's
    first round); ``target_of`` names the incoming attack. ``wielding`` and
    ``worn`` are the equipment-in-use axis — the weapon a model is acting with
    (Arrows of Isha's "any bow", matched by family or name) and the armour it
    wears (Parry's shield, matched among every piece worn) — read off the
    engagement context by the dice walk and the folds alike, so a rule gates on
    its gear exactly as it gates on the engagement. A subject or property outside
    these models is a data error at load (``extra=forbid``) — the closed
    vocabulary the flat Condition enum gave, now structural. Every set fact is
    conjoined; without a ``when`` the modifier applies to every attack.
    """

    combat: bool | CombatGate | None = None
    movement: MovementGate | None = None
    shooting: ShootingGate | None = None
    wielding: WeaponGate | None = None
    worn: ArmourGate | None = None
    target_of: bool | AttackGate | None = None
    foe: FoeGate | None = None
    natural: NaturalRoll | None = None

    @model_validator(mode="after")
    def _gates_something(self) -> "When":
        if not any(
            (
                self.combat,
                self.movement,
                self.shooting,
                self.wielding,
                self.worn,
                self.target_of,
                self.foe,
                self.natural,
            )
        ):
            raise ValueError(
                "a when must gate on something: combat, movement, shooting, "
                "wielding, worn, target_of, foe, or natural"
            )
        return self


# A printed operation's amount: a signed number, or the rule's bracketed X.
Amount = int | Literal["X"]


class Bounded(BaseModel):
    """An amount with the printed bound on the value it moves.

    The page prints a bound attached to the quantity it bounds, inside the
    parenthetical that follows it — "improves its armour value by 1 (to a
    maximum of 2+)", "a -1 modifier to their Strength characteristic (to a
    minimum of 1)" — so the bound is written on the amount, not beside the
    operation. An operation moving two quantities then cannot lend one's
    bound to the other.

    ``maximum`` is the printed limit on the modified value: a ceiling on a
    characteristic, the best attainable save (so numerically a floor) on an
    armour value. ``minimum`` is the floor a malus cannot push a
    characteristic below; an armour value needs none, its own floor being
    what ``maximum`` already names.

    Write the amount plainly (``S: -1``) where the page prints no bound —
    the long form exists to carry one.
    """

    model_config = ConfigDict(extra="forbid")

    amount: Amount
    maximum: int | None = None
    minimum: int | None = None

    @model_validator(mode="after")
    def _carries_a_bound(self) -> "Bounded":
        # Without a bound this is a plain amount spelled the long way: two
        # spellings of one thing, and a reader left wondering what the second
        # means. One way to write it, enforced at load.
        if self.maximum is None and self.minimum is None:
            raise ValueError("a bounded amount needs a maximum or a minimum; write it plainly")
        return self


class Add(NamedTuple):
    """One ``add`` as a seam reads it: the amount, and its printed bounds.

    The authored :class:`Bounded` must carry a bound; a read amount need not,
    so the two are kept apart rather than one faking the other.
    """

    amount: Amount
    maximum: int | None = None
    minimum: int | None = None


class GatedEffect(BaseModel):
    """The gating an effect carries whatever its consequence: the ``when``.

    A modifier and a re-roll grant apply under one gate — the ``when``, a typed
    tree of the facts that must hold (its ``natural`` die event apart) —
    evaluated the same way wherever a seam consumes the effect. Engagement state
    and equipment in use are both subjects of that one tree, so a seam that can
    answer a gate can answer all of it. The consequence (a modifier's operation,
    a re-roll's stage) is the subclass's own; the gate is shared here so a new
    effect kind is gate-able for free.
    """

    # populate_by_name so a subclass's aliased operation (ModifierEffect's
    # ``set``) is reachable in Python as the non-shadowing attribute.
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    when: When | None = None

    @property
    def natural(self) -> NaturalRoll | None:
        """The die event the when names, if any.

        Returns:
            The natural roll, or None for a state-only when.
        """
        return self.when.natural if self.when is not None else None


class ModifierEffect(GatedEffect):
    """One printed conditional modifier, shaped as the sentence prints it.

    "*If* a model rolls a natural 6 when making a roll To Wound, the
    Armour Piercing of its weapon is improved by X" — ``when`` holds
    the if (a :class:`When` gate), the operation (``add`` / ``set``) holds
    the consequence. ``When`` is a typed tree, ``subject -> property``: the
    combat's facts, the model's movement, the volley it fires, and the
    ``natural`` die event. Every set fact is conjoined; a state fact the
    engine cannot answer leaves the whole rule unfactored and reported, one
    answered False is honoured by not applying. Without a ``when`` the
    modifier applies to every attack. A rule needing branching or ``else``
    belongs in a code handler, not this data.

    The operation names itself, mirroring how the page prints it. ``add``
    is a signed delta the rulebook writes as a modifier — To Hit penalties
    negative ("-1 To Hit modifier" is ``add: {to-hit: -1}``), Armour
    Piercing improvements positive ("improved by 1" is
    ``add: {armour-piercing: 1}``). ``set`` is a replacement the rulebook
    writes as prose — "improves its Initiative characteristic to 10" is
    ``set: {I: 10}`` — applied before any additive modifier, and honoured
    only where a base value is read (the characteristic query and its
    siblings); the dice walk and the armour fold, which move a target
    rather than replace a base, read ``add`` alone. An effect carries at
    least one operation, and both map each quantity to its printed amount.
    A quantity is a roll of the attack sequence by its kind (consumed by
    the dice walk), a profile characteristic by its printed abbreviation
    ("+1 modifier to its Initiative characteristic" is ``add: {I: 1}``,
    consumed by the effective-characteristic query), a formation quantity
    like the number of fighting ranks (``add: {fighting-ranks: 1}``,
    consumed by the fighting-rank query), a combat-result point
    (``add: {combat-result: 1}``, summed into the round's score), or an
    armour-value improvement (``add: {armour-value: 1}``, folded into the
    defender's save), or a ward save at its printed Warding value
    ("has a 6+ Ward save" is ``set: {ward-save: 6}``, folded into the
    defender's ward — the best of the values granted, since wards never
    stack). The literal ``"X"`` means the rule's bracketed
    parameter ("the amount shown in brackets after the name of this
    special rule").
    Where a change lands follows from its quantity, so no stage is spelled
    out. Equipment in use is gated in the ``when`` like any other fact — Parry's
    "a hand weapon and a shield" is
    ``{wielding: {name: Hand Weapon}, worn: {name: Shield}}`` — evaluated against
    the loadout the consuming seam has in its context. A printed bound ("to a
    maximum of 10", "to a minimum of 1") is written on the amount it bounds, as
    a :class:`Bounded` — ``add: {S: {amount: -1, minimum: 1}}`` — never beside
    the operation, where an effect moving two quantities could not say which
    one it bounds. Only an ``add`` takes a bound: the page prints bounds on
    modifiers, and a ``set`` names the value outright.

    ``enemy`` transcribes the printed sentence's subject when it is the
    other party: "enemy units ... suffer a -1 To Hit modifier" moves the
    *enemy's* To Hit, where the default (the page speaks of the bearer)
    moves the bearer's own. Whose quantity it then is in a given attack
    follows from the quantity's owner side — the rulebook's constant,
    never authored — flipped by this word: a bearer's ``to-hit`` shapes
    the attacks it makes, an enemy's the attacks it suffers. Two seams
    resolve the flip today: the dice walk (roll quantities), and the
    effective-characteristic query, which folds the *foe's* enemy-subject
    operations beside the bearer's own wherever both sides are in hand
    ("enemy models suffer a -1 modifier to their Strength characteristic",
    "enemy models become subject to ... Strike Last"). Every other seam
    folds a side's own values, so ``enemy`` there is a data error until a
    printed rule needs it.
    """

    add: (
        Annotated[dict[Quantity | Characteristic, Amount | Bounded], Field(min_length=1)] | None
    ) = None
    set_: Annotated[dict[Quantity | Characteristic, Amount], Field(min_length=1)] | None = Field(
        default=None, alias="set"
    )
    enemy: bool = False

    @property
    def quantities(self) -> set["Quantity | Characteristic"]:
        """Every quantity this effect touches, across its operations.

        Returns:
            The union of the ``add`` and ``set`` keys.
        """
        return {*(self.add or {}), *(self.set_ or {})}

    def added(self, quantity: "Quantity | Characteristic") -> "Add":
        """The ``add`` on one quantity, with its printed bounds.

        Both spellings — a plain amount and a :class:`Bounded` one — read
        alike here, so a consuming seam never asks which was authored.

        Returns:
            The amount and its bounds, the latter None where none is printed.
        """
        amount = (self.add or {})[quantity]
        if isinstance(amount, Bounded):
            return Add(amount.amount, amount.maximum, amount.minimum)
        return Add(amount)

    @model_validator(mode="after")
    def _carries_an_operation(self) -> "ModifierEffect":
        # A modifier without a consequence is meaningless: it must add or
        # set something (a present-but-empty map fails its own min_length).
        if not self.add and not self.set_:
            raise ValueError("a modifier needs an operation: add or set")
        return self

    @model_validator(mode="after")
    def _set_replaces_a_base(self) -> "ModifierEffect":
        # A set replaces a base value, so it is meaningful only where a base is
        # read: the effective-value fold's seams (a characteristic, a rank
        # depth, a combat-result running total), and the ward fold, where the
        # set *is* the printed Warding value a rule grants. The dice walk
        # *moves* a roll's target and the armour fold *improves* a value —
        # neither has a base to replace, so a set there is a data error caught
        # loudly at load, not a note that would go silently unfactored forever.
        forbidden = {Seam.ROLL, Seam.ARMOUR}
        offending = sorted(seam_of(q) for q in (self.set_ or {}) if seam_of(q) in forbidden)
        if offending:
            raise ValueError(f"a set cannot replace a roll or armour quantity: {offending}")
        return self

    @model_validator(mode="after")
    def _ward_is_granted_at_a_value(self) -> "ModifierEffect":
        # A Warding value "is always given in the description of the item or
        # spell that grants it, or shown after the name of a special rule"
        # (the-shooting-phase/ward-saves): a ward is granted whole, as a set.
        # No printed rule adds to one, so an add is a data error caught loudly
        # at load rather than a note going silently unfactored forever.
        if any(seam_of(quantity) is Seam.WARD for quantity in (self.add or {})):
            raise ValueError("a ward save is granted at a value (set), never moved (add)")
        return self

    @model_validator(mode="after")
    def _bounds_belong_to_a_capped_quantity(self) -> "ModifierEffect":
        # A bound is checked against the quantity carrying it: a ceiling caps a
        # characteristic or the armour value, a floor is only ever printed on a
        # characteristic malus. On any other quantity a bound is meaningless,
        # so a data error caught loudly at load.
        for quantity, amount in (self.add or {}).items():
            if not isinstance(amount, Bounded):
                continue
            seam = seam_of(quantity)
            if amount.maximum is not None and seam not in {Seam.CHARACTERISTIC, Seam.ARMOUR}:
                raise ValueError(
                    f"maximum bounds a characteristic or armour value, not {quantity}"
                )
            if amount.minimum is not None and seam is not Seam.CHARACTERISTIC:
                raise ValueError(f"minimum floors a characteristic, not {quantity}")
        return self

    @model_validator(mode="after")
    def _enemy_flips_a_flippable_quantity(self) -> "ModifierEffect":
        # The enemy subject flips a quantity to the other seat of the attack.
        # The dice walk resolves that flip for every roll quantity, but the
        # characteristic query folds foe rules only where a caller threads
        # both sides through it: the melee strike's S and WS, the striking
        # order's I, and the Break test's Ld. Any other characteristic (T, M,
        # BS, W, A) has no consumer — an authored ``enemy: {T: -1}`` would
        # load cleanly and apply nowhere — and the remaining value folds (the
        # armour value, ranks, combat-result points, wards) fold one side's
        # own values only. Forbidden loudly at load until a seam threads them,
        # rather than left to go silently unfactored forever.
        if self.enemy:
            threaded = {
                Characteristic.STRENGTH,
                Characteristic.WEAPON_SKILL,
                Characteristic.INITIATIVE,
                Characteristic.LEADERSHIP,
            }
            offending = sorted(
                str(q)
                for q in self.quantities
                if seam_of(q) is not Seam.ROLL and q not in threaded
            )
            if offending:
                raise ValueError(
                    "enemy flips a roll quantity or a threaded characteristic "
                    f"(S, WS, I, Ld) only, not: {offending}"
                )
        return self

    @model_validator(mode="after")
    def _ops_speak_to_one_seam(self) -> "ModifierEffect":
        # Each seam (the dice walk, the characteristic query, the fighting-rank
        # query, the combat-result fold) consumes its quantities all-or-nothing,
        # so one effect may not straddle two: a mixed operation could be half-
        # consumed while its rule's note is dropped whole. Split the sentence
        # into one effect per seam. Add and set are weighed together — a single
        # effect that both adds and sets must still land on one seam.
        seams = {seam_of(quantity) for quantity in self.quantities}
        if len(seams) > 1:
            raise ValueError(
                "an operation may not mix quantities across seams "
                f"(roll / characteristic / rank / combat-result / armour / ward): {sorted(seams)}"
            )
        return self


class RollResult(StrEnum):
    """One die's result, in the printed re-roll vocabulary.

    The rulebook restricts a re-roll by the result of the dice it names:
    "may re-roll *failed* rolls To Hit", "must re-roll *successful*
    Armour Saves". Transcribed as printed; the walk re-rolls exactly the
    dice the word covers, with no assumption about whom the re-roll
    serves.
    """

    FAILED = "failed"
    SUCCESSFUL = "successful"


class RerollEffect(GatedEffect):
    """Re-roll a test, under the printed re-roll rules.

    The re-roll operation, named by its own key — ``reroll: <stage>``, the
    self-naming peer of ``add`` and ``set`` (spelled without a hyphen so it is
    a plain field, no alias). The operation *is* the key; its value is the test
    re-rolled, and the seam owning that stage consumes the grant directly (an
    attack roll by the dice walk, a panic test by the fold). A re-roll happens
    at most once whatever its source ("no single dice can be re-rolled more than
    once, regardless of the source"), and a multi-dice roll re-rolls all its
    dice. There is no discriminator field: an effect that carries ``reroll`` is
    one, exactly as one carrying ``add`` is a modifier (both models forbid the
    other's keys).

    A grant is restricted to the part of the roll it names, and which
    restriction is legal depends on the stage's seam. ``causes`` restricts
    a panic-test re-roll to specific panic causes (Valour of Ages re-rolls
    only heavy casualties and fled through); empty means any cause.
    ``on_natural`` restricts an attack-roll re-roll to the dice showing that
    natural face (Ithilmar Weapons re-rolls rolls To Hit of a natural 1);
    None re-rolls every covered die at the stage. The two restrictions are
    mutually exclusive — a panic test shows no natural face, an attack roll
    has no panic cause — so each belongs to its own seam's stages.

    ``of`` is the printed result restriction: which dice the grant covers,
    ``failed`` (the default — "may re-roll failed rolls To Hit", and the
    only re-roll a rational bearer takes of its own dice) or ``successful``
    ("must re-roll successful Armour Saves" — a re-roll imposed on the
    roller). ``enemy`` transcribes the sentence's subject when the roller
    is the other party: "*Enemy units* must re-roll ..." names the enemy's
    die, where the default names the bearer's own. Whose die a stage rolls
    is the sequence's constant (:attr:`~avelorn.tow.schema.stage.Stage.rolled_by`),
    so the seat a grant applies from follows — an enemy-subject save
    re-roll fires on the attacks the bearer *makes*, a bearer-subject one
    on the attacks it suffers. Both restrictions name a single die's
    result or face, so they cover only stages rolling one die per attack.
    """

    reroll: Stage
    causes: list[PanicCause] = Field(default_factory=list)
    on_natural: int | None = Field(default=None, ge=1, le=6)
    of: RollResult = RollResult.FAILED
    enemy: bool = False

    @model_validator(mode="after")
    def _restriction_matches_the_stage(self) -> "RerollEffect":
        per_attack = self.reroll.dice is Dice.D6_PER_ATTACK
        if self.on_natural is not None and not per_attack:
            raise ValueError(f"on_natural restricts a per-attack die, not {self.reroll}")
        if self.causes and per_attack:
            raise ValueError(f"causes restricts a panic test, not the attack roll {self.reroll}")
        if self.of is RollResult.SUCCESSFUL and not per_attack:
            raise ValueError(f"a successful-dice re-roll names a per-attack die: {self.reroll}")
        if self.enemy and not per_attack:
            raise ValueError(f"enemy flips a per-attack die, not {self.reroll}")
        return self


class GrantEffect(GatedEffect):
    """Confer a named special rule, gated like any other effect.

    "gains the Armour Bane (1) special rule" — the rule is granted *by name*, not
    copied: the consuming seam resolves ``grants`` to its entry (the one
    resolution convention, parameter substituted) and applies that rule's own
    effects under this grant's gate. So a change to the granted rule — or to how
    its quantity resolves — is tracked automatically, and a rule granted on top of
    one a model already carries stacks (two Armour Bane (1) → +2 on a natural 6),
    because each instance is a separate effect. The grant's shared ``when`` is the
    *outer* gate; the granted rule keeps its *own* inner gate
    (Armour Bane's natural-6 To Wound), the two conjoined at evaluation without
    merging the gate trees. There is no discriminator field: an effect carrying
    ``grants`` is one, exactly as one carrying ``add`` is a modifier (each model
    forbids the others' keys).
    """

    grants: str  # the printed name of the rule conferred, e.g. "Armour Bane (1)"


def _as_outcome(value: object) -> "Outcome":
    # Resolve a slug to the one Outcome subclass that defines it: the base has no
    # members, so a ChoiceEffect discovers the concrete set rather than naming it.
    for outcomes in Outcome.__subclasses__():
        with suppress(ValueError):
            return outcomes(value)
    raise ValueError(f"{value!r} is not a decision outcome")


class Decision(StrEnum):
    """A point where an outcome is rolled or chosen, that a rule may force.

    The routing key of a :class:`ChoiceEffect` — the peer of :class:`Quantity`
    for a modifier: the seam that owns a decision reads the effects forcing it.
    Closed and append-only; a member joins when a rule forces a new decision (a
    charge reaction, ...).
    """

    BREAK = "break"


class ChoiceEffect(GatedEffect):
    """Force the outcome of a decision that is otherwise rolled or chosen.

    ``forces`` maps a :class:`Decision` to the :class:`~avelorn.tow.schema.psychology.Outcome`
    it takes instead of rolling — ``{break: fall-back-in-good-order}``. Keyed by
    the decision exactly as a modifier's ``add`` is keyed by the quantity, so the
    seam that owns a decision reads its own key ("is ``break`` mine, and forced
    to what?") with no per-rule handler. The value is typed as the ``Outcome``
    base; each decision's own results are a subclass (a break's are
    :class:`~avelorn.tow.schema.psychology.BreakOutcome`), resolved by slug, so
    this generic effect names no decision. Self-naming by ``forces`` (the peer of
    ``add`` / ``grants``); each model forbids the others' keys. Forbidding an
    option rather than forcing one is the sibling (a ``forbids`` key) for when
    one lands.
    """

    forces: dict[Decision, Outcome]

    @field_validator("forces", mode="plain")
    @classmethod
    def _resolve_forced(cls, raw: object) -> dict["Decision", "Outcome"]:
        # Resolve each entry: the key against the Decision vocabulary, the value
        # against whichever Outcome subclass defines that slug — so the base is
        # all this generic effect declares, the concrete set discovered.
        if not isinstance(raw, dict) or not raw:
            raise ValueError("forces maps at least one decision to the outcome it forces")
        resolved: dict[Decision, Outcome] = {}
        for decision, outcome in raw.items():
            key = decision if isinstance(decision, Decision) else Decision(decision)
            resolved[key] = outcome if isinstance(outcome, Outcome) else _as_outcome(outcome)
        return resolved

    @field_serializer("forces")
    def _dump_forced(self, forces: dict["Decision", "Outcome"]) -> dict[str, str]:
        # The values are Outcome subclasses, not the base the field is typed as,
        # so serialise their slugs explicitly rather than let pydantic warn.
        return {decision.value: outcome.value for decision, outcome in forces.items()}


class AttackMarks(BaseModel):
    """The properties a rule stamps on the attacks its bearer makes.

    One optional flag per property of the incoming-attack facts a defender's
    gates read (:class:`AttackGate`, ``kind`` excepted — what kind an attack
    is belongs to the phase resolving it, never to a rule). A mark is only
    ever conferred: an unmarked attack is already not magical, so a False
    here would say nothing and is a data error.
    """

    model_config = ConfigDict(extra="forbid")

    magical: bool | None = None
    flaming: bool | None = None

    @model_validator(mode="after")
    def _confers_something(self) -> "AttackMarks":
        set_flags = [flag for flag in (self.magical, self.flaming) if flag is not None]
        if not set_flags:
            raise ValueError("a mark must confer a property: magical or flaming")
        if not all(set_flags):
            raise ValueError("a mark is conferred, never revoked: only true is meaningful")
        return self


class AttackMarkEffect(GatedEffect):
    """Classify the attacks the bearer makes: they are Magical, or Flaming.

    The vocabulary for the rules that modify no quantity but change what an
    attack *is* — "any attack made by a model with this special rule, or
    made using a weapon with this special rule, is a 'Magical' attack". The
    fact producers consume it when they build the incoming-attack facts a
    defender's gates read (Lion Cloak's non-magical armour bonus, a ward's
    flame gate), from the striker's unit rules and the profile in use
    alike. Self-naming by ``attack`` (the peer of ``add`` / ``reroll`` /
    ``grants`` / ``forces``); each model forbids the others' keys.
    """

    attack: AttackMarks


class BarEffect(GatedEffect):
    """The bearer cannot use a piece of armour while this rule is in force.

    "A model cannot use a shield alongside a weapon with this special rule
    during the Combat phase": a model has two hands, and wielding decides
    what else it can hold. The barred piece is *withdrawn* from what the
    bearer effectively wears — its armour bonus, whatever its size, and its
    presence to any gate that asks — never compensated with a counter-
    modifier, which would couple the rule to the piece's printed value.
    Consumed where the bearer's usable armour is assembled; scoped by the
    weapon in use when the entry rides a weapon profile, as any weapon rule
    is. Self-naming by ``bars``; each model forbids the others' keys.
    """

    bars: str  # the printed name of the armour piece barred, e.g. "Shield"


class BlowEffect(GatedEffect):
    """The rulebook's "X Blow" shape: a triggered strike the foe cannot save.

    "If a model with this special rule rolls a natural 6 when making a roll
    To Wound for an attack made in combat ... the enemy is not permitted an
    armour save (Ward saves can be attempted as normal)": ``denies`` names
    the save stages the foe may not attempt on the trigger branch, and
    ``slays`` escalates the unsaved wound to the rulebook's Instant Kill
    ("loses all of its remaining Wounds") — Killing Blow sets both, Cleaving
    Blow denies alone. The ``when`` must carry the natural trigger, on a
    roll before the denied stage; that a die must show a face is also what
    keeps the printed automatic-wound exception free — an automatic roll
    shows no die. Self-naming by ``denies``.
    """

    denies: Annotated[list[Stage], Field(min_length=1)]
    slays: bool = False

    @model_validator(mode="after")
    def _denies_the_armour_save(self) -> "BlowEffect":
        # The printed blows deny the armour (and Regeneration, which does not
        # exist) save; a ward denial has no printed rule, so it is a data
        # error until one needs it, not a note going silently wrong.
        outside = sorted(str(s) for s in self.denies if s is not Stage.MAKE_ARMOUR_SAVES)
        if outside:
            raise ValueError(f"a blow denies the armour save; no printed rule denies: {outside}")
        return self

    @model_validator(mode="after")
    def _fires_on_a_natural_face(self) -> "BlowEffect":
        # The shape is triggered ("rolls a natural 6 ..."), and the trigger's
        # die must come before the save it denies.
        if self.natural is None:
            raise ValueError("a blow fires on a natural face; the when must carry one")
        if self.natural.roll not in (Stage.ROLL_TO_HIT, Stage.ROLL_TO_WOUND):
            raise ValueError("a blow's trigger must precede the save it denies")
        return self


class WoundMultiplierEffect(GatedEffect):
    """The rulebook's Multiple Wounds shape: each unsaved wound is multiplied.

    "Each unsaved wound inflicted by an attack with this special rule is
    multiplied by the number shown in brackets" — ``multiplies`` is that
    number: a printed constant, a die ("D3", rolled separately for each
    unsaved wound, so a distribution and never an expectation), or the
    rule's "X" parameter, bound from the bracketed value exactly as a
    modifier's amounts are. The printed cap — "excess wounds caused to a
    model will have no additional effect", and they "do not 'spill over'
    onto other models" — is not authored here: it is the Remove Casualties
    fold's own knowledge, where a wound lands on a model with so many
    Wounds remaining. Self-naming by ``multiplies``; each model forbids
    the others' keys.
    """

    multiplies: int | Literal["D3", "D6", "X"]

    @model_validator(mode="after")
    def _multiplies_meaningfully(self) -> "WoundMultiplierEffect":
        # Multiplying each wound by one changes nothing — a data error, not
        # a rule honoured silently as a no-op.
        if isinstance(self.multiplies, int) and self.multiplies < 2:
            raise ValueError("multiplying each unsaved wound by less than 2 says nothing")
        return self


class VolleyEffect(GatedEffect):
    """Volley Fire's printed mechanic: rear ranks join the volley by halves.

    "Half of the models in each rank other than the front rank, rounding
    up, can shoot" — a shot-count rule, landing on how many models fire,
    never on the dice. The one printed fraction is the closed vocabulary;
    a variant joins when a rule prints one. Gated as the page gates it
    (no move this turn, never on a Stand & Shoot); the hill variant is
    terrain and stays in the entry's notes. Self-naming by ``volley``.
    """

    volley: Literal["half-of-each-rear-rank"]


class ReplaceEffect(GatedEffect):
    """Replace one of a decision's outcomes with another, leaving the rest rolled.

    The sibling of :class:`ChoiceEffect` for a choice narrower than the whole
    decision: Shieldwall's "may Give Ground rather than Fall Back in Good
    Order" takes effect only where the Break test would have resolved Fall
    Back — the Breaks and Gives Ground slices roll as ever, where a *forced*
    decision sends the whole mass one way. ``replaces`` maps the decision to
    ``{outcome replaced: outcome taken}``, each resolved by slug against the
    decision's own outcome set, exactly as ``forces`` values are.
    Self-naming by ``replaces``; each model forbids the others' keys.
    """

    replaces: dict[Decision, dict[Outcome, Outcome]]

    @field_validator("replaces", mode="plain")
    @classmethod
    def _resolve_replaced(cls, raw: object) -> dict["Decision", dict["Outcome", "Outcome"]]:
        if not isinstance(raw, dict) or not raw:
            raise ValueError("replaces maps at least one decision to {replaced: taken}")
        resolved: dict[Decision, dict[Outcome, Outcome]] = {}
        for decision, swaps in raw.items():
            key = decision if isinstance(decision, Decision) else Decision(decision)
            if not isinstance(swaps, dict) or not swaps:
                raise ValueError("a replaced decision maps at least one outcome to another")
            pairs: dict[Outcome, Outcome] = {}
            for replaced, taken in swaps.items():
                one = replaced if isinstance(replaced, Outcome) else _as_outcome(replaced)
                other = taken if isinstance(taken, Outcome) else _as_outcome(taken)
                if one == other:
                    raise ValueError(f"replacing {one.value!r} with itself says nothing")
                pairs[one] = other
            resolved[key] = pairs
        return resolved

    @field_serializer("replaces")
    def _dump_replaced(
        self, replaces: dict["Decision", dict["Outcome", "Outcome"]]
    ) -> dict[str, dict[str, str]]:
        return {
            decision.value: {replaced.value: taken.value for replaced, taken in swaps.items()}
            for decision, swaps in replaces.items()
        }


class HitOrder(StrEnum):
    """When a rule's extra hits land in a round of close combat.

    The two printed timings: ``first`` — "resolved against the charged
    unit when the combat is chosen ... before issuing challenges"
    (Impact Hits), ahead of every Initiative step — and ``last`` — "must
    be made last, after all other attacks have been made, including
    attacks made at Initiative 1" (Stomp Attacks). A member joins when a
    rule prints a third timing.
    """

    FIRST = "first"
    LAST = "last"


class HitsEffect(GatedEffect):
    """Extra hits that land automatically, outside the Initiative-ordered blows.

    The "X automatic hits" shape Stomp Attacks and Impact Hits share: each
    model with the rule causes ``hits`` hits — a number or a
    :class:`DiceQuantity`, usually the bracketed parameter — that skip the
    Roll to Hit ("they hit automatically") and wound at the unmodified
    Strength of the model making them, at the point of the round ``order``
    names. Consumed by the combat round, which folds the batch in at that
    point, a dice quantity as its exact distribution. Self-naming by
    ``hits``; each model forbids the others' keys.
    """

    hits: int | DiceQuantity | Literal["X"]
    order: HitOrder

    @model_validator(mode="after")
    def _lands_something(self) -> "HitsEffect":
        # Zero hits would say nothing — a rule granting none simply has no
        # effect — so a numeric count must be at least one.
        if isinstance(self.hits, int) and self.hits < 1:
            raise ValueError("an automatic-hits effect lands at least one hit")
        return self


RuleEffect = (
    ModifierEffect
    | RerollEffect
    | GrantEffect
    | ChoiceEffect
    | AttackMarkEffect
    | BarEffect
    | BlowEffect
    | WoundMultiplierEffect
    | VolleyEffect
    | ReplaceEffect
    | HitsEffect
)


def references_parameter(effect: RuleEffect) -> bool:
    """Whether any of the effect's values reference the X parameter.

    Introspects the effect's fields, looking inside mappings (an
    operation's amounts), so a new X-bearing field participates
    automatically.

    Returns:
        True if the literal "X" appears as a field or mapping value.
    """
    for name in type(effect).model_fields:
        value = getattr(effect, name)
        if value == "X" or (isinstance(value, Mapping) and "X" in value.values()):
            return True
    return False


class Rule(BaseModel):
    """A rules-page entry (special rule or core rule), text verbatim."""

    model_config = ConfigDict(extra="forbid")

    id: str  # stable slug, e.g. "armour-bane"
    name: str  # printed name, e.g. "Armour Bane (X)"
    page: int | None = None  # rulebook page reference
    category: str | None = None  # site rule category, e.g. "Special Rules"
    flavour: str | None = None  # italic flavour line, if any
    paragraphs: list[str] = Field(min_length=1)  # rule text, as displayed
    effects: list[RuleEffect] = Field(default_factory=list)
    # Hand-authored modelling notes: the scope this build covers and the parts
    # of the printed rule it does not, in the author's words. A seam that
    # factors the rule surfaces them (break_test does, for Stubborn), so a
    # simplification is stated in data — maintainable, diffable against the
    # paragraphs — never composed as prose in the engine.
    notes: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _hoist_shared_when(cls, data: object) -> object:
        # A rule-level ``when`` is the condition the whole rule reads — Arrows
        # of Isha's "any bow" holds for every clause. Written once at the rule
        # and conjoined into each effect's own gate here, so the data does not
        # repeat it and the rest of the engine still reads one gate per effect.
        # A subject constrained at both the rule and an effect is ambiguous —
        # a data error, not a silent override — but the union of disjoint
        # subjects (the rule's "wielding a bow" beside an effect's natural 6)
        # is the ordinary conjunction.
        if not isinstance(data, dict) or "when" not in data:
            return data
        data = dict(data)
        shared = data.pop("when")
        merged: list[object] = []
        for effect in data.get("effects") or []:
            if not isinstance(effect, dict):
                raise TypeError("a rule-level `when` needs its effects written as mappings")
            own = effect.get("when")
            if own is None:
                combined = shared
            elif overlap := set(shared) & set(own):
                raise ValueError(
                    f"a subject is gated at both the rule and an effect: {sorted(overlap)}"
                )
            else:
                combined = {**shared, **own}
            merged.append({**effect, "when": combined})
        data["effects"] = merged
        return data

    @model_validator(mode="after")
    def _parameter_requires_placeholder_name(self) -> "Rule":
        # An effect may reference the bracketed parameter ("X") only if
        # the printed name declares one ("Armour Bane (X)") — checked at
        # load, so an unbindable placeholder is a data error, not a
        # runtime surprise. Introspects the effect's fields, so a new
        # X-bearing kind participates automatically.
        if not self.name.endswith(PARAMETER_SUFFIX):
            for effect in self.effects:
                if references_parameter(effect):
                    raise ValueError(
                        f"an effect of {self.name!r} references the X parameter, "
                        f"but the name does not end in {PARAMETER_SUFFIX!r}"
                    )
        return self
