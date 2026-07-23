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

from collections.abc import Mapping
from enum import StrEnum
from typing import Annotated, Literal, assert_never

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from avelorn.tow.schema.psychology import PanicCause
from avelorn.tow.schema.stage import ATTACK_ROLLS, Stage
from avelorn.tow.schema.unit import Characteristic

# The printed convention for a parameterised rule: the name is filed
# under an "(X)" placeholder ("Armour Bane (X)"), and effects reference
# the parameter as the literal "X" ("the amount shown in brackets after
# the name of this special rule").
PARAMETER_SUFFIX = " (X)"


class EquipmentUse(StrEnum):
    """How a model uses a piece of equipment — the ``requires`` vocabulary.

    A rule can be gated on the gear a model has in use, beside the engagement
    ``when``: ``wielding`` names the weapon in hand, ``worn`` a piece of armour
    worn. A closed, append-only vocabulary like :class:`Quantity`; a member
    joins when a rule needs a use the loadout can answer (a mount, later).
    """

    WIELDING = "wielding"
    WORN = "worn"


class Seam(StrEnum):
    """Where an operation's quantity is consumed.

    A modifier's quantity lands in exactly one place, and the seam names it:
    the dice walk (roll quantities); the effective-characteristic query; the
    fighting-rank query; the combat-result fold; or the armour fold, which
    improves the defender's armour value before its save.
    :meth:`ModifierEffect._ops_speak_to_one_seam` holds a single effect to
    one seam, so all-or-nothing reporting stays per consumer. The
    characteristic and armour seams cap a value at a printed maximum — a
    ceiling on a characteristic, a floor (the best save) on the armour value.
    """

    ROLL = "roll"
    CHARACTERISTIC = "characteristic"
    RANK = "rank"
    COMBAT_RESULT = "combat-result"
    ARMOUR = "armour"


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
    unknown. ``roll`` must name one of the attack sequence's rolls —
    the closed :data:`~avelorn.tow.schema.stage.ATTACK_ROLLS`
    vocabulary, checked at data load.
    """

    model_config = ConfigDict(extra="forbid")

    face: int = Field(ge=1, le=6)
    roll: Stage

    @field_validator("roll")
    @classmethod
    def _a_die_is_rolled_there(cls, roll: Stage) -> Stage:
        if roll not in ATTACK_ROLLS:
            raise ValueError(f"{roll} is not an attack roll; no natural face is shown there")
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
    Martial Prowess) and ``outnumbers`` — whether this side's Unit Strength
    beats the foe's (Massed Infantry). Both are booleans today; the subject is
    where a round *number* or a flank/rear facing would join.
    """

    first_round: bool | None = None
    outnumbers: bool | None = None


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
    maximum range (Firing at Long Range). The subject is where a range band or
    a cover fact would join.
    """

    at_long_range: bool | None = None


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
    fires only ``against ... shooting attacks``) and whether it is ``magical``
    (Lion Cloak wants non-magical, the reason it does not help against a magical
    bow). Orthogonal facts — a shooting or a close-combat attack may be magical.
    """

    kind: AttackKind | None = None
    magical: bool | None = None


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
    first round); ``target_of`` names the incoming attack. A subject or property
    outside these models is a data error at load (``extra=forbid``) — the closed
    vocabulary the flat Condition enum gave, now structural. Every set fact is
    conjoined; without a ``when`` the modifier applies to every attack.
    """

    combat: bool | CombatGate | None = None
    movement: MovementGate | None = None
    shooting: ShootingGate | None = None
    target_of: bool | AttackGate | None = None
    natural: NaturalRoll | None = None

    @model_validator(mode="after")
    def _gates_something(self) -> "When":
        if not any((self.combat, self.movement, self.shooting, self.target_of, self.natural)):
            raise ValueError(
                "a when must gate on something: combat, movement, shooting, target_of, or natural"
            )
        return self


class GatedEffect(BaseModel):
    """The gating an effect carries whatever its consequence: when and requires.

    A modifier and a re-roll grant apply under the same two gates — the
    engagement ``when`` (a typed state tree, its ``natural`` die event apart)
    and the equipment a model must have in use (``requires``) — evaluated the
    same way wherever a seam consumes the effect. The consequence (a modifier's
    operation, a re-roll's stage) is the subclass's own; the gate is shared here
    so a new effect kind is gate-able and equipment-gate-able for free.
    """

    # populate_by_name so a subclass's aliased operation (ModifierEffect's
    # ``set``) is reachable in Python as the non-shadowing attribute.
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    when: When | None = None
    requires: Annotated[dict[EquipmentUse, str], Field(min_length=1)] | None = None

    @property
    def natural(self) -> NaturalRoll | None:
        """The die event the when names, if any.

        Returns:
            The natural roll, or None for a state-only when.
        """
        return self.when.natural if self.when is not None else None

    @property
    def requirements(self) -> dict[EquipmentUse, str]:
        """The equipment the effect needs in use, by how it is used.

        Returns:
            The required equipment name per use, empty when the effect names
            none (it applies whatever the loadout).
        """
        return dict(self.requires or {})


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
    defender's save). The literal ``"X"`` means the rule's bracketed
    parameter ("the amount shown in brackets after the name of this
    special rule").
    Where a change lands follows from its quantity, so no stage is spelled
    out. ``requires`` gates the effect on equipment in use beside the
    engagement ``when`` — Parry's "a hand weapon and a shield" is
    ``{wielding: Hand Weapon, worn: Shield}`` — evaluated against the
    contingent's loadout wherever the consuming seam has it. ``maximum`` is a
    printed limit on the modified value ("to a maximum of 10" / "to a maximum
    of 3+"): a ceiling on a characteristic, the best attainable save (a floor)
    on an armour value.
    """

    add: (
        Annotated[dict[Quantity | Characteristic, int | Literal["X"]], Field(min_length=1)] | None
    ) = None
    set_: (
        Annotated[dict[Quantity | Characteristic, int | Literal["X"]], Field(min_length=1)] | None
    ) = Field(default=None, alias="set")
    maximum: int | None = None

    @property
    def quantities(self) -> set["Quantity | Characteristic"]:
        """Every quantity this effect touches, across its operations.

        Returns:
            The union of the ``add`` and ``set`` keys.
        """
        return {*(self.add or {}), *(self.set_ or {})}

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
        # depth, a combat-result running total). The dice walk *moves* a roll's
        # target and the armour fold *improves* a value — neither has a base to
        # replace, so a set there is a data error caught loudly at load, not a
        # note that would go silently unfactored forever.
        forbidden = {Seam.ROLL, Seam.ARMOUR}
        offending = sorted(seam_of(q) for q in (self.set_ or {}) if seam_of(q) in forbidden)
        if offending:
            raise ValueError(f"a set cannot replace a roll or armour quantity: {offending}")
        return self

    @model_validator(mode="after")
    def _maximum_bounds_a_capped_quantity(self) -> "ModifierEffect":
        # A printed ceiling caps a characteristic or the armour value; on any
        # other quantity it is meaningless, so a data error.
        if self.maximum is not None and not any(
            isinstance(quantity, Characteristic) or quantity == Quantity.ARMOUR_VALUE
            for quantity in self.quantities
        ):
            raise ValueError(
                "maximum bounds a characteristic or armour value; the operation moves neither"
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
                f"(roll / characteristic / rank / combat-result / armour): {sorted(seams)}"
            )
        return self


class RerollEffect(GatedEffect):
    """Re-roll a failed test, under the printed re-roll rules.

    A re-roll happens at most once whatever its source ("no single dice
    can be re-rolled more than once, regardless of the source"), and a
    multi-dice roll re-rolls all its dice. Unlike a modifier, the
    ``stage`` here is the payload — *which* test is re-rolled — and the
    seam owning that stage consumes the grant directly.

    A grant is restricted to the part of the roll it names, and which
    restriction is legal depends on the stage's seam. ``causes`` restricts
    a panic-test re-roll to specific panic causes (Valour of Ages re-rolls
    only heavy casualties and fled through); empty means any cause.
    ``on_natural`` restricts an attack-roll re-roll to the dice showing that
    natural face (Ithilmar Weapons re-rolls rolls To Hit of a natural 1);
    None re-rolls every failing die at the stage. The two restrictions are
    mutually exclusive — a panic test shows no natural face, an attack roll
    has no panic cause — so each belongs to its own seam's stages.
    """

    kind: Literal["re-roll"]
    stage: Stage
    causes: list[PanicCause] = Field(default_factory=list)
    on_natural: int | None = Field(default=None, ge=1, le=6)

    @model_validator(mode="after")
    def _restriction_matches_the_stage(self) -> "RerollEffect":
        if self.on_natural is not None and self.stage not in ATTACK_ROLLS:
            raise ValueError(f"on_natural restricts an attack roll, not {self.stage}")
        if self.causes and self.stage in ATTACK_ROLLS:
            raise ValueError(f"causes restricts a panic test, not the attack roll {self.stage}")
        return self


RuleEffect = ModifierEffect | RerollEffect


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
