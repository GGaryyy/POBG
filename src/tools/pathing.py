"""
pathing.py — Which passive nodes must be allocated to reach a set of targets.

Connecting several targets to a start with the fewest nodes is the Steiner tree problem, which
has no fast exact solution. This module gives a good approximation: attach the nearest target
first (shortest-path heuristic, never worse than twice the optimum), then try to re-attach each
target more cheaply. Pure functions over node ids and neighbour lists; no IO.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

MAX_TARGETS = 40
MAX_IMPROVE_PASSES = 3

# ---------------------------------------------------------------------------
# RESULT
# ---------------------------------------------------------------------------


@dataclass
class Route:
    start: str
    order: list[str] = field(default_factory=list)        # nodes to allocate, each next to an earlier one
    alone: dict[str, int] = field(default_factory=dict)   # target -> points when it is the only target
    exclusive: dict[str, int] = field(default_factory=dict)  # target -> points only this target needs
    unreachable: list[str] = field(default_factory=list)

    @property
    def points(self) -> int:
        return len(self.order)


# ---------------------------------------------------------------------------
# PATHFINDER
# ---------------------------------------------------------------------------


class PassivePathfinder:
    def __init__(self, nodes: dict[str, dict]) -> None:
        self.adjacent = {node_id: sorted(n for n in node.get("neighbors") or [] if n in nodes)
                         for node_id, node in nodes.items()}

    def route(self, start: str, targets: list[str], allowed: set[str]) -> Route:
        """Approximate cheapest set of `allowed` nodes joining `start` to every reachable target."""
        allowed = allowed | {start}
        wanted = sorted({t for t in targets if t != start})
        distance = self._distances(start, allowed)
        reachable = [t for t in wanted if t in distance]
        route = Route(start=start, alone={t: distance[t] for t in reachable},
                      unreachable=[t for t in wanted if t not in distance])
        tree = self._grow(start, reachable, allowed)
        tree = self._improve(start, reachable, tree, allowed)
        route.order = self._allocation_order(start, tree)
        parents = self._spanning_parents(start, tree)
        route.exclusive = {t: len(self._own_branch(t, start, set(reachable), parents)) for t in reachable}
        return route

    # -- construction -------------------------------------------------------------

    def _grow(self, start: str, targets: list[str], allowed: set[str]) -> set[str]:
        tree, remaining = {start}, set(targets)
        while remaining:
            path = self._nearest(tree, remaining, allowed)
            tree.update(path)
            remaining -= tree
        return tree

    def _improve(self, start: str, targets: list[str], tree: set[str], allowed: set[str]) -> set[str]:
        """Key-path exchange: take out one stretch of plain travel nodes at a time and reconnect
        the two halves by the shortest path; keep the change when it needs fewer nodes."""
        terminals = set(targets)
        for _ in range(MAX_IMPROVE_PASSES):
            gained = False
            for chain in self._chains(start, terminals, tree):
                if not chain <= tree:
                    continue                                  # already replaced earlier in this pass
                rest = tree - chain
                near = set(self._spanning_parents(start, rest))
                far = rest - near
                path = self._nearest(near, far, allowed) if far else []
                candidate = rest | set(path)
                if len(candidate) < len(tree) and terminals <= set(self._spanning_parents(start, candidate)):
                    tree, gained = candidate, True
            if not gained:
                break
        return self._prune(start, terminals, tree)

    def _chains(self, start: str, terminals: set[str], tree: set[str]) -> list[set[str]]:
        """Stretches of travel nodes between two nodes that matter (start, targets, forks)."""
        parents = self._spanning_parents(start, tree)
        children: dict[str, int] = {}
        for parent in parents.values():
            if parent is not None:
                children[parent] = children.get(parent, 0) + 1
        key = {start} | (terminals & set(parents)) | {n for n, count in children.items() if count > 1}
        chains = []
        for node in sorted(key - {start}):
            chain, above = set(), parents[node]
            while above is not None and above not in key:
                chain.add(above)
                above = parents[above]
            if chain:
                chains.append(chain)
        return chains

    def _prune(self, start: str, terminals: set[str], tree: set[str]) -> set[str]:
        """Drop nodes that lead to no target (left over when a cheaper attachment made a loop)."""
        parents = self._spanning_parents(start, tree)
        children: dict[str, int] = {node: 0 for node in parents}
        for parent in parents.values():
            if parent is not None:
                children[parent] += 1
        keep = set(parents)
        leaves = [n for n, count in children.items() if count == 0]
        while leaves:
            node = leaves.pop()
            if node == start or node in terminals:
                continue
            keep.discard(node)
            parent = parents[node]
            children[parent] -= 1
            if children[parent] == 0:
                leaves.append(parent)
        return keep

    # -- breadth-first helpers ----------------------------------------------------------

    def _distances(self, start: str, allowed: set[str]) -> dict[str, int]:
        distance, queue = {start: 0}, deque([start])
        while queue:
            node = queue.popleft()
            for other in self.adjacent.get(node, ()):
                if other in allowed and other not in distance:
                    distance[other] = distance[node] + 1
                    queue.append(other)
        return distance

    def _nearest(self, sources: set[str], goals: set[str], allowed: set[str]) -> list[str]:
        """Nodes to add (goal included) to join the closest goal to `sources`; ties go to the
        smallest id. Empty when a goal is already a source or none can be reached."""
        if goals & sources:
            return []
        parent: dict[str, str | None] = {s: None for s in sources}
        level = sorted(sources)
        while level:
            nxt: list[str] = []
            for node in level:
                for other in self.adjacent.get(node, ()):
                    if other in allowed and other not in parent:
                        parent[other] = node
                        nxt.append(other)
            found = sorted(goals.intersection(nxt))
            if found:
                path, node = [], found[0]
                while node not in sources:
                    path.append(node)
                    node = parent[node]
                return path[::-1]
            level = nxt
        return []

    def _spanning_parents(self, start: str, tree: set[str]) -> dict[str, str | None]:
        parents: dict[str, str | None] = {start: None}
        queue = deque([start])
        while queue:
            node = queue.popleft()
            for other in self.adjacent.get(node, ()):
                if other in tree and other not in parents:
                    parents[other] = node
                    queue.append(other)
        return parents

    def _own_branch(self, target: str, start: str, terminals: set[str], parents: dict[str, str | None]) -> set[str]:
        """The target and the nodes above it that serve no other target."""
        if target not in parents:
            return set()
        children: dict[str, int] = {}
        for parent in parents.values():
            if parent is not None:
                children[parent] = children.get(parent, 0) + 1
        if children.get(target, 0):
            return set()          # other nodes hang below this target: removing it frees nothing
        branch, node = {target}, parents[target]
        while node is not None and node != start and node not in terminals and children.get(node, 0) == 1:
            branch.add(node)
            node = parents[node]
        return branch

    def _allocation_order(self, start: str, tree: set[str]) -> list[str]:
        return [node for node in self._spanning_parents(start, tree) if node != start]
