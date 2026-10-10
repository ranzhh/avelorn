"""A round of close combat on the graph."""

from collections.abc import Hashable, Mapping
from fractions import Fraction
from functools import partial
from typing import NamedTuple

import pytest

from avelorn.core.distribution import Probability
from avelorn.core.graph import Decision, Verdict
from avelorn.tow.changes import Added, Uses
from avelorn.tow.contingent import ChargeArc, Contingent
from avelorn.tow.data import TOWRepository
from avelorn.tow.fielding import SHIELD, Fielding, Held, Initiatives
from avelorn.tow.kernels import Standing, Standings
from avelorn.tow.programs import (
    ROUND,
    STAND_AND_SHOOT,
    Evaluated,
    Knowns,
    Loaded,
    load_program,
)
from avelorn.tow.schema.effect import Effect, Role
from avelorn.tow.schema.quantity import Quantity
from avelorn.tow.schema.rule import Clause, RuleGraph
from avelorn.tow.schema.stage import Side
from avelorn.tow.schema.unit import Characteristic
from avelorn.tow.steps import (
    NO_ROLL,
    SUPPORTING_ATTACK,
    WEAPON_CHOICE,
    BreakTest,
    Fought,
    how_many_attacks,
    loser_falls_back_in_good_order,
    roll_to_hit_in_combat,
    who_is_the_winner,
    who_strikes_first,
)

REPO = TOWRepository()
ROUND_PROGRAM = load_program(ROUND, REPO.rules)
SCORE = "round/attacker/calculate-combat-result"


class _Armed(NamedTuple):
    """A side fielded for combat, and what it holds to fight."""

    side: Fielding
    held: Held


def _fielded(
    unit: str,
    weapon: str,
    models: int,
    frontage: int | None = None,
    equipment: tuple[str, ...] = (),
    shield: bool = True,
) -> _Armed:
    datasheet = REPO.units[unit]
    armed = datasheet.model_copy(update={"equipment": [*datasheet.equipment, *equipment]})
    contingent = Contingent.field(armed, models, data=REPO, frontage=frontage)
    worn = {piece.id for piece in contingent.loadout.armour}
    shields = {SHIELD} & worn if shield else set()
    held = Held({contingent.loadout.weapon(weapon).id, *shields})
    return _Armed(Fielding.of(contingent, combat=True), held)


def _knowns(
    attacker: _Armed,
    target: _Armed,
    attacker_standing: int = 1,
    attacker_charges: int = 0,
    attacker_at_start: int | None = None,
    charge_move: int = 0,
    enemy_arc: ChargeArc = ChargeArc.FRONT,
    rounds_fought: int = 1,
) -> dict[str, Hashable]:
    fielded = sum(part.count for part in attacker.side.parts)
    at_start = fielded if attacker_at_start is None else attacker_at_start
    target_standing = target.side.standing(sum(part.count for part in target.side.parts))
    return {
        "attacker/standing": attacker.side.standing(attacker_standing),
        "target/standing": target_standing,
        "attacker/standing-at-start-of-round": attacker.side.standing(at_start),
        "target/standing-at-start-of-round": target_standing,
        "attacker/standing-at-start-of-turn": attacker.side.standing(at_start),
        "target/standing-at-start-of-turn": target_standing,
        "attacker/rounds-fought": rounds_fought,
        "target/rounds-fought": rounds_fought,
        "attacker/charges-made": attacker_charges,
        "target/charges-made": 0,
        "attacker/charge-move": charge_move,
        "target/charge-move": 0,
        "attacker/enemy-arc": enemy_arc,
        "target/enemy-arc": ChargeArc.FRONT,
        "attacker/charges-received": 0,
        "target/charges-received": attacker_charges,
        "attacker/break-tests-taken": 0,
        "target/break-tests-taken": 0,
        "attacker/uses-this-game": Uses(),
        "target/uses-this-game": Uses(),
    }


def _lanes(
    attacker: _Armed,
    target: _Armed,
    attacker_standing: int = 1,
    program: Loaded = ROUND_PROGRAM,
    attacker_charges: int = 0,
    wielding: bool = False,
    attacker_at_start: int | None = None,
    charge_move: int = 0,
    enemy_arc: ChargeArc = ChargeArc.FRONT,
    rounds_fought: int = 1,
) -> tuple[Evaluated, ...]:
    built = program.built({Side.ATTACKER: attacker.side, Side.TARGET: target.side})
    choices = {Side.ATTACKER: attacker.held, Side.TARGET: target.held}
    knowns = _knowns(
        attacker,
        target,
        attacker_standing,
        attacker_charges,
        attacker_at_start,
        charge_move,
        enemy_arc,
        rounds_fought,
    )
    return built.evaluate(knowns, choices if wielding else {})


def _held(fought: Evaluated) -> Mapping[Side, frozenset[str]]:
    return {
        Side(decision.side): option
        for decision, option in fought.lane.choices.items()
        if decision.name == WEAPON_CHOICE
    }


def _fought(
    attacker: _Armed,
    target: _Armed,
    attacker_standing: int = 1,
    program: Loaded = ROUND_PROGRAM,
    attacker_charges: int = 0,
    attacker_at_start: int | None = None,
    charge_move: int = 0,
    enemy_arc: ChargeArc = ChargeArc.FRONT,
    rounds_fought: int = 1,
) -> Evaluated:
    lanes = _lanes(
        attacker,
        target,
        attacker_standing,
        program,
        attacker_charges,
        True,
        attacker_at_start,
        charge_move,
        enemy_arc,
        rounds_fought,
    )
    (fought,) = (each for each in lanes if not each.lane.out)
    return fought


def _falls(fought: Evaluated, side: Side) -> Probability:
    return fought.at(f"round/stomp-attacks/{side}/remove-casualties").read("models").mass[0]


def _needed(fought: Evaluated, path: str) -> set[str]:
    shown = fought.at(path).read("needed").mass
    return {str(each) for each in shown} - {NO_ROLL}


def test_equal_initiative_strikes_at_once() -> None:
    """One Elven Spearman a side, both Initiative 4, strike from the same standings.

    Weapon Skill 4 against 4 hits on 4+ (1/2), Strength 3 against Toughness 3
    wounds on 4+ (1/2), and light armour with a shield saves on 5+ (fails 2/3):
    each falls on 1/6, as neither blow waits for the other.
    """
    spearman = _fielded("elven-spearmen", "Thrusting Spear", 1)

    fought = _fought(spearman, spearman)

    assert _falls(fought, Side.ATTACKER) == _falls(fought, Side.TARGET) == Fraction(1, 6)


def test_the_higher_initiative_strikes_first() -> None:
    """An Elven Spearman (I4) strikes before the Dwarf Warrior (I2) attacking it.

    The Spearman hits on 4+ (1/2), wounds Toughness 4 on 5+ (1/3) and beats
    heavy armour's 5+ save on 2/3: the Dwarf falls on 1/9. The Dwarf swings
    back only while it stands (8/9), hitting on 4+, wounding on 4+ and beating
    the 5+ save on 1/6: the Spearman falls on 8/9 * 1/6 = 4/27.
    """
    dwarf = _fielded("dwarf-warriors", "Hand Weapon", 1)
    spearman = _fielded("elven-spearmen", "Thrusting Spear", 1)

    fought = _fought(dwarf, spearman)

    assert _falls(fought, Side.ATTACKER) == Fraction(1, 9)
    assert _falls(fought, Side.TARGET) == Fraction(4, 27)


def test_a_fighting_rank_model_that_falls_takes_its_attacks() -> None:
    """Fifteen Spearmen five wide that charged and lost three this round throw 2 attacks, not 5.

    On the turn they charged, Who Can Fight names the front rank alone, and a
    casualty suffered in the round comes off it before the rear rank (FAQ v1.5.3).
    """
    spearmen = _fielded("elven-spearmen", "Thrusting Spear", 15, frontage=5)
    dwarf = _fielded("dwarf-warriors", "Hand Weapon", 1)

    fought = _fought(spearmen, dwarf, attacker_standing=12, attacker_charges=1)

    attacks = fought.at("round/initiative-4/attacker/how-many-attacks").read("attacks")
    assert attacks.mass == {2: 1}


def test_a_supporting_attack_is_one_whatever_the_model_s_attacks() -> None:
    """Fifteen Spearmen five wide at Attacks 2: two fighting ranks make 20, a supporting rank 5."""
    spearmen = _fielded("elven-spearmen", "Thrusting Spear", 15, frontage=5).side
    (part,) = spearmen.parts
    standing = spearmen.standing(15)
    ranks = frozenset({"rank-1", "rank-2", SUPPORTING_ATTACK})
    doubled = (Added(Characteristic.ATTACKS, 1, of=Side.ATTACKER),)

    (attacks,) = how_many_attacks(
        spearmen, 4, ranks, Initiatives(((part.id, 4),)), standing, standing, doubled
    ).mass

    assert attacks.of(part.id) == 25


def test_a_combat_hit_pushed_past_6_still_lands_on_a_natural_6() -> None:
    """Weapon Skill 4 against 4 hits on 4+; at -3 To Hit it needs 7+ and hits on a 6 alone."""
    spearman = _fielded("elven-spearmen", "Thrusting Spear", 1).side.hit
    penalised = (Added(Quantity.TO_HIT, -3),)

    hit = roll_to_hit_in_combat(spearman, spearman, penalised)

    assert hit.prob(lambda die: die.success) == Fraction(1, 6)


def test_an_entry_acting_for_the_target_swaps_the_sides() -> None:
    """The target's attack group holds its part as the attacker, and its rules land on its steps.

    Without the swap, the Spearman's blow would wound as the Dwarf's does, Strength
    3 against Toughness 3 on 4+; it wounds Toughness 4 on 5+. Elven Reflexes, the
    Spearmen's own, lands on the target's Who Strikes First alone.
    """
    dwarf = _fielded("dwarf-warriors", "Hand Weapon", 1)
    spearman = _fielded("elven-spearmen", "Thrusting Spear", 1)

    fought = _fought(dwarf, spearman)

    wound = fought.at("round/initiative-4/target/attack/elven-spearman/roll-to-wound")
    assert wound.read("needed").mass == {"5+": 1}
    program = fought.built.program
    reflexes = program.rules["target/elven-spearmen/elven-reflexes"]
    assert [program.paths[landing.at] for landing in reflexes.landings] == [
        "round/target/who-strikes-first"
    ]


def test_a_list_of_sides_builds_the_entry_once_for_each_in_order() -> None:
    """Both sides decide and measure at the head; the target's casualties come off first."""
    spearman = _fielded("elven-spearmen", "Thrusting Spear", 1).side

    program = ROUND_PROGRAM.built({Side.ATTACKER: spearman, Side.TARGET: spearman}).program

    paths = [program.paths[step] for step in program.steps]
    assert paths[:8] == [
        "round/attacker/the-charge-move",
        "round/target/the-charge-move",
        "round/attacker/choose-combat-and-determine-who-can-fight",
        "round/target/choose-combat-and-determine-who-can-fight",
        "round/attacker/who-can-fight",
        "round/target/who-can-fight",
        "round/attacker/who-strikes-first",
        "round/target/who-strikes-first",
    ]
    assert [
        path
        for path in paths
        if path.startswith("round/initiative-4/") and path.endswith("/remove-casualties")
    ] == [
        "round/initiative-4/target/remove-casualties",
        "round/initiative-4/attacker/remove-casualties",
    ]


def test_a_side_chooses_each_weapon_it_carries_with_or_without_its_shield() -> None:
    """Elven Spearmen given great weapons may fight with any weapon they carry, shield or not."""
    spearmen = _fielded(
        "elven-spearmen", "Great Weapon", 10, equipment=("Great Weapon",), shield=False
    )

    choice = _fought(spearmen, spearmen).at(
        "round/target/choose-combat-and-determine-who-can-fight"
    )

    assert isinstance(choice.step, Decision)
    assert [str(option) for option in choice.step.options] == [
        "hand-weapon",
        "hand-weapon+shield",
        "thrusting-spear",
        "thrusting-spear+shield",
        "great-weapon",
        "great-weapon+shield",
    ]


def test_a_rule_two_carried_weapons_give_is_in_force_once_in_each_option() -> None:
    """Spearmen given a great weapon and a halberd attach Requires Two Hands, which both give.

    No option holds both weapons, so each sees the rule once, as each sees
    Fight in Extra Rank from the spear or the halberd once. Neither weapon
    fights beside the shield, and every other option is a lane.
    """
    two_handed = ("Great Weapon", "Ceremonial Halberd")
    spearman = _fielded("elven-spearmen", "Great Weapon", 1, equipment=two_handed, shield=False)
    dwarf = _fielded("dwarf-warriors", "Hand Weapon", 1)

    lanes = _lanes(dwarf, spearman)

    assert {str(_held(each)[Side.TARGET]) for each in lanes} == {
        "hand-weapon",
        "hand-weapon+shield",
        "thrusting-spear",
        "thrusting-spear+shield",
        "great-weapon",
        "ceremonial-halberd",
    }
    (lane, *_) = lanes
    assert lane.built.program.rules["target/elven-spearmen/armour-bane"].name == "Armour Bane (1)"


def _granting(*grants: tuple[str, dict[str, object]]) -> Loaded:
    rules = dict(REPO.rules)
    for rule, grant in grants:
        printed = rules[rule]
        effects = () if printed.graph is None else printed.graph.effects
        clauses = (
            *(Clause(effect=effect) for effect in effects),
            Clause(effect=Effect.model_validate(grant)),
        )
        rules[rule] = printed.with_graph(RuleGraph(clauses=clauses))
    return load_program(ROUND, rules)


def test_a_rule_a_weapon_grants_is_in_force_only_while_the_weapon_is_held() -> None:
    """Magical Attacks rewritten to grant Strike First sends the halberd to Initiative 10 alone.

    The Ceremonial Halberd gives the Spearmen Magical Attacks, so what it grants
    rides the halberd: with a hand weapon they strike at their own 4.
    """
    program = _granting(("magical-attacks", {"grants": "strike-first", "to": "this-model"}))
    dwarf = _fielded("dwarf-warriors", "Hand Weapon", 1)
    struck = {
        weapon: _fought(
            dwarf,
            _fielded("elven-spearmen", weapon, 1, equipment=("Ceremonial Halberd",), shield=False),
            program=program,
        )
        for weapon in ("Hand Weapon", "Ceremonial Halberd")
    }

    assert {weapon: _strikes_at(fought, Side.TARGET) for weapon, fought in struck.items()} == {
        "Hand Weapon": 4,
        "Ceremonial Halberd": 10,
    }


def _strikes_at(fought: Evaluated, side: Side) -> int:
    return max(
        slot
        for slot in range(10, 0, -1)
        if fought.at(f"round/initiative-{slot}/{side}/how-many-attacks")
        .read("attacks")
        .prob(lambda attacks: attacks > 0)
    )


@pytest.mark.parametrize(
    ("inches", "arc", "slot"),
    [
        pytest.param(2, ChargeArc.FRONT, 6, id="two-inches"),
        pytest.param(5, ChargeArc.FRONT, 7, id="front-at-most-3"),
        pytest.param(5, ChargeArc.FLANK, 8, id="flank-at-most-4"),
        pytest.param(5, ChargeArc.REAR, 8, id="rear-at-most-4"),
    ],
)
def test_a_charge_adds_an_initiative_point_for_each_full_inch_up_to_its_arc_s_cap(
    inches: int, arc: ChargeArc, slot: int
) -> None:
    """An Initiative 4 Spearman that charged strikes at 4 plus its inches, capped by the arc."""
    spearman = _fielded("elven-spearmen", "Hand Weapon", 1)
    dwarf = _fielded("dwarf-warriors", "Hand Weapon", 1)

    fought = _fought(spearman, dwarf, attacker_charges=1, charge_move=inches, enemy_arc=arc)

    assert _strikes_at(fought, Side.ATTACKER) == slot


def test_a_charge_never_takes_initiative_past_10() -> None:
    """A Swordmaster at Initiative 6, +1 by a rule, charging 6" into the rear strikes at 10."""
    swordmaster = _fielded("swordmasters-of-hoeth", "Sword of Hoeth", 1).side
    quickened = (Added(Characteristic.INITIATIVE, 1, of=Side.ATTACKER),)

    (initiatives,) = who_strikes_first(swordmaster, 6, ChargeArc.REAR, quickened).mass

    assert {initiatives.of(part.id) for part in swordmaster.parts} == {10}


def test_a_steed_takes_the_charge_bonus_on_its_own_initiative() -> None:
    """Silver Helms that charged 2" strike at I5 plus 2, and their steeds at I4 plus 2."""
    helms = _fielded("silver-helms", "Lance", 5, frontage=5).side

    (initiatives,) = who_strikes_first(helms, 2, ChargeArc.FRONT, ()).mass

    assert {part.id: initiatives.of(part.id) for part in helms.fighters} == {
        "silver-helm": 7,
        "silver-helm-barded-elven-steed": 6,
    }


@pytest.mark.parametrize(
    ("arc", "points"),
    [
        pytest.param(ChargeArc.FLANK, 1, id="flank"),
        pytest.param(ChargeArc.REAR, 2, id="rear"),
    ],
)
def test_a_side_in_the_enemy_s_flank_or_rear_claims_its_points(
    arc: ChargeArc, points: int
) -> None:
    """One Spearman a side: in the enemy's flank it scores 1 more, in its rear 2 more."""
    spearman = _fielded("elven-spearmen", "Hand Weapon", 1)

    front, behind = (
        set(_fought(spearman, spearman, enemy_arc=each).at(SCORE).read("score").mass)
        for each in (ChargeArc.FRONT, arc)
    )

    assert behind == {score + points for score in front}


MANEATER_WITH_A_GREAT_WEAPON = ("maneaters", "Great Weapon", ("Great Weapon",))


@pytest.mark.parametrize(
    ("hitter", "foe", "slot", "needed"),
    [
        pytest.param(
            MANEATER_WITH_A_GREAT_WEAPON,
            ("ironbreakers", "Hand Weapon", ()),
            "impact-hits",
            ({"3+"}, {"2+"}),
            id="impact-hit-without-the-great-weapon",
        ),
        pytest.param(
            ("maneaters", "Hand Weapon", ()),
            ("merwyrm", "Lashing Talons", ()),
            "impact-hits",
            ({"5+"}, {"6+"}),
            id="impact-hit-without-enfeebling-cold",
        ),
        pytest.param(
            ("merwyrm", "Lashing Talons", ()),
            ("merwyrm", "Lashing Talons", ()),
            "stomp-attacks",
            ({"4+"}, {"5+"}),
            id="stomp-without-enfeebling-cold",
        ),
    ],
)
def test_an_automatic_hit_wounds_at_the_model_s_unmodified_strength(
    hitter: tuple[str, str, tuple[str, ...]],
    foe: tuple[str, str, tuple[str, ...]],
    slot: str,
    needed: tuple[set[str], set[str]],
) -> None:
    """A hit made with no weapon wounds at the model's printed Strength, its blows as moved.

    A Maneater charging 6" hits at S5, where its great weapon strikes at S7; against
    the Merwyrm it hits at S5 where Enfeebling Cold leaves its blows at S4, and a
    Merwyrm stomps another at S6 where its blows strike at S5.
    """
    (unit, weapon, equipment), (enemy, held, worn) = hitter, foe
    attacker = _fielded(unit, weapon, 1, equipment=equipment)
    target = _fielded(enemy, held, 1, equipment=worn)
    charge = 6 if slot == "impact-hits" else 0

    fought = _fought(attacker, target, attacker_charges=int(charge > 0), charge_move=charge)

    part = attacker.side.hit.id
    blow = f"round/initiative-{_strikes_at(fought, Side.ATTACKER)}/attacker/attack/{part}"
    hit = f"round/{slot}/attacker/attack/{part}"
    assert (_needed(fought, f"{hit}/roll-to-wound"), _needed(fought, f"{blow}/roll-to-wound")) == (
        needed
    )


def test_only_the_front_rank_makes_automatic_hits() -> None:
    """Six Maneaters three abreast charge 6": the front three make an impact hit each."""
    maneaters = _fielded("maneaters", "Hand Weapon", 6, frontage=3)
    ironbreaker = _fielded("ironbreakers", "Hand Weapon", 1)

    fought = _fought(
        maneaters, ironbreaker, attacker_standing=6, attacker_charges=1, charge_move=6
    )

    assert fought.at("round/impact-hits/attacker/impact-hits").read("hits").mass == {3: 1}


def test_no_weapon_s_rule_reaches_an_automatic_hit() -> None:
    """A Maneater's impact hit fells an Ironbreaker as often with a great weapon as without.

    The great weapon's Armour Bane rides the weapon, and the hit is made with none.
    """
    ironbreaker = _fielded("ironbreakers", "Hand Weapon", 1)
    unit, weapon, equipment = MANEATER_WITH_A_GREAT_WEAPON

    felled = [
        _fought(maneater, ironbreaker, attacker_charges=1, charge_move=6)
        .at("round/impact-hits/target/remove-casualties")
        .read("models")
        .mass
        for maneater in (
            _fielded("maneaters", "Hand Weapon", 1),
            _fielded(unit, weapon, 1, equipment=equipment),
        )
    ]

    assert felled[0] == felled[1]


def test_the_struck_side_keeps_its_weapon_s_rules_against_an_automatic_hit() -> None:
    """Resolute rewritten to grant Dragon Armour to the hand weapon wards a charged Dwarf.

    The Maneater's impact hit is made with no weapon, but the Dwarf Warrior it
    strikes still holds its hand weapon, so the ward meets the hit on 6+.
    """
    program = _granting(("resolute", {"grants": "dragon-armour", "to": {"weapon": "hand-weapon"}}))
    maneater = _fielded("maneaters", "Hand Weapon", 1)
    dwarf = _fielded("dwarf-warriors", "Hand Weapon", 1)

    fought = _fought(maneater, dwarf, program=program, attacker_charges=1, charge_move=6)

    assert _needed(fought, "round/impact-hits/attacker/attack/maneater/ward-saves") == {"6+"}


def test_a_steed_strikes_beside_its_rider_with_its_own_profile() -> None:
    """Ten Silver Helms with lances against Dwarf Warriors: five riders strike at I5 with S5.

    Their five steeds strike at their own I4 with S3 hooves, so they wound on 5+ where
    the lances wound on 3+, and the lance's Armour Bane never reaches their blows.
    """
    helms = _fielded("silver-helms", "Lance", 10, frontage=5)
    dwarfs = _fielded("dwarf-warriors", "Hand Weapon", 10, frontage=5)
    steed = "round/initiative-4/attacker/attack/silver-helm-barded-elven-steed"
    rider = "round/initiative-5/attacker/attack/silver-helm"

    fought = _fought(helms, dwarfs, attacker_standing=10)

    attacks = [
        fought.at(f"round/initiative-{slot}/attacker/how-many-attacks").read("attacks").mass
        for slot in (5, 4)
    ]
    saves = fought.at(f"{steed}/make-armour-saves").step
    assert attacks == [{5: 1}, {5: 1}]
    assert (
        _needed(fought, f"{rider}/roll-to-wound"),
        _needed(fought, f"{steed}/roll-to-wound"),
    ) == (
        {"3+"},
        {"5+"},
    )
    assert fought.lane.verdicts("attacker/silver-helms/armour-bane", saves).mass == {
        Verdict.HONOURED: 1
    }


def test_a_steed_strikes_only_for_its_rider_still_standing() -> None:
    """Ten Silver Helms five wide that lost two this round strike with three riders, three steeds.

    A casualty comes off the fighting rank first, and its steed's blows go with it.
    """
    helms = _fielded("silver-helms", "Lance", 10, frontage=5)
    dwarfs = _fielded("dwarf-warriors", "Hand Weapon", 10, frontage=5)

    fought = _fought(helms, dwarfs, attacker_standing=8, attacker_at_start=10)

    attacks = [
        fought.at(f"round/initiative-{slot}/attacker/how-many-attacks").read("attacks").mass
        for slot in (5, 4)
    ]
    assert attacks == [{3: 1}, {3: 1}]


def test_wounds_on_a_model_carry_from_one_initiative_to_the_next() -> None:
    """Two Silver Helms fell a lone three-Wound Maneater only with Wounds carried across slots.

    Each rider's lance lands a Wound on 1/3 at I5 (4+, 3+, no save), and each
    steed on 5/36 at I4 (4+, 5+, beating the 6+ save). Neither slot lands three
    alone, so the Maneater falls on two then one or more, or one then two:
    1/9 * 335/1296 + 4/9 * 25/1296 = 145/3888.
    """
    helms = _fielded("silver-helms", "Lance", 2, frontage=2)
    maneater = _fielded("maneaters", "Hand Weapon", 1)

    fought = _fought(helms, maneater, attacker_standing=2)

    standing = fought.at("round/stomp-attacks/target/remove-casualties").read("models")
    assert standing.mass == {0: Fraction(145, 3888), 1: Fraction(3743, 3888)}


def test_a_rule_printed_not_to_reach_mounts_leaves_the_steeds_as_they_are() -> None:
    """In the first round Silver Helms strike at I6 by Elven Reflexes; their steeds keep I4.

    Dragon Princes re-roll their own natural 1s To Hit by Ithilmar Weapons, never
    their steeds'.
    """
    helms = _fielded("silver-helms", "Lance", 5, frontage=5)
    princes = _fielded("dragon-princes", "Hand Weapon", 5, frontage=5)
    dwarfs = _fielded("dwarf-warriors", "Hand Weapon", 10, frontage=5)

    first = _fought(helms, dwarfs, attacker_standing=5, rounds_fought=0)
    reroll = _fought(princes, dwarfs, attacker_standing=5)

    attacks = {
        slot: first.at(f"round/initiative-{slot}/attacker/how-many-attacks").read("attacks").mass
        for slot in (6, 5, 4)
    }
    rider, steed = (
        reroll.at(f"round/initiative-{slot}/attacker/attack/{part}/roll-to-hit").step
        for slot, part in ((5, "dragon-prince"), (4, "dragon-prince-barded-elven-steed"))
    )
    rerolls = "attacker/dragon-princes/ithilmar-weapons"
    assert attacks == {6: {5: 1}, 5: {0: 1}, 4: {5: 1}}
    assert Verdict.APPLIED in reroll.lane.verdicts(rerolls, rider).mass
    assert Verdict.APPLIED not in reroll.lane.verdicts(rerolls, steed).mass


def test_a_stand_and_shoot_volley_thins_the_chargers_from_the_back_and_scores() -> None:
    """Ten Archers stand and shoot at twenty Spearmen charging 5" into them.

    The Spearmen the volley fells come off the back, so the two ranks that fight
    strike whole whatever falls; each Wound it caused counts toward the Archers'
    combat result.
    """
    archers = _fielded("elven-archers", "Hand Weapon", 10)
    spearmen = _fielded("elven-spearmen", "Hand Weapon", 20, frontage=5)
    shooting = Fielding.of(Contingent.field(REPO.units["elven-archers"], 10, data=REPO), "Longbow")
    (stood,) = (
        load_program(STAND_AND_SHOOT, REPO.rules)
        .built({Side.ATTACKER: shooting, Side.TARGET: spearmen.side})
        .evaluate(
            {
                "distance": 0,
                "can-shoot": True,
                "line-of-sight": True,
                "attacker/moved": False,
                "attacker/standing": shooting.standing(10),
                "target/standing": spearmen.side.standing(20),
            }
        )
    )
    left = stood.at("stand-and-shoot/remove-casualties").read("standing")
    knowns = _knowns(spearmen, archers, 20, attacker_charges=1, charge_move=5)
    built = ROUND_PROGRAM.built({Side.ATTACKER: spearmen.side, Side.TARGET: archers.side})
    choices = {Side.ATTACKER: spearmen.held, Side.TARGET: archers.held}

    def started(credited: bool, standing: Standings) -> Knowns:
        at_start = {"attacker/standing": standing, "attacker/standing-at-start-of-round": standing}
        turn = {} if credited else {"attacker/standing-at-start-of-turn": standing}
        return Knowns.of({**knowns, **at_start, **turn})

    (credited,), (uncredited,) = (
        built.evaluate_from(left.map(partial(started, each)), choices) for each in (True, False)
    )

    attacks = credited.at("round/initiative-7/attacker/how-many-attacks").read("attacks")
    scores = [
        each.at("round/target/calculate-combat-result").read("score").expect(int)
        for each in (credited, uncredited)
    ]
    felled = 20 - stood.at("stand-and-shoot/remove-casualties").read("models").expect(int)
    assert len(attacks.mass) == 1
    assert scores[0] - scores[1] == felled > 0


def test_a_rule_also_granted_by_the_unit_is_in_force_whatever_the_weapon() -> None:
    """Magical Attacks granted through Fear and by the halberd: Strike First rides no weapon.

    Valour of Ages grants Fear, Fear grants Magical Attacks, and Magical Attacks
    grants Strike First. The unit's own chain keeps Magical Attacks in force with
    a hand weapon, so the Spearmen strike at 10 with either.
    """
    program = _granting(
        ("valour-of-ages", {"grants": "fear", "to": "this-model"}),
        ("fear", {"grants": "magical-attacks", "to": "this-model"}),
        ("magical-attacks", {"grants": "strike-first", "to": "this-model"}),
    )
    dwarf = _fielded("dwarf-warriors", "Hand Weapon", 1)

    struck = [
        _fought(
            dwarf,
            _fielded("elven-spearmen", weapon, 1, equipment=("Ceremonial Halberd",), shield=False),
            program=program,
        )
        for weapon in ("Hand Weapon", "Ceremonial Halberd")
    ]

    assert [_strikes_at(fought, Side.TARGET) for fought in struck] == [10, 10]


def test_a_rule_granted_to_a_weapon_rides_it_in_combat() -> None:
    """Valour of Ages rewritten to grant Armour Bane (1) to the hand weapon attaches in combat."""
    program = _granting(
        (
            "valour-of-ages",
            {"grants": {"rule": "armour-bane", "X": 1}, "to": {"weapon": "hand-weapon"}},
        )
    )
    spearman = _fielded("elven-spearmen", "Hand Weapon", 1)

    built = program.built({Side.ATTACKER: spearman.side, Side.TARGET: spearman.side})

    assert [
        str(source.item)
        for source in built.program.rules["attacker/elven-spearmen/armour-bane"].sources
    ] == ["hand-weapon"]


def test_the_target_s_part_reads_its_weapon_strength_at_its_own_blow() -> None:
    """A Swordmaster striking back wounds at the Sword of Hoeth's S+2, so 5, not its printed 3.

    At its own roll To Wound the Swordmaster plays the attacker: Strength 5
    against the Spearman's Toughness 3 wounds on 2+.
    """
    spearman = _fielded("elven-spearmen", "Thrusting Spear", 1)
    swordmaster = _fielded("swordmasters-of-hoeth", "Sword of Hoeth", 1)

    wound = _fought(spearman, swordmaster).at(
        "round/initiative-6/target/attack/swordmaster/roll-to-wound"
    )

    assert wound.read("needed").mass == {"2+": 1}


def test_each_weapon_a_side_may_fight_with_is_a_lane() -> None:
    """Spearmen given great weapons and struck by a Dwarf Warrior save as their choice allows.

    Light armour alone saves on 6+, with the shield on 5+, and with a hand
    weapon and shield Parry makes it 4+. Requires Two Hands leaves no lane
    for the great weapon with the shield.
    """
    spearman = _fielded(
        "elven-spearmen", "Great Weapon", 1, equipment=("Great Weapon",), shield=False
    )
    dwarf = _fielded("dwarf-warriors", "Hand Weapon", 1)

    lanes = _lanes(dwarf, spearman)

    saves = "round/initiative-2/attacker/attack/dwarf-warrior/make-armour-saves"
    assert {str(_held(each)[Side.TARGET]): _needed(each, saves) for each in lanes} == {
        "hand-weapon": {"6+"},
        "hand-weapon+shield": {"4+"},
        "thrusting-spear": {"6+"},
        "thrusting-spear+shield": {"5+"},
        "great-weapon": {"6+"},
    }


def test_the_target_s_magical_blows_meet_no_runes_of_protection() -> None:
    """The Swordmasters' magical blows meet no 6+ ward from the Ironbreakers they strike back at.

    The Runes of Protection ward only a non-magical attack, and the attack is the
    Swordmasters' own, not the Ironbreakers'.
    """
    ironbreaker = _fielded("ironbreakers", "Hand Weapon", 1)
    swordmaster = _fielded("swordmasters-of-hoeth", "Sword of Hoeth", 1)

    ward = _fought(ironbreaker, swordmaster).at(
        "round/initiative-6/target/attack/swordmaster/ward-saves"
    )

    assert ward.read("needed").mass == {"-": 1}


def test_a_strength_change_of_the_model_struck_is_held_at_the_blow() -> None:
    """Enfeebling Cold rewritten to lower the Merwyrm's own Strength leaves the Lions' blow alone.

    The White Lions' roll To Wound folds the Strength of the Lions striking: their
    great blade's 6 against Toughness 6 wounds on 4+. The blade strikes last, and
    the Merwyrm's four Attacks before it leave one of a rank of five standing.
    """
    printed = REPO.rules["enfeebling-cold"]
    assert printed.graph is not None
    (effect,) = printed.graph.effects
    own = effect.model_copy(update={"of": Role.THIS_MODEL})
    rules = {
        **REPO.rules,
        "enfeebling-cold": printed.with_graph(RuleGraph(clauses=(Clause(effect=own),))),
    }
    lions = _fielded("white-lions-of-chrace", "Chracian Great Blade", 5, frontage=5)
    merwyrm = _fielded("merwyrm", "Lashing Talons", 1)

    fought = _fought(lions, merwyrm, attacker_standing=5, program=load_program(ROUND, rules))

    wound = fought.at("round/initiative-1/attacker/attack/white-lion/roll-to-wound")
    assert wound.read("needed").mass == {"4+": 1}


WITHOUT_MASSED_INFANTRY = load_program(
    ROUND, {**REPO.rules, "massed-infantry": REPO.rules["massed-infantry"].with_graph(None)}
)


@pytest.mark.parametrize(
    ("program", "lead"),
    [
        pytest.param(ROUND_PROGRAM, 2, id="massed-infantry"),
        pytest.param(WITHOUT_MASSED_INFANTRY, 1, id="without-massed-infantry"),
    ],
)
def test_the_combat_result_scores_the_wounds_and_the_unit_strength_left(
    program: Loaded, lead: int
) -> None:
    """One Elven Spearman a side, striking at once, each falls on 1/6.

    A Spearman that alone fells its foe scores its Wound and, standing at a
    higher Unit Strength, Massed Infantry's +1: it wins by 2, or by 1 without
    the rule. Both falling score a Wound each and draw, as does neither.
    """
    spearman = _fielded("elven-spearmen", "Thrusting Spear", 1)

    won = _fought(spearman, spearman, program=program).at("round/attacker/who-is-the-winner")

    alone = Fraction(5, 36)
    assert won.read("margin").mass == {-lead: alone, 0: 1 - 2 * alone, lead: alone}
    assert won.read("result").mass == {"won": alone, "lost": alone, "drawn": 1 - 2 * alone}


def test_the_combat_result_scores_only_the_wounds_of_this_round() -> None:
    """Spearmen that start the round at twelve of fifteen score the Dwarf nothing for the three.

    The Dwarf scores the one Wound its blow may land, never the casualties the
    Spearmen took before the round.
    """
    spearmen = _fielded("elven-spearmen", "Thrusting Spear", 15, frontage=5)
    dwarf = _fielded("dwarf-warriors", "Hand Weapon", 1)

    fought = _fought(spearmen, dwarf, attacker_standing=12, attacker_at_start=12)

    assert set(fought.at("round/target/calculate-combat-result").read("score").mass) == {0, 1}


def test_the_combat_result_scores_the_wounds_a_standing_model_lost() -> None:
    """An Elven Spearman scores the Wound it lands on a lone three-Wound Maneater that stands.

    It hits on 4+, wounds Toughness 4 on 5+ and beats light armour's 6+ save on
    5/6: it scores 1 on 5/36, though no Maneater falls.
    """
    spearman = _fielded("elven-spearmen", "Thrusting Spear", 1)
    maneater = _fielded("maneaters", "Hand Weapon", 1)

    fought = _fought(spearman, maneater)

    standing = fought.at("round/stomp-attacks/target/remove-casualties").read("models")
    assert standing.mass == {1: 1}
    assert fought.at(SCORE).read("score").mass == {0: Fraction(31, 36), 1: Fraction(5, 36)}


def test_a_side_standing_more_models_than_at_the_start_of_the_round_is_refused() -> None:
    """Spearmen said to stand at twelve after starting the round at ten fail the round."""
    spearmen = _fielded("elven-spearmen", "Thrusting Spear", 15, frontage=5)
    dwarf = _fielded("dwarf-warriors", "Hand Weapon", 1)

    with pytest.raises(ValueError, match="elven-spearman stand more models than at the start"):
        _fought(spearmen, dwarf, attacker_standing=12, attacker_at_start=10)


@pytest.mark.parametrize(
    ("models", "fought"),
    [
        pytest.param((0, 5), Fought.LOST, id="the-wiped-out-side-loses"),
        pytest.param((0, 0), Fought.DRAWN, id="two-wiped-out-sides-draw"),
    ],
)
def test_a_side_wiped_out_loses_whatever_it_scored(
    models: tuple[int, int], fought: Fought
) -> None:
    """A side's 3 against its foe's 1 wins nothing once the side is wiped out."""
    standing, enemy = (Standings((("part", Standing(each, 0)),)) for each in models)

    assert who_is_the_winner(standing, enemy, 3, 1).mass == {fought: 1}


def test_a_loser_more_than_twice_outnumbered_breaks_instead_of_falling_back() -> None:
    """A lone Dwarf beaten by twenty Spearmen breaks wherever it would fall back.

    The Spearmen, at more than twice its Unit Strength whatever falls, turn its
    Fall Back in Good Order into a Break; its Give Ground stands.
    """
    spearmen = _fielded("elven-spearmen", "Thrusting Spear", 20, frontage=5)
    dwarf = _fielded("dwarf-warriors", "Hand Weapon", 1)

    fought = _fought(spearmen, dwarf, attacker_standing=20)

    test = fought.at("round/target/break-test").read("test").mass
    acted = fought.at("round/target/loser-falls-back-in-good-order").read("result").mass
    assert test[BreakTest.FALLS_BACK_IN_GOOD_ORDER] > 0
    assert acted == {
        BreakTest.NOT_TAKEN: test[BreakTest.NOT_TAKEN],
        BreakTest.GIVES_GROUND: test[BreakTest.GIVES_GROUND],
        BreakTest.BREAKS: test[BreakTest.BREAKS] + test[BreakTest.FALLS_BACK_IN_GOOD_ORDER],
    }


@pytest.mark.parametrize(
    ("winners", "acted"),
    [
        pytest.param(10, BreakTest.FALLS_BACK_IN_GOOD_ORDER, id="exactly-twice"),
        pytest.param(11, BreakTest.BREAKS, id="more-than-twice"),
    ],
)
def test_only_a_winner_more_than_twice_the_loser_s_unit_strength_turns_a_fall_back_to_a_break(
    winners: int, acted: BreakTest
) -> None:
    """Five Spearmen left falling back from ten fall back; from eleven, they break."""
    spearmen = _fielded("elven-spearmen", "Thrusting Spear", 20).side

    settled = loser_falls_back_in_good_order(
        spearmen,
        spearmen,
        spearmen.standing(5),
        spearmen.standing(winners),
        BreakTest.FALLS_BACK_IN_GOOD_ORDER,
        (),
    )

    assert settled.mass == {acted: 1}


def test_a_side_wiped_out_takes_no_break_test() -> None:
    """One Elven Spearman a side: whichever falls alone has lost, and no one is left to test."""
    spearman = _fielded("elven-spearmen", "Thrusting Spear", 1)

    fought = _fought(spearman, spearman)

    for side in Side:
        assert fought.at(f"round/{side}/break-test").read("test").mass == {BreakTest.NOT_TAKEN: 1}
