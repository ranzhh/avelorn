"""Combat mathematics for The Old World: roll charts and attack chains."""

from avelorn.tow.combat.charts import (
    armour_save_target,
    hit_probability,
    save_probability,
    shooting_hit_target,
    wound_target,
)
from avelorn.tow.combat.shooting import ShootingResult, shoot, shoot_unit
from avelorn.tow.combat.weapons import LONGBOW, MissileWeapon

__all__ = [
    "LONGBOW",
    "MissileWeapon",
    "ShootingResult",
    "armour_save_target",
    "hit_probability",
    "save_probability",
    "shoot",
    "shoot_unit",
    "shooting_hit_target",
    "wound_target",
]
