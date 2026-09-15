import datetime as dt

from nfl_pipeline.sources.wikipedia_staff import (
    _roles_for_title,
    article_title,
    parse_date,
    parse_staff,
    resolve_week_note,
    staff_block,
)

BLOCK = """intro text
{{NFL final staff
|Front Office=
*Owner – [[Some Owner]]
|Head Coaches=
*Head coach – [[Frank Reich]]; ''fired on November 27''
*Interim head coach/special teams coordinator – [[Chris Tabor]]
*Assistant head coach/running backs – [[Duce Staley]]; ''fired on November 27''
*Offensive coordinator – [[Thomas Brown (American football coach)|Thomas Brown]]
*Passing game coordinator – [[Parks Frazier]]
*Defensive coordinator – [[Ejiro Evero]]<ref>cite</ref>
}}
== Schedule ==
"""


def test_staff_block_extracts_template_only():
    block = staff_block(BLOCK)
    assert block.startswith("{{NFL final staff")
    assert "Schedule" not in block


def test_parse_roles_names_dates_and_interim_inference():
    rows = {(e.role, e.coach): e for e in parse_staff(BLOCK, 2023, "CAR")}
    reich = rows[("head_coach", "Frank Reich")]
    assert reich.end_date == dt.date(2023, 11, 27) and not reich.is_interim
    tabor = rows[("head_coach", "Chris Tabor")]
    assert tabor.is_interim and tabor.start_date == dt.date(2023, 11, 27)
    assert ("special_teams_coordinator", "Chris Tabor") in rows
    assert rows[("offensive_coordinator", "Thomas Brown")].end_date is None
    assert rows[("defensive_coordinator", "Ejiro Evero")].note is None
    # assistants and passing-game coordinators are not coordinators
    assert not any(c == "Duce Staley" or c == "Parks Frazier" for _, c in rows)


def test_parse_hyphen_separator_and_parenthetical_note():
    wt = """{{NFL final staff
*Offensive coordinator - [[Luke Getsy]] ''(fired on November 5)''
*Interim offensive coordinator - [[Scott Turner (American football coach)|Scott Turner]]
}}"""
    rows = {e.coach: e for e in parse_staff(wt, 2024, "LV")}
    assert rows["Luke Getsy"].end_date == dt.date(2024, 11, 5)
    assert rows["Scott Turner"].start_date == dt.date(2024, 11, 5)
    assert rows["Luke Getsy"].note == "fired on November 5"


def test_parse_date_year_inference():
    assert parse_date("fired on November 5", 2024) == dt.date(2024, 11, 5)
    assert parse_date("promoted January 3", 2024) == dt.date(2025, 1, 3)
    assert parse_date("stepped down July 13, 2019", 2019) == dt.date(2019, 7, 13)
    assert parse_date("no date here", 2024) is None


def test_missing_block_returns_empty():
    assert parse_staff("no staff here", 2010, "PIT") == []


def test_article_title_overrides():
    assert article_title("LV", "Las Vegas Raiders", 2019) == "2019 Oakland Raiders season"
    assert article_title("LV", "Las Vegas Raiders", 2020) == "2020 Las Vegas Raiders season"
    assert (
        article_title("WAS", "Washington Commanders", 2021)
        == "2021 Washington Football Team season"
    )
    assert article_title("KC", "Kansas City Chiefs", 2024) == "2024 Kansas City Chiefs season"


def test_roles_for_title_segment_matching():
    assert _roles_for_title("Head coach") == [("head_coach", False)]
    assert _roles_for_title("Interim head coach/special teams coordinator") == [
        ("head_coach", True),
        ("special_teams_coordinator", False),
    ]
    assert _roles_for_title("Assistant head coach/offensive coordinator") == [
        ("offensive_coordinator", False)
    ]
    assert _roles_for_title("Offensive coordinator/quarterbacks") == [
        ("offensive_coordinator", False)
    ]
    assert _roles_for_title("Co-defensive coordinator/linebackers") == [
        ("defensive_coordinator", False)
    ]
    assert _roles_for_title("Associate head coach/running backs") == []
    assert _roles_for_title("Director of football / head coach administration") == []
    assert _roles_for_title("Head coach research specialist") == []
    assert _roles_for_title("Defensive backs/passing game coordinator") == []
    assert _roles_for_title("Run game coordinator/offensive line") == []


def test_week_note_resolution_and_name_interim():
    week_dates = {10: dt.date(2023, 11, 13), 11: dt.date(2023, 11, 19)}
    assert resolve_week_note("fired after Week 10", week_dates) == dt.date(2023, 11, 14)
    assert resolve_week_note("before Week 11", week_dates) == dt.date(2023, 11, 19)
    assert resolve_week_note("fired on November 5", week_dates) is None
    wt = """{{NFL final staff
*Offensive coordinator – [[Ken Dorsey]]; ''fired after Week 10''
*Interim offensive coordinator/quarterbacks – [[Joe Brady (American football coach)|Joe Brady]]
*Defensive coordinator – Ron Rivera (interim)
}}"""
    rows = {e.coach: e for e in parse_staff(wt, 2023, "BUF", week_dates=week_dates)}
    assert rows["Ken Dorsey"].end_date == dt.date(2023, 11, 14)
    assert rows["Joe Brady"].start_date == dt.date(2023, 11, 14)
    assert rows["Ron Rivera"].is_interim and rows["Ron Rivera"].role == "defensive_coordinator"


def test_bare_current_staff_template_is_parsed():
    wt = """;Head coaches
*Head coach – [[Andy Reid]]
*Assistant head coach/special teams coordinator – [[Dave Toub]]
*Offensive coordinator – [[Eric Bieniemy]]
*Pass game coordinator – [[Joe Bleymaier]]
*Defensive coordinator – [[Steve Spagnuolo]]
"""
    roles = {e.role: e.coach for e in parse_staff(wt, 2026, "KC")}
    assert roles == {
        "head_coach": "Andy Reid",
        "special_teams_coordinator": "Dave Toub",
        "offensive_coordinator": "Eric Bieniemy",
        "defensive_coordinator": "Steve Spagnuolo",
    }


def test_disambiguator_in_link_is_not_a_note():
    wt = """{{NFL final staff
*Head coach – [[Arthur Smith (American football, born 1982)|Arthur Smith]]
*Head coach – [[Robert Saleh]]; <br>''fired on October 8''
}}"""
    rows = {e.coach: e for e in parse_staff(wt, 2023, "ATL")}
    assert rows["Arthur Smith"].note is None
    assert rows["Robert Saleh"].note == "fired on October 8"
    assert rows["Robert Saleh"].end_date == dt.date(2023, 10, 8)


def test_linked_titles_in_current_staff_template():
    wt = """;Head coach
* [[List of Washington Commanders head coaches|Head coach]] – [[Dan Quinn (American football)|Dan Quinn]]
;Offensive coaches
* [[Offensive coordinator]] – [[David Blough]]
* Offensive pass game coordinator – [[David Raih]]
"""
    roles = {e.role: e.coach for e in parse_staff(wt, 2026, "WAS")}
    assert roles == {"head_coach": "Dan Quinn", "offensive_coordinator": "David Blough"}
