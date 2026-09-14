from dataclasses import dataclass
from fractions import Fraction

import pytest

from avelorn.core.dice import binomial_distribution
from avelorn.core.distribution import Distribution
from avelorn.core.graph import Graph, GraphError, Node, Provenance

_SHOTS = 3
_P_UNSAVED = Fraction(1, 3)


def _binomial(shots: int, p_unsaved: Fraction) -> Distribution[int]:
    return Distribution.from_counts(binomial_distribution(shots, p_unsaved))


def _wounds(shots: Node[int], p_unsaved: Node[Fraction]) -> Distribution[int]:
    return _binomial(shots.value, p_unsaved.value)


def _halve(wounds: Node[Distribution[int]]) -> Distribution[int]:
    return wounds.value >> (lambda k: Distribution.pure(k // 2))


def _same(wounds: Node[Distribution[int]]) -> Distribution[int]:
    return wounds.value


def _chain() -> tuple[Graph, Node[int], Node[Fraction], Node[Distribution[int]]]:
    graph = Graph()
    shots = graph.source("shots", "count", "Shots", _SHOTS)
    chance = graph.source("attack", "walk", "Attack", _P_UNSAVED)
    wounds = graph.node("roll-to-wound", "fold", "Wounds", shots, chance, body=_wounds)
    return graph, shots, chance, wounds


def test_source_carries_the_given_value_and_no_inputs() -> None:
    graph, shots, _, _ = _chain()
    assert shots.value == _SHOTS
    assert shots.inputs == ()
    assert graph.nodes["shots"] is shots


def test_node_value_is_the_body_over_its_inputs_in_order() -> None:
    _, _, _, wounds = _chain()
    assert wounds.value == _binomial(_SHOTS, _P_UNSAVED)
    assert wounds.inputs == ("shots", "attack")


def test_graph_adds_no_math_to_a_fold() -> None:
    graph, _, _, wounds = _chain()
    felled = graph.node("remove-casualties", "fold", "Casualties", wounds, body=_halve)
    assert felled.value == wounds.value.map(lambda k: k // 2)
    assert felled.value.total() == 1


def test_iteration_is_topological() -> None:
    graph, _, _, wounds = _chain()
    graph.node("survivors", "read", "Survivors", wounds, body=_same)
    seen: set[str] = set()
    for node in graph.nodes.values():
        assert set(node.inputs) <= seen
        seen.add(node.id)
    assert list(graph.nodes) == ["shots", "attack", "roll-to-wound", "survivors"]


def test_duplicate_id_is_refused() -> None:
    graph, _, _, _ = _chain()
    with pytest.raises(GraphError, match="already in the graph"):
        graph.source("shots", "count", "Shots", 1)


def test_input_from_another_graph_is_refused() -> None:
    _, _, _, wounds = _chain()
    other = Graph()
    with pytest.raises(GraphError, match="not a node of this graph"):
        other.node("copy", "read", "Copy", wounds, body=_same)


@dataclass(frozen=True)
class _Effective:
    value: int
    factored: tuple[str, ...]
    unfactored: tuple[str, ...]

    def provenance(self) -> Provenance:
        return Provenance(frozenset(self.factored), frozenset(self.unfactored))


def _martial_prowess(base: Node[int]) -> _Effective:
    return _Effective(base.value + 1, ("Martial Prowess",), ("Hatred",))


def test_provenance_is_read_off_the_value_and_unioned_over_the_graph() -> None:
    graph = Graph()
    base = graph.source("base", "read", "Weapon Skill", 4)
    effective = graph.node(
        "effective",
        "effective",
        "Weapon Skill",
        base,
        body=_martial_prowess,
        provenance=_Effective.provenance,
    )
    graph.source(
        "armour", "effective", "Armour", 5, provenance=Provenance(frozenset({"Lion Cloak"}))
    )
    assert effective.value.value == 5
    assert effective.provenance == Provenance(
        frozenset({"Martial Prowess"}), frozenset({"Hatred"})
    )
    assert graph.provenance == Provenance(
        frozenset({"Martial Prowess", "Lion Cloak"}), frozenset({"Hatred"})
    )
