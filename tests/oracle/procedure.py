"""The printed attack procedure, re-derived from the rulebook to settle engine disputes.

One attack is enumerated die face by die face, and Remove Casualties wound by wound.
The oracle reads plain numbers and imports no engine: its charts are transcribed
from the printed tables on tow.whfb.app, each cited where it is used.
"""

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from fractions import Fraction
from functools import cache

SIXTH = Fraction(1, 6)
FACES = range(1, 7)

SHOOTING_TO_HIT = {1: 6, 2: 5, 3: 4, 4: 3, 5: 2}

HIGH_BS_RE_ROLL = {6: 6, 7: 5, 8: 4, 9: 3, 10: 2}

SEVEN_PLUS = {7: 4, 8: 5, 9: 6}

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

NO_ARMOUR = 7
BEST_ARMOUR = 2

type Throw = list[tuple[Fraction, int, bool]]

NOT_ROLLED: Throw = [(Fraction(1), 0, False)]

AUTOMATIC: Throw = [(Fraction(1), 0, True)]


class Phase(StrEnum):
    SHOOTING = "shooting"
    COMBAT = "combat"


class ReRoll(StrEnum):
    """Which dice of one roll a re-roll grant picks up, as the corpus prints them."""

    ONES = "ones"
    FAILED = "failed"
    SUCCESSFUL = "successful"


@dataclass(frozen=True)
class Attack:
    """One attack's printed inputs, as plain numbers.

    ``skill`` is Ballistic Skill when shooting and Weapon Skill in combat, where
    ``foe_weapon_skill`` is the target's. Modifiers follow the printed sign: a
    penalty is negative. ``armour_piercing`` is printed negative (AP -1),
    ``armour_bane`` is Armour Bane's X. ``killing_blow`` and ``cleaving_blow``
    are set only when the target's troop type is one the rule names.
    ``automatic_hit`` skips the roll To Hit, as Impact Hits and Stomp Attacks do.
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
    automatic_hit: bool = False

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
    if attack.automatic_hit:
        hits, needed = AUTOMATIC, 0
    else:
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


def most_removed(losses: list[int | None], models: int, wounds: int) -> int:
    """The most models any order of ``losses`` removes, entries as in :func:`removed`.

    Source: removing-casualties/multiple-wound-models ("you must remove as many
    whole models as possible"). A Killing Blow fells a model whatever it carries,
    so it goes on a fresh one; the order of the rest is searched.

    Returns:
        The models removed, at most ``models``.
    """
    kills = losses.count(None)
    plain = Counter(loss for loss in losses if loss is not None)
    return min(models, kills + _most_felled(tuple(sorted(plain.items())), wounds, wounds))


@cache
def _most_felled(counts: tuple[tuple[int, int], ...], remaining: int, wounds: int) -> int:
    best = 0
    for i, (loss, n) in enumerate(counts):
        rest = counts[:i] + (((loss, n - 1),) if n > 1 else ()) + counts[i + 1 :]
        if loss >= remaining:
            best = max(best, 1 + _most_felled(rest, wounds, wounds))
        else:
            best = max(best, _most_felled(rest, remaining - loss, wounds))
    return best


def casualties(
    attacks: Sequence[AttackOdds],
    *,
    models: int,
    wounds: int,
    damage: Mapping[int, Fraction] | None = None,
) -> dict[int, Fraction]:
    """The exact casualty distribution of ``attacks`` applied as rolled, one after another.

    Each attack has its own odds; ``damage`` is the Wounds each unsaved wound
    takes, as a distribution (Multiple Wounds (D3) is a third on each of 1, 2,
    3), None for one Wound. Wounds land as :func:`removed` lands them: on one
    model until it is removed, the excess lost.

    Returns:
        The probability of each casualty count reached, zeros left out.
    """
    damage = damage or {1: Fraction(1)}
    states: dict[tuple[int, int], Fraction] = {(0, wounds): Fraction(1)}
    for odds in attacks:
        rolled: dict[tuple[int, int], Fraction] = {}
        for (count, remaining), p in states.items():
            if count == models:
                outcomes = [((count, remaining), Fraction(1))]
            else:
                outcomes = [
                    ((count, remaining), 1 - odds.unsaved),
                    ((count + 1, wounds), odds.kill),
                ]
                for loss, q in damage.items():
                    felled = loss >= remaining
                    state = (count + 1, wounds) if felled else (count, remaining - loss)
                    outcomes.append((state, odds.wound * q))
            for state, q in outcomes:
                rolled[state] = rolled.get(state, Fraction(0)) + p * q
        states = rolled
    result: dict[int, Fraction] = {}
    for (count, _), p in states.items():
        if p:
            result[count] = result.get(count, Fraction(0)) + p
    return result


def exchange(
    first: AttackOdds, back: AttackOdds, *, models: int
) -> dict[tuple[int, int], Fraction]:
    """Two single ranks of ``models`` one-Wound, one-Attack models trade blows in turn.

    Source: the-combat-phase/who-strikes-first: the faster side strikes, and only
    the slower side's survivors strike back.

    Returns:
        The chance of each pair (slower side's casualties, faster side's casualties).
    """
    joint: dict[tuple[int, int], Fraction] = {}
    for felled, p in casualties([first] * models, models=models, wounds=1).items():
        for lost, q in casualties([back] * (models - felled), models=models, wounds=1).items():
            joint[felled, lost] = joint.get((felled, lost), Fraction(0)) + p * q
    return joint


def _two_dice() -> list[tuple[int, int]]:
    return [(first, second) for first in FACES for second in FACES]


def leadership_test(leadership: int, *, re_roll_failed: bool = False) -> Fraction:
    """The chance a Leadership test passes, a failed test re-rolled once if granted.

    Source: model-profiles/leadership-tests: 2D6 equal to or less than Leadership
    passes, a natural 2 always passes and a natural 12 always fails;
    general-principles/re-rolls.

    Returns:
        The probability of a pass.
    """
    passes = sum(
        1
        for first, second in _two_dice()
        if first + second == 2 or (first + second != 12 and first + second <= leadership)
    )
    p = Fraction(passes, 36)
    return p + (1 - p) * p if re_roll_failed else p


@dataclass(frozen=True)
class BreakOdds:
    """The chance of each Break test result for a unit that lost its combat."""

    gives_ground: Fraction
    falls_back: Fraction
    breaks: Fraction


def break_test(leadership: int, lost_by: int) -> BreakOdds:
    """The Break test of a unit that lost its combat by ``lost_by``.

    Source: the-combat-phase/break-test: 2D6 plus the difference in combat result
    scores; a natural roll over Leadership Breaks, a modified roll over it Falls
    Back in Good Order, and a modified roll within it or a natural double 1 Gives
    Ground.

    Returns:
        The probability of each result.
    """
    gives = falls = breaks = 0
    for first, second in _two_dice():
        natural = first + second
        if natural + lost_by <= leadership or (first, second) == (1, 1):
            gives += 1
        elif natural <= leadership:
            falls += 1
        else:
            breaks += 1
    return BreakOdds(Fraction(gives, 36), Fraction(falls, 36), Fraction(breaks, 36))
