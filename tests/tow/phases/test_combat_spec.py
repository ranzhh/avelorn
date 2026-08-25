"""One end-to-end specification for a round of close combat.

The single test here is the spec the combat rewrite is built against. Each
entry in :data:`CHECKS` pins one printed rule or one modifiable point, named
after what it asserts, and returns ``(actual, expected)``. Two halves:

- **What the page says** — the printed sequence, from who strikes first to the
  Break test, sourced against the Combat phase chapter on tow.whfb.app and the
  rulebook FAQ & Errata (v1.5.3), which settles the ordering questions the
  chapter leaves open.
- **What data can reach** — every seam a rule is allowed to move. A modifiable
  point that no authored rule can shift is not a seam, it is a hard-coded
  number, so each of these asserts that a synthetic rule both *moves the maths*
  and *is reported factored*.

Three rows of the combat-result table are absent, not overlooked: a Standard
and a Battle Standard need a fielded command group, which a
:class:`~avelorn.tow.contingent.Contingent` carries no state for; the high
ground needs terrain; and Overkill needs challenges. A check asserting only
that an API does not exist states nothing about the rules, so they are recorded
here instead of written as fake gaps.

:data:`KNOWN_GAPS` names the checks that do not hold yet. The test asserts
those still fail, so a gap cannot be quietly fixed and left in the set, nor
silently regress once it leaves. Implementing a part of the rewrite means
moving its name out of the set — that is what "growing the test" looks like.
"""

from collections.abc import Callable
from fractions import Fraction

from avelorn.core.registry import Registry
from avelorn.tow.contingent import Charge, ChargeArc, Contingent
from avelorn.tow.data import TOWRepository
from avelorn.tow.game import TOWGame
from avelorn.tow.phases.combat import (
    CombatResult,
    FightResult,
    StrikeResult,
    break_test,
    combat_result,
    strike_unit,
)
from avelorn.tow.schema.rule import (
    HitsEffect,
    ModifierEffect,
    RerollEffect,
    Rule,
    RuleEffect,
    WoundMultiplierEffect,
)
from avelorn.tow.schema.unit import Characteristic as C
from avelorn.tow.schema.unit import Unit
from avelorn.tow.schema.weapon import Weapon, WeaponProfile

# WS4 vs WS4 is 4+, S3 vs T3 is 4+, and a stripped target has no save, so every
# attack below is an exact 1/4 to land an unsaved wound. Every expectation in
# this file is derived from that quarter and the model counts, never read off
# the engine.
P_UNSAVED = Fraction(1, 4)
# The width every body is fielded at. Regular Infantry fights two ranks deep
# (Press of Battle), so 5 models throw 5 attacks and 15 throw 10 -- both pinned
# by `the-fixture-throws-what-it-states` rather than inherited from a datasheet.
FRONTAGE = 5


def _rule(name: str, effect: RuleEffect) -> Rule:
    return Rule(id=name.lower().replace(" ", "-"), name=name, paragraphs=["…"], effects=[effect])


def _mod(payload: dict) -> ModifierEffect:
    return ModifierEffect.model_validate({"when": {"combat": True}, **payload})


# One synthetic rule per modifiable point, each the smallest thing that moves
# its seam. `multiplies` is absent: a wound multiplier is read off the weapon
# in use, so it rides on a weapon profile below rather than on a unit.
DOCTORED: dict[str, Rule] = {
    "to-hit": _rule("Doctored To Hit", _mod({"add": {"to-hit": 1}})),
    "armour-piercing": _rule("Doctored AP", _mod({"add": {"armour-piercing": 1}})),
    "weapon-skill": _rule("Doctored WS", _mod({"add": {"WS": 2}})),
    "strength": _rule("Doctored S", _mod({"add": {"S": 2}})),
    "initiative": _rule("Doctored I", _mod({"add": {"I": 3}})),
    "attacks": _rule("Doctored A", _mod({"add": {"A": 1}})),
    "leadership": _rule("Doctored Ld", _mod({"add": {"Ld": 2}})),
    "enemy-strength": _rule("Doctored Enemy S", _mod({"enemy": True, "add": {"S": -2}})),
    "armour-value": _rule("Doctored Armour", _mod({"add": {"armour-value": 1}})),
    "ward-save": _rule("Doctored Ward", _mod({"set": {"ward-save": 5}})),
    "fighting-ranks": _rule("Doctored Ranks", _mod({"add": {"fighting-ranks": 1}})),
    "combat-result": _rule("Doctored Points", _mod({"add": {"combat-result": 1}})),
    "reroll": _rule(
        "Doctored Reroll",
        RerollEffect.model_validate(
            {"when": {"combat": True}, "reroll": "roll-to-hit", "of": "failed"}
        ),
    ),
    "automatic-hits": _rule(
        "Doctored Stomp",
        HitsEffect.model_validate({"hits": 2, "order": "last"}),
    ),
}

MULTIPLIER = _rule("Doctored Multiplier", WoundMultiplierEffect.model_validate({"multiplies": 2}))


class _Field:
    """The doctored corpus every check fights in."""

    def __init__(self) -> None:
        repo = TOWRepository()
        self._base = repo.units["elven-spearmen"]
        blade = Weapon(
            id="doctored-blade",
            name="Doctored Blade",
            profiles=[
                WeaponProfile.model_validate(
                    {"R": "Combat", "S": "S", "AP": "-", "special_rules": [MULTIPLIER.name]}
                )
            ],
        )
        repo.weapons = Registry([*repo.weapons.values(), blade], kind="weapon")
        repo.rules = Registry([*repo.rules.values(), *DOCTORED.values(), MULTIPLIER], kind="rule")
        self._repo = repo
        self._units: dict[tuple, Unit] = {}

    def unit(
        self,
        *,
        wounds: int = 1,
        initiative: int = 4,
        attacks: int = 1,
        rules: tuple[str, ...] = (),
        blade: bool = False,
        armoured: bool = False,
    ) -> Unit:
        """A stripped spearman body with the characteristics and rules asked for.

        Returns:
            The doctored unit, registered in the corpus every check fights in.
        """
        key = (wounds, initiative, attacks, rules, blade, armoured)
        if key in self._units:
            return self._units[key]
        equipment = ["Doctored Blade"] if blade else ["Hand Weapon"]
        if armoured:
            equipment.append("Heavy Armour")
        unit = self._base.model_copy(
            deep=True,
            update={
                "id": f"u{len(self._units)}",
                "name": f"u{len(self._units)}",
                "equipment": equipment,
                "special_rules": [*self._base.special_rules, *rules],
            },
        )
        unit.profiles[0].characteristics[C.WOUNDS] = wounds
        unit.profiles[0].characteristics[C.INITIATIVE] = initiative
        unit.profiles[0].characteristics[C.ATTACKS] = attacks
        self._units[key] = unit
        self._repo.units = Registry([*self._repo.units.values(), unit], kind="unit")
        return unit

    def passive(self, *, wounds: int = 1) -> Unit:
        """A body that absorbs and never replies: Attacks 0, so it throws none.

        Returns:
            The dummy target.
        """
        return self.unit(attacks=0, wounds=wounds)

    def field(self, unit: Unit, models: int) -> Contingent:
        """Field a body at the pinned frontage, wielding whatever it carries.

        Returns:
            The fielded contingent.
        """
        weapon = "Doctored Blade" if "Doctored Blade" in unit.equipment else "Hand Weapon"
        return Contingent.field(unit, models, data=self._repo, frontage=FRONTAGE).wielding(weapon)

    def strike(self, a: Unit, b: Unit, a_models: int = 5, b_models: int = 30) -> StrikeResult:
        """One side striking, so the target numbers and per-attack odds are read bare.

        Returns:
            The strike's result.
        """
        return strike_unit(self.field(a, a_models), self.field(b, b_models))

    def fight(self, a: Unit, b: Unit, a_models: int = 5, b_models: int = 5) -> FightResult:
        """One round between two fielded bodies.

        Returns:
            The round's result.
        """
        with TOWGame.assemble(self._repo).turn().combat() as combat:
            return combat.fight(self.field(a, a_models), self.field(b, b_models))


def _mean(pmf: list) -> Fraction:
    """The mean of a pmf indexed by outcome, exact over the round's own masses.

    Returns:
        The mean outcome.
    """
    return Fraction(sum(Fraction(k) * mass for k, mass in enumerate(pmf)))


def _margin(result: FightResult) -> Fraction:
    """The mean signed combat-result margin, A's Wounds inflicted minus B's.

    Returns:
        The mean margin, positive where A is ahead.
    """
    return Fraction(sum(Fraction(diff) * mass for diff, mass in result.scoring_wounds.items()))


def _scored_margin(result: FightResult) -> Fraction:
    """The mean signed margin after Rank Bonus and rule-granted points.

    Returns:
        The mean scored margin, positive where A is ahead.
    """
    return Fraction(
        sum(Fraction(lead) * mass for lead, mass in combat_result(result).margin.items())
    )


# --- what the page says ---


def _the_fixture_throws_what_it_states(f: _Field) -> tuple:
    # Every expectation below rests on these: 5 models at frontage 5 throw 5
    # attacks, 15 throw 10 (Regular Infantry fights two ranks deep), and a bare
    # attack is 4+ To Hit, 4+ To Wound, no save. Pinned so a datasheet change
    # breaks here and not in twenty derived numbers.
    plain, dummy = f.unit(), f.passive()
    five, fifteen = f.strike(plain, dummy, 5), f.strike(plain, dummy, 15)
    return (
        (five.attacks, fifteen.attacks, five.hit_target, five.wound_target, five.save_target),
        (5, 10, 4, 4, None),
    )


def _initiative_orders_the_blows(f: _Field) -> tuple:
    # who-strikes-first: the higher Initiative swings first.
    quick, slow = f.unit(initiative=6), f.unit(initiative=4)
    striker = f.fight(quick, slow).first_striker
    return (striker.unit.name if striker is not None else None), quick.name


def _equal_initiative_is_simultaneous(f: _Field) -> tuple:
    # simultaneous-combat: "Casualties caused by the active player during
    # simultaneous combat do not reduce the number of attacks made by enemy
    # models with the same Initiative value." Both sides at I4, so each throws
    # its full 5 attacks and scores 5/4 -- a wash, and no first striker.
    plain = f.unit()
    result = f.fight(plain, plain)
    return (result.first_striker, _margin(result)), (None, Fraction(0))


def _a_thinned_body_strikes_back_with_fewer(f: _Field) -> tuple:
    # fight-on: the slower side replies from its survivors. One model each, the
    # quick one at I6 against a 1-Wound body: it replies only when it lives, so
    # its 1/4 is scaled by the 3/4 chance it survived -- 3/16, not 1/4.
    quick, slow = f.unit(initiative=6), f.unit(initiative=4)
    return _margin(f.fight(quick, slow, 1, 1)), Fraction(1, 4) - Fraction(3, 16)


def _a_stepped_forward_model_cannot_attack(f: _Field) -> tuple:
    # FAQ v1.5.3: "casualties inflicted reduce, firstly, the number of models in
    # the fighting rank(s) that are able to fight (starting with the first
    # fighting rank) and, secondly, the number of models in the 'supporting
    # rank' that are able to fight." And separately: "Q: ... can I remove
    # casualties from the second rank? A: No. Models in the first fighting rank,
    # the rank in base contact with the enemy, fall first as casualties."
    #
    # 15 models throw 10 attacks. Three casualties take three of those away.
    # The engine spends its rearmost rank instead and keeps all 10.
    plain, dummy = f.unit(), f.passive()
    body = f.field(plain, 15)
    return strike_unit(body.remove_casualties(3), f.field(dummy, 30)).attacks, 7


def _wounds_carry_across_initiative_steps(f: _Field) -> tuple:
    # remove-casualties-combat: each unsaved wound costs the unit a Wound and
    # the tally continues "until there are no more unsaved wounds to be
    # applied", so a model wounded at one Initiative step meets the next step
    # already hurt. FAQ v1.5.3 says the same: "one at a time and one model at
    # a time".
    #
    # One model a side, the target on 3 Wounds. The striker lands at most 1
    # wound with its attack and at most 2 with its closing stomp. Resolving each
    # step against a fresh model can never reach 3, so a reset fells nothing
    # whatever the dice; carrying the tally fells the model whenever all three
    # land. Any mass at all means the wounds carried.
    stomper = f.unit(initiative=6, rules=("Doctored Stomp",))
    return _mean(f.fight(stomper, f.passive(wounds=3), 1, 1).b_casualties) > 0, True


def _kill_outright_wounds_are_applied_first(f: _Field) -> tuple:
    # FAQ v1.5.3: "apply unsaved wounds that cause models to lose all of their
    # remaining Wounds first (Killing Blows and Monster Slaying Blows, for
    # example), then unsaved wounds that cause multiple Wounds to be lost
    # (Multiple Wounds (X), for example), then, finally, unsaved wounds that
    # cause a single Wound to be lost."
    #
    # Two attacks from a Killing Blow bearer wielding a doubling blade, into
    # 3-Wound models. Per attack: 3/4 nothing, 1/6 a plain wound (hit, then a
    # 4 or 5 To Wound), 1/12 a Killing Blow (hit, then a natural 6). Wounds
    # scored, in the printed order: one plain 2, one blow 3, two plain 3 (the
    # second is capped by what the first left), a blow and a plain 5, two blows
    # 6. Over 144 branches that is (2*36 + 3*18 + 3*4 + 5*4 + 6)/144 = 41/36.
    # Arrival order would spend the doubled wound first and leave the blow one
    # Wound to take, reading 13/12.
    slayer = f.unit(rules=("Killing Blow",), blade=True)
    return _margin(f.fight(slayer, f.passive(wounds=3), 2, 5)), Fraction(41, 36)


def _multiple_wounds_multiplies_each_wound(f: _Field) -> tuple:
    # multiple-wounds: each unsaved wound costs two Wounds. Against 2-Wound
    # models that is the whole model, so 5 attacks at a quarter score 5/2.
    return _margin(f.fight(f.unit(blade=True), f.passive(wounds=2), 5, 30)), Fraction(5, 2)


def _excess_wounds_do_not_spill_over(f: _Field) -> tuple:
    # hits-that-inflict-multiple-wounds: "A model cannot suffer more wounds than
    # it has on its profile. Should a model do so, it dies instantly and any
    # excess wounds are wasted." Against 1-Wound models a doubled wound scores
    # one, not two, and nothing passes to the next model.
    return _margin(f.fight(f.unit(blade=True), f.passive(), 5, 30)), 5 * P_UNSAVED


def _the_score_counts_wounds_not_casualties(f: _Field) -> tuple:
    # unsaved-wounds-inflicted: "count the number of Wounds lost, rather than
    # the number of casualties". 5 attacks at a quarter, doubled, into 3-Wound
    # models: the wounds absorbed for 0..5 unsaved wounds are 0, 2, 3, 5, 6, 8,
    # which over the binomial is 271/128. Counting models removed would read
    # 49/128 -- the same fight, a different winner.
    return _margin(f.fight(f.unit(blade=True), f.passive(wounds=3), 5, 30)), Fraction(271, 128)


def _a_wiped_out_side_loses_the_round(f: _Field) -> tuple:
    # calculate-combat-result: "If one side has been completely wiped out, the
    # other side is automatically the winner, regardless of the rules that
    # follow." So the foe wins at least as often as this side is wiped out. A
    # lone doubling model against 3-Wound bodies trades up before it dies, and
    # some of that mass currently wins the round while dead.
    result = f.fight(f.unit(blade=True), f.unit(wounds=3), 1, 5)
    return combat_result(result).p_b_wins >= _mean(result.a_casualties), True


def _equal_scores_draw(f: _Field) -> tuple:
    # drawn-combat: a mirror match must leave real mass on a drawn round.
    plain = f.unit()
    return combat_result(f.fight(plain, plain)).p_draw > 0, True


def _the_rank_bonus_scores(f: _Field) -> tuple:
    # rank-bonus: "+1 for each extra rank behind the first, up to the maximum
    # determined by its troop type". 15 models at frontage 5 are three ranks, so
    # two behind the first, and Regular Infantry caps at two. One rank claims
    # none.
    plain = f.unit()
    fought = f.fight(plain, plain, 15, 5)
    return (fought.a_rank_bonus, fought.b_rank_bonus), (2, 0)


def _outnumbering_scores_massed_infantry(f: _Field) -> tuple:
    # combat-result-score: "Massed Infantry +1 point if higher Unit Strength".
    # 15 models against 5, both Regular Infantry, so the wider body claims it
    # and the other does not.
    plain = f.unit()
    fought = f.fight(plain, plain, 15, 5)
    return (fought.a_combat_result_bonus, fought.b_combat_result_bonus), (1, 0)


def _the_score_adds_the_bonuses_to_the_wounds(f: _Field) -> tuple:
    # combat-result-score: the score is the wounds plus the Rank Bonus plus the
    # rule-granted points. 15 against 5 claims two ranks and Massed Infantry, so
    # the scored margin sits exactly three above the wounds margin.
    plain = f.unit()
    fought = f.fight(plain, plain, 15, 5)
    return _scored_margin(fought) - _margin(fought), Fraction(3)


def _a_flank_attack_scores(f: _Field) -> tuple:
    # combat-result-score: "Flank attack +1 point". A charge into the flank is
    # expressible -- the arc rides on the charge -- so the round it forms must
    # score it.
    return _arc_bonus(f, ChargeArc.FLANK), 1


def _a_rear_attack_scores(f: _Field) -> tuple:
    # combat-result-score: "Rear attack +2 points".
    return _arc_bonus(f, ChargeArc.REAR), 2


def _arc_bonus(f: _Field, arc: ChargeArc) -> int:
    # The combat-result points the charging side claims for the arc it hit.
    plain = f.unit()
    game = TOWGame.assemble(f._repo)
    with game.turn().movement() as movement:
        engagement = movement.charge(f.field(plain, 5), f.field(plain, 5), Charge(6, arc))
    with game.turn().combat() as combat:
        return combat.fight(engagement).a_combat_result_bonus


def _the_break_test_rolls_the_printed_bands(f: _Field) -> tuple:
    # break-test: 2D6 against the loser's Leadership, the winner's margin added.
    # A natural above Leadership Breaks; a natural within it but a modified roll
    # above Falls Back; the rest Gives Ground, as does a natural double 1.
    # At Ld8 losing by 2: naturals 9-12 Break (10 of 36), 7-8 Fall Back
    # (11 of 36), 2-6 Give Ground (15 of 36).
    plain = f.unit()
    lost_by_two = CombatResult(
        p_a_wins=Fraction(1), p_draw=Fraction(0), p_b_wins=Fraction(0), margin={2: Fraction(1)}
    )
    side = break_test(lost_by_two, f.field(plain, 5), f.field(plain, 5)).b
    return (
        (side.p_breaks, side.p_falls_back, side.p_gives_ground),
        (Fraction(10, 36), Fraction(11, 36), Fraction(15, 36)),
    )


def _only_the_loser_takes_a_break_test(f: _Field) -> tuple:
    # break-test: the winner never rolls, so the two sides' outcomes and the
    # drawn mass partition the round.
    plain = f.unit()
    scored = combat_result(f.fight(plain, plain))
    broken = break_test(scored, f.field(plain, 5), f.field(plain, 5))
    return (
        broken.a.p_gives_ground
        + broken.a.p_falls_back
        + broken.a.p_breaks
        + broken.b.p_gives_ground
        + broken.b.p_falls_back
        + broken.b.p_breaks
        + broken.p_draw
    ), Fraction(1)


# --- what a rule can state ---

# Each seam, with the exact figure the rule's own words demand. A seam is not
# "somewhere the outcome moved" -- it is a stated amount, so a wrong magnitude
# is as much a failure as a dead hook. Every figure is derived from the bare
# 4+/4+/no-save fixture, never read off the engine.
#
# `Doctored WS` is +2, taking WS4 to WS6 against WS4: the chart hits on 3+.
# `Doctored S` is +2, taking S3 to S5 against T3: wounds on 2+.
# `Doctored Enemy S` is -2 on the foe, dropping the striker to S1 against T3:
# wounds on 6+. Heavy armour is a 5+ save, so the armoured baseline is
# 1/4 * 2/3 = 1/6; +1 armour value makes it 4+ (1/8), and -1 armour piercing
# makes it 6+ (5/24).


def _reaches_to_hit(f: _Field) -> tuple:
    # "a +1 To Hit modifier": the 4+ becomes 3+, so 2/3 * 1/2 = 1/3.
    strike = f.strike(f.unit(rules=(DOCTORED["to-hit"].name,)), f.passive())
    return (strike.hit_target, strike.p_unsaved), (3, Fraction(1, 3))


def _reaches_weapon_skill(f: _Field) -> tuple:
    # WS6 against WS4 hits on 3+.
    strike = f.strike(f.unit(rules=(DOCTORED["weapon-skill"].name,)), f.passive())
    return (strike.hit_target, strike.p_unsaved), (3, Fraction(1, 3))


def _reaches_strength(f: _Field) -> tuple:
    # S5 against T3 wounds on 2+, so 1/2 * 5/6 = 5/12.
    strike = f.strike(f.unit(rules=(DOCTORED["strength"].name,)), f.passive())
    return (strike.wound_target, strike.p_unsaved), (2, Fraction(5, 12))


def _reaches_enemy_strength(f: _Field) -> tuple:
    # The foe's rule drops the striker to S1 against T3: wounds on 6+.
    target = f.unit(attacks=0, rules=(DOCTORED["enemy-strength"].name,))
    strike = f.strike(f.unit(), target)
    return (strike.wound_target, strike.p_unsaved), (6, Fraction(1, 12))


def _reaches_armour_piercing(f: _Field) -> tuple:
    # A 5+ save worsened by 1 is a 6+: 1/4 * 5/6 = 5/24, against the armoured
    # baseline of 1/6.
    armoured = f.unit(attacks=0, armoured=True)
    bare = f.strike(f.unit(), armoured).p_unsaved
    pierced = f.strike(f.unit(rules=(DOCTORED["armour-piercing"].name,)), armoured).p_unsaved
    return (bare, pierced), (Fraction(1, 6), Fraction(5, 24))


def _reaches_armour_value(f: _Field) -> tuple:
    # The foe's 5+ save improved by 1 is a 4+: 1/4 * 1/2 = 1/8.
    target = f.unit(attacks=0, armoured=True, rules=(DOCTORED["armour-value"].name,))
    strike = f.strike(f.unit(), target)
    return (strike.save_target, strike.p_unsaved), (4, Fraction(1, 8))


def _reaches_ward_save(f: _Field) -> tuple:
    # A 5+ ward turns aside a third: 1/4 * 2/3 = 1/6.
    target = f.unit(attacks=0, rules=(DOCTORED["ward-save"].name,))
    strike = f.strike(f.unit(), target)
    return (strike.ward_target, strike.p_unsaved), (5, Fraction(1, 6))


def _reaches_reroll(f: _Field) -> tuple:
    # Re-rolling failed To Hit takes 1/2 to 3/4, so 3/4 * 1/2 = 3/8.
    return f.strike(f.unit(rules=(DOCTORED["reroll"].name,)), f.passive()).p_unsaved, Fraction(
        3, 8
    )


def _reaches_attacks(f: _Field) -> tuple:
    # "+1 Attack": 5 models at A2 throw 10.
    return f.strike(f.unit(rules=(DOCTORED["attacks"].name,)), f.passive()).attacks, 10


def _reaches_fighting_ranks(f: _Field) -> tuple:
    # A third fighting rank: 15 models at frontage 5 throw all 15.
    doctored = f.unit(rules=(DOCTORED["fighting-ranks"].name,))
    return f.strike(doctored, f.passive(), 15).attacks, 15


def _reaches_initiative(f: _Field) -> tuple:
    # +3 Initiative takes I4 past a plain I4, so the bearer strikes first.
    doctored = f.unit(rules=(DOCTORED["initiative"].name,))
    striker = f.fight(doctored, f.unit()).first_striker
    return (striker.unit.name if striker is not None else None), doctored.name


def _reaches_automatic_hits(f: _Field) -> tuple:
    # Two automatic hits per model, struck after every Initiative step: 5 models
    # land 10 hits that skip To Hit and wound on 4+, so 5 Wounds on top of the
    # 5/4 the attacks themselves score.
    doctored = f.unit(rules=(DOCTORED["automatic-hits"].name,))
    return _margin(f.fight(doctored, f.passive(), 5, 30)), Fraction(25, 4)


def _reaches_the_multiplier(f: _Field) -> tuple:
    # The weapon's own seam: each unsaved wound worth two, against 2-Wound
    # models, so 5 attacks at a quarter score 5/2.
    return _margin(f.fight(f.unit(blade=True), f.passive(wounds=2), 5, 30)), Fraction(5, 2)


def _reaches_combat_result(f: _Field) -> tuple:
    # "+1 combat result point": the scored margin gains exactly one over the
    # wounds margin the same fight produces.
    doctored = f.unit(rules=(DOCTORED["combat-result"].name,))
    without = _scored_margin(f.fight(f.unit(), f.passive(), 5, 30))
    return _scored_margin(f.fight(doctored, f.passive(), 5, 30)) - without, Fraction(1)


def _reaches_leadership(f: _Field) -> tuple:
    # +2 Leadership, read where the loser rolls. At Ld10 losing by 2: naturals
    # 11-12 Break (3 of 36), 9-10 Fall Back (7 of 36), 2-8 Give Ground (26).
    doctored = f.unit(rules=(DOCTORED["leadership"].name,))
    lost_by_two = CombatResult(
        p_a_wins=Fraction(1), p_draw=Fraction(0), p_b_wins=Fraction(0), margin={2: Fraction(1)}
    )
    side = break_test(lost_by_two, f.field(f.unit(), 5), f.field(doctored, 5)).b
    return (
        (side.p_breaks, side.p_falls_back, side.p_gives_ground),
        (Fraction(3, 36), Fraction(7, 36), Fraction(26, 36)),
    )


CHECKS: dict[str, Callable[[_Field], tuple]] = {
    # the fixture's own premises
    "the-fixture-throws-what-it-states": _the_fixture_throws_what_it_states,
    # the printed sequence
    "initiative-orders-the-blows": _initiative_orders_the_blows,
    "equal-initiative-is-simultaneous": _equal_initiative_is_simultaneous,
    "a-thinned-body-strikes-back-with-fewer": _a_thinned_body_strikes_back_with_fewer,
    "a-stepped-forward-model-cannot-attack": _a_stepped_forward_model_cannot_attack,
    "wounds-carry-across-initiative-steps": _wounds_carry_across_initiative_steps,
    "kill-outright-wounds-are-applied-first": _kill_outright_wounds_are_applied_first,
    "multiple-wounds-multiplies-each-wound": _multiple_wounds_multiplies_each_wound,
    "excess-wounds-do-not-spill-over": _excess_wounds_do_not_spill_over,
    "the-score-counts-wounds-not-casualties": _the_score_counts_wounds_not_casualties,
    "a-wiped-out-side-loses-the-round": _a_wiped_out_side_loses_the_round,
    "equal-scores-draw": _equal_scores_draw,
    "the-rank-bonus-scores": _the_rank_bonus_scores,
    "outnumbering-scores-massed-infantry": _outnumbering_scores_massed_infantry,
    "the-score-adds-the-bonuses-to-the-wounds": _the_score_adds_the_bonuses_to_the_wounds,
    "a-flank-attack-scores": _a_flank_attack_scores,
    "a-rear-attack-scores": _a_rear_attack_scores,
    "the-break-test-rolls-the-printed-bands": _the_break_test_rolls_the_printed_bands,
    "only-the-loser-takes-a-break-test": _only_the_loser_takes_a_break_test,
    # what a rule can state
    "reaches-to-hit": _reaches_to_hit,
    "reaches-weapon-skill": _reaches_weapon_skill,
    "reaches-strength": _reaches_strength,
    "reaches-enemy-strength": _reaches_enemy_strength,
    "reaches-armour-piercing": _reaches_armour_piercing,
    "reaches-armour-value": _reaches_armour_value,
    "reaches-ward-save": _reaches_ward_save,
    "reaches-reroll": _reaches_reroll,
    "reaches-attacks": _reaches_attacks,
    "reaches-fighting-ranks": _reaches_fighting_ranks,
    "reaches-initiative": _reaches_initiative,
    "reaches-automatic-hits": _reaches_automatic_hits,
    "reaches-the-multiplier": _reaches_the_multiplier,
    "reaches-combat-result": _reaches_combat_result,
    "reaches-leadership": _reaches_leadership,
}

# Checks the engine does not satisfy yet. The test asserts each still fails, so
# a gap can neither be quietly fixed and left here nor regress once it leaves.
KNOWN_GAPS = frozenset(
    {
        "a-stepped-forward-model-cannot-attack",
        "wounds-carry-across-initiative-steps",
        "a-wiped-out-side-loses-the-round",
        # One root cause: `effective_attacks` and `effective_fighting_ranks`
        # read against Contingent._charge_context(), which carries movement and
        # equipment but no `combat` entity, so a rule gated on the engagement
        # is honoured as not-applying. Ungated, the same rule lands.
        "reaches-attacks",
        "reaches-fighting-ranks",
    }
)


def test_a_round_of_close_combat() -> None:
    """Every printed rule of the Combat phase, and every amount a rule can state.

    One test, one fixture, one pass over :data:`CHECKS`. A name in
    :data:`KNOWN_GAPS` must still fail; every other must hold.
    """
    field = _Field()
    held: list[str] = []
    failed: dict[str, tuple] = {}
    for name, check in CHECKS.items():
        try:
            actual, expected = check(field)
        except Exception as err:  # a seam that cannot even be reached is a failure
            failed[name] = (f"raised {type(err).__name__}: {err}", "no error")
            continue
        if actual == expected:
            held.append(name)
        else:
            failed[name] = (actual, expected)

    regressed = {n: v for n, v in failed.items() if n not in KNOWN_GAPS}
    assert not regressed, "\n".join(
        f"{n}: got {a!r}, want {e!r}" for n, (a, e) in regressed.items()
    )

    fixed = KNOWN_GAPS.intersection(held)
    assert not fixed, f"now passing -- take out of KNOWN_GAPS: {sorted(fixed)}"

    assert set(CHECKS) == set(held) | set(failed)
