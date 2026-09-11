"""What each rule in a volley is worth, and why that depends on the question.

Resolves one volley repeatedly with subsets of its compiled rules, and prints
each rule's exact contribution to several different reported numbers. Two things
it exists to show. A rule's contribution does not decompose by leaving it out
one at a time, because rules interact. And whether a rule matters at all is
decided by which number you asked about, not by the rule.

Reads the corpus in process, so it needs no server. The numbers quoted in
docs/decisions.md under "Attribution needs a chosen quantity" come from here.
"""

from collections.abc import Callable, Iterable, Sequence
from itertools import combinations
from math import comb

from avelorn.tow.contingent import Contingent
from avelorn.tow.data import TOWRepository
from avelorn.tow.engine.attack import Modifier, Reroll
from avelorn.tow.engine.rules import AttackFacts, GateContext
from avelorn.tow.engine.seats import Defence, Offence
from avelorn.tow.phases.shooting import (
    PanicResult,
    ShootingResult,
    _engagement_conditions,
    make_panic_tests,
    shoot,
    shoot_unit,
)
from avelorn.tow.schema.rule import AttackKind
from avelorn.tow.schema.unit import Characteristic

SHOOTER, WEAPON, TARGET = "sisters-of-avelorn", "Bow of Avelorn", "dwarf-warriors"
RANGE_INCHES = 6

# The reported numbers a reader might be asking about. Each is a pure function
# of what the volley resolved, which is what makes the set extensible.
Quantity = Callable[[ShootingResult, PanicResult], float]
QUANTITIES: dict[str, Quantity] = {
    "p_unsaved": lambda volley, panic: float(volley.p_unsaved),
    "felled": lambda volley, panic: float(volley.expected_casualties),
    "forced to test": lambda volley, panic: float(panic.p_test),
    "flees or wiped": lambda volley, panic: float(panic.p_flees + panic.p_destroyed),
}


def seats(
    shooter: Contingent, defender: Contingent
) -> tuple[list[Modifier], Defence, tuple[Reroll, ...]]:
    """Compile both sides of the volley, the way the resolver does.

    Returns:
        The modifier records, the defender's resolved defence, and the re-roll
        grants the walk applies.
    """
    weapon = shooter.in_hand()
    profile = weapon.missile_profile
    assert profile is not None
    conditions = _engagement_conditions(shooter, weapon, profile, RANGE_INCHES, False, False)
    offence = Offence.resolve(
        profile,
        weapon_rules=shooter.loadout.weapon_rules,
        rules=shooter.loadout.rules,
        grants=shooter.loadout.granted_rules,
        conditions=conditions,
    )
    incoming = GateContext(
        wielding=defender.weapon_facts,
        worn=defender.armour_facts,
        target_of=AttackFacts(
            kind=AttackKind.SHOOTING,
            magical=offence.marks.magical,
            flaming=offence.marks.flaming,
            at_long_range=conditions.shooting.at_long_range,
        ),
    )
    defence = Defence.resolve(
        armour=defender.loadout.armour,
        rules=defender.loadout.rules,
        grants=defender.loadout.granted_rules,
        incoming=incoming,
        weapon_rules_in_use=defender.in_hand_rules(),
    )
    rerolls = (
        *offence.rerolls.rerolls,
        *offence.weapon_rerolls.rerolls,
        *defence.rerolls.rerolls,
    )
    return [*offence.modifiers, *defence.modifiers], defence, rerolls


def measure(
    repo: TOWRepository, shooter: Contingent, size: int, shots: int, keep: Iterable[str]
) -> dict[str, float]:
    """Resolve the volley with only the named rules in force.

    Returns:
        Every quantity, under that subset.
    """
    held = set(keep)
    defender = Contingent.field(repo.units[TARGET], size, data=repo)
    modifiers, defence, rerolls = seats(shooter, defender)
    profile = shooter.in_hand().missile_profile
    assert profile is not None
    volley = shoot(
        shots,
        ballistic_skill=shooter.unit.main[Characteristic.BALLISTIC_SKILL] or 0,
        strength=profile.strength.resolve(shooter.unit.main[Characteristic.STRENGTH] or 0),
        toughness=defender.unit.main[Characteristic.TOUGHNESS] or 0,
        armour_value=defence.armour_value,
        armour_piercing=profile.armour_piercing,
        ward_target=defence.ward.target,
        targets=size,
        modifiers=[record for record in modifiers if record.source in held],
        rerolls=rerolls,
    )
    panic = make_panic_tests(volley, defender)
    return {name: read(volley, panic) for name, read in QUANTITIES.items()}


def shapley(sources: Sequence[str], value: Callable[[frozenset[str]], float]) -> dict[str, float]:
    """Each rule's Shapley contribution to one quantity.

    Averages a rule's marginal effect over every order it could have been added
    in, which is the only weighting under which the contributions sum to the
    whole. Costs 2^N evaluations; N is small enough in a volley to do exactly.

    Returns:
        The contribution per source.
    """
    total = len(sources)
    out: dict[str, float] = {}
    for source in sources:
        rest = [other for other in sources if other != source]
        share = 0.0
        for taken in range(total):
            for subset in combinations(rest, taken):
                without = frozenset(subset)
                marginal = value(without | {source}) - value(without)
                share += marginal / (comb(total - 1, taken) * total)
        out[source] = share
    return out


def main() -> None:
    """Print the interaction between two rules, then their worth per quantity."""
    repo = TOWRepository()
    shooter = Contingent.field(repo.units[SHOOTER], 10, data=repo).wielding(WEAPON)
    reference = Contingent.field(repo.units[TARGET], 20, data=repo)
    shots = shoot_unit(shooter, reference, distance=RANGE_INCHES).shots
    modifiers, _, rerolls = seats(shooter, reference)
    sources = sorted({record.source for record in modifiers if record.source})
    print(f"{shots} shots, rules in force: {sources}, re-roll grants: {len(rerolls)}\n")

    print("leaving one rule out does not decompose, because rules interact")
    size = 20
    cache: dict[frozenset[str], dict[str, float]] = {}

    def read(keep: frozenset[str], quantity: str) -> float:
        if keep not in cache:
            cache[keep] = measure(repo, shooter, size, shots, keep)
        return cache[keep][quantity]

    none = frozenset()
    everything = frozenset(sources)
    q = "p_unsaved"
    floor = read(none, q)
    joint = read(everything, q) - floor
    print(f"  neither                {floor:.5f}")
    for source in sources:
        only = read(frozenset({source}), q)
        print(f"  {source:22} {only:.5f}   alone {only - floor:+.5f}")
    print(f"  both                   {read(everything, q):.5f}   joint {joint:+.5f}")
    alone = sum(read(frozenset({s}), q) - floor for s in sources)
    print(f"  sum of the alones      {alone:+.5f}, overshooting by {alone - joint:+.5f}")
    exact = shapley(sources, lambda keep: read(keep, q))
    print("  Shapley                " + ", ".join(f"{s} {v:+.5f}" for s, v in exact.items()))
    print(f"  Shapley sums to        {sum(exact.values()):+.5f}\n")

    print("whether a rule matters at all is decided by the question asked")
    sizes = (8, 16, 20)
    header = "".join(f"{f'x{n}':>12}" for n in sizes)
    print(f"{'quantity':16}{header}")
    for quantity in QUANTITIES:
        cells = []
        for n in sizes:
            per_size: dict[frozenset[str], dict[str, float]] = {}

            def one(
                keep: frozenset[str],
                n: int = n,
                store: dict = per_size,
                quantity: str = quantity,
            ) -> float:
                if keep not in store:
                    store[keep] = measure(repo, shooter, n, shots, keep)
                return store[keep][quantity]

            contributions = shapley(sources, one)
            cells.append(f"{sum(contributions.values()) / len(sources):+12.5f}")
        print(f"{quantity:16}" + "".join(cells))
    print("\nA unit tests its nerve only when it loses more than a quarter of its models.")
    print("Twenty Dwarf Warriors need 6 gone. This volley averages 2.")


if __name__ == "__main__":
    main()
