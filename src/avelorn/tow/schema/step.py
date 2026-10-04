"""The printed steps of the rulebook, each with the sequences that print it.

One member per step id of the printed step table (tow.whfb.app, read
2026-09-16). A step printed in two sequences, as Roll To Hit is in shooting
and in combat, is one member listing both. The vocabulary is closed: a step
joins when a printed step is modelled or an imported rule names one.
"""

from enum import StrEnum


class StepSequence(StrEnum):
    """A printed sequence, by the name an address gives it."""

    SHOOTING = "shooting"
    CHARGE = "charge"
    COMBAT = "combat"
    COMBAT_RESULT = "combat-result"
    BREAK = "break"
    PANIC = "panic"
    FLEE = "flee"
    GIVE_GROUND = "give-ground"
    STRATEGY = "strategy"
    TURN = "turn"


class StepKind(StrEnum):
    """How a step's outcome is settled."""

    MEASUREMENT = "measurement"
    DECISION = "decision"
    ROLL = "roll"
    CONSEQUENCE = "consequence"


_SHOOTING = (StepSequence.SHOOTING,)
_CHARGE = (StepSequence.CHARGE,)
_COMBAT = (StepSequence.COMBAT,)
_BREAK = (StepSequence.BREAK,)
_PANIC = (StepSequence.PANIC,)
_FLEE = (StepSequence.FLEE,)
_GIVE_GROUND = (StepSequence.GIVE_GROUND,)
_ATTACK = (StepSequence.SHOOTING, StepSequence.COMBAT)
_PANICKED = (StepSequence.SHOOTING, StepSequence.PANIC)


class Step(StrEnum):
    """A printed step, the sequences that print it, and its kind.

    Ward Saves is printed in the shooting sequence and runs in combat too: the
    combat page settles wounds "as described in the Shooting section"
    (the-combat-phase/roll-to-wound-and-make-armour-saves-combat), and Killing
    Blow and Cleaving Blow print that Ward saves are attempted as normal
    against a blow struck in combat.
    """

    _value_: str
    sequences: tuple[StepSequence, ...]
    kind: StepKind

    def __new__(cls, value: str, sequences: tuple[StepSequence, ...], kind: StepKind) -> "Step":
        """Build one row: the id is the member's value, the rest its attributes."""
        member = str.__new__(cls, value)
        member._value_ = value
        member.sequences = sequences
        member.kind = kind
        return member

    WHO_CAN_SHOOT = "who-can-shoot", _SHOOTING, StepKind.MEASUREMENT
    CHECK_LINE_OF_SIGHT = "check-line-of-sight", _SHOOTING, StepKind.MEASUREMENT
    CHECK_RANGE = "check-range", _SHOOTING, StepKind.MEASUREMENT
    DECLARE_TARGET = "declare-target", _SHOOTING, StepKind.DECISION
    HOW_MANY_SHOTS = "how-many-shots", _SHOOTING, StepKind.MEASUREMENT
    ROLL_TO_HIT = "roll-to-hit", _ATTACK, StepKind.ROLL
    ROLL_TO_WOUND = "roll-to-wound", _ATTACK, StepKind.ROLL
    MAKE_ARMOUR_SAVES = "make-armour-saves", _ATTACK, StepKind.ROLL
    WARD_SAVES = "ward-saves", _ATTACK, StepKind.ROLL
    REMOVE_CASUALTIES = "remove-casualties", _ATTACK, StepKind.CONSEQUENCE
    MAKE_PANIC_TESTS = "make-panic-tests", _PANICKED, StepKind.ROLL
    FALL_BACK_OR_FLEE = "fall-back-or-flee", _PANICKED, StepKind.CONSEQUENCE
    WHO_CAN_CHARGE = "who-can-charge", _CHARGE, StepKind.MEASUREMENT
    DECLARE_CHARGES = "declare-charges", _CHARGE, StepKind.DECISION
    CHARGE_REACTIONS = "charge-reactions", _CHARGE, StepKind.DECISION
    HOLD = "hold", _CHARGE, StepKind.CONSEQUENCE
    STAND_AND_SHOOT = "stand-and-shoot", _CHARGE, StepKind.CONSEQUENCE
    FLEE_CHARGE_REACTION = "flee-charge-reaction", _CHARGE, StepKind.CONSEQUENCE
    DETERMINE_CHARGE_RANGE = "determine-charge-range", _CHARGE, StepKind.ROLL
    THE_CHARGE_MOVE = "the-charge-move", _CHARGE, StepKind.CONSEQUENCE
    FAILED_CHARGE = "failed-charge", _CHARGE, StepKind.CONSEQUENCE
    RUNNING_DOWN_THE_FOE = "running-down-the-foe", _CHARGE, StepKind.CONSEQUENCE
    REDIRECTING_A_CHARGE = "redirecting-a-charge", _CHARGE, StepKind.ROLL
    CHOOSE_COMBAT_AND_DETERMINE_WHO_CAN_FIGHT = (
        "choose-combat-and-determine-who-can-fight",
        _COMBAT,
        StepKind.DECISION,
    )
    WHO_CAN_FIGHT = "who-can-fight", _COMBAT, StepKind.MEASUREMENT
    HOW_MANY_ATTACKS = "how-many-attacks", _COMBAT, StepKind.MEASUREMENT
    WHO_STRIKES_FIRST = "who-strikes-first", _COMBAT, StepKind.MEASUREMENT
    DIVIDING_ATTACKS = "dividing-attacks", _COMBAT, StepKind.DECISION
    IMPACT_HITS = "impact-hits", _COMBAT, StepKind.ROLL
    ISSUING_A_CHALLENGE = "issuing-a-challenge", _COMBAT, StepKind.DECISION
    ACCEPTING_A_CHALLENGE = "accepting-a-challenge", _COMBAT, StepKind.DECISION
    REFUSING_A_CHALLENGE = "refusing-a-challenge", _COMBAT, StepKind.CONSEQUENCE
    FIGHT_ON = "fight-on", _COMBAT, StepKind.MEASUREMENT
    STOMP_ATTACKS = "stomp-attacks", _COMBAT, StepKind.ROLL
    CALCULATE_COMBAT_RESULT = (
        "calculate-combat-result",
        (StepSequence.COMBAT_RESULT,),
        StepKind.CONSEQUENCE,
    )
    WHO_IS_THE_WINNER = "who-is-the-winner", (StepSequence.COMBAT_RESULT,), StepKind.CONSEQUENCE
    BREAK_TEST = "break-test", _BREAK, StepKind.ROLL
    LOSER_BREAKS_AND_FLEES = "loser-breaks-and-flees", _BREAK, StepKind.CONSEQUENCE
    LOSER_FALLS_BACK_IN_GOOD_ORDER = (
        "loser-falls-back-in-good-order",
        _BREAK,
        StepKind.CONSEQUENCE,
    )
    LOSER_GIVES_GROUND = "loser-gives-ground", _BREAK, StepKind.CONSEQUENCE
    RESTRAIN_AND_REFORM = "restrain-and-reform", _BREAK, StepKind.ROLL
    CHANGE_FACING = "change-facing", _BREAK, StepKind.DECISION
    FOLLOW_UP = "follow-up", _BREAK, StepKind.CONSEQUENCE
    PURSUIT = "pursuit", _BREAK, StepKind.DECISION
    THE_PURSUIT_MOVE = "the-pursuit-move", _BREAK, StepKind.ROLL
    OVERRUN = "overrun", _BREAK, StepKind.DECISION
    CATCHING_THE_CURS = "catching-the-curs", _BREAK, StepKind.CONSEQUENCE
    PURSUIT_INTO_A_FRESH_ENEMY = "pursuit-into-a-fresh-enemy", _BREAK, StepKind.CONSEQUENCE
    PURSUIT_OFF_THE_BATTLEFIELD = "pursuit-off-the-battlefield", _BREAK, StepKind.CONSEQUENCE
    HEAVY_CASUALTIES = "heavy-casualties", _PANIC, StepKind.MEASUREMENT
    NEARBY_FRIEND_DESTROYED = "nearby-friend-destroyed", _PANIC, StepKind.MEASUREMENT
    NEARBY_FRIEND_FLEES_COMBAT = "nearby-friend-flees-combat", _PANIC, StepKind.MEASUREMENT
    FLED_THROUGH = "fled-through", _PANIC, StepKind.MEASUREMENT
    DIRECTION_OF_FLIGHT = "direction-of-flight", _FLEE, StepKind.MEASUREMENT
    THE_FLEE_MOVE = "the-flee-move", _FLEE, StepKind.ROLL
    FLEEING_THROUGH_ENEMY_UNITS = "fleeing-through-enemy-units", _FLEE, StepKind.ROLL
    DESTRUCTION_OF_A_FLEEING_UNIT = (
        "destruction-of-a-fleeing-unit",
        _FLEE,
        StepKind.CONSEQUENCE,
    )
    GIVE_GROUND = "give-ground", _GIVE_GROUND, StepKind.CONSEQUENCE
    FALL_BACK_IN_GOOD_ORDER = "fall-back-in-good-order", _GIVE_GROUND, StepKind.ROLL
    RALLY_FLEEING_UNITS = "rally-fleeing-units", (StepSequence.STRATEGY,), StepKind.ROLL
    END_OF_TURN = "end-of-turn", (StepSequence.TURN,), StepKind.CONSEQUENCE
