"""A round of close combat on the graph."""

from collections.abc import Mapping
from fractions import Fraction
from typing import NamedTuple

import pytest

from avelorn.core.distribution import Probability
from avelorn.core.graph import Decision
from avelorn.tow.contingent import Contingent
from avelorn.tow.data import TOWRepository
from avelorn.tow.fielding import SHIELD, Fielding, Held
from avelorn.tow.kernels import Standing, Standings
from avelorn.tow.programs import ROUND, Evaluated, Loaded, load_program
from avelorn.tow.schema.effect import Effect, Role
from avelorn.tow.schema.rule import Clause, RuleGraph
from avelorn.tow.schema.stage import Side
from avelorn.tow.steps import NO_ROLL, WEAPON_CHOICE, Fought, who_is_the_winner

REPO = TOWRepository()
ROUND_PROGRAM = load_program(ROUND, REPO.rules)


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


def _lanes(
    attacker: _Armed,
    target: _Armed,
    attacker_standing: int = 1,
    program: Loaded = ROUND_PROGRAM,
    attacker_charges: int = 0,
    wielding: bool = False,
    attacker_at_start: int | None = None,
) -> tuple[Evaluated, ...]:
    built = program.built({Side.ATTACKER: attacker.side, Side.TARGET: target.side})
    choices = {Side.ATTACKER: attacker.held, Side.TARGET: target.held}
    fielded = sum(part.count for part in attacker.side.parts)
    at_start = fielded if attacker_at_start is None else attacker_at_start
    target_standing = target.side.standing(sum(part.count for part in target.side.parts))
    return built.evaluate(
        {
            "attacker/standing": attacker.side.standing(attacker_standing),
            "target/standing": target_standing,
            "attacker/standing-at-start-of-round": attacker.side.standing(at_start),
            "target/standing-at-start-of-round": target_standing,
            "attacker/rounds-fought": 1,
            "target/rounds-fought": 1,
            "attacker/charges-made": attacker_charges,
            "target/charges-made": 0,
        },
        choices if wielding else {},
    )


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
) -> Evaluated:
    (fought,) = _lanes(
        attacker, target, attacker_standing, program, attacker_charges, True, attacker_at_start
    )
    return fought


def _falls(fought: Evaluated, side: Side) -> Probability:
    return fought.at(f"round/initiative-1/{side}/remove-casualties").read("models").mass[0]


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
    assert paths[:6] == [
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
