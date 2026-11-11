"""The poe.ninja response layout as the ladder fetcher reads it (synthetic data only)."""
import pytest

from src import fetch_poe_ninja_builds as ninja
from tests.ninja_support import CLASSES, GEMS, KEYSTONES, LEAGUE, FakeNinja, characters, field, ndic, search_page, varint

pytestmark = pytest.mark.unit


def parse(page, classes=CLASSES, gems=GEMS, keystones=KEYSTONES):
    return ninja._parse_search_response(page, classes, gems, keystones, LEAGUE, "dps", False, 0, "2026-01-01T00:00:00+00:00")


# -- dictionaries ------------------------------------------------------------------------------

@pytest.mark.parametrize("strings", [[], ["Titan"], CLASSES, [f"Gem {i}" for i in range(40)], ["靈魂", "Zerphi's Infamy", ""]])
def test_ndic_dictionary_round_trips(strings):
    assert ninja._decode_dict_blob(ndic(strings)) == strings


def test_ndic_with_sizes_that_do_not_add_up_gives_no_names_rather_than_wrong_ones():
    blob = ndic(CLASSES)
    assert ninja._decode_dict_blob(blob[:-1]) == [] and ninja._decode_dict_blob(blob + b"x") == []
    assert ninja._decode_dict_blob(blob[:20]) == [] and ninja._decode_dict_blob(b"NDIC") == []


def test_older_protobuf_dictionary_is_still_read():
    blob = field(1, "class") + field(2, "Titan") + field(2, "Deadeye")
    assert ninja._decode_dict_blob(blob) == ["Titan", "Deadeye"]


def test_unknown_dictionary_bytes_give_an_empty_list():
    assert ninja._decode_dict_blob(b"\xff\xff\xff\xff not a dictionary") == []


# -- search response ---------------------------------------------------------------------------

def test_rows_are_decoded_with_class_level_skills_and_keystones():
    rows = characters(6)
    records = parse(search_page(rows))
    assert [r["character_name"] for r in records] == [f"SecretHero{i}" for i in range(6)]
    assert [r["account_name"] for r in records] == [f"SecretAccount{i}" for i in range(6)]
    assert [r["class"] for r in records] == ["Blood Mage", "Deadeye", "Titan", "Blood Mage", "Deadeye", "Titan"]
    assert [r["level"] for r in records] == [80, 81, 82, 83, 84, 85]
    assert records[1]["skill_gems"] == ["Fireball", "Comet"] and records[4]["skill_gems"] == ["Arc", "Spark"]
    assert records[0]["keystones"] is None and records[1]["keystones"] == ["Mind Over Matter"]
    assert [r["rank"] for r in records] == [1, 2, 3, 4, 5, 6]
    assert {r["league"] for r in records} == {LEAGUE} and {r["sort_key"] for r in records} == {"dps_desc"}


def test_main_skill_is_the_dps_skill_when_the_character_has_it():
    records = parse(search_page(characters(3)))
    assert [r["main_skill"] for r in records] == ["Arc", "Comet", "Fireball"]          # the second listed skill
    assert all(r["main_skill"] != r["skill_gems"][0] for r in records)


def test_main_skill_falls_back_to_the_first_skill():
    rows = characters(3)
    assert [r["main_skill"] for r in parse(search_page(rows, with_dps_skill=False))] == ["Comet", "Fireball", "Leap Slam"]
    foreign = [{**row, "dps_skill": 3} for row in rows[:1]]                           # a skill the character lacks
    assert parse(search_page(foreign))[0]["main_skill"] == "Comet"
    assert ninja._main_skill(99, GEMS, []) is None and ninja._main_skill(None, GEMS, ["Arc"]) == "Arc"


def test_index_outside_a_dictionary_becomes_missing_not_an_error():
    records = parse(search_page(characters(3)), classes=["Blood Mage"], gems=[], keystones=[])
    assert [r["class"] for r in records] == ["Blood Mage", None, None]
    assert all(r["skill_gems"] is None and r["main_skill"] is None and r["keystones"] is None for r in records)


def test_rows_without_a_name_are_skipped():
    rows = characters(3)
    rows[1]["name"] = ""
    assert [r["character_name"] for r in parse(search_page(rows))] == ["SecretHero0", "SecretHero2"]


def test_page_in_an_unknown_layout_gives_no_rows_and_a_warning_without_names(capsys):
    old_layout = field(1, field(5, field(1, "name") + field(2, field(1, "SecretHero0"))))
    assert parse(old_layout) == []
    assert parse(b"") == [] and parse(field(2, b"x")) == []
    err = capsys.readouterr().err
    assert "response format may have changed" in err and "Secret" not in err


def test_varint_helper_matches_the_fetcher():
    for value in (0, 1, 127, 128, 300, 2**21 + 5):
        assert ninja._read_varint(varint(value), 0) == (value, len(varint(value)))
    assert ninja._unpack_varints(varint(5) + varint(300) + varint(0)) == [5, 300, 0]


# -- the collection loop -----------------------------------------------------------------------

def test_collect_builds_reads_through_the_given_transport_and_keeps_each_character_once(capsys):
    site = FakeNinja(characters(120))
    records = ninja._validate(ninja.collect_builds(site.get_json, site.get_binary))
    assert len(records) == 120 and len({r["character_name"] for r in records}) == 120      # ten passes, same 120 rows
    assert [u for u in site.calls if "index-state" in u] == [ninja.INDEX_STATE_URL]
    assert sum("/dictionary/" in u for u in site.calls) == 3
    assert sum("/search" in u for u in site.calls) == 1 + len(ninja.SORT_KEYS) - 1 + len(ninja.SORT_KEYS_ASC)
    assert {r["class"] for r in records} == set(CLASSES) and all(r["main_skill"] for r in records)
    assert "Secret" not in capsys.readouterr().out                 # progress output names no character


def test_collect_builds_without_a_league_raises():
    site = FakeNinja(index_state={"buildLeagues": [], "snapshotVersions": []})
    with pytest.raises(RuntimeError, match="No build leagues"):
        ninja.collect_builds(site.get_json, site.get_binary)


def test_written_snapshot_from_the_new_layout_holds_no_names(tmp_path):
    site = FakeNinja(characters(5))
    path = tmp_path / "ladder.jsonl"
    assert ninja._write_jsonl(ninja._validate(ninja.collect_builds(site.get_json, site.get_binary)), path) == 5
    text = path.read_text(encoding="utf-8")
    assert "Secret" not in text and text.count("\n") == 5 and "\r" not in text
    assert '"main_skill": "Arc"' in text and f'"league": "{LEAGUE}"' in text


# -- malformed and hostile input ---------------------------------------------------------------

def test_dictionary_with_long_strings_uses_multi_byte_lengths():
    strings = ["x" * 130, "短", "y" * 300]
    assert ninja._decode_dict_blob(ndic(strings)) == strings


@pytest.mark.parametrize("data", [b"\xff" * 11, b"\x80", b"\xff" * 200_000])
def test_unterminated_or_overlong_varint_is_malformed(data):
    with pytest.raises(ValueError):
        ninja._read_varint(data, 0)
    assert ninja._unpack_varints(data) == []
    assert ninja._parse_proto(data) == []


def test_dictionary_header_that_claims_more_strings_than_it_holds_gives_nothing():
    import struct
    blob = bytearray(ndic(["Titan", "Deadeye"]))
    struct.pack_into("<I", blob, ninja.NDIC_COUNT_OFFSET, 2**32 - 1)
    assert ninja._decode_dict_blob(bytes(blob)) == []
    struct.pack_into("<I", blob, ninja.NDIC_COUNT_OFFSET, 2)
    struct.pack_into("<I", blob, ninja.NDIC_BLOCKS_OFFSET, 2**31)
    assert ninja._decode_dict_blob(bytes(blob)) == []


def test_column_with_the_wrong_number_of_rows_is_dropped_instead_of_shifting_every_row(capsys):
    from tests.ninja_support import column
    rows = characters(4)
    good = [column("name", strings=[r["name"] for r in rows]), column("level", ints=[r["level"] for r in rows])]
    short_class = column("class", ints=[2, 2, 2], dictionary="class")                 # one value missing
    long_skills = column("skills", lists=[[0]] * 5, dictionary="gem")                  # one cell too many
    page = field(1, b"".join(field(12, c) for c in (*good, short_class, long_skills)))
    records = parse(page)
    assert [r["level"] for r in records] == [80, 81, 82, 83]
    assert all(r["class"] is None and r["skill_gems"] is None and r["main_skill"] is None for r in records)
    err = capsys.readouterr().err
    assert "column class has 3 values for 4 rows" in err and "Secret" not in err


def test_dps_skill_is_used_only_when_its_column_points_at_the_gem_dictionary():
    from tests.ninja_support import column
    rows = characters(2)
    base = [column("name", strings=[r["name"] for r in rows]), column("skills", lists=[r["skills"] for r in rows], dictionary="gem")]
    def page(dictionary):
        return field(1, b"".join(field(12, c) for c in (*base, column("dps.skill", ints=[r["dps_skill"] for r in rows], dictionary=dictionary))))
    assert [r["main_skill"] for r in parse(page("gem"))] == ["Arc", "Comet"]
    assert [r["main_skill"] for r in parse(page("item"))] == ["Comet", "Fireball"]     # first listed skill instead


def test_only_the_three_needed_dictionaries_are_fetched_once_each():
    site = FakeNinja(characters(3))
    ninja.collect_builds(site.get_json, site.get_binary)
    fetched = [u.rsplit("/", 1)[-1] for u in site.calls if "/dictionary/" in u]
    assert sorted(fetched) == sorted(["c1a55", "9e3", "4e9"])                          # no "item", no repeat, no "../../etc"


def test_failed_result_page_stops_the_collection():
    import requests
    site = FakeNinja(characters(120))
    seen = []

    def flaky(url):
        if "/search" in url:
            seen.append(url)
            if len(seen) == 2:
                raise requests.ConnectionError("reset")
        return site.get_binary(url)

    with pytest.raises(requests.ConnectionError):
        ninja.collect_builds(site.get_json, flaky)


def test_fetcher_has_no_assert_on_network_data():
    import inspect
    assert "assert " not in inspect.getsource(ninja)
