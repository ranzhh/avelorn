"""Shooting chain tests, golden values hand-computed from the rulebook charts."""

from dataclasses import replace
from fractions import Fraction

import pytest

from avelorn.tow.contingent import Contingent, Movement
from avelorn.tow.data import TOWRepository
from avelorn.tow.engine.attack import AttackProfile, Outcome, RollState, Transform
from avelorn.tow.muster import Complement
from avelorn.tow.phases.shooting import _engagement_conditions, shoot, shoot_unit
from avelorn.tow.schema.rule import RerollEffect, RollResult, Rule
from avelorn.tow.schema.stage import Stage
from avelorn.tow.schema.unit import Characteristic, Unit
from avelorn.tow.schema.weapon import WeaponType

REPO = TOWRepository()


def _fielded(
    unit: Unit, models: int, frontage: int | None = None, *, moved: bool = False
) -> Contingent:
    # Field at the printed, optionless loadout, with the real registries;
    # ``moved`` sets the unit's movement (stationary by default).
    base = Contingent.field(
        unit,
        models,
        data=REPO,
        frontage=frontage,
    )
    return base.after(Movement.march()) if moved else base


def test_shoot_golden_chain() -> None:
    """BS4, S3 vs T3, 5+ save: p = 2/3 * 1/2 * 2/3 = 2/9 per shot."""
    result = shoot(3, ballistic_skill=4, strength=3, toughness=3, armour_value=5)
    assert result.hit_target == 3
    assert result.wound_target == 4
    assert result.save_target == 5
    assert result.p_unsaved == pytest.approx(2 / 9)
    assert result.expected_wounds == pytest.approx(2 / 3)
    assert sum(result.distribution) == pytest.approx(1.0)
    assert result.distribution[0] == pytest.approx((7 / 9) ** 3)


def test_shoot_ward_save_stacks_multiplicatively() -> None:
    """A 4+ ward halves the unsaved-wound probability."""
    base = shoot(1, ballistic_skill=4, strength=3, toughness=3)
    warded = shoot(1, ballistic_skill=4, strength=3, toughness=3, ward_target=4)
    assert warded.p_unsaved == pytest.approx(base.p_unsaved / 2)


def test_shoot_impossible_wound_kills_nothing() -> None:
    """S1 vs T7 is a printed dash: zero wounds regardless of dice."""
    result = shoot(10, ballistic_skill=5, strength=1, toughness=7)
    assert result.p_unsaved == 0.0
    assert result.distribution[0] == pytest.approx(1.0)


def test_shoot_unit_archers_vs_spearmen() -> None:
    """End-to-end from data files: 3 Elven Archers shoot Elven Spearmen.

    Spearmen carry light armour (6+) and a shield (+1), so they save on
    5+; the longbow's Armour Bane (1), resolved at fielding, worsens it
    to 6+ on a natural 6 To Wound. Expected wounds = 3 * 13/54.
    """
    archers = REPO.units["elven-archers"]
    spearmen = REPO.units["elven-spearmen"]
    result = shoot_unit(
        _fielded(archers, 3).wielding("Longbow"),
        _fielded(spearmen, 10),
    )
    assert result.hit_target == 3  # BS 4
    assert result.save_target == 5  # 7 - light armour - shield (the chart value)
    assert result.expected_wounds == pytest.approx(3 * 13 / 54)  # Armour Bane factored
    # Equipment and the weapon's modelled rules resolved at fielding:
    # neither is left to report.
    assert not any("equipment not factored" in note for note in result.notes)
    assert not any("Armour Bane" in note for note in result.notes)
    assert any("Valour of Ages" in note for note in result.notes)


def test_defender_size_does_not_affect_wounds() -> None:
    """Wounds depend on the shooters, not on how many models receive them.

    Regression guard: 3 archers shooting 20 spearmen and 3 archers
    shooting 30 spearmen must produce the identical wound distribution.
    """
    archers = _fielded(REPO.units["elven-archers"], 3)
    spearmen = REPO.units["elven-spearmen"]

    vs_twenty = shoot_unit(archers.wielding("Longbow"), _fielded(spearmen, 20))
    vs_thirty = shoot_unit(archers.wielding("Longbow"), _fielded(spearmen, 30))

    assert vs_twenty.p_unsaved == vs_thirty.p_unsaved
    assert vs_twenty.distribution == vs_thirty.distribution
    assert vs_twenty.expected_wounds == vs_thirty.expected_wounds


def test_shoot_caps_casualties_at_target_size() -> None:
    """A volley cannot remove more models than the unit contains.

    10 shots at p = 1/2 against a 2-model unit: the wound distribution
    keeps all 11 outcomes, but casualties collapse to 0, 1, or 2, with
    P(2) absorbing every outcome of 2+ wounds.
    """
    result = shoot(10, ballistic_skill=4, strength=3, toughness=3, targets=2)
    assert len(result.distribution) == 11
    assert len(result.casualties) == 3
    assert result.casualties[2] == pytest.approx(sum(result.distribution[2:]))
    assert sum(result.casualties) == pytest.approx(1.0)
    assert result.expected_casualties < result.expected_wounds


def test_shoot_casualties_equal_wounds_when_uncapped() -> None:
    """With no target size, casualties are exactly the wound distribution."""
    result = shoot(3, ballistic_skill=4, strength=3, toughness=3, armour_value=5)
    assert result.target_models is None
    assert result.casualties == result.distribution
    assert result.expected_casualties == pytest.approx(result.expected_wounds)


def test_shoot_rejects_negative_targets() -> None:
    """A negative target count is meaningless."""
    with pytest.raises(ValueError, match="targets must be >= 0"):
        shoot(3, ballistic_skill=4, strength=3, toughness=3, targets=-1)


def test_only_the_front_rank_fires() -> None:
    """A unit fires with its front rank, not every model.

    Ten archers ranked five wide stand in two ranks; only the front five
    fire on flat ground. They moved, so the longbow's Volley Fire does not
    add the rear rank — isolating the front-rank count.
    """
    archers = REPO.units["elven-archers"]
    spearmen = REPO.units["elven-spearmen"]
    result = shoot_unit(
        _fielded(archers, 10, frontage=5, moved=True).wielding("Longbow"),
        _fielded(spearmen, 20),
    )
    assert result.shots == 5


def test_volley_fire_adds_half_of_each_rear_rank_when_stationary() -> None:
    """A stationary Volley Fire weapon adds half of each rear rank (rounding up).

    Ten archers five wide with longbows, stationary (the default): the
    front five fire, plus ceil(5/2) = 3 from the second rank — eight
    shots. Factored into the count, the rule leaves no note.
    """
    archers = REPO.units["elven-archers"]
    spearmen = REPO.units["elven-spearmen"]
    result = shoot_unit(
        _fielded(archers, 10, frontage=5).wielding("Longbow"),
        _fielded(spearmen, 20),
    )
    assert result.shots == 8
    assert not any("Volley Fire" in note for note in result.notes)


def test_volley_fire_does_not_apply_to_a_unit_that_moved() -> None:
    """A unit that moved cannot volley fire: front rank only, honoured with no note."""
    archers = REPO.units["elven-archers"]
    spearmen = REPO.units["elven-spearmen"]
    result = shoot_unit(
        _fielded(archers, 10, frontage=5, moved=True).wielding("Longbow"),
        _fielded(spearmen, 20),
    )
    assert result.shots == 5
    assert not any("Volley Fire" in note for note in result.notes)


def test_volley_fire_never_on_a_stand_and_shoot() -> None:
    """A Stand & Shoot reaction cannot volley fire, even standing still."""
    archers = REPO.units["elven-archers"]
    spearmen = REPO.units["elven-spearmen"]
    result = shoot_unit(
        _fielded(archers, 10, frontage=5).wielding("Longbow"),
        _fielded(spearmen, 20),
        stand_and_shoot=True,
    )
    assert result.shots == 5
    assert not any("Volley Fire" in note for note in result.notes)


def test_forcing_short_range_alone_does_not_forbid_volley_fire() -> None:
    """Only a Stand & Shoot forbids Volley Fire, not the short-range mechanic.

    A future ability that forces a shot short of its range must leave
    Volley Fire available; the ban keys off the reaction, not the flag.
    """
    archers = REPO.units["elven-archers"]
    spearmen = REPO.units["elven-spearmen"]
    result = shoot_unit(
        _fielded(archers, 10, frontage=5).wielding("Longbow"),
        _fielded(spearmen, 20),
        force_short_range=True,
    )
    assert result.shots == 8  # front five plus three from the second rank


def test_shoot_unit_caps_casualties_but_not_wounds() -> None:
    """``defenders`` bounds casualties while leaving the wound math intact.

    30 archers ranked one rank wide (so all fire) into 5 spearmen: the
    wound distribution is unbounded over 30 shots, but the spearmen unit
    can lose at most 5 models.
    """
    archers = REPO.units["elven-archers"]
    spearmen = REPO.units["elven-spearmen"]
    result = shoot_unit(
        _fielded(archers, 30, frontage=30).wielding("Longbow"),
        _fielded(spearmen, 5),
    )
    assert result.target_models == 5
    assert len(result.distribution) == 31
    assert len(result.casualties) == 6
    assert result.expected_casualties < result.expected_wounds


def test_shoot_folds_wounds_into_multi_wound_models() -> None:
    """With Wounds 3, casualties are wounds // 3 — models, not wounds.

    6 shots produce a 0..6 wound distribution; folded by 3 it becomes a
    0..2 models-removed distribution, each bucket the sum of its three
    wound outcomes.
    """
    result = shoot(6, ballistic_skill=4, strength=3, toughness=3, wounds_per_model=3)
    d = result.distribution
    assert len(result.casualties) == 3  # 0, 1, 2 models from 0..6 wounds
    assert result.casualties[0] == pytest.approx(d[0] + d[1] + d[2])
    assert result.casualties[1] == pytest.approx(d[3] + d[4] + d[5])
    assert result.casualties[2] == pytest.approx(d[6])
    assert result.expected_casualties < result.expected_wounds  # 3 wounds per kill
    assert sum(result.casualties) == pytest.approx(1.0)


def test_shoot_rejects_non_positive_wounds_per_model() -> None:
    """A model with fewer than 1 Wound is meaningless."""
    with pytest.raises(ValueError, match="wounds_per_model must be >= 1"):
        shoot(3, ballistic_skill=4, strength=3, toughness=3, wounds_per_model=0)


def test_shoot_unit_folds_multi_wound_casualties_and_caps() -> None:
    """A W3 target: wounds fold into slain models, then cap at the unit size.

    30 archers ranked one rank wide (so all fire) into 5 Wounds-3 models:
    casualties are models removed (three wounds each), capped at 5, and
    fewer than the wounds inflicted. The old "carry-over not modelled"
    disclaimer is gone.
    """
    archers = REPO.units["elven-archers"]
    spearmen = REPO.units["elven-spearmen"]
    multi_wound = spearmen.model_copy(deep=True)
    multi_wound.profiles[0].characteristics[Characteristic.WOUNDS] = 3
    result = shoot_unit(
        _fielded(archers, 30, frontage=30).wielding("Longbow"),
        _fielded(multi_wound, 5),
    )
    assert result.target_models == 5  # cap now applied
    assert len(result.casualties) == 6  # 0..5 models
    assert result.expected_casualties < result.expected_wounds
    assert sum(result.casualties) == pytest.approx(1.0)
    assert not any("carry-over" in note for note in result.notes)


def test_shoot_unit_warbow_uses_wielders_strength() -> None:
    """End-to-end from data files: Lothern Sea Guard shoot Elven Spearmen.

    The warbow's printed Strength is "S", so shots resolve at the Sea
    Guard's S3 vs T3: wound on 4+, same 2/9 per-shot chain as the longbow
    golden test (spearmen save on 5+, no AP).
    """
    sea_guard = REPO.units["lothern-sea-guard"]
    spearmen = REPO.units["elven-spearmen"]
    result = shoot_unit(
        _fielded(sea_guard, 3).wielding("Warbow"),
        _fielded(spearmen, 10),
    )
    assert result.hit_target == 3  # BS 4
    assert result.wound_target == 4  # wielder's S3 vs T3
    assert result.expected_wounds == pytest.approx(2 / 3)


def test_shoot_unit_rejects_wielder_strength_weapon_without_strength() -> None:
    """A "Strength: S" weapon cannot resolve if the wielder has no S."""
    spearmen = REPO.units["elven-spearmen"]
    strengthless = spearmen.model_copy(deep=True)
    strengthless.profiles[0].characteristics[Characteristic.STRENGTH] = None
    strengthless.equipment.append("Warbow")  # carried, so the choice is legal
    with pytest.raises(ValueError, match="wielder's Strength"):
        shoot_unit(_fielded(strengthless, 1).wielding("Warbow"), _fielded(spearmen, 10))


def test_shoot_unit_rejects_pure_melee_weapon() -> None:
    """A weapon with no missile profile cannot shoot."""
    spearmen = REPO.units["elven-spearmen"]
    with pytest.raises(ValueError, match="missile profile"):
        shoot_unit(_fielded(spearmen, 1).wielding("Hand Weapon"), _fielded(spearmen, 10))


def test_shoot_unit_rejects_missing_ballistic_skill() -> None:
    """A unit whose profile has BS "-" cannot shoot."""
    spearmen = REPO.units["elven-spearmen"]
    crewless = spearmen.model_copy(deep=True)
    crewless.profiles[0].characteristics[Characteristic.BALLISTIC_SKILL] = None
    crewless.equipment.append("Longbow")  # carried, so the choice is legal
    with pytest.raises(ValueError, match="Ballistic Skill"):
        shoot_unit(_fielded(crewless, 1).wielding("Longbow"), _fielded(spearmen, 10))


def _killing_blow_double() -> Transform:
    def escalate(face: int, profile: AttackProfile) -> AttackProfile:
        if face != 6:
            return profile
        return replace(
            profile.with_target(Stage.MAKE_ARMOUR_SAVES, RollState.IMPOSSIBLE),
            unsaved_outcome=Outcome.INSTANT_KILL,
        )

    return Transform(stage=Stage.ROLL_TO_WOUND, on_success=escalate)


def test_shoot_instant_kills_remove_multi_wound_models_outright() -> None:
    """Two attacks can only fell both Wounds-3 models via two kills.

    Hit 3+, wound 4+, save 5+ with the kill double: p_kill = 1/9 per
    attack and plain wounds (at most 2 < 3) fell nobody, so casualties
    are Binomial(2, 1/9): P(2) = 1/81.
    """
    result = shoot(
        2,
        ballistic_skill=4,
        strength=3,
        toughness=3,
        armour_value=5,
        wounds_per_model=3,
        targets=2,
        transforms=[_killing_blow_double()],
    )
    assert result.casualties[2] == pytest.approx(1 / 81)
    assert result.casualties[1] == pytest.approx(2 * (1 / 9) * (8 / 9))
    assert result.casualties[0] == pytest.approx((8 / 9) ** 2)
    assert sum(result.casualties) == pytest.approx(1.0)


def test_shoot_instant_kills_match_the_spike_distribution() -> None:
    """12 attacks vs 2 Wounds-3 models reproduce the class-aware spike.

    Spike values (verified there against Monte Carlo): P(0)=0.165,
    P(1)=0.342, P(2)=0.493.
    """
    result = shoot(
        12,
        ballistic_skill=4,
        strength=3,
        toughness=3,
        armour_value=5,
        wounds_per_model=3,
        targets=2,
        transforms=[_killing_blow_double()],
    )
    assert result.casualties[0] == pytest.approx(0.165, abs=5e-4)
    assert result.casualties[1] == pytest.approx(0.342, abs=5e-4)
    assert result.casualties[2] == pytest.approx(0.493, abs=5e-4)
    assert sum(result.casualties) == pytest.approx(1.0)
    assert sum(result.distribution) == pytest.approx(1.0)


def test_engagement_conditions_build_the_shooting_facts() -> None:
    """The shooting producer sets the shooting facts and leaves the rest absent.

    A moved shooter at unknown range: ``moved`` true, ``at_long_range`` unknown
    (no distance). The weapon in hand is the bow it fires, so ``wielding`` names
    its family, and the armour worn rides along — empty for archers at their
    printed loadout, which is *known* to be nothing rather than unknown. The
    shooter is not engaged in close combat and is the attacker, not a target, so
    ``combat`` and ``target_of`` are both absent (the defender's incoming-attack
    facts are built separately for its save); ``charge`` is None because a
    shooter never charged.
    """
    archers = _fielded(REPO.units["elven-archers"], 5, moved=True)
    longbow = REPO.weapons["longbow"]
    profile = longbow.missile_profile
    assert profile is not None
    context = _engagement_conditions(
        archers, longbow, profile, distance=None, force_short_range=False, stand_and_shoot=False
    )
    assert context.wielding.type is WeaponType.BOW
    assert context.worn == ()  # unarmoured, and known so — not left unknown
    assert context.movement.moved is True
    assert context.shooting.at_long_range is None  # no distance -> unknown band
    assert context.shooting.stand_and_shoot is False  # an ordinary volley, known
    assert context.combat is None
    assert context.target_of is None
    assert context.movement.charge is None


def test_arrows_of_isha_worsens_the_bow_save_and_is_claimed() -> None:
    """The Sisters' unit rule reaches the bow: -1 save, and out of the notes.

    Firing the Bow of Avelorn at White Lions, Arrows of Isha's Armour Piercing
    worsens their Heavy Armour save from 5+ to 6+ (Lion Cloak is a magical-shot
    no-op, so 5+ is the base). The rule is factored into the walk, so it drops
    out of the "special rule not factored" notes — while the Sisters' rules the
    volley cannot honour (Strike First) stay listed.
    """
    sisters = _fielded(REPO.units["sisters-of-avelorn"], 5).wielding("Bow of Avelorn")
    lions = _fielded(REPO.units["white-lions-of-chrace"], 10)
    result = shoot_unit(sisters, lions, force_short_range=True)
    assert result.save_target == 6  # 5+ Heavy Armour, worsened one by the bow's AP
    assert not any("Arrows of Isha" in note for note in result.notes)
    assert any("Strike First" in note for note in result.notes)


def test_shoot_unit_skirmishers_impose_minus_one_to_hit_on_the_shooter() -> None:
    """Enemy Fire (Skirmishers): the defender's rule, the shooter's die.

    Skirmishers grants the formation's own Enemy Fire (Skirmishers), whose
    enemy-subject -1 To Hit lands on this volley's Roll to Hit: shooting the
    same unit stripped of the rule hits one point easier. The rule is claimed
    (never listed as not factored) and its formation simplification is noted.
    """
    archers, shadows = REPO.units["elven-archers"], REPO.units["shadow-warriors"]
    formed = shadows.model_copy(
        update={"special_rules": [r for r in shadows.special_rules if r != "Skirmishers"]}
    )
    shooter = _fielded(archers, 5).wielding("Longbow")

    skirmishing = shoot_unit(shooter, _fielded(shadows, 10))
    formed_up = shoot_unit(shooter, _fielded(formed, 10))
    assert skirmishing.hit_target == formed_up.hit_target + 1
    assert not any("not factored: Skirmishers" in note for note in skirmishing.notes)
    assert any("Skirmish formation is not modelled" in note for note in skirmishing.notes)
    # The granted rule's own caveat surfaces too: Enemy Fire (Skirmishers)
    # lives only in granted_rules, and its Unit Strength scope is authored
    # there, not on the granting rule.
    assert any("Unit Strength 1" in note for note in skirmishing.notes)


def test_shoot_unit_skirmish_formation_option_imposes_the_same_penalty() -> None:
    """The Skirmish Formation option reaches Enemy Fire (Skirmishers) too.

    Ship's Company buys the formation as an option rather than printing the
    Skirmishers rule, so the grant hangs off the formation's own entry: the
    mustered unit is a point harder to hit than the same unit without it.
    """
    company = REPO.units["ships-company"]
    shooter = _fielded(REPO.units["elven-archers"], 5).wielding("Longbow")
    formed = Contingent.field(Complement(unit=company, size=10), data=REPO)
    skirmishing = Contingent.field(
        Complement(unit=company, size=10, options=["Skirmish Formation"]), data=REPO
    )

    assert (
        shoot_unit(shooter, skirmishing).hit_target == shoot_unit(shooter, formed).hit_target + 1
    )


def test_shoot_unit_gromril_armour_re_rolls_the_targets_save_against_arrows() -> None:
    """The defender's own save re-roll reaches a volley's walk too.

    Archers (BS4; longbow S3, Armour Bane (1)) shoot Ironbreakers (T4,
    save 3+): hit 3+, wound 5+, and a wound's natural 6 improves Armour
    Piercing by one, so the save is 4+ on that branch and 3+ on the
    natural 5, and Runes of Protection wards what passes them on a 6+
    against the mundane arrows (a further 5/6 factor). Stripped of the
    re-roll, p_unsaved = 2/3 * (1/6 * 1/2 + 1/6 * 1/3) * 5/6 = 25/324;
    re-rolling the save's natural 1s lifts the passes to 7/12 and 7/9, so
    p_unsaved = 2/3 * (1/6 * 5/12 + 1/6 * 2/9) * 5/6 = 115/1944.
    """
    archers, ironbreakers = REPO.units["elven-archers"], REPO.units["ironbreakers"]
    stripped = ironbreakers.model_copy(
        update={"special_rules": [r for r in ironbreakers.special_rules if r != "Gromril Armour"]}
    )
    shooter = _fielded(archers, 5).wielding("Longbow")

    plain = shoot_unit(shooter, _fielded(stripped, 10))
    gromril = shoot_unit(shooter, _fielded(ironbreakers, 10))
    assert plain.p_unsaved == pytest.approx(25 / 324)
    assert gromril.p_unsaved == pytest.approx(115 / 1944)
    assert not any("Gromril Armour" in note for note in gromril.notes)


def test_shoot_unit_notes_the_defenders_rules_no_volley_could_use() -> None:
    """A volley claims only what its own single walk factored.

    Shot at, the Shadow Warriors' Ithilmar Weapons re-rolls the To Hit 1s of
    blows *they* throw — the seat of the walk a volley does not resolve — and
    their Elven Reflexes moves an Initiative no volley reads. Both are
    reported. Neither may pass for factored merely because the volley's facts
    answer its combat gate False: a strike, whose facts leave the round open,
    reports the same pair.
    """
    archers, shadows = REPO.units["elven-archers"], REPO.units["shadow-warriors"]
    result = shoot_unit(_fielded(archers, 5).wielding("Longbow"), _fielded(shadows, 10))
    reported = [note for note in result.notes if "(Shadow Warriors)" in note]
    assert "special rule not factored: Ithilmar Weapons (Shadow Warriors)" in reported
    assert "special rule not factored: Elven Reflexes (Shadow Warriors)" in reported


def _with_a_magic_bow(archers: Contingent) -> Contingent:
    # No printed magic bow grants a re-roll, so doctor the longbow with a rule
    # in Daith's Reaper's shape — "enemy models must re-roll any successful
    # Armour Save rolls" — printed on its missile profile and filed in the
    # loadout's weapon rules under that name, exactly as fielding a real magic
    # missile weapon would file it.
    rule = Rule(
        id="doctored-bow",
        name="Doctored Bow",
        paragraphs=["…"],
        effects=[
            RerollEffect(reroll=Stage.MAKE_ARMOUR_SAVES, of=RollResult.SUCCESSFUL, enemy=True)
        ],
    )
    longbow = archers.loadout.weapon("Longbow")
    printed = longbow.profiles[0]
    doctored = longbow.model_copy(
        update={
            "profiles": [
                printed.model_copy(update={"special_rules": [*printed.special_rules, rule.name]})
            ]
        }
    )
    loadout = replace(
        archers.loadout,
        weapons=(doctored, *(w for w in archers.loadout.weapons if w.name != longbow.name)),
        weapon_rules={**archers.loadout.weapon_rules, rule.name: rule},
    )
    return replace(archers, loadout=loadout).wielding("Longbow")


def test_shoot_unit_factors_a_missile_profiles_own_re_roll_grant() -> None:
    """A magic bow's own grant reaches the volley, as a magic blade's reaches a melee.

    Archers (BS4; longbow S3, Armour Bane (1)) shoot White Lions (T3, Heavy
    Armour and a Lion Cloak that betters a non-magical shot's save to 4+): hit
    3+, wound 4+, and a wound's natural 6 improves Armour Piercing by one, so
    the save is 5+ on that branch and 4+ on the natural 4 or 5 —
    p_unsaved = 2/3 * (2/6 * 1/2 + 1/6 * 2/3) = 5/27. Forced to re-roll its
    successful saves, the defender keeps only the passes it makes twice: 1/4
    where it saved on 4+, 1/9 on the branch worsened to 5+, so
    p_unsaved = 2/3 * (2/6 * 3/4 + 1/6 * 8/9) = 43/162. The grant rides the
    profile in use, so it is claimed off the weapon-rule notes.
    """
    archers, lions = REPO.units["elven-archers"], REPO.units["white-lions-of-chrace"]
    target = _fielded(lions, 10)

    plain = shoot_unit(_fielded(archers, 5).wielding("Longbow"), target)
    magic = shoot_unit(_with_a_magic_bow(_fielded(archers, 5)), target)

    assert plain.save_target == 4
    assert plain.p_unsaved == pytest.approx(5 / 27)
    assert magic.save_target == 4  # a re-roll shifts the probability, not the target
    assert magic.p_unsaved == pytest.approx(43 / 162)
    assert not any("Doctored Bow" in note for note in magic.notes)


def test_shoot_unit_grants_the_defenders_ward_against_a_mundane_volley() -> None:
    """Runes of Protection wards Ironbreakers on a 6+ against ordinary arrows.

    The real entry from the data: a 6+ ward fails 5/6 of the time, so the
    per-shot unsaved probability is exactly 5/6 of the unwarded one, and the
    rule is claimed out of the notes -- it is in the math.
    """
    archers = REPO.units["elven-archers"]
    breakers = Contingent.deploy("ironbreakers", 10, data=REPO)
    stripped_unit = REPO.units["ironbreakers"].model_copy(
        update={
            "special_rules": [
                r for r in REPO.units["ironbreakers"].special_rules if r != "Runes of Protection"
            ]
        }
    )
    stripped = Contingent.field(stripped_unit, 10, data=REPO)

    warded = shoot_unit(_fielded(archers, 5).wielding("Longbow"), breakers)
    unwarded = shoot_unit(_fielded(archers, 5).wielding("Longbow"), stripped)

    assert warded.ward_target == 6
    assert unwarded.ward_target is None
    assert warded.p_unsaved == pytest.approx(unwarded.p_unsaved * 5 / 6)
    assert not any("Runes of Protection" in note for note in warded.notes)


def test_shoot_unit_denies_the_ward_to_a_magical_volley() -> None:
    """Runes of Protection reads the incoming attack: the Bow of Avelorn turns it off.

    A magical volley answers the gate False -- honoured, not unfactored -- so
    no ward is rolled and the rule still never reaches the notes.
    """
    sisters = REPO.units["sisters-of-avelorn"]
    breakers = Contingent.deploy("ironbreakers", 10, data=REPO)

    result = shoot_unit(_fielded(sisters, 5).wielding("Bow of Avelorn"), breakers)

    assert result.ward_target is None
    assert not any("Runes of Protection" in note for note in result.notes)
    # The bow's mark is in the facts, so it is claimed, never "not factored".
    assert not any("not factored: Magical Attacks" in note for note in result.notes)


# --- cavalry: a ridden target is shot as its rider; a ridden shooter fires as one ---


def test_shoot_unit_at_cavalry_reads_the_riders_row_and_armour() -> None:
    """A volley at Silver Helms wounds the rider's T3 behind the rider's save.

    The steed's row prints "-" for Toughness and Wounds: the model is shot on
    the rider's values and saves on the rider's heavy armour (5+)
    (troop-types-in-detail/split-profile-cavalry). Longbows at S3: 4+ to
    wound, AP 0.
    """
    archers = REPO.units["elven-archers"]
    helms = Contingent.deploy("silver-helms", 5, data=REPO)

    result = shoot_unit(_fielded(archers, 5).wielding("Longbow"), helms)

    assert result.wound_target == 4  # S3 vs the rider's T3
    assert result.save_target == 5  # the rider's heavy armour
    assert result.target_models == 5


def test_shoot_unit_with_cavalry_fires_the_riders_ballistic_skill() -> None:
    """Ellyrian Reavers with shortbows shoot at the rider's BS4; steeds print no BS.

    Light Cavalry ranks 5 wide, so 5 reavers are one firing rank: 5 shots,
    hitting on 3+ at short range from a standing start.
    """
    reavers = Contingent.deploy("ellyrian-reavers", 5, ["Shortbow"], data=REPO).wielding(
        "Shortbow"
    )
    spearmen = _fielded(REPO.units["elven-spearmen"], 10)

    result = shoot_unit(reavers, spearmen, distance=9)

    assert result.shots == 5
    assert result.hit_target == 3


def test_shoot_unit_leaves_a_two_handed_wielders_shield_counting() -> None:
    """Requires Two Hands withdraws the shield in the Combat phase alone.

    "(a shield can still be used against wounds caused by shooting)": the
    same doctored great-weapon wielder saves arrows on its full 5+.
    """
    spearmen = REPO.units["elven-spearmen"]
    two_handed = spearmen.model_copy(update={"equipment": [*spearmen.equipment, "Great Weapon"]})
    greatswords = Contingent.field(two_handed, 10, data=REPO).wielding("Great Weapon")

    result = shoot_unit(_fielded(REPO.units["elven-archers"], 5).wielding("Longbow"), greatswords)

    assert result.save_target == 5


def test_a_blow_never_fires_in_a_volley() -> None:
    """Killing Blow reads "an attack made in combat": a volley leaves it honoured inert."""
    archers = REPO.units["elven-archers"]
    marked = archers.model_copy(update={"special_rules": [*archers.special_rules, "Killing Blow"]})
    target = _fielded(REPO.units["elven-spearmen"], 10)

    blow = shoot_unit(_fielded(marked, 5).wielding("Longbow"), target, distance=10)
    plain = shoot_unit(_fielded(archers, 5).wielding("Longbow"), target, distance=10)

    assert blow.p_unsaved == plain.p_unsaved
    assert not any("not factored: Killing Blow" in n for n in blow.notes)


def test_multiple_wounds_d3_shoots_as_a_distribution_not_an_expectation() -> None:
    """The real entry over a volley: MW (D3) rolled separately per unsaved wound.

    One archer with a doctored Maw Bow (S3, Multiple Wounds (D3)) at an
    unarmoured 3-Wound target: BS4 (3+), S3 vs T3 (4+), no save —
    p_unsaved = 1/3, and the single model falls only on the D3's 3, so
    P(casualty) = 1/3 * 1/3 = 1/9, exactly. The plain bow never fells it.
    """
    from avelorn.core.registry import Registry
    from avelorn.tow.schema.weapon import Weapon, WeaponProfile

    bow = Weapon(
        id="maw-bow",
        name="Maw Bow",
        profiles=[
            WeaponProfile.model_validate(
                {"R": 30, "S": 3, "AP": "-", "special_rules": ["Multiple Wounds (D3)"]}
            )
        ],
    )
    repo = TOWRepository()
    repo.weapons = Registry([*REPO.weapons.values(), bow], kind="weapon")
    archers = REPO.units["elven-archers"]
    armed = archers.model_copy(update={"equipment": [*archers.equipment, "Maw Bow"]})
    spearmen = REPO.units["elven-spearmen"]
    monster = spearmen.model_copy(
        deep=True, update={"id": "w3", "name": "W3 Target", "equipment": ["Hand Weapon"]}
    )
    monster.profiles[0].characteristics[Characteristic.WOUNDS] = 3
    target = Contingent.field(monster, 1, data=repo)

    volley = shoot_unit(Contingent.field(armed, 1, data=repo).wielding("Maw Bow"), target)

    assert volley.shots == 1
    assert volley.p_unsaved == pytest.approx(1 / 3)
    assert volley.casualties == [Fraction(8, 9), Fraction(1, 9)]
    assert not any("not factored: Multiple Wounds" in note for note in volley.notes)

    plain = shoot_unit(Contingent.field(archers, 1, data=repo).wielding("Longbow"), target)
    assert plain.casualties == [1]  # one wound never fells a 3-Wound model
