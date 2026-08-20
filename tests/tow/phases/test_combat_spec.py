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

:data:`KNOWN_GAPS` names the checks that do not hold yet. The test asserts
those still fail, so a gap cannot be quietly fixed and left in the set, nor
silently regress once it leaves. Implementing a part of the rewrite means
moving its name out of the set — that is what "growing the test" looks like.
"""

from collections.abc import Callable
from fractions import Fraction

from avelorn.core.distribution import Distribution
from avelorn.core.registry import Registry
from avelorn.tow.data import TOWRepository
from avelorn.tow.engine.casualties import AttackBatch, Toll, strike_toll
from avelorn.tow.game import TOWGame
from avelorn.tow.phases.combat import FightResult, break_test, combat_result
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
        base = repo.units["elven-spearmen"]
        self._base = base
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
        self.game = TOWGame.assemble(repo)

    def unit(
        self,
        *,
        wounds: int = 1,
        initiative: int = 4,
        rules: tuple[str, ...] = (),
        blade: bool = False,
        armoured: bool = False,
    ) -> Unit:
        """A stripped spearman body with the characteristics and rules asked for.

        Returns:
            The doctored unit, registered in the corpus every check fights in.
        """
        key = (wounds, initiative, rules, blade, armoured)
        if key in self._units:
            return self._units[key]
        equipment = ["Doctored Blade"] if blade else ["Hand Weapon"]
        if armoured:
            equipment.append("Heavy Armour")
        slug = "u" + str(abs(hash(key)))
        unit = self._base.model_copy(
            deep=True,
            update={
                "id": slug,
                "name": slug,
                "equipment": equipment,
                "special_rules": [*self._base.special_rules, *rules],
            },
        )
        unit.profiles[0].characteristics[C.WOUNDS] = wounds
        unit.profiles[0].characteristics[C.INITIATIVE] = initiative
        self._units[key] = unit
        self._repo.units = Registry([*self._repo.units.values(), unit], kind="unit")
        self.game = TOWGame.assemble(self._repo)
        return unit

    def fight(self, a: Unit, b: Unit, a_models: int = 5, b_models: int = 5) -> FightResult:
        """One round between two fielded bodies, each swinging what it carries.

        Returns:
            The round's result.
        """
        a_weapon = "Doctored Blade" if "Doctored Blade" in a.equipment else "Hand Weapon"
        b_weapon = "Doctored Blade" if "Doctored Blade" in b.equipment else "Hand Weapon"
        with self.game.turn().combat() as combat:
            return combat.fight(
                self.game.field(a, a_models).wielding(a_weapon),
                self.game.field(b, b_models).wielding(b_weapon),
            )


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


def _support(toll) -> tuple:
    """The outcomes a toll actually reaches; Distribution keeps zero-mass keys.

    Returns:
        The reachable outcomes, in insertion order.
    """
    return tuple(entry for entry, mass in toll.mass.items() if mass)


# --- what the page says -------------------------------------------------------


def _initiative_orders_the_blows(f: _Field) -> tuple:
    # who-strikes-first: the higher Initiative swings first.
    quick, slow = f.unit(initiative=6), f.unit(initiative=4)
    striker = f.fight(quick, slow).first_striker
    return (striker.unit.name if striker is not None else None), quick.name


def _equal_initiative_is_simultaneous(f: _Field) -> tuple:
    # simultaneous-combat: neither side's casualties reduce the other's attacks,
    # so both throw their full 5 attacks at a quarter each.
    plain = f.unit()
    result = f.fight(plain, plain)
    return (result.first_striker, _margin(result)), (None, Fraction(0))


def _each_side_throws_its_fighting_rank(f: _Field) -> tuple:
    # how-many-attacks: 5 models in one rank, one Attack each, a quarter each.
    plain = f.unit()
    return _mean(f.fight(plain, plain).b_casualties), 5 * P_UNSAVED


def _a_thinned_body_strikes_back_with_fewer(f: _Field) -> tuple:
    # fight-on: the slower side replies from its survivors, so it inflicts less
    # than its full-strength 1.25.
    quick, slow = f.unit(initiative=6), f.unit(initiative=4)
    reply = _mean(f.fight(quick, slow).a_casualties)
    return reply < 5 * P_UNSAVED, True


def _a_stepped_forward_model_cannot_attack(f: _Field) -> tuple:
    # FAQ v1.5.3: "casualties inflicted reduce, firstly, the number of models in
    # the fighting rank(s) that are able to fight (starting with the first
    # fighting rank) and, secondly, the number of models in the 'supporting
    # rank' that are able to fight." And separately: "Q: ... can I remove
    # casualties from the second rank? A: No. Models in the first fighting rank,
    # the rank in base contact with the enemy, fall first as casualties."
    #
    # So a 15-strong body that has lost 3 replies with 3 fewer attacks. The
    # engine spends its rearmost rank first and keeps the fighting ranks full,
    # which is the same answer only when no rank is held in reserve.
    plain = f.unit()
    body = f.game.field(plain, 15).wielding("Hand Weapon")
    return body.remove_casualties(3).melee_attacks(), body.melee_attacks() - 3


def _wounds_carry_across_initiative_steps(f: _Field) -> tuple:
    # remove-casualties-combat: each unsaved wound costs the unit a Wound and
    # the tally *continues* -- "until there are no more unsaved wounds to be
    # applied" -- so a model wounded at one Initiative step meets the next step
    # already hurt.
    #
    # One model a side, the target on 3 Wounds. A lands at most 1 wound with its
    # attack and at most 2 with its closing stomp. Resolving each step against a
    # fresh model can never reach 3, so a reset scores exactly zero whatever the
    # dice; carrying the tally fells the model whenever all three land. The
    # discriminator needs no arithmetic: any mass at all means the wounds
    # carried.
    #
    # The same persistence is what makes the kill-outright tier exact. Once a
    # partially wounded model survives a step, a Killing Blow arriving at the
    # next one takes "all of its remaining Wounds" -- what it has left, not the
    # printed allotment the fold charges for every kill today. The two are one
    # change, which is why only this name carries both.
    stomper = f.unit(initiative=6, rules=("Doctored Stomp",))
    tough = f.unit(wounds=3)
    return _mean(f.fight(stomper, tough, 1, 1).b_casualties) > 0, True


def _kill_outright_wounds_are_applied_first(f: _Field) -> tuple:
    # FAQ v1.5.3: "apply unsaved wounds that cause models to lose all of their
    # remaining Wounds first (Killing Blows and Monster Slaying Blows, for
    # example), then unsaved wounds that cause multiple Wounds to be lost
    # (Multiple Wounds (X), for example), then, finally, unsaved wounds that
    # cause a single Wound to be lost."
    #
    # One Killing Blow and one doubled wound against 3-Wound models. In the
    # printed order the blow takes a whole fresh model (3 Wounds) and the
    # doubled wound then takes 2 off the next: 5 Wounds, one casualty. Applying
    # them in arrival order would spend the doubled wound first and leave the
    # blow only 1 remaining Wound to take -- 3 Wounds, the same one casualty,
    # and a different combat result. So `inflicted` is what tells them apart,
    # and it is the number a rewrite to one ordered stream could quietly lose.
    one, zero = Fraction(1), Fraction(0)
    toll = strike_toll(
        [AttackBatch(1, one, one), AttackBatch(1, one, zero)],
        wounds_per_model=3,
        targets=5,
        damage=Distribution.pure(2),
    )
    return _support(toll), (Toll(wounds=2, felled=1, inflicted=5),)


def _multiple_wounds_multiplies_each_wound(f: _Field) -> tuple:
    # multiple-wounds: each unsaved wound costs two Wounds, so against 2-Wound
    # models every unsaved wound fells one and casualties equal wounds.
    mw, two = f.unit(blade=True), f.unit(wounds=2)
    return _mean(f.fight(mw, two).b_casualties), 5 * P_UNSAVED


def _excess_wounds_do_not_spill_over(f: _Field) -> tuple:
    # multiple-wounds: against 1-Wound models the multiplier is inert, the
    # excess going nowhere rather than onto the next model.
    mw, plain = f.unit(blade=True), f.unit()
    return _mean(f.fight(mw, plain).b_casualties), _mean(f.fight(plain, plain).b_casualties)


def _the_score_counts_wounds_not_casualties(f: _Field) -> tuple:
    # unsaved-wounds-inflicted: "count the number of Wounds lost, rather than
    # the number of casualties". Multiple Wounds (2) over 5 attacks at a
    # quarter, against 3-Wound models: the absorb chain takes 2 per wound
    # capped at what the model has left, giving 0, 2, 3, 5, 6, 8 Wounds for 0..5
    # unsaved wounds, so A scores 271/128 against B's plain 5/4. Scoring the
    # models removed instead would read 0.38 against 1.25 — a different winner.
    mw, tough = f.unit(blade=True), f.unit(wounds=3)
    return _margin(f.fight(mw, tough)), Fraction(111, 128)


def _a_side_never_scores_more_than_the_foe_had(f: _Field) -> tuple:
    # unsaved-wounds-inflicted: a model removed "counts as having lost a number
    # of Wounds equal to the number it had remaining", so no side can score
    # more Wounds than its foe brought. A killing blow slays outright, which is
    # where the bookkeeping is easiest to get wrong.
    slayer = f.unit(rules=("Killing Blow",))
    lone = f.unit(wounds=3)
    result = f.fight(slayer, lone, 5, 1)
    scored = _margin(result) + 1 * P_UNSAVED  # A's own, B's lone reply removed
    return scored <= 1 * 3, True


def _a_wiped_out_side_loses_the_round(f: _Field) -> tuple:
    # calculate-combat-result: "If one side has been completely wiped out, the
    # other side is automatically the winner, regardless of the rules that
    # follow." A lone model that trades up before dying still loses.
    wiped = FightResult(
        losses=[[Fraction(0), Fraction(0)], [Fraction(0), Fraction(1)]],
        first_striker=None,
        wound_margin={2: Fraction(1)},  # A inflicted 3, B inflicted 1
    )
    return combat_result(wiped).p_b_wins, Fraction(1)


def _equal_scores_draw(f: _Field) -> tuple:
    # drawn-combat: a mirror match must leave real mass on a drawn round.
    plain = f.unit()
    return combat_result(f.fight(plain, plain)).p_draw > 0, True


def _the_rank_bonus_scores(f: _Field) -> tuple:
    # rank-bonus: a deeper body scores its extra rank, so the same fight at
    # greater depth shifts the margin in its favour.
    plain = f.unit()
    shallow = combat_result(f.fight(plain, plain, 5, 5)).p_a_wins
    deep = combat_result(f.fight(plain, plain, 15, 5)).p_a_wins
    return deep > shallow, True


def _only_the_loser_takes_a_break_test(f: _Field) -> tuple:
    # break-test: the winner never rolls, so each side's outcomes sum to the
    # mass of the rounds it lost and the two are mutually exclusive.
    plain = f.unit()
    result = f.fight(plain, plain)
    scored = combat_result(result)
    broken = break_test(
        scored,
        f.game.field(plain, 5).wielding("Hand Weapon"),
        f.game.field(plain, 5).wielding("Hand Weapon"),
    )
    total = (
        broken.a.p_gives_ground
        + broken.a.p_falls_back
        + broken.a.p_breaks
        + broken.b.p_gives_ground
        + broken.b.p_falls_back
        + broken.b.p_breaks
        + broken.p_draw
    )
    return total, Fraction(1)


# --- what data can reach ------------------------------------------------------


# Which side carries the doctored rule, and which figure its seam moves. An
# enemy-subject rule and a defensive one are the foe's to carry; both then show
# up in what the *bearer's* foe loses, so the figure watched differs from the
# side doctored.
_ON_THE_FOE = {"enemy-strength", "armour-value", "ward-save"}
# A seam needing depth to show: an extra fighting rank does nothing to a body
# only one rank deep.
_NEEDS_DEPTH = {"fighting-ranks"}


def _moves_and_is_claimed(f: _Field, point: str) -> tuple:
    # A seam is only a seam if an authored rule reaches it: the doctored rule
    # must both change the round's outcome and be reported factored rather than
    # riding along unapplied.
    rule = DOCTORED[point]
    armoured = point in {"armour-value", "armour-piercing"}
    models = 15 if point in _NEEDS_DEPTH else 5
    plain = f.unit(armoured=armoured)
    doctored = f.unit(rules=(rule.name,), armoured=armoured)
    if point == "leadership":
        return _leadership_reaches_the_break_test(f, plain, doctored, rule)
    if point in _ON_THE_FOE:
        before, after = f.fight(plain, plain, models), f.fight(plain, doctored, models)
    else:
        before, after = f.fight(plain, plain, models), f.fight(doctored, plain, models)
    moved = _mean(before.b_casualties) != _mean(after.b_casualties) or (
        combat_result(before).p_a_wins != combat_result(after).p_a_wins
    )
    unfactored = any(rule.name in note and "not factored" in note for note in after.notes)
    return (moved, unfactored), (True, False)


def _leadership_reaches_the_break_test(f: _Field, plain, doctored, rule) -> tuple:
    # Leadership moves nothing in the fight: it is read where the loser rolls,
    # so this seam is watched at the Break test.
    result = f.fight(plain, plain)
    scored = combat_result(result)
    field = lambda unit: f.game.field(unit, 5).wielding("Hand Weapon")  # noqa: E731
    before = break_test(scored, field(plain), field(plain))
    after = break_test(scored, field(doctored), field(plain))
    moved = before.a.p_breaks != after.a.p_breaks
    unfactored = any(rule.name in note and "not factored" in note for note in after.notes)
    return (moved, unfactored), (True, False)


def _multiplier_is_reachable(f: _Field) -> tuple:
    # The casualty seam's own point, read off the weapon in use.
    mw, plain = f.unit(blade=True), f.unit(wounds=2)
    result = f.fight(mw, plain)
    unfactored = any(MULTIPLIER.name in n and "not factored" in n for n in result.notes)
    return (_mean(result.b_casualties) > 0, unfactored), (True, False)


CHECKS: dict[str, Callable[[_Field], tuple]] = {
    # the printed sequence
    "initiative-orders-the-blows": _initiative_orders_the_blows,
    "equal-initiative-is-simultaneous": _equal_initiative_is_simultaneous,
    "each-side-throws-its-fighting-rank": _each_side_throws_its_fighting_rank,
    "a-thinned-body-strikes-back-with-fewer": _a_thinned_body_strikes_back_with_fewer,
    "a-stepped-forward-model-cannot-attack": _a_stepped_forward_model_cannot_attack,
    "wounds-carry-across-initiative-steps": _wounds_carry_across_initiative_steps,
    "kill-outright-wounds-are-applied-first": _kill_outright_wounds_are_applied_first,
    "multiple-wounds-multiplies-each-wound": _multiple_wounds_multiplies_each_wound,
    "excess-wounds-do-not-spill-over": _excess_wounds_do_not_spill_over,
    "the-score-counts-wounds-not-casualties": _the_score_counts_wounds_not_casualties,
    "a-side-never-scores-more-than-the-foe-had": _a_side_never_scores_more_than_the_foe_had,
    "a-wiped-out-side-loses-the-round": _a_wiped_out_side_loses_the_round,
    "equal-scores-draw": _equal_scores_draw,
    "the-rank-bonus-scores": _the_rank_bonus_scores,
    "only-the-loser-takes-a-break-test": _only_the_loser_takes_a_break_test,
    # the modifiable points
    "reaches-the-multiplier": _multiplier_is_reachable,
    **{
        f"reaches-{point}": (lambda p: lambda f: _moves_and_is_claimed(f, p))(point)
        for point in DOCTORED
    },
}

# Checks the engine does not satisfy yet. Each name here is a piece of the
# rewrite still to land; the test holds the set honest in both directions.
KNOWN_GAPS = frozenset(
    {
        "a-stepped-forward-model-cannot-attack",
        "wounds-carry-across-initiative-steps",
        "a-wiped-out-side-loses-the-round",
        # One root cause: `effective_attacks` and `effective_fighting_ranks`
        # read against Contingent._charge_context(), which carries movement and
        # equipment but no `combat` entity. A rule gated on the engagement is
        # therefore honoured as not-applying, silently, wherever it moves one of
        # these two. Ungated, the same rule lands.
        "reaches-attacks",
        "reaches-fighting-ranks",
    }
)


def test_a_round_of_close_combat() -> None:
    """Every printed rule of the Combat phase, and every point data can move.

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
    assert not fixed, f"now passing — take out of KNOWN_GAPS: {sorted(fixed)}"

    assert set(CHECKS) == set(held) | set(failed)
