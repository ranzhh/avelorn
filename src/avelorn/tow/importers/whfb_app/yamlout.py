"""Serialize a Unit to YAML in the hand-authored style used under data/.

Profiles are emitted as one flow mapping per line (mirroring the printed
stat line), defaults and empty fields are omitted, and "-" stands in for
not-applicable stats, as in the source material.
"""

from __future__ import annotations

import re

import yaml

from avelorn.tow.schema.unit import Profile, Unit, UnitOption


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

    text = yaml.dump(doc, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=120)
    # Pad flow-mapping braces ({ name: ... }) to match the hand-authored style.
    text = re.sub(r"^(\s*- )\{(.*)\}$", r"\1{ \2 }", text, flags=re.M)
    if source_url:
        text = f"# Source: {source_url}\n" + text
    return text


def _profile_row(profile: Profile) -> _FlowMap:
    row = profile.model_dump(by_alias=True)
    return _FlowMap({k: "-" if v is None else v for k, v in row.items()})


def _option_row(option: UnitOption) -> dict:
    row: dict = {"name": option.name, "kind": option.kind.value}
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
