"""The corpus wired up: printed rules reaching the maths on real datasheets.

`tests/tow/phases/test_combat_spec.py` pins what the rules *mean*, using
stripped synthetic bodies so every figure is exact. This file asks the other
question: do the datasheets actually connect? A rule can be authored, tested
against a doctored unit, and still never fire for the unit that prints it --
the name misspelled, the gate unanswerable from that seat, the entry filed
where nothing looks. Nothing above catches that.

What each rule changes on a real datasheet is tested in ``tests/rules/``; what
stays here is that every datasheet printing a rule reaches it.
"""

from avelorn.tow.data import TOWRepository
from avelorn.tow.game import TOWGame

REPO = TOWRepository()
GAME = TOWGame.load_data()


def test_stomp_attacks_are_claimed_by_every_behemoth_that_prints_them() -> None:
    """The closing automatic hits fire for the real datasheets, not just a fixture.

    Each of these prints Stomp Attacks and the Merwyrm prints Impact Hits too;
    both land outside the Initiative order, so a round must claim them rather
    than report them unapplied.
    """
    foe = GAME.field(REPO.units["swordmasters-of-hoeth"], 5).wielding("Hand Weapon")
    for slug, weapon in (
        ("merwyrm", "Lashing Talons"),
        ("frostheart-phoenix", "Wicked Claws"),
        ("flamespyre-phoenix", "Wicked Claws"),
        ("great-eagle", "Serrated Maw"),
    ):
        with GAME.turn().combat() as combat:
            fought = combat.fight(GAME.field(REPO.units[slug], 1).wielding(weapon), foe)
        unapplied = [
            name for name in fought.held if name.startswith(("Stomp Attacks", "Impact Hits"))
        ]
        assert not unapplied, f"{slug}: {unapplied}"
