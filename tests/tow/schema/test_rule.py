"""Rule schema tests: data/ validation."""

from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from avelorn.core.loading import load_yaml
from avelorn.tow.data import TOWRepository, rule_paths
from avelorn.tow.schema.rule import ModifierEffect, Quantity, RerollEffect, Rule, RuleEffect
from avelorn.tow.schema.unit import Characteristic

_EFFECT = TypeAdapter(RuleEffect)

RULE_FILES = rule_paths()


def test_data_glob_finds_files() -> None:
    """The data/ glob finds rule files; guards the parametrized test below."""
    assert RULE_FILES


@pytest.mark.parametrize("path", RULE_FILES, ids=lambda p: p.stem)
def test_rule_yaml_is_valid(path: Path) -> None:
    """Every rule YAML under data/ validates against the schema."""
    rule = load_yaml(path, Rule)
    assert rule.id == path.stem
    assert rule.paragraphs


def test_when_parses_a_subject_fact_beside_the_event() -> None:
    """A when carries subject facts (movement) beside the natural die event."""
    effect = _EFFECT.validate_python(
        {
            "when": {"movement": {"moved": True}, "natural": {"face": 6, "roll": "roll-to-wound"}},
            "add": {"to-hit": -1},
        }
    )
    assert isinstance(effect, ModifierEffect)
    assert effect.when is not None and effect.when.movement is not None
    assert effect.when.movement.moved is True
    assert effect.natural is not None and effect.natural.face == 6
    assert effect.add == {"to-hit": -1}


def test_when_parses_a_wielding_family_gate() -> None:
    """A when gates on the weapon in hand's family (Arrows of Isha's any bow)."""
    effect = _EFFECT.validate_python(
        {"when": {"wielding": {"type": "bow"}}, "add": {"armour-piercing": 1}}
    )
    assert isinstance(effect, ModifierEffect)
    assert effect.when is not None and effect.when.wielding is not None
    assert effect.when.wielding.type == "bow"
    assert effect.when.wielding.name is None


def test_wielding_gate_must_constrain_type_or_name() -> None:
    """An equipment gate that asks nothing is a data error, not a no-op."""
    with pytest.raises(ValidationError, match="type or name"):
        _EFFECT.validate_python({"when": {"wielding": {}}, "add": {"armour-piercing": 1}})


def test_wielding_gate_rejects_an_unknown_family() -> None:
    """A weapon family outside the closed WeaponType set is a data error."""
    with pytest.raises(ValidationError, match="wielding"):
        _EFFECT.validate_python(
            {"when": {"wielding": {"type": "crossbow"}}, "add": {"armour-piercing": 1}}
        )


def test_when_parses_a_worn_gate_beside_a_wielding_one() -> None:
    """Parry's gear reads as two subjects of one when: the weapon and the armour.

    The equipment-in-use axis has both halves, gated exactly like any other fact
    and conjoined with them.
    """
    effect = _EFFECT.validate_python(
        {
            "when": {
                "combat": True,
                "wielding": {"name": "Hand Weapon"},
                "worn": {"name": "Shield"},
            },
            "add": {"armour-value": 1},
        }
    )
    assert isinstance(effect, ModifierEffect)
    assert effect.when is not None
    assert effect.when.wielding is not None and effect.when.wielding.name == "Hand Weapon"
    assert effect.when.worn is not None and effect.when.worn.name == "Shield"


def test_worn_gate_must_constrain_a_name() -> None:
    """An armour gate that asks nothing is a data error, not a no-op."""
    with pytest.raises(ValidationError, match="armour gate must constrain name"):
        _EFFECT.validate_python({"when": {"worn": {}}, "add": {"armour-value": 1}})


def test_worn_gate_has_no_family_axis() -> None:
    """Armour is only ever its printed name, so a ``type`` on it is a load error.

    The asymmetry with the weapon gate is deliberate: weapons carry a modelled
    family (a bow), armour does not, so asking for one is a data error rather
    than a silently-ignored key.
    """
    with pytest.raises(ValidationError, match="worn"):
        _EFFECT.validate_python(
            {"when": {"worn": {"name": "Shield", "type": "bow"}}, "add": {"armour-value": 1}}
        )


def test_grant_effect_parses_and_discriminates_by_its_key() -> None:
    """``grants`` names a conferred rule and discriminates the effect, like ``add``.

    An effect carrying ``grants`` is a grant; it takes the shared gate and
    rejects a modifier's keys, the same structural discrimination the re-roll
    effect uses.
    """
    from avelorn.tow.schema.rule import GrantEffect

    effect = _EFFECT.validate_python(
        {"grants": "Armour Bane (1)", "when": {"wielding": {"type": "bow"}}}
    )
    assert isinstance(effect, GrantEffect)
    assert effect.grants == "Armour Bane (1)"
    assert effect.when is not None and effect.when.wielding is not None
    with pytest.raises(ValidationError):  # a grant is not a modifier
        _EFFECT.validate_python({"grants": "Armour Bane (1)", "add": {"to-hit": -1}})


def test_rule_level_when_folds_into_each_effect() -> None:
    """A rule-level ``when`` is the shared gate, conjoined into every effect.

    Written once at the rule (Arrows of Isha's "any bow"), it lands on each
    clause — a flat modifier and a grant — so the data does not repeat it and
    the engine still reads one gate per effect.
    """
    rule = Rule.model_validate(
        {
            "id": "doctored",
            "name": "Doctored",
            "paragraphs": ["…"],
            "when": {"wielding": {"type": "bow"}},
            "effects": [{"add": {"armour-piercing": 1}}, {"grants": "Armour Bane (1)"}],
        }
    )
    for effect in rule.effects:
        assert effect.when is not None and effect.when.wielding is not None
        assert effect.when.wielding.type == "bow"


def test_rule_level_when_conjoins_with_an_effect_gate() -> None:
    """The rule's gate unions with a disjoint effect gate; a clash is an error."""
    rule = Rule.model_validate(
        {
            "id": "doctored",
            "name": "Doctored",
            "paragraphs": ["…"],
            "when": {"wielding": {"type": "bow"}},
            "effects": [
                {"when": {"natural": {"face": 6, "roll": "roll-to-wound"}}, "add": {"to-hit": -1}}
            ],
        }
    )
    (effect,) = rule.effects
    assert effect.when is not None
    assert effect.when.wielding is not None and effect.when.natural is not None
    with pytest.raises(ValidationError, match="gated at both the rule and an effect"):
        Rule.model_validate(
            {
                "id": "doctored",
                "name": "Doctored",
                "paragraphs": ["…"],
                "when": {"wielding": {"type": "bow"}},
                "effects": [{"when": {"wielding": {"name": "Longbow"}}, "add": {"to-hit": -1}}],
            }
        )


def test_choice_effect_forces_a_decision_outcome() -> None:
    """``forces`` maps a decision to its forced outcome, keyed like a modifier's ``add``.

    An effect carrying ``forces`` is a choice effect; it rejects a modifier's
    keys, and both the decision key and the outcome value are closed vocabularies.
    """
    from avelorn.tow.schema.rule import ChoiceEffect

    effect = _EFFECT.validate_python({"forces": {"break": "fall-back-in-good-order"}})
    assert isinstance(effect, ChoiceEffect)
    assert effect.forces == {"break": "fall-back-in-good-order"}
    with pytest.raises(ValidationError):  # a choice effect is not a modifier
        _EFFECT.validate_python(
            {"forces": {"break": "fall-back-in-good-order"}, "add": {"to-hit": -1}}
        )
    with pytest.raises(ValidationError):  # decision outside the vocabulary
        _EFFECT.validate_python({"forces": {"rally": "fall-back-in-good-order"}})
    with pytest.raises(ValidationError):  # outcome outside the vocabulary
        _EFFECT.validate_python({"forces": {"break": "hold-the-line"}})


def test_when_is_optional() -> None:
    """Without a when, the modifier applies to every attack."""
    effect = _EFFECT.validate_python({"add": {"armour-piercing": 1}})
    assert isinstance(effect, ModifierEffect)
    assert effect.when is None
    assert effect.natural is None


def test_natural_rejects_an_unknown_roll() -> None:
    """A roll outside the registry is a data error, not a silent inert."""
    with pytest.raises(ValidationError, match="roll"):
        _EFFECT.validate_python(
            {
                "when": {"natural": {"face": 6, "roll": "roll-to-wnd"}},
                "add": {"armour-piercing": 1},
            }
        )


def test_natural_rejects_an_impossible_face() -> None:
    """A natural face outside the die is a data error."""
    with pytest.raises(ValidationError, match="face"):
        _EFFECT.validate_python(
            {
                "when": {"natural": {"face": 7, "roll": "roll-to-wound"}},
                "add": {"armour-piercing": 1},
            }
        )


def test_natural_rejects_a_rollless_stage() -> None:
    """A natural face can only be shown by an attack roll's die.

    Make Panic Tests is a registry stage, but it rolls 2d6 for the
    whole unit — no single natural face exists there, so naming it is a
    data error at load, not a quiet unfactored note at compile.
    """
    with pytest.raises(ValidationError, match="no natural face is shown there"):
        _EFFECT.validate_python(
            {
                "when": {"natural": {"face": 6, "roll": "make-panic-tests"}},
                "add": {"armour-piercing": 1},
            }
        )


def test_natural_requires_a_roll_fact() -> None:
    """The event key takes a die's face, not a true/false."""
    with pytest.raises(ValidationError, match="natural"):
        _EFFECT.validate_python({"when": {"natural": True}, "add": {"armour-piercing": 1}})


def test_a_boolean_subject_fact_rejects_a_die_face() -> None:
    """A subject's boolean fact takes true/false, not a die's face."""
    with pytest.raises(ValidationError, match="movement"):
        _EFFECT.validate_python(
            {
                "when": {"movement": {"moved": {"face": 6, "roll": "roll-to-wound"}}},
                "add": {"to-hit": -1},
            }
        )


def test_add_rejects_an_unknown_quantity() -> None:
    """A quantity outside the closed vocabulary is a data error."""
    with pytest.raises(ValidationError, match="add"):
        _EFFECT.validate_python({"add": {"to-wnd": -1}})


def test_an_effect_needs_an_operation() -> None:
    """A modifier without an add or set is meaningless."""
    with pytest.raises(ValidationError, match="operation"):
        _EFFECT.validate_python({"when": {"movement": {"moved": True}}})


def test_an_operation_must_move_something() -> None:
    """An empty add is meaningless."""
    with pytest.raises(ValidationError, match="at least 1"):
        _EFFECT.validate_python({"add": {}})


def test_add_moves_a_characteristic() -> None:
    """A profile characteristic is one more quantity an add can move."""
    effect = _EFFECT.validate_python({"add": {"I": 1}, "maximum": 10})
    assert isinstance(effect, ModifierEffect)
    assert effect.add == {Characteristic.INITIATIVE: 1}
    assert effect.maximum == 10


def test_set_parses_under_its_alias() -> None:
    """The set operation loads under its printed key and reads back as set_.

    Strike First's shape: replace the Initiative characteristic outright,
    no add. The YAML key is ``set``; the attribute dodges the builtin.
    """
    effect = _EFFECT.validate_python({"set": {"I": 10}})
    assert isinstance(effect, ModifierEffect)
    assert effect.set_ == {Characteristic.INITIATIVE: 10}
    assert effect.add is None
    assert effect.quantities == {Characteristic.INITIATIVE}


def test_add_and_set_may_share_a_seam() -> None:
    """One effect may both add and set, as long as it stays on one seam."""
    effect = _EFFECT.validate_python({"set": {"I": 10}, "add": {"I": 1}})
    assert isinstance(effect, ModifierEffect)
    assert effect.set_ == {Characteristic.INITIATIVE: 10}
    assert effect.add == {Characteristic.INITIATIVE: 1}


def test_set_rejects_a_roll_quantity() -> None:
    """A set replaces a base value; a roll's target has none, so it is a data error.

    Loud at load — the same discipline as a maximum on a roll — rather than a
    note that would go silently unfactored forever. Armour value is likewise
    an improvement, not a base to replace.
    """
    with pytest.raises(ValidationError, match="set cannot replace a roll or armour"):
        _EFFECT.validate_python({"set": {"to-hit": 1}})
    with pytest.raises(ValidationError, match="set cannot replace a roll or armour"):
        _EFFECT.validate_python({"set": {"armour-value": 3}})


def test_maximum_requires_a_characteristic() -> None:
    """Only a characteristic prints a ceiling; on a roll it is a data error."""
    with pytest.raises(ValidationError, match="maximum"):
        _EFFECT.validate_python({"add": {"to-hit": -1}, "maximum": 10})


def test_modifier_rejects_a_spelled_out_stage() -> None:
    """Where a change lands follows from its quantity; a stage is a data error.

    Pins the migration: earlier shapes carried a top-level ``stage``,
    which must now fail loudly rather than parse inert.
    """
    with pytest.raises(ValidationError, match="stage"):
        _EFFECT.validate_python({"stage": "roll-to-hit", "add": {"to-hit": -1}})


def test_modifier_rejects_the_retired_then_key() -> None:
    """The old bare-number ``then`` field is gone; it must fail loudly.

    Pins the migration to named operations — a leftover ``then`` in data
    is a forbidden extra, not a silent inert.
    """
    with pytest.raises(ValidationError, match="then"):
        _EFFECT.validate_python({"then": {"to-hit": -1}})


def test_condition_outside_the_vocabulary_rejected() -> None:
    """A condition name outside the closed vocabulary is a data error."""
    with pytest.raises(ValidationError, match="when"):
        _EFFECT.validate_python({"when": {"sprinting": True}, "add": {"to-hit": -1}})


def test_condition_must_ask_something() -> None:
    """An empty when is meaningless."""
    with pytest.raises(ValidationError, match="gate on something"):
        _EFFECT.validate_python({"when": {}, "add": {"to-hit": -1}})


def test_parameter_reference_requires_a_placeholder_name() -> None:
    """An effect may use "X" only under a name that prints one.

    An unbindable placeholder is a data error at load, not a runtime
    surprise.
    """
    with pytest.raises(ValidationError, match="X parameter"):
        Rule(
            id="armour-bane",
            name="Armour Bane",
            paragraphs=["…"],
            effects=[ModifierEffect(add={Quantity.ARMOUR_PIERCING: "X"})],
        )


def test_reroll_effect_parses_with_causes() -> None:
    """The re-roll operation names its seam by key and carries the cause filter."""
    effect = _EFFECT.validate_python(
        {"reroll": "make-panic-tests", "causes": ["heavy-casualties", "fled-through"]}
    )
    assert isinstance(effect, RerollEffect)
    assert effect.reroll == "make-panic-tests"
    assert len(effect.causes) == 2


def test_reroll_effect_rejects_unknown_cause() -> None:
    """A cause outside the printed taxonomy is a data error."""
    with pytest.raises(ValidationError, match="causes"):
        _EFFECT.validate_python({"reroll": "make-panic-tests", "causes": ["bad-day"]})


def test_reroll_is_its_own_operation_key_beside_add_and_set() -> None:
    """``re-roll`` discriminates the effect by key, like ``add`` — no ``kind``.

    An effect carrying ``re-roll`` is a re-roll; one carrying ``add`` a modifier.
    The retired ``kind`` discriminator, and a stray ``add`` on a re-roll, are
    both forbidden extras — the two shapes reject each other's keys.
    """
    assert isinstance(_EFFECT.validate_python({"reroll": "roll-to-hit"}), RerollEffect)
    with pytest.raises(ValidationError):  # the old kind discriminator is gone
        _EFFECT.validate_python({"kind": "reroll", "reroll": "roll-to-hit"})
    with pytest.raises(ValidationError):  # a re-roll is not a modifier
        _EFFECT.validate_python({"reroll": "roll-to-hit", "add": {"to-hit": -1}})


def test_reroll_effect_parses_a_natural_face_on_an_attack_roll() -> None:
    """An attack-roll re-roll carries the natural face it re-rolls, and its gate."""
    effect = _EFFECT.validate_python(
        {
            "reroll": "roll-to-hit",
            "on_natural": 1,
            "when": {"combat": True, "wielding": {"name": "Hand Weapon"}},
        }
    )
    assert isinstance(effect, RerollEffect)
    assert effect.reroll == "roll-to-hit"
    assert effect.on_natural == 1
    assert effect.when is not None
    assert effect.when.wielding is not None
    assert effect.when.wielding.name == "Hand Weapon"


def test_reroll_effect_rejects_a_natural_face_on_a_panic_test() -> None:
    """on_natural restricts an attack roll; a panic test shows no natural face."""
    with pytest.raises(ValidationError, match="on_natural"):
        _EFFECT.validate_python({"reroll": "make-panic-tests", "on_natural": 1})


def test_reroll_effect_rejects_a_cause_on_an_attack_roll() -> None:
    """Causes restricts a panic test; an attack roll has no panic cause."""
    with pytest.raises(ValidationError, match="causes"):
        _EFFECT.validate_python({"reroll": "roll-to-hit", "causes": ["heavy-casualties"]})


def test_reroll_effect_rejects_a_face_out_of_range() -> None:
    """A natural face is a die face: 1 to 6."""
    with pytest.raises(ValidationError):
        _EFFECT.validate_python({"reroll": "roll-to-hit", "on_natural": 7})


def test_ops_speak_to_one_seam() -> None:
    """One effect may not move quantities from two seams together.

    Roll quantities are consumed by the dice walk, characteristics by the
    characteristic read, rank quantities by the fighting-rank query; all-
    or-nothing reporting holds per consumer, so a mixed operation could be
    half-consumed while its rule's note is dropped whole. A rule whose
    sentence spans seams writes one effect per seam — and add and set are
    weighed together.
    """
    with pytest.raises(ValidationError, match="may not mix"):
        _EFFECT.validate_python({"add": {"to-hit": -1, "I": 1}})  # roll + characteristic
    with pytest.raises(ValidationError, match="may not mix"):
        _EFFECT.validate_python({"add": {"fighting-ranks": 1, "I": 1}})  # rank + characteristic
    with pytest.raises(ValidationError, match="may not mix"):
        _EFFECT.validate_python({"add": {"fighting-ranks": 1, "to-hit": -1}})  # rank + roll
    with pytest.raises(ValidationError, match="may not mix"):
        _EFFECT.validate_python({"set": {"I": 10}, "add": {"to-hit": -1}})  # set + add, two seams


def test_a_rank_quantity_is_its_own_seam() -> None:
    """A formation quantity is a valid, single-seam operation (Press of Battle's shape)."""
    effect = _EFFECT.validate_python(
        {"when": {"movement": {"charge": False}}, "add": {"fighting-ranks": 1}}
    )
    assert isinstance(effect, ModifierEffect)
    assert effect.add == {"fighting-ranks": 1}
    assert effect.when is not None and effect.when.movement is not None
    assert effect.when.movement.charge is False


def test_charge_gate_parses_a_distance_predicate() -> None:
    """The charge is a path: movement -> charge -> distance -> comparator (Furious Charge)."""
    effect = _EFFECT.validate_python(
        {"when": {"movement": {"charge": {"distance": {"at_least": 3}}}}, "add": {"A": 1}}
    )
    assert isinstance(effect, ModifierEffect)
    assert effect.when is not None and effect.when.movement is not None
    gate = effect.when.movement.charge
    assert gate is not None and not isinstance(gate, bool)
    assert gate.distance is not None and gate.distance.at_least == 3


def test_charge_gate_rejects_an_unknown_property() -> None:
    """A charge property outside the model is a data error at load (path validation)."""
    with pytest.raises(ValidationError, match="speed"):
        _EFFECT.validate_python(
            {"when": {"movement": {"charge": {"speed": {"at_least": 3}}}}, "add": {"A": 1}}
        )


def test_unknown_subject_is_rejected() -> None:
    """A subject outside the When vocabulary is a data error at load."""
    with pytest.raises(ValidationError, match="when"):
        _EFFECT.validate_python({"when": {"weather": {"raining": True}}, "add": {"to-hit": -1}})


def test_comparison_names_exactly_one_comparator() -> None:
    """A comparison leaf tests one thing; two comparators is a data error."""
    with pytest.raises(ValidationError, match="exactly one"):
        _EFFECT.validate_python(
            {
                "when": {"movement": {"charge": {"distance": {"at_least": 3, "at_most": 6}}}},
                "add": {"A": 1},
            }
        )


def test_every_quantity_routes_to_a_seam() -> None:
    """Each Quantity member declares its seam; a new one without a case fails.

    Drift guard: the seam property's match is total, so calling it for every
    member both proves the routing exists and (via its assert_never fallthrough)
    trips at runtime the moment a member joins without being placed.
    """
    from avelorn.tow.schema.rule import Quantity, Seam

    assert {q.seam for q in Quantity} == {
        Seam.ROLL,
        Seam.RANK,
        Seam.COMBAT_RESULT,
        Seam.ARMOUR,
        Seam.WARD,
    }


def test_enemy_flips_only_a_roll_quantity() -> None:
    """The enemy subject flips a quantity to the other seat, which only the walk resolves.

    An enemy-subject armour-value operation has no consumer (the armour fold
    folds a side's own save), so it is a data error at load, not a silent
    unfactored note forever.
    """
    with pytest.raises(ValidationError, match="enemy flips a roll quantity"):
        _EFFECT.validate_python({"enemy": True, "add": {"armour-value": 1}})


def test_successful_dice_re_roll_names_a_per_attack_die() -> None:
    """The successful/failed restriction reads a single die's result.

    Make Panic Tests rolls 2D6 for the whole unit — no single die succeeds
    or fails on its own, so a successful-dice re-roll there is a data error.
    """
    with pytest.raises(ValidationError, match="successful-dice re-roll"):
        _EFFECT.validate_python({"reroll": "make-panic-tests", "of": "successful"})


def test_enemy_re_roll_names_a_per_attack_die() -> None:
    """The enemy subject flips a per-attack die; the panic seam folds a side's own tests."""
    with pytest.raises(ValidationError, match="enemy flips a per-attack die"):
        _EFFECT.validate_python({"reroll": "make-panic-tests", "enemy": True})


def test_every_rule_entry_carries_effects() -> None:
    """A rule the engine cannot apply is filed by not filing it at all.

    An entry with no effects reports "special rule not factored" exactly as a
    rule with no file does, so the file adds nothing but the appearance of
    having been modelled. `avelorn rules list --unmodelled` names what is
    missing; data/ holds only what folds.
    """
    idle = sorted(rule.id for rule in TOWRepository().rules.values() if not rule.effects)
    assert idle == []


def test_a_ward_save_is_granted_at_a_value_never_moved() -> None:
    """A ward is granted whole ("has a 6+ Ward save"), so a set; an add has no printed form."""
    _EFFECT.validate_python({"set": {"ward-save": 6}})
    with pytest.raises(ValidationError, match="granted at a value"):
        _EFFECT.validate_python({"add": {"ward-save": 1}})


def test_a_ward_save_takes_no_maximum() -> None:
    """A printed ceiling caps a characteristic or the armour value, never a ward."""
    with pytest.raises(ValidationError, match="maximum bounds"):
        _EFFECT.validate_python({"set": {"ward-save": 6}, "maximum": 4})
