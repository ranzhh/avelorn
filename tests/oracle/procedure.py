"""The printed attack procedure, re-derived from the rulebook to settle engine disputes.

One attack is enumerated die face by die face, and Remove Casualties is a seeded
Monte Carlo. The oracle reads plain numbers and imports no engine: its charts are
transcribed from the printed tables on tow.whfb.app, each cited where it is used.
"""

import math
import random
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from fractions import Fraction

SIXTH = Fraction(1, 6)
FACES = range(1, 7)

# the-shooting-phase/roll-to-hit-shooting: Ballistic Skill -> D6 roll To Hit.
SHOOTING_TO_HIT = {1: 6, 2: 5, 3: 4, 4: 3, 5: 2}

# the-shooting-phase/bs-of-6-or-higher: 2+, then a failed roll is re-rolled at this.
HIGH_BS_RE_ROLL = {6: 6, 7: 5, 8: 4, 9: 3, 10: 2}

# the-shooting-phase/7-to-hit: the D6 roll needed -> a natural 6 followed by this.
SEVEN_PLUS = {7: 4, 8: 5, 9: 6}

# the-combat-phase/roll-to-hit-combat, To Hit Chart: attacker's WS row, target's WS column.
COMBAT_TO_HIT = (
    (4, 4, 5, 5, 5, 5, 5, 5, 5, 5),
    (3, 4, 4, 4, 5, 5, 5, 5, 5, 5),
    (2, 3, 4, 4, 4, 4, 5, 5, 5, 5),
    (2, 3, 3, 4, 4, 4, 4, 4, 5, 5),
    (2, 2, 3, 3, 4, 4, 4, 4, 4, 4),
    (2, 2, 3, 3, 3, 4, 4, 4, 4, 4),
    (2, 2, 2, 3, 3, 3, 4, 4, 4, 4),
    (2, 2, 2, 3, 3, 3, 3, 4, 4, 4),
    (2, 2, 2, 2, 3, 3, 3, 3, 4, 4),
    (2, 2, 2, 2, 3, 3, 3, 3, 3, 4),
)

# the-shooting-phase/roll-to-wound-shooting, To Wound Chart (the combat page prints the
# same): Strength row, Toughness column, None for the printed "-".
TO_WOUND = (
    (4, 5, 6, 6, 6, 6, None, None, None, None),
    (3, 4, 5, 6, 6, 6, 6, None, None, None),
    (2, 3, 4, 5, 6, 6, 6, 6, None, None),
    (2, 2, 3, 4, 5, 6, 6, 6, 6, None),
    (2, 2, 2, 3, 4, 5, 6, 6, 6, 6),
    (2, 2, 2, 2, 3, 4, 5, 6, 6, 6),
    (2, 2, 2, 2, 2, 3, 4, 5, 6, 6),
    (2, 2, 2, 2, 2, 2, 3, 4, 5, 6),
    (2, 2, 2, 2, 2, 2, 2, 3, 4, 5),
    (2, 2, 2, 2, 2, 2, 2, 2, 3, 4),
)

# the-shooting-phase/determining-armour-value: no armour counts as 7+, improved at most to 2+.
NO_ARMOUR = 7
BEST_ARMOUR = 2

# One roll enumerated: (mass, natural face, success). Face 0 is a roll not taken.
type Throw = list[tuple[Fraction, int, bool]]

NOT_ROLLED: Throw = [(Fraction(1), 0, False)]


class Phase(StrEnum):
    SHOOTING = "shooting"
    COMBAT = "combat"


class ReRoll(StrEnum):
    """Which dice of one roll a re-roll grant picks up, as the corpus prints them."""

    ONES = "ones"
    FAILED = "failed"
    SUCCESSFUL = "successful"


class Order(StrEnum):
    """The order a strike's unsaved wounds reach the unit; the rulebook prints none."""

    AS_ROLLED = "as-rolled"
    KILLS_FIRST = "kills-first"


@dataclass(frozen=True)
class Attack:
    """One attack's printed inputs, as plain numbers.

    ``skill`` is Ballistic Skill when shooting and Weapon Skill in combat, where
    ``foe_weapon_skill`` is the target's. Modifiers follow the printed sign: a
    penalty is negative. ``armour_piercing`` is printed negative (AP -1),
    ``armour_bane`` is Armour Bane's X. ``killing_blow`` and ``cleaving_blow``
    are set only when the target's troop type is one the rule names.
    """

    phase: Phase
    skill: int
    strength: int
    toughness: int
    foe_weapon_skill: int | None = None
    hit_modifier: int = 0
    wound_modifier: int = 0
    armour_value: int = NO_ARMOUR
    armour_piercing: int = 0
    ward: int | None = None
    armour_bane: int = 0
    killing_blow: bool = False
    cleaving_blow: bool = False
    poisoned: bool = False
    hit_re_rolls: frozenset[ReRoll] = frozenset()
    save_re_rolls: frozenset[ReRoll] = frozenset()

    def __post_init__(self) -> None:
        if (self.phase is Phase.COMBAT) != (self.foe_weapon_skill is not None):
            raise ValueError("a foe's Weapon Skill is read in combat and only there")
        if (self.killing_blow or self.cleaving_blow) and self.phase is not Phase.COMBAT:
            raise ValueError("Killing and Cleaving Blow are printed for attacks made in combat")
        if not BEST_ARMOUR <= self.armour_value <= NO_ARMOUR:
            raise ValueError(f"armour value {self.armour_value}+ is outside 2+..7+")
        if self.armour_piercing > 0 or self.armour_bane < 0:
            raise ValueError("Armour Piercing is printed as a negative modifier")


@dataclass(frozen=True)
class AttackOdds:
    """The exact chance one attack ends as each class Remove Casualties tells apart.

    ``wound`` is an unsaved wound, ``kill`` an unsaved Killing Blow, which takes
    all of a model's remaining Wounds.
    """

    wound: Fraction
    kill: Fraction

    @property
    def unsaved(self) -> Fraction:
        return self.wound + self.kill


def shooting_to_hit(ballistic_skill: int) -> int:
    """The D6 roll To Hit for Ballistic Skill 1 to 5.

    Source: the-shooting-phase/roll-to-hit-shooting.

    Returns:
        The printed target number.
    """
    return SHOOTING_TO_HIT[ballistic_skill]


def combat_to_hit(weapon_skill: int, foe_weapon_skill: int) -> int:
    """The D6 roll To Hit in combat, attacker's WS against the target's.

    Source: the-combat-phase/roll-to-hit-combat, To Hit Chart.

    Returns:
        The printed target number.
    """
    return _cell(COMBAT_TO_HIT, weapon_skill, foe_weapon_skill)


def to_wound(strength: int, toughness: int) -> int | None:
    """The D6 roll To Wound, Strength against Toughness.

    Source: the-shooting-phase/roll-to-wound-shooting and
    the-combat-phase/roll-to-wound-combat, To Wound Chart.

    Returns:
        The printed target number, or None for "-" (too tough to wound).
    """
    return _cell(TO_WOUND, strength, toughness)


def _cell[T](chart: tuple[tuple[T, ...], ...], row: int, column: int) -> T:
    if not (1 <= row <= len(chart) and 1 <= column <= len(chart[0])):
        raise ValueError(f"({row}, {column}) is off the printed chart")
    return chart[row - 1][column - 1]


def _d6(success: Callable[[int], bool]) -> Throw:
    return [(SIXTH, face, success(face)) for face in FACES]


def _re_rolled(throw: Throw, grants: frozenset[ReRoll], again: Throw | None = None) -> Throw:
    """Pick up each die a grant covers and roll it once more; the new result stands.

    Source: general-principles/re-rolls: "You must accept the result of the
    re-roll" and "No single dice can be re-rolled more than once".

    Returns:
        The roll with every covered die replaced by ``again`` (the same roll by default).
    """
    again = throw if again is None else again
    covered = {
        ReRoll.ONES: lambda face, success: face == 1,
        ReRoll.FAILED: lambda face, success: face != 0 and not success,
        ReRoll.SUCCESSFUL: lambda face, success: success,
    }
    result: Throw = []
    for p, face, success in throw:
        if any(covered[grant](face, success) for grant in grants):
            result.extend((p * q, face_again, ok) for q, face_again, ok in again)
        else:
            result.append((p, face, success))
    return result


def _shooting_hit(attack: Attack) -> tuple[Throw, int]:
    """The roll To Hit when shooting, and the D6 roll it needs.

    Sources: the-shooting-phase/roll-to-hit-shooting (a natural 1 always fails),
    the-shooting-phase/7-to-hit, the-shooting-phase/bs-of-6-or-higher,
    the-shooting-phase/to-hit-modifiers ("In the case of models with a BS of 6 or
    higher, these modifiers are only applied to the first dice roll").

    Returns:
        The enumerated roll, each natural face the last die rolled, and the first roll's need.

    Raises:
        ValueError: a case the printed text does not settle.
    """
    bs, modifier = attack.skill, attack.hit_modifier
    if bs >= 6:
        if attack.hit_re_rolls:
            raise ValueError("unprinted: which re-roll a BS 6+ miss takes when another applies")
        if 2 - modifier > 6:
            raise ValueError("unprinted: a BS 6+ first roll that needs 7+")
        first = _d6(lambda face: face != 1 and face + modifier >= 2)
        second = _d6(lambda face: face != 1 and face >= HIGH_BS_RE_ROLL[bs])
        return _re_rolled(first, frozenset({ReRoll.FAILED}), second), 2 - modifier
    target = shooting_to_hit(bs)
    needed = target - modifier
    if needed <= 6:
        throw = _d6(lambda face: face != 1 and face + modifier >= target)
    elif needed in SEVEN_PLUS:
        if ReRoll.FAILED in attack.hit_re_rolls:
            raise ValueError("unprinted: whether a failed 7+ confirmation may be re-rolled")
        confirm = SEVEN_PLUS[needed]
        throw = [(SIXTH, face, False) for face in FACES if face != 6]
        throw += [(SIXTH * SIXTH, 6, again >= confirm) for again in FACES]
    else:
        throw = NOT_ROLLED
    return _re_rolled(throw, attack.hit_re_rolls), needed


def _combat_hit(attack: Attack) -> tuple[Throw, int]:
    """The roll To Hit in combat, and the D6 roll it needs.

    Source: the-combat-phase/roll-to-hit-combat: a natural 1 always fails and a
    natural 6 always hits, regardless of modifiers.

    Returns:
        The enumerated roll and the roll needed.
    """
    assert attack.foe_weapon_skill is not None
    target = combat_to_hit(attack.skill, attack.foe_weapon_skill)
    modifier = attack.hit_modifier
    throw = _d6(lambda face: face == 6 or (face != 1 and face + modifier >= target))
    return _re_rolled(throw, attack.hit_re_rolls), target - modifier


def _wound(attack: Attack, poisoned: bool) -> Throw:
    """The roll To Wound; Poisoned Attacks adds +2 to it.

    Sources: the-shooting-phase/roll-to-wound-shooting, the-combat-phase/roll-to-wound-combat
    (a natural 1 always fails), the-shooting-phase/too-tough-to-wound,
    special-rules/poisoned-attacks.

    Returns:
        The enumerated roll, or no roll when the chart prints "-".
    """
    target = to_wound(attack.strength, attack.toughness)
    if target is None:
        return NOT_ROLLED
    modifier = attack.wound_modifier + (2 if poisoned else 0)
    return _d6(lambda face: face != 1 and face + modifier >= target)


def _armour_save(attack: Attack, armour_piercing: int) -> Throw:
    """The Armour Save roll, Armour Piercing applied to the roll.

    Sources: the-shooting-phase/make-armour-saves-shooting,
    the-combat-phase/make-armour-saves-combat (a natural 1 always fails),
    the-shooting-phase/armour-piercing, the-shooting-phase/more-than-one-save
    (a save modified past passing is not rolled).

    Returns:
        The enumerated roll, re-rolls applied.
    """
    if attack.armour_value - armour_piercing > 6:
        return NOT_ROLLED
    throw = _d6(lambda face: face != 1 and face + armour_piercing >= attack.armour_value)
    return _re_rolled(throw, attack.save_re_rolls)


def _ward_save(ward: int | None) -> Throw:
    """The Ward save, made "in the same manner as armour saves".

    Source: the-shooting-phase/ward-saves.

    Returns:
        The enumerated roll, or no roll without a ward.
    """
    if ward is None:
        return NOT_ROLLED
    return _d6(lambda face: face != 1 and face >= ward)


def one_attack(attack: Attack) -> AttackOdds:
    """Enumerate every die of one attack's printed procedure, exactly.

    Natural-6 triggers read the face of the die they name: Poisoned Attacks on
    the To Hit die when it needed 6 or less (special-rules/poisoned-attacks),
    Armour Bane, Killing Blow and Cleaving Blow on the To Wound die
    (special-rules/armour-bane; special-rules/killing-blow and
    special-rules/cleaving-blow deny the armour save but not the ward, and only
    Killing Blow slays).

    Returns:
        The probability of each unsaved class.
    """
    hits, needed = (_shooting_hit if attack.phase is Phase.SHOOTING else _combat_hit)(attack)
    wound = kill = Fraction(0)
    for p_hit, hit_face, hit in hits:
        if not hit:
            continue
        poisoned = attack.poisoned and hit_face == 6 and needed <= 6
        for p_wound, wound_face, wounded in _wound(attack, poisoned):
            if not wounded:
                continue
            blow = attack.killing_blow and wound_face == 6
            cleaves = attack.cleaving_blow and wound_face == 6
            bane = attack.armour_bane if wound_face == 6 else 0
            denied = blow or cleaves
            saves = NOT_ROLLED if denied else _armour_save(attack, attack.armour_piercing - bane)
            for p_save, _, saved in saves:
                if saved:
                    continue
                for p_ward, _, warded in _ward_save(attack.ward):
                    if warded:
                        continue
                    mass = p_hit * p_wound * p_save * p_ward
                    if blow:
                        kill += mass
                    else:
                        wound += mass
    return AttackOdds(wound=wound, kill=kill)


def removed(losses: list[int | None], models: int, wounds: int) -> int:
    """Apply unsaved wounds in order to a unit and count the models removed.

    Each entry is the Wounds one unsaved wound takes (Multiple Wounds' roll), or
    None for a Killing Blow. Sources: the-shooting-phase/remove-casualties-shooting,
    removing-casualties/multiple-wound-models (Wounds are lost by one model until
    it is removed), special-rules/multiple-wounds (excess is lost, never spilt),
    special-rules/killing-blow (the model loses all its remaining Wounds).

    Returns:
        The models removed, at most ``models``.
    """
    count, remaining = 0, wounds
    for loss in losses:
        if count == models:
            break
        if loss is None or loss >= remaining:
            count, remaining = count + 1, wounds
        else:
            remaining -= loss
    return count


def remove_casualties(
    attacks: int,
    odds: AttackOdds,
    *,
    models: int,
    wounds: int,
    order: Order,
    trials: int,
    seed: int,
    damage: Mapping[int, Fraction] | None = None,
) -> dict[int, float]:
    """Monte Carlo of ``attacks`` identical attacks against a unit, then Remove Casualties.

    ``damage`` is the Wounds each unsaved wound takes, as a distribution (Multiple
    Wounds (D3) is a third on each of 1, 2, 3); None is one Wound.

    Returns:
        The frequency of each casualty count 0..``models``.
    """
    rng = random.Random(seed)
    values, weights = zip(*(damage or {1: Fraction(1)}).items(), strict=True)
    p_kill, p_unsaved = float(odds.kill), float(odds.unsaved)
    counts = dict.fromkeys(range(models + 1), 0)
    for _ in range(trials):
        losses: list[int | None] = []
        for _ in range(attacks):
            draw = rng.random()
            if draw < p_kill:
                losses.append(None)
            elif draw < p_unsaved:
                losses.append(rng.choices(values, weights)[0])
        if order is Order.KILLS_FIRST:
            losses.sort(key=lambda loss: loss is not None)
        counts[removed(losses, models, wounds)] += 1
    return {casualties: n / trials for casualties, n in counts.items()}


def trials_for(tolerance: float, *, z: float = 4.0) -> int:
    """Trials that put every frequency within ``tolerance`` of its probability at ``z`` sigma.

    A frequency's standard error is at most 1 / (2 sqrt(n)), its value at p = 1/2.
    To settle a dispute between two probabilities d apart, ask for d / 2.

    Returns:
        The number of trials.
    """
    return math.ceil((z / (2 * tolerance)) ** 2)
