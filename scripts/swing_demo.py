"""Every condition of one pairing, ranked by how far it moves the round.

Resolves one matchup repeatedly, varying a single field of the ``POST /fight``
body at a time, and prints the range each field spans. The point is which
fields move the answer and which do not: the ranking is the interesting output,
and the conditions that move nothing are the interesting part of the ranking.

Reads the corpus in process rather than over the wire, so it needs no server.
The numbers quoted in docs/decisions.md under "The swing view" come from here.
"""

import json
from typing import Any

from fastapi.testclient import TestClient

from avelorn.api.app import app

# The state every range is measured from. A shock-cavalry pairing resolved
# stationary says nothing, so the reference has the cavalry charging.
REFERENCE: dict[str, Any] = {
    "a": {
        "unit": "dragon-princes",
        "size": 5,
        "options": [],
        "weapon": "Lance",
        "frontage": None,
    },
    "b": {
        "unit": "swordmasters-of-hoeth",
        "size": 20,
        "options": [],
        "weapon": "Sword of Hoeth",
        "frontage": None,
    },
    "charge": {"side": "a", "full_inches": 3, "arc": "front"},
}

# Enough inches to cap the Initiative bonus in each arc: +3 front, +4 flank or rear.
CHARGES: list[tuple[str, dict[str, Any] | None]] = [
    ("neither", None),
    ("DP front", {"side": "a", "full_inches": 3, "arc": "front"}),
    ("DP flank", {"side": "a", "full_inches": 8, "arc": "flank"}),
    ("DP rear", {"side": "a", "full_inches": 8, "arc": "rear"}),
    ("SM front", {"side": "b", "full_inches": 3, "arc": "front"}),
    ("SM flank", {"side": "b", "full_inches": 8, "arc": "flank"}),
    ("SM rear", {"side": "b", "full_inches": 8, "arc": "rear"}),
]

# Each axis is one field of the request body, plus what varying it costs.
AXES: list[tuple[str, object, list[tuple[str, dict[str, Any]]]]] = [
    ("charge and arc", "free", [(name, {"charge": ch}) for name, ch in CHARGES]),
    ("DP weapon", "free", [(w, {"a.weapon": w}) for w in ("Lance", "Hand Weapon")]),
    ("SM weapon", "free", [(w, {"b.weapon": w}) for w in ("Sword of Hoeth", "Hand Weapon")]),
    ("DP frontage", "free", [(f"{f} wide", {"a.frontage": f}) for f in (1, 2, 3, 4, 5)]),
    ("SM frontage", "free", [(f"{f} wide", {"b.frontage": f}) for f in (4, 5, 6, 7, 10)]),
    ("DP size", "37/model", [(f"{n} models", {"a.size": n}) for n in (3, 5, 7, 10)]),
    (
        "DP standard bearer",
        7,
        [("none", {"a.options": []}), ("bought", {"a.options": ["Standard Bearer"]})],
    ),
    (
        "DP drakemaster",
        7,
        [("none", {"a.options": []}), ("bought", {"a.options": ["Drakemaster"]})],
    ),
    (
        "SM standard bearer",
        6,
        [("none", {"b.options": []}), ("bought", {"b.options": ["Standard Bearer"]})],
    ),
    ("SM bladelord", 6, [("none", {"b.options": []}), ("bought", {"b.options": ["Bladelord"]})]),
    ("SM drilled", 20, [("none", {"b.options": []}), ("bought", {"b.options": ["Drilled"]})]),
]


def resolve(client: TestClient, **over: Any) -> dict[str, Any]:
    """Resolve the reference round with some fields replaced.

    A key of ``charge`` replaces the charge outright. Anything else is
    ``side.field``, addressing one field of one deployment.

    A body the API refuses is a bug in an axis rather than a case to render
    around, so this asserts rather than reporting.

    Returns:
        The fight report.
    """
    body = json.loads(json.dumps(REFERENCE))
    for key, value in over.items():
        if key == "charge":
            body["charge"] = value
        else:
            side, field = key.split(".")
            body[side][field] = value
    response = client.post("/fight", json=body)
    assert response.status_code == 200, (over, response.json())
    return response.json()


def breaks_given_loss(side: dict[str, Any]) -> float | None:
    """A side's chance of Breaking, conditioned on it losing the round.

    The three Break outcomes sum to the chance this side lost, so dividing by
    that sum recovers the multiplier the Break test applies. It is a function
    of Leadership alone; the demo prints it to show the combat result margin
    never reaches it.

    Returns:
        The conditional probability, or None where the side never loses.
    """
    lost = side["gives_ground"] + side["falls_back"] + side["breaks"]
    return side["breaks"] / lost if lost > 1e-12 else None


def main() -> None:
    """Print the ranking, the multiplier, and the weapon-by-charge interaction."""
    client = TestClient(app)
    reference = resolve(client)
    held = set(reference["not_modelled"])
    print(f"reference: P(DP win) {reference['p_a_wins'] * 100:.1f}%, {len(held)} rules held\n")

    ranked = []
    for name, cost, states in AXES:
        results = [(label, resolve(client, **over)) for label, over in states]
        wins = [report["p_a_wins"] for _, report in results]
        added = set()
        for _, report in results:
            added |= set(report["not_modelled"]) - held
        ranked.append((max(wins) - min(wins), name, cost, min(wins), max(wins), sorted(added)))

    print(f"{'condition':22} {'range %':>13} {'swing pp':>9} {'cost':>10}  held")
    for swing, name, cost, low, high, added in sorted(ranked, reverse=True):
        shown = f"{cost} pts" if isinstance(cost, int) else str(cost)
        why = added[0] if added else ("silently dropped" if swing < 0.0005 else "")
        print(
            f"{name:22} {low * 100:5.1f}-{high * 100:5.1f} {swing * 100:9.1f} {shown:>10}  {why}"
        )

    print("\nP(breaks | loses), which the margin never reaches:")
    for key in ("a", "b"):
        side = reference[key]
        print(f"  {side['name']:24} {breaks_given_loss(side):.4f}")

    print("\nP(DP win) by weapon and charge, the interaction a flat ranking hides:")
    header = "".join(f"{label:>10}" for label, _ in CHARGES)
    print(f"{'':16}{header}")
    by_weapon = {}
    for weapon in ("Lance", "Hand Weapon"):
        row = [
            resolve(client, **{"a.weapon": weapon, "charge": ch})["p_a_wins"] for _, ch in CHARGES
        ]
        by_weapon[weapon] = row
        print(f"{weapon:16}" + "".join(f"{value * 100:10.1f}" for value in row))
    gap = [
        lance - hand
        for lance, hand in zip(by_weapon["Lance"], by_weapon["Hand Weapon"], strict=True)
    ]
    print(f"{'difference':16}" + "".join(f"{value * 100:+10.1f}" for value in gap))


if __name__ == "__main__":
    main()
