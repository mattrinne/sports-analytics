import json
import re
from pathlib import Path

import pytest

from nfl_pipeline.metadata import (
    AXES,
    ColumnMeta,
    Curated,
    Override,
    Rule,
    _pg_array,
    label_column,
    read_dictionary,
)

ROOT = Path(__file__).resolve().parents[1] / "data" / "metadata"


# ------------------------------------------------------------------ dictionary parsers


def test_read_dictionary_csv_capitalized(tmp_path):
    p = tmp_path / "d.csv"
    p.write_text('"Field","Description","Type"\n"play_id","Numeric play id.","numeric"\n')
    assert read_dictionary(p) == {"play_id": ("Numeric play id.", "numeric")}


def test_read_dictionary_csv_lowercase_with_data_type(tmp_path):
    p = tmp_path / "d.csv"
    p.write_text('field,data_type,description\ngame_id,character,"Game id, human readable"\n')
    assert read_dictionary(p) == {"game_id": ("Game id, human readable", "character")}


def test_read_dictionary_json(tmp_path):
    p = tmp_path / "d.json"
    p.write_text(
        json.dumps(
            [{"field": "Season", "data_type": "numeric", "description": " Official season "}]
        )
    )
    assert read_dictionary(p) == {"season": ("Official season", "numeric")}


def test_curated_load_with_in_memory_dictionaries(tmp_path):
    (tmp_path / "tables.yaml").write_text(
        "pbp:\n  default_entity: play\n  dictionaries: [dictionary_pbp.csv]\n"
    )
    (tmp_path / "labels.yaml").write_text(
        "role: {measure: m}\nside: {}\nentity: {play: p}\ncategory: {}\n"
    )
    (tmp_path / "rules.yaml").write_text("rules: []\n")
    (tmp_path / "overrides.yaml").write_text("columns: []\n")
    texts = {
        "dictionary_pbp.csv": '"Field","Description","Type"\n"epa","Expected points added","numeric"\n'
    }
    curated = Curated.load(tmp_path, texts)
    assert curated.dictionaries["pbp"]["epa"] == ("Expected points added", "numeric")
    with pytest.raises(FileNotFoundError):
        Curated.load(tmp_path, {})


def test_repo_tables_yaml_only_references_known_dictionaries():
    import yaml

    from nfl_pipeline.metadata import NFLVERSE_DICT_FILES

    tables = yaml.safe_load((ROOT / "tables.yaml").read_text())
    for name, meta in tables.items():
        for f in meta.get("dictionaries") or []:
            assert f in NFLVERSE_DICT_FILES, f"{name}: {f}"


# ------------------------------------------------------------------ rule engine


def _curated(rules, overrides=(), default_entity="play", dictionary=None):
    return Curated(
        tables={"pbp": {"default_entity": default_entity}},
        labels={
            "role": {"measure": "", "model": "", "identifier": "", "system": ""},
            "side": {"offense": "", "defense": "", "neutral": ""},
            "entity": {"play": "", "player": ""},
            "category": {"passing": "", "expected_points": ""},
        },
        rules=list(rules),
        overrides=list(overrides),
        dictionaries={"pbp": dictionary or {}},
    )


def _col(name, data_type="double precision"):
    return ColumnMeta(table="pbp", column=name, ordinal=1, data_type=data_type)


def test_defaults_from_type_and_table():
    c = label_column(_col("yards", "double precision"), _curated([]))
    assert c.labels["role"] == "measure"
    assert c.labels["entity"] == "play"
    assert c.labels["side"] is None


def test_later_rule_wins_and_tags_accumulate():
    rules = [
        Rule("a", re.compile("^epa$"), None, {"category": "passing", "side": "offense"}, ("t1",)),
        Rule(
            "b",
            re.compile("epa"),
            None,
            {"category": "expected_points", "role": "model"},
            ("t2", "t1"),
        ),
    ]
    c = label_column(_col("epa"), _curated(rules))
    assert c.labels == {
        "role": "model",
        "side": "offense",
        "entity": "play",
        "category": "expected_points",
    }
    assert c.tags == ["t1", "t2"]
    assert c.sources == ["rule:a", "rule:b"]


def test_rule_table_scoping():
    rules = [Rule("a", re.compile("^x$"), frozenset({"schedules"}), {"side": "offense"})]
    c = label_column(_col("x"), _curated(rules))
    assert c.labels["side"] is None


def test_rule_can_clear_axis_with_null():
    rules = [Rule("sys", re.compile("^_loaded_at$"), None, {"role": "system", "entity": None})]
    c = label_column(_col("_loaded_at", "timestamp with time zone"), _curated(rules))
    assert c.labels["role"] == "system"
    assert c.labels["entity"] is None


def test_override_beats_rules_and_dictionary():
    rules = [Rule("a", re.compile("^epa$"), None, {"side": "offense"})]
    ov = Override(
        tables=None, column="epa", description="curated text", set={"side": "defense"}, tags=("x",)
    )
    c = label_column(
        _col("epa"), _curated(rules, [ov], dictionary={"epa": ("nflverse text", None)})
    )
    assert c.labels["side"] == "defense"
    assert c.description == "curated text"
    assert c.description_source == "curated"
    assert c.tags == ["x"]
    assert c.sources[-1] == "override"


def test_dictionary_description_applied():
    c = label_column(
        _col("epa"), _curated([], dictionary={"epa": ("Expected points added", "numeric")})
    )
    assert c.description == "Expected points added"
    assert c.description_source == "nflverse"


def test_validate_vocabulary_reports_unknown_labels():
    rules = [Rule("bad", re.compile("x"), None, {"side": "sideways", "bogus_axis": "y"})]
    problems = _curated(rules).validate_vocabulary()
    assert any("unknown side label 'sideways'" in p for p in problems)
    assert any("unknown axis 'bogus_axis'" in p for p in problems)


# ------------------------------------------------------------------ repo curated files


def test_repo_curated_files_are_valid():
    from nfl_pipeline.metadata import NFLVERSE_DICT_FILES

    empty = {
        f: ('"Field","Description"\n' if f.endswith(".csv") else "[]") for f in NFLVERSE_DICT_FILES
    }
    curated = Curated.load(ROOT, empty)
    problems = [p for p in curated.validate_vocabulary()]
    assert problems == []
    assert set(curated.labels) == set(AXES)


def test_pg_array_literal():
    assert _pg_array([]) == "{}"
    assert _pg_array(["a", "perspective:home"]) == '{"a","perspective:home"}'
    assert _pg_array(['q"uote']) == '{"q\\"uote"}'


@pytest.mark.parametrize("axis", AXES)
def test_every_axis_has_labels(axis):
    import yaml

    assert yaml.safe_load((ROOT / "labels.yaml").read_text())[axis]
