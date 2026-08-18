"""Map whfb.app Weapons of War pages onto the weapon and armour schemas.

A weapon page embeds one `weaponProfile` entry per printed profile row,
followed by optional "Notes:" paragraphs. An armour page has no profile:
its mechanics are stated in prose ("Armour Value: 6+", "improves its
armour value by 1"). As with units, nothing is guessed silently — prose
the parser does not understand becomes a warning for the reviewing human.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic import ValidationError

from avelorn.tow.schema.armour import Armour
from avelorn.tow.schema.weapon import Weapon, WeaponProfile

from . import richtext
from .parse import WhfbParseError
from .richtext import Node

_PROFILE_NAME_SUFFIX = " (Profile)"
_RANGE_INCHES_RE = re.compile(r'(\d+)\s*"')
_ARMOUR_VALUE_RE = re.compile(r"Armour Value:\s*(\d+)\+")
_IMPROVEMENT_RE = re.compile(r"improves its armour value by (\d+)")


@dataclass
class WeaponImport:
    """A parsed weapon plus everything the parser was unsure about."""

    weapon: Weapon
    warnings: list[str]


@dataclass
class ArmourImport:
    """A parsed armour entry plus everything the parser was unsure about."""

    armour: Armour
    warnings: list[str]


def parse_weapon(entry: Node) -> WeaponImport:
    """Parse a Weapons of War page entry into a Weapon.

    Returns:
        The weapon and the warnings raised while mapping it.

    Raises:
        WhfbParseError: The page has no profile or a field is unparseable.
    """
    fields = entry.get("fields", {})
    slug, name = _slug_and_name(fields)
    warnings: list[str] = []

    profiles: list[WeaponProfile] = []
    notes: list[str] = []
    for block in _body_blocks(fields):
        profile_fields = _embedded_profile_fields(block)
        if profile_fields is not None:
            profiles.append(_parse_profile(slug, name, profile_fields))
            continue
        text = " ".join(richtext.text_of(block).split())
        if text.startswith("Notes:"):
            notes.append(text.removeprefix("Notes:").strip())
        elif text:
            warnings.append(f"{slug}: body text not captured: {text!r}")
    if not profiles:
        raise WhfbParseError(f"{slug}: page embeds no weapon profile")

    weapon = Weapon(id=slug, name=name, profiles=profiles, notes=" ".join(notes) or None)
    return WeaponImport(weapon=weapon, warnings=warnings)


def parse_armour(entry: Node) -> ArmourImport:
    """Parse a Weapons of War page entry into an Armour item.

    Returns:
        The armour entry and the warnings raised while mapping it.

    Raises:
        WhfbParseError: No armour value or improvement is stated.
    """
    fields = entry.get("fields", {})
    slug, name = _slug_and_name(fields)
    warnings: list[str] = []

    value: int | None = None
    improvement: int | None = None
    notes: list[str] = []
    for block in _body_blocks(fields):
        if _embedded_profile_fields(block) is not None:
            raise WhfbParseError(f"{slug}: page embeds a weapon profile; not armour?")
        text = " ".join(richtext.text_of(block).split())
        if not text:
            continue
        if m := _ARMOUR_VALUE_RE.search(text):
            value = int(m.group(1))
        elif m := _IMPROVEMENT_RE.search(text):
            improvement = int(m.group(1))
        elif text.startswith("Note"):
            notes.append(text)
        else:
            # Usually flavour prose; the reviewing human decides.
            warnings.append(f"{slug}: body text not captured: {text!r}")
    if value is None and improvement is None:
        raise WhfbParseError(f"{slug}: no armour value or improvement found in page text")

    armour = Armour(
        id=slug,
        name=name,
        armour_value=value,
        armour_value_improvement=improvement,
        notes=" ".join(notes) or None,
    )
    return ArmourImport(armour=armour, warnings=warnings)


def _slug_and_name(fields: Node) -> tuple[str, str]:
    slug = fields.get("slug")
    if not slug:
        raise WhfbParseError("entry has no slug")
    name = fields.get("name")
    if not isinstance(name, str) or not name:
        raise WhfbParseError(f"{slug}: missing or invalid required field 'name'")
    return slug, name


def _body_blocks(fields: Node) -> list[Node]:
    return fields.get("body", {}).get("content", [])


def _embedded_profile_fields(block: Node) -> Node | None:
    if block.get("nodeType") != "embedded-entry-block":
        return None
    target = block.get("data", {}).get("target", {})
    content_type = target.get("sys", {}).get("contentType", {}).get("sys", {}).get("id")
    if content_type != "weaponProfile":
        return None
    return target.get("fields", {})


def _parse_profile(slug: str, weapon_name: str, fields: Node) -> WeaponProfile:
    try:
        return WeaponProfile.model_validate(
            {
                "name": _profile_name(weapon_name, fields.get("name", "")),
                "R": _parse_range(slug, fields.get("range")),
                "S": fields.get("strength"),
                "AP": fields.get("armourPiercing", "-"),
                "special_rules": _special_rules(fields.get("specialRules")),
            }
        )
    except ValidationError as err:
        raise WhfbParseError(f"{slug}: profile does not fit the weapon schema: {err}") from err


def _profile_name(weapon_name: str, raw: str) -> str | None:
    """Reduce the site's profile title to the printed row name.

    "Longbow (Profile)" carries no information beside the weapon name;
    "Brace of Pistols Ranged (Profile)" names its row "Ranged".

    Returns:
        The row name, or None for the weapon's single unnamed row.
    """
    name = raw.removesuffix(_PROFILE_NAME_SUFFIX).strip()
    if name.startswith(weapon_name):
        name = name.removeprefix(weapon_name).strip()
    return name or None


def _parse_range(slug: str, raw: object) -> object:
    text = str(raw).strip()
    if text in ("Combat", "N/A"):
        return text
    if m := _RANGE_INCHES_RE.fullmatch(text):
        return int(m.group(1))
    # e.g. min-max bands ('12"-60"'): not in the schema yet — fail loudly.
    raise WhfbParseError(f"{slug}: cannot parse weapon range {raw!r}")


def _special_rules(doc: Node | None) -> list[str]:
    """Split the profile's special-rules text into printed rule names.

    Parameters stay attached ("Multiple Shots (2)"); parameter
    parentheses never contain commas, so the comma split is safe.

    Returns:
        The rule names, in printed order.
    """
    if doc is None:
        return []
    text = " ".join(richtext.text_of(doc).split())
    if text in ("", "-"):
        return []
    return [chunk.strip() for chunk in text.split(",") if chunk.strip()]
