"""A round of combat drawn in two lanes, served for the body /fight resolves."""

from collections.abc import Iterator
from fractions import Fraction
from math import comb, sqrt

import pytest
from fastapi.testclient import TestClient

from avelorn.api.app import app, corpus
from avelorn.tow.data import TOWRepository

REPO = TOWRepository()

PRINCES_CHARGE_DWARFS = {
    "a": {"unit": "dragon-princes", "size": 5, "options": ["drakemaster"]},
    "b": {"unit": "dwarf-warriors", "size": 10, "options": ["veteran"]},
    "charge": {"side": "a", "full_inches": 7, "arc": "front"},
}
PRINCES_CHARGE_ARMED_DWARFS = {
    "a": {
        "unit": "dragon-princes",
        "size": 6,
        "frontage": 6,
        "options": ["drakemaster", "standard-bearer", "musician"],
    },
    "b": {
        "unit": "dwarf-warriors",
        "size": 20,
        "frontage": 5,
        "options": [
            "great-weapon",
            "shield",
            "veteran",
            "standard-bearer",
            "musician",
            "veteran-rule",
        ],
    },
    "charge": {"side": "a", "full_inches": 10, "arc": "front"},
}
PRINCES_CHARGE_DWARFS_FROM_AFAR = {
    "a": {"unit": "dragon-princes", "size": 5, "options": ["drakemaster"], "weapon": "Lance"},
    "b": {"unit": "dwarf-warriors", "size": 10, "frontage": 5, "options": ["veteran"]},
    "charge": {"side": "a", "full_inches": 12, "arc": "front"},
}
SPEARMEN_CHARGE_ARCHERS = {
    "a": {"unit": "elven-archers", "size": 10, "frontage": 5},
    "b": {"unit": "elven-spearmen", "size": 20, "frontage": 5},
    "charge": {"side": "b", "full_inches": 8, "arc": "front", "reaction": "stand-and-shoot"},
}


@pytest.fixture
def client() -> Iterator[TestClient]:
    """A client serving the committed corpus.

    Yields:
        The test client, its repository dependency pinned to one instance.
    """
    app.dependency_overrides[corpus] = lambda: REPO
    yield TestClient(app)
    app.dependency_overrides.clear()


def binomial(trials: int, p: Fraction) -> list[float]:
    """The chance of each count of successes in ``trials`` at ``p`` each.

    Returns:
        The chances, from none to every trial.
    """
    return [float(comb(trials, k) * p**k * (1 - p) ** (trials - k)) for k in range(trials + 1)]


def moments(spread: dict) -> tuple[float, float]:
    """The mean and the standard deviation a spread's chances give.

    Returns:
        The mean, then the standard deviation.
    """
    counts = range(spread["least"], spread["least"] + len(spread["distribution"]))
    mean = sum(count * p for count, p in zip(counts, spread["distribution"], strict=True))
    variance = sum(
        (count - mean) ** 2 * p for count, p in zip(counts, spread["distribution"], strict=True)
    )
    return mean, sqrt(variance)


def served(client: TestClient, route: str, body: dict) -> dict:
    """Post a body, failing loudly on a refusal.

    Returns:
        The response body.
    """
    response = client.post(route, json=body)
    assert response.status_code == 200, response.json()
    return response.json()


@pytest.mark.parametrize(
    ("inches", "reaches"),
    [
        pytest.param(7, Fraction(35, 36), id="needs-a-2"),
        pytest.param(11, Fraction(11, 36), id="needs-a-6"),
        pytest.param(12, Fraction(0), id="past-the-maximum"),
    ],
)
def test_the_charge_reaches_on_the_higher_of_two_dice(
    client: TestClient, inches: int, reaches: Fraction
) -> None:
    """Elven Spearmen move 5 and add the higher of two D6 to it.

    At 7in the higher die needs a 2, failing only on two 1s: 1 - (1/6)^2. At
    11in it needs a 6 on either die: 1 - (5/6)^2. 12in is past the maximum
    possible charge range of 5 + 6. Both routes report the chance.
    """
    charge = {**SPEARMEN_CHARGE_ARCHERS["charge"], "full_inches": inches}
    body = {**SPEARMEN_CHARGE_ARCHERS, "charge": charge}
    report = served(client, "/fight", body)
    lanes = served(client, "/graph/fight", body)

    assert [report["p_charge_reaches"], lanes["charge"]["reaches"]] == [float(reaches)] * 2


@pytest.mark.parametrize("body", [PRINCES_CHARGE_DWARFS, SPEARMEN_CHARGE_ARCHERS])
def test_the_lanes_are_the_round_the_fight_reports(client: TestClient, body: dict) -> None:
    """The charger takes the upper lane, and every figure is the one /fight reports."""
    report = served(client, "/fight", body)
    lanes = served(client, "/graph/fight", body)

    charger = body["charge"]["side"]
    seats = {"attacker": charger, "target": "b" if charger == "a" else "a"}
    for seat, side in seats.items():
        size = report[side]["size"]
        assert lanes["units"][seat]["unit"] == report[side]["unit"]
        standing = lanes["standing"][seat][-1]["models"]["distribution"]
        lost = report[side]["casualties"]
        assert {left: p for left, p in enumerate(standing) if p} == pytest.approx(
            {size - count: p for count, p in enumerate(lost) if p}
        )
        broke = lanes["breaks"][seat]
        assert [broke["give_ground"], broke["fall_back_in_good_order"], broke["break"]] == [
            pytest.approx(report[side][outcome])
            for outcome in ("gives_ground", "falls_back", "breaks")
        ]
    result = lanes["result"]
    assert [result["attacker_wins"], result["draw"], result["target_wins"]] == [
        pytest.approx(report[f"p_{charger}_wins"]),
        pytest.approx(report["p_draw"]),
        pytest.approx(report[f"p_{seats['target']}_wins"]),
    ]


def test_a_strike_lists_the_parts_that_make_it(client: TestClient) -> None:
    """Five Dragon Princes, a Drakemaster among them, charge ten Dwarf Warriors 7in into the front.

    Four wide, the Drakemaster and three Princes stand in the front rank. The
    riders strike at I5, +1 for Elven Reflexes and +3 for the charge, and the
    steeds at I4 +3; the Dwarfs at I2. A rider hits on 3+ (WS5 against WS4)
    and, with the Lance's S+2, wounds T4 on 3+ at AP -2, past the Dwarfs'
    heavy armour: 4/9 of an attack goes unsaved, of the Drakemaster's three
    and the Princes' six. A steed hits on 4+, wounds on 5+, and the Dwarf
    saves on 5+: 1/9 of each steed's attack. A Dwarf hits on 4+ and wounds
    on 4+; a Prince saves on 2+ in full plate, shield and barding, with a 6+
    ward from Dragon Armour. Every other step is empty.
    """
    lanes = served(client, "/graph/fight", PRINCES_CHARGE_DWARFS)

    struck = [
        (
            strike["label"],
            strike["side"],
            [
                (
                    part["name"],
                    part["models"]["mean"],
                    part["attacks"]["mean"],
                    part["unsaved"]["mean"],
                )
                for part in strike["parts"]
            ],
        )
        for strike in lanes["strikes"][:2]
    ]
    assert struck == [
        (
            "Initiative 9",
            "attacker",
            [
                ("Drakemaster", 1, 3, pytest.approx(3 * 4 / 9)),
                ("Dragon Prince", 3, 6, pytest.approx(6 * 4 / 9)),
            ],
        ),
        ("Initiative 7", "attacker", [("Barded Elven Steed", 4, 4, pytest.approx(4 / 9))]),
    ]
    dwarfs = lanes["strikes"][2:]
    assert [(strike["label"], strike["side"]) for strike in dwarfs] == [("Initiative 2", "target")]
    assert [part["name"] for part in dwarfs[0]["parts"]] == ["Veteran", "Dwarf Warrior"]
    assert dwarfs[0]["needed"] == {"hit": "4+", "wound": "4+", "save": "2+", "ward": "6+"}


def test_the_command_models_are_no_options_of_the_lane(client: TestClient) -> None:
    """Twenty Dwarf Warriors buy gear, a full command group and the Veteran rule.

    The champion, the standard bearer and the musician stand in the front rank
    instead; the options left are the gear and the rule, which prints the
    champion's name.
    """
    dwarfs = served(client, "/graph/fight", PRINCES_CHARGE_ARMED_DWARFS)["units"]["target"]

    assert [option["name"] for option in dwarfs["options"]] == [
        "Great Weapon",
        "Shield",
        "Veteran",
    ]
    assert [model["kind"] for model in dwarfs["command"]] == [
        "champion",
        "standard_bearer",
        "musician",
    ]


def test_each_champion_a_unit_buys_stands_in_its_command(client: TestClient) -> None:
    """A Ship's Company buys both its champions, the Midshipman and the Bosun.

    Each stands in the front rank by name, beside the standard bearer and the
    musician.
    """
    body = {
        **PRINCES_CHARGE_DWARFS,
        "b": {
            "unit": "ships-company",
            "size": 20,
            "frontage": 5,
            "options": ["bosun", "midshipman", "musician", "standard-bearer"],
        },
    }
    company = served(client, "/graph/fight", body)["units"]["target"]

    assert [(model["kind"], model["name"]) for model in company["command"]] == [
        ("champion", "Midshipman"),
        ("champion", "Bosun"),
        ("standard_bearer", "Standard Bearer"),
        ("musician", "Musician"),
    ]


@pytest.mark.parametrize(
    ("options", "held"),
    [
        pytest.param(["great-weapon", "shield"], ["Great Weapon"], id="two-hands"),
        pytest.param(["shield"], ["Hand Weapon", "Shield"], id="hand-weapon-and-shield"),
    ],
)
def test_a_unit_holds_what_its_weapon_choice_took_up(
    client: TestClient, options: list[str], held: list[str]
) -> None:
    """Dwarf Warriors who buy a great weapon swing it, and its Requires Two Hands bars the shield.

    Without one they fight with the datasheet's Hand Weapon and their shield.
    The Dragon Princes charging them hold their Lance and Shield.
    """
    body = {
        **PRINCES_CHARGE_DWARFS,
        "b": {"unit": "dwarf-warriors", "size": 10, "options": options},
    }
    units = served(client, "/graph/fight", body)["units"]

    assert [units["attacker"]["held"], units["target"]["held"]] == [["Lance", "Shield"], held]


def test_a_stand_and_shoot_thins_the_charger(client: TestClient) -> None:
    """Ten Archers five wide stand and shoot at twenty Spearmen charging them.

    The front rank's five shoot; a Stand & Shoot never Volley Fires. BS4 hits
    on 3+, 4+ for Standing and Shooting; the Longbow's S3 wounds T3 on 4+; the
    Spearmen's light armour and shield save on 5+, on 6+ against a natural 6
    To Wound for the Longbow's Armour Bane (1). Each shot goes unsaved
    1/2 x (2/6 x 4/6 + 1/6 x 5/6) = 13/72 of the time. Both rules are the
    Archers', who fight from the target's lane.
    """
    lanes = served(client, "/graph/fight", SPEARMEN_CHARGE_ARCHERS)

    assert lanes["units"]["attacker"]["unit"] == "elven-spearmen"
    assert lanes["reaction"] == {
        "chosen": "stand-and-shoot",
        "offered": {"hold": True, "stand_and_shoot": True, "flee": False},
    }
    volley = lanes["volley"]
    assert (volley["shots"], volley["needed"]) == (
        5,
        {"hit": "4+", "wound": "4+", "save": "5+ or 6+", "ward": "-"},
    )
    assert [
        (each["after"], each["models"]["mean"]) for each in lanes["standing"]["attacker"][:2]
    ] == [
        (None, 20),
        ("volley", pytest.approx(20 - 5 * 13 / 72)),
    ]
    shooting = {rule["name"]: rule["side"] for rule in volley["rules"] if rule["applied"]}
    assert shooting == {"Armour Bane (1)": "target", "Standing and Shooting": "target"}


def test_a_strike_spreads_its_unsaved_wounds_as_its_dice_fall(client: TestClient) -> None:
    """Five Dragon Princes, a Drakemaster among them, charge ten Dwarf Warriors from 12in.

    The Drakemaster's three attacks and the three Princes' six hit on 3+ and,
    with the Lance, wound on 3+ past any save: each goes unsaved on 4/9 alone,
    so the riders' unsaved wounds fall as nine trials at 4/9, and each part's
    as its own. The four steeds, one under the Drakemaster and three under the
    Princes, are one part of four attacks at 1/9. Every mean and standard
    deviation is the one its chances give, the Dwarfs' too.
    """
    strikes = served(client, "/graph/fight", PRINCES_CHARGE_DWARFS_FROM_AFAR)["strikes"]

    riders, steeds = strikes[:2]
    assert [
        riders["unsaved"]["distribution"],
        *(part["unsaved"]["distribution"] for part in riders["parts"]),
        *(part["unsaved"]["distribution"] for part in steeds["parts"]),
    ] == [
        pytest.approx(binomial(9, Fraction(4, 9))),
        pytest.approx(binomial(3, Fraction(4, 9))),
        pytest.approx(binomial(6, Fraction(4, 9))),
        pytest.approx(binomial(4, Fraction(1, 9))),
    ]
    spreads = [
        spread
        for strike in strikes
        for spread in (strike["unsaved"], *(part["unsaved"] for part in strike["parts"]))
    ]
    assert [(spread["mean"], spread["sd"]) for spread in spreads] == [
        pytest.approx(moments(spread)) for spread in spreads
    ]


def test_each_part_of_a_stand_and_shoot_shoots_at_its_own_skill(client: TestClient) -> None:
    """Ten Archers five wide, a Sentinel among them, stand and shoot at charging Spearmen.

    The Sentinel's one shot hits on 3+ at BS5 and the four Archers' on 4+,
    then each wounds and goes unsaved on 13/36 (as above): 13/54 for the
    Sentinel's, 13/72 for each Archer's. A Spearman has one Wound, so the
    casualties are every unsaved wound.
    """
    archers = {**SPEARMEN_CHARGE_ARCHERS["a"], "options": ["sentinel"]}
    volley = served(client, "/graph/fight", {**SPEARMEN_CHARGE_ARCHERS, "a": archers})["volley"]

    assert [
        (part["name"], part["shots"], part["unsaved"]["distribution"]) for part in volley["parts"]
    ] == [
        ("Sentinel", 1, pytest.approx(binomial(1, Fraction(13, 54)))),
        ("Elven Archer", 4, pytest.approx(binomial(4, Fraction(13, 72)))),
    ]
    assert volley["casualties"]["mean"] == pytest.approx(13 / 54 + 4 * 13 / 72)
