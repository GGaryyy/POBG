import itertools
import random

import pytest

from src.tools.pathing import MAX_IMPROVE_PASSES, MAX_TARGETS, PassivePathfinder, Route

pytestmark = pytest.mark.unit


def finder(edges, extra=()):
    ids = {n for edge in edges for n in edge} | set(extra)
    nodes = {i: {"neighbors": []} for i in ids}
    for a, b in edges:
        nodes[a]["neighbors"].append(b)
        nodes[b]["neighbors"].append(a)
    return PassivePathfinder(nodes), set(ids)


def assert_allocatable(pf, route, targets):
    """Every node is next to the start or to a node allocated before it; every target is in."""
    have = {route.start}
    for node in route.order:
        assert any(n in have for n in pf.adjacent[node]), f"{node} is not next to an allocated node"
        assert node not in have
        have.add(node)
    assert set(targets) - set(route.unreachable) <= have


# trunk s-a-b-c, branch c-d-T1, branch c-e-T2, side road s-x-y-z-T1 (one node shorter to T1 alone)
TRAP = [("s", "a"), ("a", "b"), ("b", "c"), ("c", "d"), ("d", "T1"), ("c", "e"), ("e", "T2"),
        ("s", "x"), ("x", "y"), ("y", "z"), ("z", "T1")]


def test_single_target_takes_the_shortest_path():
    pf, ids = finder(TRAP)
    route = pf.route("s", ["T1"], ids)
    assert route.order == ["x", "y", "z", "T1"] and route.points == 4
    assert route.alone == {"T1": 4} and route.exclusive == {"T1": 4} and route.unreachable == []


def test_two_targets_share_the_trunk_after_the_improvement_pass():
    pf, ids = finder(TRAP)
    route = pf.route("s", ["T1", "T2"], ids)
    # nearest-first takes the side road to T1 (4) and reaches T2 from there (4) = 8 points
    assert sorted(route.order) == ["T1", "T2", "a", "b", "c", "d", "e"] and route.points == 7
    assert route.order == ["a", "b", "c", "d", "e", "T1", "T2"]          # breadth-first from the start
    assert route.alone == {"T1": 4, "T2": 5}
    assert route.exclusive == {"T1": 2, "T2": 2}
    assert_allocatable(pf, route, ["T1", "T2"])


def test_without_the_improvement_pass_the_greedy_route_is_longer(monkeypatch):
    import src.tools.pathing as pathing
    monkeypatch.setattr(pathing, "MAX_IMPROVE_PASSES", 0)
    pf, ids = finder(TRAP)
    route = pf.route("s", ["T1", "T2"], ids)
    assert route.points == 8 and route.order == ["x", "y", "z", "T1", "d", "c", "e", "T2"]


def test_start_is_free_and_never_listed():
    pf, ids = finder([("s", "a")])
    route = pf.route("s", ["a"], ids)
    assert route.order == ["a"] and route.points == 1 and route.start == "s"


def test_start_as_a_target_and_duplicates_cost_nothing_extra():
    pf, ids = finder([("s", "a"), ("a", "b")])
    route = pf.route("s", ["s", "b", "b"], ids)
    assert route.order == ["a", "b"] and route.alone == {"b": 2}


def test_no_targets_gives_an_empty_route():
    pf, ids = finder([("s", "a")])
    route = pf.route("s", [], ids)
    assert route == Route(start="s") and route.points == 0


def test_unreachable_target_is_reported_and_the_rest_is_routed():
    pf, ids = finder([("s", "a"), ("p", "q")])
    route = pf.route("s", ["a", "q", "missing"], ids | {"missing"})
    assert route.order == ["a"] and route.unreachable == ["missing", "q"]
    assert "q" not in route.alone and "q" not in route.exclusive


def test_allowed_set_closes_a_shortcut():
    edges = [("s", "k"), ("k", "T"), ("s", "a"), ("a", "b"), ("b", "T")]
    pf, ids = finder(edges)
    assert pf.route("s", ["T"], ids).order == ["k", "T"]
    assert pf.route("s", ["T"], ids - {"k"}).order == ["a", "b", "T"]


def test_target_outside_allowed_is_unreachable():
    pf, ids = finder([("s", "a"), ("a", "T")])
    route = pf.route("s", ["T"], ids - {"T"})
    assert route.order == [] and route.unreachable == ["T"]


def test_start_does_not_need_to_be_in_allowed():
    pf, ids = finder([("s", "a")])
    assert pf.route("s", ["a"], {"a"}).order == ["a"]


def test_target_on_the_way_to_another_has_no_exclusive_points():
    pf, ids = finder([("s", "a"), ("a", "M"), ("M", "b"), ("b", "E")])
    route = pf.route("s", ["M", "E"], ids)
    assert route.order == ["a", "M", "b", "E"]
    assert route.exclusive == {"M": 0, "E": 2}        # dropping M frees nothing; E needs b and itself


def test_equal_routes_are_chosen_the_same_way_every_time():
    edges = [("s", "a1"), ("a1", "T"), ("s", "a2"), ("a2", "T")]
    pf, ids = finder(edges)
    shuffled = finder(list(reversed([(b, a) for a, b in edges])))[0]
    assert pf.route("s", ["T"], ids).order == shuffled.route("s", ["T"], ids).order == ["a1", "T"]


def test_neighbours_missing_from_the_node_table_are_ignored():
    pf = PassivePathfinder({"s": {"neighbors": ["a", "ghost"]}, "a": {"neighbors": ["s"]}, "lonely": {}})
    assert pf.adjacent == {"s": ["a"], "a": ["s"], "lonely": []}
    assert pf.route("s", ["a"], {"a"}).order == ["a"]


def test_limits():
    assert MAX_TARGETS == 40 and MAX_IMPROVE_PASSES == 3


def optimum(pf, start, targets, ids):
    """Fewest extra nodes that connect start and targets (brute force over subsets)."""
    others = sorted(ids - {start} - set(targets))
    for extra in range(len(others) + 1):
        for chosen in itertools.combinations(others, extra):
            group = {start, *targets, *chosen}
            seen, stack = {start}, [start]
            while stack:
                for n in pf.adjacent[stack.pop()]:
                    if n in group and n not in seen:
                        seen.add(n)
                        stack.append(n)
            if seen == group:
                return len(group) - 1
    raise AssertionError("not connected")


@pytest.mark.parametrize("seed", range(40))
def test_random_graphs_are_valid_and_within_twice_the_optimum(seed):
    rng = random.Random(seed)
    size = rng.randint(6, 11)
    names = [f"n{i:02d}" for i in range(size)]
    edges = [(names[i], names[rng.randrange(i)]) for i in range(1, size)]          # a random tree: connected
    edges += [tuple(rng.sample(names, 2)) for _ in range(rng.randint(0, size))]    # plus some cycles
    pf, ids = finder(edges)
    targets = rng.sample(names[1:], rng.randint(1, 4))
    route = pf.route(names[0], targets, ids)
    best = optimum(pf, names[0], targets, ids)
    assert_allocatable(pf, route, targets)
    assert route.unreachable == [] and len(set(route.order)) == len(route.order)
    assert best <= route.points <= 2 * best
    if len(targets) == 1:
        assert route.points == best == route.alone[targets[0]]
    again = pf.route(names[0], list(reversed(targets)), ids)
    assert again.order == route.order                 # target order in the request does not matter
