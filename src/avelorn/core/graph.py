"""A graph of evaluated nodes.

Adding a node evaluates it. The body receives the input nodes in order and
its result is stored on the new node, so every value in the graph sits on a
node. Inputs must already be in the graph, so there are no cycles and
insertion order is a valid evaluation order. The body is not kept.

A body is a named function whose parameters are annotated ``Node[...]``.
The node's type is inferred from the body's return type, and a checker
that implements PEP 646 rejects an input node of the wrong type.
"""

from collections.abc import Callable, Hashable, Mapping
from dataclasses import dataclass

from avelorn.core.errors import AvelornError


class GraphError(AvelornError, ValueError):
    pass


@dataclass(frozen=True)
class Provenance:
    factored: frozenset[Hashable] = frozenset()
    unfactored: frozenset[Hashable] = frozenset()


UNREPORTED = Provenance()


@dataclass(frozen=True)
class Node[V]:
    id: str
    kind: str
    label: str
    inputs: tuple[str, ...]
    value: V
    provenance: Provenance = UNREPORTED


class Graph:
    def __init__(self) -> None:
        self._nodes: dict[str, Node[object]] = {}

    @property
    def nodes(self) -> Mapping[str, Node[object]]:
        return self._nodes

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Graph) and self._nodes == other._nodes

    def __hash__(self) -> int:
        return id(self)

    def source[V](
        self,
        id: str,
        kind: str,
        label: str,
        value: V,
        *,
        provenance: Provenance = UNREPORTED,
    ) -> Node[V]:
        return self._add(Node(id, kind, label, (), value, provenance))

    def node[*Ts, V](
        self,
        id: str,
        kind: str,
        label: str,
        *inputs: *Ts,
        body: Callable[[*Ts], V],
        provenance: Callable[[V], Provenance] | None = None,
    ) -> Node[V]:
        ids: list[str] = []
        for source in inputs:
            if not isinstance(source, Node) or self._nodes.get(source.id) is not source:
                raise GraphError(f"an input of {id!r} is not a node of this graph: {source!r}")
            ids.append(source.id)
        value = body(*inputs)
        report = UNREPORTED if provenance is None else provenance(value)
        return self._add(Node(id, kind, label, tuple(ids), value, report))

    def _add[V](self, node: Node[V]) -> Node[V]:
        if node.id in self._nodes:
            raise GraphError(f"node {node.id!r} is already in the graph")
        self._nodes[node.id] = node
        return node

    @property
    def provenance(self) -> Provenance:
        reports = [node.provenance for node in self._nodes.values()]
        return Provenance(
            frozenset().union(*(r.factored for r in reports)),
            frozenset().union(*(r.unfactored for r in reports)),
        )
