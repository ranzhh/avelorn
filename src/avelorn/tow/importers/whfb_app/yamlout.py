"""Serialize imported models to YAML in the hand-authored style used under data/.

Profiles are emitted as one flow mapping per line (mirroring the printed
stat line), defaults and empty fields are omitted, and "-" stands in for
not-applicable stats, as in the source material.
"""

from __future__ import annotations

import re

import yaml

from avelorn.tow.schema.armour import Armour
from avelorn.tow.schema.correction import Correction
from avelorn.tow.schema.rule import Rule
from avelorn.tow.schema.unit import Characteristic, Profile, ProfileRole, Unit, UnitOption
from avelorn.tow.schema.weapon import Weapon, WeaponProfile


class _FlowMap(dict):
    pass


class _FlowList(list):
    pass


class _Dumper(yaml.SafeDumper):
    def increase_indent(self, flow: bool = False, indentless: bool = False) -> None:
        # Indent block sequences under their key, as the hand-authored files do.
        return super().increase_indent(flow, False)


_Dumper.add_representer(
    _FlowMap,
    lambda d, data: d.represent_mapping("tag:yaml.org,2002:map", data, flow_style=True),
)
_Dumper.add_representer(
    _FlowList,
    lambda d, data: d.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=True),
)


def unit_to_yaml(unit: Unit, source_url: str | None = None) -> str:
    """Serialize a unit for data/, with its source URL as a header comment.

    Returns:
        The YAML document text.
    """
    doc: dict = {
        "id": unit.id,
        "name": unit.name,
        "points": unit.points,
        "unit_size": {"min": unit.unit_size.min}
        | ({"max": unit.unit_size.max} if unit.unit_size.max is not None else {}),
        "troop_type": unit.troop_type.value,
    }
    if unit.base_size is not None:
        doc["base_size"] = {
            "width_mm": unit.base_size.width_mm,
            "depth_mm": unit.base_size.depth_mm,
        }
    doc["profiles"] = [_profile_row(p) for p in unit.profiles]
    if unit.equipment:
        doc["equipment"] = list(unit.equipment)
    if unit.special_rules:
        doc["special_rules"] = list(unit.special_rules)
    if unit.options:
        doc["options"] = [_option_row(o) for o in unit.options]
    _add_caveats(doc, unit.caveats)
    _add_corrections(doc, unit.corrections)
    return _dump(doc, source_url)


def weapon_to_yaml(weapon: Weapon, source_url: str | None = None) -> str:
    """Serialize a weapon for data/, with its source URL as a header comment.

    Returns:
        The YAML document text.
    """
    doc: dict = {"id": weapon.id, "name": weapon.name}
    # Hand-set, never scraped: written back so a re-import does not drop it.
    if weapon.weapon_type is not None:
        doc["weapon_type"] = weapon.weapon_type.value
    doc["profiles"] = [_weapon_profile_row(p) for p in weapon.profiles]
    if weapon.notes is not None:
        doc["notes"] = weapon.notes
    _add_caveats(doc, weapon.caveats)
    _add_corrections(doc, weapon.corrections)
    return _dump(doc, source_url)


def armour_to_yaml(armour: Armour, source_url: str | None = None) -> str:
    """Serialize an armour item for data/, with its source URL as a header comment.

    Returns:
        The YAML document text.
    """
    doc: dict = {"id": armour.id, "name": armour.name}
    if armour.armour_value is not None:
        doc["armour_value"] = armour.armour_value
    if armour.armour_value_improvement is not None:
        doc["armour_value_improvement"] = armour.armour_value_improvement
    if armour.notes is not None:
        doc["notes"] = armour.notes
    _add_caveats(doc, armour.caveats)
    _add_corrections(doc, armour.corrections)
    return _dump(doc, source_url)


def rule_to_yaml(rule: Rule, source_url: str | None = None) -> str:
    """Serialize a rule for data/, with its source URL as a header comment.

    Returns:
        The YAML document text.
    """
    doc: dict = {"id": rule.id, "name": rule.name}
    if rule.page is not None:
        doc["page"] = rule.page
    if rule.category is not None:
        doc["category"] = rule.category
    if rule.flavour is not None:
        doc["flavour"] = rule.flavour
    doc["paragraphs"] = list(rule.paragraphs)
    if rule.effects:
        # by_alias so an operation prints as the rulebook names it: a
        # ModifierEffect's `set` is `set_` on the model only to clear the
        # keyword.
        doc["effects"] = [
            e.model_dump(mode="json", exclude_none=True, by_alias=True) for e in rule.effects
        ]
    _add_caveats(doc, rule.caveats)
    _add_corrections(doc, rule.corrections)
    return _dump(doc, source_url)


def _add_caveats(doc: dict, caveats: str | None) -> None:
    """Write what this build does not model, where anything was written."""
    if caveats is not None:
        doc["caveats"] = caveats


def _add_corrections(doc: dict, corrections: list[Correction]) -> None:
    """Close the document with where this corpus departs from the source."""
    if corrections:
        doc["corrections"] = [c.model_dump(mode="json", exclude_none=True) for c in corrections]


def _dump(doc: dict, source_url: str | None) -> str:
    text = yaml.dump(doc, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=120)
    # Pad flow-mapping braces ({ name: ... }) to match the hand-authored style.
    text = re.sub(r"^(\s*- )\{(.*)\}$", r"\1{ \2 }", text, flags=re.M)
    if source_url:
        text = f"# Source: {source_url}\n" + text
    return text


def _profile_row(profile: Profile) -> _FlowMap:
    row: dict = {"name": profile.name}
    # Written only when it is not the default, so a plain infantry datasheet
    # reads as it always did.
    if profile.role is not ProfileRole.RANK_AND_FILE:
        row["role"] = profile.role.value
    for characteristic in Characteristic:
        value = profile[characteristic]
        row[characteristic.value] = "-" if value is None else value
    return _FlowMap(row)


def _weapon_profile_row(profile: WeaponProfile) -> _FlowMap:
    row: dict = {}
    if profile.name is not None:
        row["name"] = profile.name
    row["R"] = profile.range
    strength = profile.strength
    row["S"] = strength.base if not strength.is_relative else strength.printed
    row["AP"] = profile.armour_piercing or "-"
    if profile.special_rules:
        row["special_rules"] = _FlowList(profile.special_rules)
    return _FlowMap(row)


def _option_row(option: UnitOption) -> dict:
    # Written key by key to keep the printed reading order rather than the
    # model's; a drift guard in the tests fails if a field is added to
    # UnitOption and not written here.
    row: dict = {"name": option.name, "kind": option.kind.value}
    if option.applies_to is not None:
        row["applies_to"] = option.applies_to
    if option.points is not None:
        row["points"] = option.points
    if option.per_model:
        row["per_model"] = True
    if option.points_budget is not None:
        row["points_budget"] = option.points_budget
    if option.adds_rules:
        row["adds_rules"] = _FlowList(option.adds_rules)
    if option.removes_rules:
        row["removes_rules"] = _FlowList(option.removes_rules)
    if option.adds_equipment:
        row["adds_equipment"] = _FlowList(option.adds_equipment)
    if option.removes_equipment:
        row["removes_equipment"] = _FlowList(option.removes_equipment)
    if option.limit is not None:
        row["limit"] = option.limit
    return row
