"""The fielded unit: Contingent.deploy / field, and the Charge bonus."""

import dataclasses

import pytest

from avelorn.tow.contingent import (
    Charge,
    ChargeArc,
    Contingent,
    Formation,
    Loadout,
    Movement,
    MovementKind,
)
from avelorn.tow.data import TOWRepository
from avelorn.tow.muster import Complement
from avelorn.tow.schema.rule import ModifierEffect
from avelorn.tow.schema.unit import Characteristic, TroopType, Unit

REPO = TOWRepository()


@pytest.fixture
def spearmen_unit() -> Unit:
    """The Elven Spearmen datasheet, whose options a Complement is built from.

    Returns:
        The validated unit model.
    """
    return REPO.units["elven-spearmen"]


def _fielded(unit: Unit, models: int, frontage: int | None = None) -> Contingent:
    # Field at the optionless loadout, optionally at a chosen frontage.
    return Contingent.field(
        unit,
        models,
        data=REPO,
        frontage=frontage,
    )


def test_field_a_complement_carries_size_and_loadout(spearmen_unit: Unit) -> None:
    """Contingent.field carries a complement's size and chosen loadout."""
    mustered = Complement(unit=spearmen_unit, size=18, options=["Shieldwall"])

    contingent = Contingent.field(mustered, data=REPO)

    assert contingent.models == 18
    # The chosen option's rule is what the engine reads, not the printed profile.
    assert "Shieldwall" in contingent.unit.special_rules
    assert "Shieldwall" not in spearmen_unit.special_rules


def test_field_a_complement_without_options_matches_the_datasheet(spearmen_unit: Unit) -> None:
    """With no options, the fielded loadout equals the printed datasheet."""
    contingent = Contingent.field(
        Complement(unit=spearmen_unit, size=10),
        data=REPO,
    )

    assert contingent.unit.equipment == spearmen_unit.equipment
    assert contingent.unit.special_rules == spearmen_unit.special_rules


def test_each_arc_carries_its_initiative_cap() -> None:
    """+3 into the front arc, +4 into the flank or rear."""
    assert ChargeArc.FRONT.initiative_cap == 3
    assert ChargeArc.FLANK.initiative_cap == 4
    assert ChargeArc.REAR.initiative_cap == 4


def test_charge_rejects_a_negative_distance() -> None:
    """A negative charge distance is a programming error, not a zero bonus."""
    with pytest.raises(ValueError, match="negative distance"):
        Charge(-1, ChargeArc.FRONT)


# --- Movement: what a contingent did in its Movement phase ---


def test_the_movement_factories_carry_their_kind_and_charge() -> None:
    """Each case factory builds its kind, and only a charge carries a Charge."""
    move = Charge(6, ChargeArc.FRONT)
    assert Movement.stationary().kind is MovementKind.STATIONARY
    assert Movement.march().kind is MovementKind.MARCHED
    assert Movement.charged(move).kind is MovementKind.CHARGED
    assert Movement.stationary().charge is None
    assert Movement.march().charge is None
    assert Movement.charged(move).charge == move


def test_a_charge_counts_as_a_move() -> None:
    """`moved` is true for a march and a charge alike; false only when standing."""
    assert not Movement.stationary().moved
    assert Movement.march().moved
    assert Movement.charged(Charge(3, ChargeArc.FRONT)).moved


def test_movement_rejects_a_charge_that_disagrees_with_its_kind() -> None:
    """The raw constructor cannot pair a charge with the wrong kind — the invariant.

    The factories cannot produce these; the guard catches a direct
    construction that would let the charge and the kind fall out of step.
    """
    with pytest.raises(ValueError, match="charged movement carries no charge"):
        Movement(MovementKind.CHARGED)
    with pytest.raises(ValueError, match="marched movement carries a charge"):
        Movement(MovementKind.MARCHED, Charge(3, ChargeArc.FRONT))


def test_a_freshly_fielded_body_is_stationary(spearmen_unit: Unit) -> None:
    """A contingent defaults to the stationary movement, no charge."""
    fielded = _fielded(spearmen_unit, 10)
    assert fielded.movement == Movement.stationary()
    assert not fielded.movement.moved
    assert fielded.movement.charge is None


def test_after_records_the_movement(spearmen_unit: Unit) -> None:
    """`after` returns the same body with its movement set; the original stands."""
    fielded = _fielded(spearmen_unit, 10)
    moved = fielded.after(Movement.march())
    assert moved.movement == Movement.march()
    assert not fielded.movement.moved  # the original is unchanged
    assert moved.models == fielded.models  # only the movement changed


def test_charging_makes_the_contingent_a_charger(spearmen_unit: Unit) -> None:
    """`charging` sets the movement to that charge, carrying it for the fight."""
    move = Charge(8, ChargeArc.FRONT)
    charger = _fielded(spearmen_unit, 10).charging(move)
    assert charger.movement.charge == move
    assert charger.movement.moved


def test_field_resolves_equipment_into_the_loadout(spearmen_unit: Unit) -> None:
    """Fielding resolves printed equipment names to weapon and armour entries.

    Spearmen carry Hand Weapon and Thrusting Spear (weapons) plus Light
    Armour and Shield (armour); the loadout partitions them resolved, in
    equipment order.
    """
    contingent = Contingent.field(
        Complement(unit=spearmen_unit, size=10),
        data=REPO,
    )
    assert contingent.loadout == Loadout(
        weapons=(REPO.weapons["hand-weapon"], REPO.weapons["thrusting-spear"]),
        armour=(REPO.armoury["light-armour"], REPO.armoury["shield"]),
        rules=(REPO.rules["elven-reflexes"], REPO.rules["valour-of-ages"]),
        unresolved_rules=(
            "Close Order",
            "Martial Prowess",
            "Regimental Unit",
        ),
    )


def test_field_resolves_option_granted_equipment() -> None:
    """Equipment added by a chosen option reaches the resolved loadout."""
    archers = REPO.units["elven-archers"]
    mustered = Complement(unit=archers, size=10, options=["Light Armour"])
    contingent = Contingent.field(mustered, data=REPO)
    assert contingent.loadout is not None
    assert REPO.armoury["light-armour"] in contingent.loadout.armour


def test_field_rejects_unresolvable_equipment(spearmen_unit: Unit) -> None:
    """A typo'd equipment name fails the fielding, naming the miss.

    The data covers every unit-referenced item, so at this seam a miss is
    an error to the list-builder, not a per-volley note.
    """
    typo = spearmen_unit.model_copy(update={"equipment": ["Hand Weapon", "Shjeld"]})
    with pytest.raises(ValueError, match=r"matches no weapon or armour: \['Shjeld'\]"):
        Contingent.field(
            Complement(unit=typo, size=10),
            data=REPO,
        )


def test_field_gives_the_printed_optionless_loadout(spearmen_unit: Unit) -> None:
    """field() is the per-unit default: the printed lists resolved, no options.

    Any model count is allowed — a what-if body needs no legal list
    size — and the loadout equals what fielding an optionless
    complement resolves.
    """
    fielded = Contingent.field(spearmen_unit, 1, data=REPO)
    from_complement = Contingent.field(
        Complement(unit=spearmen_unit, size=10),
        data=REPO,
    )
    assert fielded.models == 1
    assert fielded.loadout == from_complement.loadout


def test_field_a_bare_datasheet_needs_a_model_count(spearmen_unit: Unit) -> None:
    """A bare datasheet has no size of its own, so ``models`` is required."""
    with pytest.raises(ValueError, match="needs a model count"):
        Contingent.field(spearmen_unit, data=REPO)


def test_a_remnant_keeps_its_loadout(spearmen_unit: Unit) -> None:
    """A post-casualty remnant is the same body, thinned: only the count changes."""
    fielded = Contingent.field(spearmen_unit, 10, data=REPO)
    remnant = fielded.remove_casualties(3)
    assert remnant.models == 7
    assert remnant.loadout is fielded.loadout
    assert remnant.unit is fielded.unit


# --- deploy(): the quick, by-name entry ---


def test_deploy_by_slug_matches_fielding_the_datasheet(spearmen_unit: Unit) -> None:
    """Deploying a slug matches fielding the same datasheet by hand.

    deploy resolves the name and musters it; with no options it fields the
    same body as field() given the datasheet directly.
    """
    by_name = Contingent.deploy("elven-spearmen", 10, data=REPO)
    by_hand = Contingent.field(spearmen_unit, 10, data=REPO)
    assert by_name == by_hand


def test_deploy_folds_options_through_the_complement() -> None:
    """Options thread through the Complement: Shieldwall rides on unresolved.

    Shieldwall has no rule entry, so it joins the loadout's printed
    remainder rather than resolving.
    """
    contingent = Contingent.deploy("elven-spearmen", 10, ["Shieldwall"], data=REPO)
    assert "Shieldwall" in contingent.loadout.unresolved_rules


def test_deploy_musters_a_list_legal_size() -> None:
    """The size must be list-legal: deploy goes through the Complement's validation."""
    with pytest.raises(ValueError, match="below the unit's minimum"):
        Contingent.deploy("elven-spearmen", 4, data=REPO)  # minimum is 5


def test_deploy_uses_the_default_repository_when_no_data_is_given() -> None:
    """Omitting data resolves the slug against the process-wide default corpus."""
    from avelorn.tow.data import default_repository

    by_name = Contingent.deploy("elven-spearmen", 10)
    assert by_name.unit.name == "Elven Spearmen"
    assert by_name == Contingent.deploy("elven-spearmen", 10, data=default_repository())


def test_default_repository_is_a_cached_singleton() -> None:
    """default_repository() returns one shared instance, built once."""
    from avelorn.tow.data import default_repository

    assert default_repository() is default_repository()


def test_field_tolerates_rules_without_entries(spearmen_unit: Unit) -> None:
    """A special rule with no entry is the norm: carried printed, not lost.

    Option-granted rules resolve on the same terms — Shieldwall has no
    entry under data/tow/rules/, so it joins the printed remainder that
    keeps feeding the "not factored" notes.
    """
    mustered = Complement(unit=spearmen_unit, size=10, options=["Shieldwall"])
    contingent = Contingent.field(mustered, data=REPO)
    assert contingent.loadout is not None
    assert [rule.id for rule in contingent.loadout.rules] == ["elven-reflexes", "valour-of-ages"]
    assert "Shieldwall" in contingent.loadout.unresolved_rules


def test_field_substitutes_rule_parameters_as_printed(spearmen_unit: Unit) -> None:
    """A parameterised unit rule arrives as the rule printed on the unit.

    No unit in data/ prints one yet, so a doctored datasheet exercises
    the path: "Armour Bane (2)" resolves to the (X) entry with the 2
    substituted into its effects, symmetric with the weapons and armour
    beside it.
    """
    doctored = spearmen_unit.model_copy(update={"special_rules": ["Armour Bane (2)"]})
    contingent = Contingent.field(
        Complement(unit=doctored, size=10),
        data=REPO,
    )
    assert contingent.loadout is not None
    (rule,) = contingent.loadout.rules
    assert rule.name == "Armour Bane (2)"
    effect = rule.effects[0]
    assert isinstance(effect, ModifierEffect)
    assert effect.then == {"armour-piercing": 2}


def test_loadout_answers_the_weapon_choice_by_printed_name(spearmen_unit: Unit) -> None:
    """The per-action choice picks a carried weapon by its printed name."""
    fielded = Contingent.field(spearmen_unit, 10, data=REPO)
    assert fielded.loadout.weapon("Thrusting Spear") is REPO.weapons["thrusting-spear"]
    with pytest.raises(ValueError, match="no 'Longbow' in this loadout; carried: Hand Weapon"):
        fielded.loadout.weapon("Longbow")


def test_loadout_resolves_the_carried_weapons_rules(spearmen_unit: Unit) -> None:
    """Weapon-rule names with entries resolve into the loadout's index.

    The archers' longbow prints Armour Bane (1) and Volley Fire: the
    first has an entry and resolves as printed; the second has none and
    is simply absent — the per-action compile reports it unfactored.
    """
    archers = Contingent.field(
        REPO.units["elven-archers"],
        10,
        data=REPO,
    )
    index = archers.loadout.weapon_rules
    assert set(index) == {"Armour Bane (1)"}
    assert index["Armour Bane (1)"].name == "Armour Bane (1)"


def test_an_uncarried_weapon_cannot_be_wielded(spearmen_unit: Unit) -> None:
    """A contingent is armed only with a weapon its loadout carries."""
    fielded = Contingent.field(spearmen_unit, 10, data=REPO)
    assert fielded.wielding("Thrusting Spear").in_hand() is REPO.weapons["thrusting-spear"]
    with pytest.raises(ValueError, match="no 'Longbow' in this loadout"):
        fielded.wielding("Longbow")


def test_an_unarmed_contingent_has_no_weapon_in_hand(spearmen_unit: Unit) -> None:
    """A freshly fielded body carries weapons but has none in hand until armed."""
    fielded = Contingent.field(spearmen_unit, 10, data=REPO)
    assert fielded.weapon is None
    with pytest.raises(ValueError, match="no weapon in hand"):
        fielded.in_hand()


def test_shooting_defaults_to_the_sole_missile_weapon() -> None:
    """An unarmed unit that carries one missile weapon shoots it without arming."""
    archers = Contingent.field(REPO.units["elven-archers"], 10, data=REPO)
    assert archers.weapon is None
    assert archers.shooting_weapon() is REPO.weapons["longbow"]


def test_shooting_still_honours_an_armed_weapon() -> None:
    """Arming overrides the default: the weapon in hand is what shoots."""
    guard = Contingent.field(REPO.units["lothern-sea-guard"], 10, data=REPO)
    assert guard.wielding("Warbow").shooting_weapon() is REPO.weapons["warbow"]


def test_a_contingent_with_no_missile_weapon_cannot_default_a_shot(spearmen_unit: Unit) -> None:
    """Spearmen carry no bow, so there is nothing to default a volley to."""
    fielded = Contingent.field(spearmen_unit, 10, data=REPO)
    with pytest.raises(ValueError, match="no missile weapon to shoot with"):
        fielded.shooting_weapon()


def test_several_missile_weapons_need_an_explicit_choice() -> None:
    """A unit carrying more than one bow must name which — no default is safe."""
    archers = Contingent.field(REPO.units["elven-archers"], 10, data=REPO)
    two_bows = dataclasses.replace(
        archers.loadout, weapons=(REPO.weapons["longbow"], REPO.weapons["warbow"])
    )
    ambiguous = dataclasses.replace(archers, loadout=two_bows)
    with pytest.raises(ValueError, match="several missile weapons"):
        ambiguous.shooting_weapon()


# --- Formation: the geometry of ranks and files ---


def test_formation_geometry() -> None:
    """files, ranks, full_ranks and remainder over a five-wide formation."""
    full = Formation(models=10, frontage=5)  # two complete ranks
    assert (full.files, full.full_ranks, full.remainder, full.ranks) == (5, 2, 0, 2)

    ragged = Formation(models=12, frontage=5)  # 5 + 5 + a rear rank of 2
    assert (ragged.files, ragged.full_ranks, ragged.remainder, ragged.ranks) == (5, 2, 2, 3)

    thin = Formation(models=3, frontage=5)  # one incomplete rank
    assert (thin.files, thin.full_ranks, thin.remainder, thin.ranks) == (3, 0, 3, 1)


# --- frontage: the formation's width ---


def test_frontage_defaults_to_the_troop_types_rank_width(spearmen_unit: Unit) -> None:
    """With no width chosen, a unit ranks at its troop type's rank width.

    Elven Spearmen are Regular Infantry: five models to a rank. The
    datasheet's troop-type profile, resolved at load, is what fielding
    reads.
    """
    fielded = _fielded(spearmen_unit, 10)
    assert fielded.unit.troop_type_profile == REPO.troop_types["regular-infantry"]
    assert fielded.frontage == 5
    assert fielded.formation == Formation(models=10, frontage=5)


def test_a_chosen_frontage_overrides_the_default(spearmen_unit: Unit) -> None:
    """A width given at fielding is the contingent's frontage, default or not."""
    assert _fielded(spearmen_unit, 10, frontage=8).frontage == 8


def test_fielding_an_unresolved_datasheet_is_refused(spearmen_unit: Unit) -> None:
    """A datasheet with no resolved troop-type profile cannot be fielded."""
    raw = spearmen_unit.model_copy(update={"troop_type_profile": None})
    with pytest.raises(ValueError, match="troop-type profile unresolved"):
        _fielded(raw, 10)


def test_every_troop_type_has_a_profile() -> None:
    """Drift guard: the registry covers the TroopType vocabulary exactly.

    So a troop type joining the enum must gain a data file, and no stray
    profile can name a troop type the enum does not.
    """
    assert {p.name for p in REPO.troop_types.values()} == {t.value for t in TroopType}


def test_frontage_must_be_a_positive_width(spearmen_unit: Unit) -> None:
    """A frontage below one model wide is a programming error, not a zero."""
    with pytest.raises(ValueError, match="at least 1 model wide"):
        _fielded(spearmen_unit, 10, frontage=0)


# --- the rank bonus a formation claims ---


def test_rank_bonus_counts_ranks_behind_the_first(spearmen_unit: Unit) -> None:
    """Regular Infantry (5 wide): +1 for each full rank behind the first."""
    assert _fielded(spearmen_unit, 5).rank_bonus == 0  # one rank
    assert _fielded(spearmen_unit, 10).rank_bonus == 1  # two ranks
    assert _fielded(spearmen_unit, 15).rank_bonus == 2  # three ranks


def test_rank_bonus_is_capped_by_troop_type(spearmen_unit: Unit) -> None:
    """Regular Infantry cap the bonus at +2, however deep the unit ranks."""
    assert _fielded(spearmen_unit, 25).rank_bonus == 2  # five ranks, capped


def test_melee_attacks_are_the_fighting_rank_alone(spearmen_unit: Unit) -> None:
    """Only the front rank fights; deeper ranks add nothing, a wider front does.

    Regular Infantry are A1, five wide by default. A single rank of five
    throws five; ten or fifteen throw the same five (the ranks behind press
    forward but do not fight); ranked wider, the whole body is one fighting
    rank and every model throws.
    """
    assert _fielded(spearmen_unit, 5).melee_attacks() == 5  # one rank of five
    assert _fielded(spearmen_unit, 10).melee_attacks() == 5  # front rank of a two-rank body
    assert _fielded(spearmen_unit, 15).melee_attacks() == 5  # deeper still, front rank only
    assert _fielded(spearmen_unit, 15, frontage=15).melee_attacks() == 15  # all in one rank


def test_melee_attacks_scale_with_the_attacks_characteristic(spearmen_unit: Unit) -> None:
    """Each fighting-rank model throws its full Attacks."""
    two_attacks = spearmen_unit.model_copy(deep=True)
    two_attacks.profiles[0].characteristics[Characteristic.ATTACKS] = 2
    assert _fielded(two_attacks, 10).melee_attacks() == 10  # a front rank of five, A2


def test_a_rear_rank_counts_only_when_wide_enough(spearmen_unit: Unit) -> None:
    """Ranked six wide, an incomplete rear rank counts only with five in it."""
    assert _fielded(spearmen_unit, 10, frontage=6).rank_bonus == 0  # 6 + rear of 4
    assert _fielded(spearmen_unit, 11, frontage=6).rank_bonus == 1  # 6 + rear of 5


def test_a_wider_frontage_trades_ranks_for_width(spearmen_unit: Unit) -> None:
    """Ranking wider claims fewer ranks: ten models ten wide is a single rank."""
    assert _fielded(spearmen_unit, 10, frontage=10).rank_bonus == 0


def test_a_troop_type_that_does_not_rank_up_claims_no_bonus(spearmen_unit: Unit) -> None:
    """A single-model troop type claims no bonus, however many models."""
    monster = spearmen_unit.model_copy(
        update={"troop_type_profile": REPO.troop_types["monstrous-creature"]}
    )
    assert _fielded(monster, 6).rank_bonus == 0
