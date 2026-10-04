"""Program loading."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from avelorn.tow.contingent import Contingent
from avelorn.tow.data import TOWRepository
from avelorn.tow.kernels import Standing
from avelorn.tow.programs import VOLLEY, ProgramError, load_program
from avelorn.tow.schema.stage import Side
from avelorn.tow.steps import Fielded

type Edit = Callable[[dict[str, Any]], None]

REPO = TOWRepository()


def _renamed_step(volley: dict[str, Any]) -> None:
    volley["items"][1]["step"] = "check-ranges"


def _hit_after_wound(volley: dict[str, Any]) -> None:
    attack = volley["items"][3]["items"]
    attack[0], attack[1] = attack[1], attack[0]


def _ward_outside_the_group(volley: dict[str, Any]) -> None:
    volley["items"].insert(4, "ward-saves")


def _standing_not_given(volley: dict[str, Any]) -> None:
    volley["inputs"].remove({"fact": "standing", "of": "target"})


def _unknown_reading(volley: dict[str, Any]) -> None:
    volley["items"][2]["readings"] = ["volleys"]


def _no_tally(volley: dict[str, Any]) -> None:
    del volley["items"][4]["tallies"]


def _group_before_its_count(volley: dict[str, Any]) -> None:
    volley["items"][2], volley["items"][3] = volley["items"][3], volley["items"][2]


def _fact_without_a_side(volley: dict[str, Any]) -> None:
    volley["inputs"].append({"fact": "moved"})


def _known_without_a_type(volley: dict[str, Any]) -> None:
    volley["inputs"].append({"known": "cover"})


def _input_twice(volley: dict[str, Any]) -> None:
    volley["inputs"].append({"known": "distance", "type": "int"})


def _known_named_as_a_fact(volley: dict[str, Any]) -> None:
    volley["inputs"].append({"known": "moved", "of": "target", "type": "bool"})


def _tally_on_a_step_that_counts_none(volley: dict[str, Any]) -> None:
    volley["items"][1]["tallies"] = ["attack"]


def _target_unfielded(volley: dict[str, Any]) -> None:
    volley["fielded"] = ["attacker"]


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        pytest.param(
            _renamed_step,
            "volley.yaml: items[1]: check-ranges is no step of the shooting sequence",
            id="unknown-step",
        ),
        pytest.param(
            _hit_after_wound,
            "volley.yaml: items[3].items[0]: roll-to-wound reads roll-to-hit, "
            "which is not in scope",
            id="output-read-before-its-step",
        ),
        pytest.param(
            _ward_outside_the_group,
            "volley.yaml: items[4]: ward-saves reads roll-to-wound, which is not in scope",
            id="output-read-outside-its-group",
        ),
        pytest.param(
            _standing_not_given,
            "volley.yaml: items[4]: remove-casualties reads target/standing, "
            "which is no input and is not written",
            id="state-read-before-written",
        ),
        pytest.param(
            _unknown_reading,
            "volley.yaml: items[2]: how-many-shots offers no reading volleys",
            id="unknown-reading",
        ),
        pytest.param(
            _no_tally,
            "volley.yaml: items[4]: remove-casualties needs the groups it tallies",
            id="tally-missing",
        ),
        pytest.param(
            _group_before_its_count,
            "volley.yaml: items[2]: attack runs how-many-shots times, which is not in scope",
            id="group-before-its-count",
        ),
        pytest.param(
            _fact_without_a_side,
            "inputs.8.FactInput.of\n  Field required",
            id="fact-without-a-side",
        ),
        pytest.param(
            _known_without_a_type,
            "inputs.8.KnownInput.type\n  Field required",
            id="known-without-a-type",
        ),
        pytest.param(
            _input_twice,
            "volley.yaml: inputs[8]: distance is an input twice",
            id="input-twice",
        ),
        pytest.param(
            _known_named_as_a_fact,
            "volley.yaml: inputs[8]: moved is listed in state.yaml",
            id="known-named-as-a-fact",
        ),
        pytest.param(
            _tally_on_a_step_that_counts_none,
            "volley.yaml: items[1]: check-range sums no group",
            id="tally-on-a-step-that-counts-none",
        ),
        pytest.param(
            _target_unfielded,
            "volley.yaml: items[3].items[1]: roll-to-wound reads the target, "
            "which volley.yaml does not field",
            id="side-not-fielded",
        ),
    ],
)
def test_a_bad_entry_fails_the_load_at_its_path(edit: Edit, message: str, tmp_path: Path) -> None:
    volley = yaml.safe_load(VOLLEY.read_text())
    edit(volley)
    path = tmp_path / "volley.yaml"
    path.write_text(yaml.safe_dump(volley))

    with pytest.raises(ProgramError) as refused:
        load_program(path, REPO.rules)

    assert message in str(refused.value)


def _fielded() -> dict[Side, Fielded]:
    archers = Contingent.deploy("elven-archers", 10, frontage=5)
    spearmen = Contingent.deploy("elven-spearmen", 20, frontage=5)
    return {Side.ATTACKER: Fielded.of(archers, "Longbow"), Side.TARGET: Fielded.of(spearmen)}


def test_building_without_every_side_fielded_is_refused() -> None:
    attacker = _fielded()[Side.ATTACKER]

    with pytest.raises(ProgramError, match="volley needs the target fielded"):
        load_program(VOLLEY, REPO.rules).built({Side.ATTACKER: attacker})


def test_evaluating_without_every_input_is_refused() -> None:
    built = load_program(VOLLEY, REPO.rules).built(_fielded())

    with pytest.raises(ProgramError, match="volley needs attacker/moved, attacker/standing"):
        built.evaluate({"distance": 12})


def test_a_bool_given_as_an_int_is_refused() -> None:
    knowns = {
        "distance": True,
        "can-shoot": True,
        "line-of-sight": True,
        "attacker/moved": False,
        "attacker/standing": Standing(10, 0),
        "target/standing": Standing(20, 0),
        "target/models-at-start-of-phase": 20,
        "target/battle-strength": 20,
    }

    with pytest.raises(ProgramError, match="distance expects int; got True"):
        load_program(VOLLEY, REPO.rules).built(_fielded()).evaluate(knowns)
