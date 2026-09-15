"""Coaching staff (head coach, OC, DC, ST coordinator) per team-season, parsed from the
`{{NFL final staff}}` block of Wikipedia's "<season> <Team> season" articles.

Wikipedia etiquette: serial, throttled requests with a descriptive User-Agent. A whole season of
team articles is fetched in one batched API call and held in memory only; nothing is cached on disk.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

import polars as pl

from ..config import settings

log = logging.getLogger(__name__)

API = "https://en.wikipedia.org/w/api.php"
USER_AGENT = "sports-analytics-nfl-pipeline/0.1 (local research warehouse; python urllib)"
MIN_INTERVAL_S = 1.0
_last_request = 0.0

ROLES = (
    "head_coach",
    "offensive_coordinator",
    "defensive_coordinator",
    "special_teams_coordinator",
)

# Article titles that don't follow "<season> <teams.team_name> season".
ARTICLE_TITLE_OVERRIDES: dict[tuple[str, int], str] = {
    **{("WAS", y): f"{y} Washington Redskins season" for y in range(1999, 2020)},
    **{("WAS", y): f"{y} Washington Football Team season" for y in (2020, 2021)},
    **{("LA", y): f"{y} St. Louis Rams season" for y in range(1999, 2016)},
    **{("LAC", y): f"{y} San Diego Chargers season" for y in range(1999, 2017)},
    **{("LV", y): f"{y} Oakland Raiders season" for y in range(1999, 2020)},
    ("LAC", 2017): "2017 Los Angeles Chargers season",
}

_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
_DATE_RE = re.compile(rf"({_MONTHS})\s+(\d{{1,2}})(?:,?\s*(\d{{4}}))?")
_PAREN_DATE_RE = re.compile(rf"\(([^)]*\b(?:\d{{4}}|{_MONTHS})\b[^)]*)\)")
_MONTH_NUM = {m: i + 1 for i, m in enumerate(_MONTHS.split("|"))}
_END_WORDS = re.compile(
    r"fired|dismissed|relieved|stepped down|resigned|parted ways|mutual|placed on (?:administrative )?leave|"
    r"left the team|retired|departed|removed|demoted|reassigned|until",
    re.IGNORECASE,
)
_START_WORDS = re.compile(
    r"promoted|hired|named|appointed|took over|beginning|from|since|starting", re.IGNORECASE
)


@dataclass
class StaffEntry:
    season: int
    team: str
    role: str
    title: str
    coach: str
    is_interim: bool
    note: str | None
    start_date: dt.date | None = None
    end_date: dt.date | None = None
    source_url: str = ""
    flags: list[str] = field(default_factory=list)


# ------------------------------------------------------------------------- fetching


def article_title(team: str, team_name: str, season: int) -> str:
    return ARTICLE_TITLE_OVERRIDES.get((team, season), f"{season} {team_name} season")


def _throttle() -> None:
    global _last_request
    wait = MIN_INTERVAL_S - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    _last_request = time.monotonic()


def _api_get(params: dict) -> dict:
    """GET the MediaWiki API with throttling, retries and Retry-After handling."""
    url = f"{API}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    delay = 10
    for attempt in range(6):
        _throttle()
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 503) or attempt == 5:
                raise
            retry_after = exc.headers.get("Retry-After")
            wait = int(retry_after) if retry_after and retry_after.isdigit() else delay
            log.warning("wikipedia HTTP %s; sleeping %ss (attempt %d)", exc.code, wait, attempt + 1)
            time.sleep(wait)
            delay = min(delay * 2, 120)
        except json.JSONDecodeError:
            log.warning("wikipedia returned non-JSON (rate limit text); sleeping %ss", delay)
            time.sleep(delay)
            delay = min(delay * 2, 120)
    raise RuntimeError("wikipedia: retries exhausted")


def fetch_wikitexts(titles: list[str]) -> dict[str, str | None]:
    """Wikitext for many articles (<=50 per API call), following redirects. None = page missing.

    Uses action=query&prop=revisions, which is far cheaper for the API than action=parse and lets
    one request cover a whole season of team articles. Results live in memory only.
    """
    out: dict[str, str | None] = {}
    for i in range(0, len(titles), 50):
        batch = titles[i : i + 50]
        data = _api_get(
            {
                "action": "query",
                "prop": "revisions",
                "rvprop": "content",
                "rvslots": "main",
                "redirects": 1,
                "titles": "|".join(batch),
                "format": "json",
                "formatversion": 2,
            }
        )
        q = data.get("query", {})
        resolved = {r["from"]: r["to"] for r in q.get("redirects", [])}
        resolved.update({n["from"]: n["to"] for n in q.get("normalized", [])})
        pages = {p["title"]: p for p in q.get("pages", [])}
        for t in batch:
            key = t
            for _ in range(3):  # follow normalization then redirect chains
                key = resolved.get(key, key)
            page = pages.get(key)
            out[t] = (
                page["revisions"][0]["slots"]["main"]["content"]
                if page and not page.get("missing")
                else None
            )
    return out


# ------------------------------------------------------------------------- parsing


def staff_block(wikitext: str) -> str | None:
    i = wikitext.find("{{NFL final staff")
    if i < 0:
        i = wikitext.find("{{NFL staff")
    if i < 0:
        # Team "current staff" templates (Template:<Team> staff) are bare bullet lists; the title
        # may itself be a wikilink ("* [[List of X head coaches|Head coach]] – ...").
        linkless = re.sub(r"\[\[[^|\]]*\|([^\]]*)\]\]", r"\1", wikitext)
        return (
            wikitext
            if re.search(r"^\s*\*\s*Head coach\b", linkless, re.MULTILINE | re.IGNORECASE)
            else None
        )
    # Template ends at the first "}}" that closes it; nested templates inside are rare here.
    depth, j = 0, i
    while j < len(wikitext) - 1:
        if wikitext.startswith("{{", j):
            depth += 1
            j += 2
        elif wikitext.startswith("}}", j):
            depth -= 1
            j += 2
            if depth == 0:
                break
        else:
            j += 1
    return wikitext[i:j]


def _clean(text: str) -> str:
    text = re.sub(r"<ref[^>]*/>", "", text)
    text = re.sub(r"<ref[^>]*>.*?</ref>", "", text, flags=re.DOTALL)
    text = re.sub(r"\[\[([^|\]]*)\|([^\]]*)\]\]", r"\2", text)  # [[a|b]] -> b
    text = re.sub(r"\[\[([^\]]*)\]\]", r"\1", text)  # [[a]] -> a
    text = re.sub(r"\{\{[^}]*\}\}", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


def normalize_name(name: str) -> str:
    """Canonical spelling of a person's name as parsed from wikitext: drop footnote markers
    (dagger/asterisk that Wikipedia uses for suspensions etc.), collapse whitespace, and write
    generational suffixes one way ("Pete Carmichael, Jr." / "Ken Norton Jr" -> "... Jr.")."""
    name = re.sub(r"[†‡*]+", "", name)
    name = re.sub(r"\s+", " ", name).strip(" ,")
    name = re.sub(
        r",?\s+(jr|sr)\.?$", lambda m: f" {m.group(1).title()}.", name, flags=re.IGNORECASE
    )
    return name


def _split_title_name(line: str) -> tuple[str, str] | None:
    # "*Head coach – [[Name]] ''note''"  separators: en dash, em dash, hyphen, colon
    body = line.lstrip("*").strip()
    m = re.match(r"(.+?)\s+[–—-]\s+(.+)$", body)
    if not m:
        m = re.match(r"(.+?):\s+(.+)$", body)
    if not m:
        return None
    return m.group(1).strip(), m.group(2).strip()


_ROLE_SEGMENT = re.compile(
    r"^(?P<prefix>(?:interim|acting|co-)\s*)?"
    r"(?P<role>head coach|offensive coordinator|defensive coordinator|special teams coordinator)$"
)
_ROLE_KEY = {
    "head coach": "head_coach",
    "offensive coordinator": "offensive_coordinator",
    "defensive coordinator": "defensive_coordinator",
    "special teams coordinator": "special_teams_coordinator",
}


def _roles_for_title(title: str) -> list[tuple[str, bool]]:
    """Roles named by a title. Titles are '/'-separated segments ("Interim head coach/special teams
    coordinator"); a segment must be exactly the role (optionally interim/acting/co-) so "assistant
    head coach", "associate head coach", "head coach research specialist" or "passing game
    coordinator" don't match.
    """
    roles: list[tuple[str, bool]] = []
    for seg in re.split(r"\s*[/&]\s*|\s+and\s+", title.lower()):
        seg = re.sub(r"\s+", " ", seg).strip(" ,")
        m = _ROLE_SEGMENT.match(seg)
        if not m:
            continue
        prefix = (m.group("prefix") or "").strip()
        interim = prefix in ("interim", "acting")
        key = _ROLE_KEY[m.group("role")]
        if key not in [r for r, _ in roles]:
            roles.append((key, interim))
    return roles


def parse_date(text: str, season: int) -> dt.date | None:
    m = _DATE_RE.search(text)
    if not m:
        return None
    month = _MONTH_NUM[m.group(1)]
    year = int(m.group(3)) if m.group(3) else (season if month >= 3 else season + 1)
    try:
        return dt.date(year, month, int(m.group(2)))
    except ValueError:
        return None


_WEEK_RE = re.compile(
    r"(after|following|before|prior to|entering)?\s*week\s+(\d{1,2})", re.IGNORECASE
)


def resolve_week_note(note: str, week_dates: dict[int, dt.date] | None) -> dt.date | None:
    """'fired after Week 10' -> the day after that team's week-10 game."""
    if not week_dates:
        return None
    m = _WEEK_RE.search(note)
    if not m:
        return None
    game_day = week_dates.get(int(m.group(2)))
    if game_day is None:
        return None
    if (m.group(1) or "").lower() in ("before", "prior to", "entering"):
        return game_day
    return game_day + dt.timedelta(days=1)


def parse_staff(
    wikitext: str,
    season: int,
    team: str,
    source_url: str = "",
    week_dates: dict[int, dt.date] | None = None,
) -> list[StaffEntry]:
    block = staff_block(wikitext)
    if block is None:
        return []
    entries: list[StaffEntry] = []
    for raw_line in block.splitlines():
        if not raw_line.lstrip().startswith("*"):
            continue
        # Simplify wikilinks first so "(American football, born 1982)" disambiguators inside link
        # targets are never mistaken for notes; then pull italic / parenthetical notes.
        linkless = re.sub(r"\[\[([^|\]]*)\|([^\]]*)\]\]", r"\2", raw_line)
        linkless = re.sub(r"\[\[([^\]]*)\]\]", r"\1", linkless)
        notes = re.findall(r"''+(.*?)''+", linkless) + _PAREN_DATE_RE.findall(linkless)
        seen: list[str] = []
        for n in notes:
            n = _clean(n).strip("();' ")
            if n and n not in seen:
                seen.append(n)
        note_text = "; ".join(seen) or None
        line = re.sub(r"''+.*?''+", "", linkless)
        line = _PAREN_DATE_RE.sub("", line)
        cleaned = _clean(line)
        split = _split_title_name(cleaned)
        if not split:
            continue
        title, name = split
        # Some pages put the note after a semicolon: "Frank Reich; fired on November 27"
        if ";" in name:
            name, extra = (p.strip() for p in name.split(";", 1))
            extra = _clean(extra).replace("'", "").strip("(); ")
            if extra and extra not in (note_text or ""):
                note_text = f"{note_text}; {extra}" if note_text else extra
        name_interim = bool(re.search(r"\((?:interim|acting)\)", name, re.IGNORECASE))
        name = normalize_name(re.sub(r"\s*\(.*?\)\s*", " ", name))
        if not name or name.lower() in ("vacant", "none", "tbd"):
            continue
        for role, interim in _roles_for_title(title):
            interim = interim or name_interim
            e = StaffEntry(
                season, team, role, title, name, interim, note_text, source_url=source_url
            )
            if note_text:
                d = parse_date(note_text, season) or resolve_week_note(note_text, week_dates)
                if d and _END_WORDS.search(note_text) and not _START_WORDS.search(note_text):
                    e.end_date = d
                elif d and _START_WORDS.search(note_text):
                    e.start_date = d
                elif d:
                    e.end_date = (
                        d  # a bare date on a non-interim entry almost always means departure
                    )
                    e.flags.append("date_kind_guessed")
            entries.append(e)
    return _infer_ranges(entries)


def _infer_ranges(entries: list[StaffEntry]) -> list[StaffEntry]:
    """Interim holders without a start date inherit the predecessor's end date, and vice versa."""
    for role in ROLES:
        group = [e for e in entries if e.role == role]
        if len(group) < 2:
            continue
        primaries = [e for e in group if not e.is_interim]
        interims = [e for e in group if e.is_interim]
        ended = [e for e in primaries if e.end_date]
        if len(interims) == 1 and len(ended) == 1:
            if interims[0].start_date is None:
                interims[0].start_date = ended[0].end_date
        elif (
            len(interims) == 1
            and len(primaries) == 1
            and interims[0].start_date
            and not primaries[0].end_date
        ):
            primaries[0].end_date = interims[0].start_date
        elif len(interims) == 1 and len(primaries) == 1:
            for e in group:
                e.flags.append("undated_change")
        if (
            len(primaries) > 1
            and sum(1 for e in primaries if e.end_date or e.start_date) < len(primaries) - 1
        ):
            for e in primaries:
                e.flags.append("ambiguous_multiple")
    return entries


# ------------------------------------------------------------------------- dataset loader


def teams_for_season(season: int) -> dict[str, str]:
    """abbr -> nflverse team_name for every team that played that season."""
    import nflreadpy

    sched = nflreadpy.load_schedules(season)
    teams = nflreadpy.load_teams()
    names = dict(zip(teams["team_abbr"].to_list(), teams["team_name"].to_list()))
    abbrs = sorted(set(sched["home_team"].to_list()) | set(sched["away_team"].to_list()))
    return {a: names.get(a, a) for a in abbrs}


def week_dates_for_season(season: int) -> dict[str, dict[int, dt.date]]:
    """team -> {week: game date} for regular-season games, used to resolve 'after Week N' notes."""
    import nflreadpy

    sched = nflreadpy.load_schedules(season).filter(pl.col("game_type") == "REG")
    out: dict[str, dict[int, dt.date]] = {}
    for row in sched.select(["week", "gameday", "home_team", "away_team"]).iter_rows(named=True):
        day = dt.date.fromisoformat(row["gameday"])
        for t in (row["home_team"], row["away_team"]):
            out.setdefault(t, {})[int(row["week"])] = day
    return out


SCHEMA = {
    "season": pl.Int64,
    "team": pl.String,
    "role": pl.String,
    "title": pl.String,
    "coach": pl.String,
    "is_interim": pl.Boolean,
    "start_date": pl.Date,
    "end_date": pl.Date,
    "note": pl.String,
    "flags": pl.String,
    "source_url": pl.String,
}


def load_coaching_staff(seasons: int) -> pl.DataFrame:
    """Dataset loader: one row per (season, team, role, coach)."""
    season = int(seasons)
    cfg = settings()
    import nflreadpy

    current = season >= nflreadpy.get_current_season()
    rows = []
    teams = teams_for_season(season)
    week_dates = week_dates_for_season(season)
    titles = {abbr: article_title(abbr, name, season) for abbr, name in teams.items()}
    texts = fetch_wikitexts(list(titles.values()))
    # In-season articles transclude the team's live "Template:<Team> staff" instead of a final
    # staff block; fall back to those templates for teams whose article has none yet.
    fallback = {
        abbr: f"Template:{teams[abbr]} staff"
        for abbr, title in titles.items()
        if texts.get(title) is not None and staff_block(texts[title]) is None
    }
    if fallback and current:
        fb_texts = fetch_wikitexts(list(fallback.values()))
        for abbr, tpl in fallback.items():
            if fb_texts.get(tpl):
                texts[tpl] = fb_texts[tpl]
                titles[abbr] = tpl
    for abbr, title in titles.items():
        url = "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))
        wikitext = texts.get(title)
        if wikitext is None:
            log.warning("no wikipedia article for %s", title)
            continue
        entries = parse_staff(wikitext, season, abbr, url, week_dates.get(abbr))
        if not entries:
            log.warning("no staff block parsed for %s", title)
        rows.extend(
            {
                "season": e.season,
                "team": e.team,
                "role": e.role,
                "title": e.title,
                "coach": e.coach,
                "is_interim": e.is_interim,
                "start_date": e.start_date,
                "end_date": e.end_date,
                "note": e.note,
                "flags": ",".join(e.flags) or None,
                "source_url": e.source_url,
            }
            for e in entries
        )
    df = pl.DataFrame(rows, schema=SCHEMA)
    overrides = _load_overrides(cfg.data_dir / "coaching_staff_overrides.csv")
    return _apply_overrides(df, overrides)


def _load_overrides(path: Path) -> pl.DataFrame:
    if not path.exists():
        return pl.DataFrame(schema=SCHEMA)
    df = pl.read_csv(
        path, schema_overrides={"season": pl.Int64, "is_interim": pl.Boolean}, try_parse_dates=True
    )
    return df.select(
        [
            pl.col(c).cast(t) if c in df.columns else pl.lit(None, dtype=t).alias(c)
            for c, t in SCHEMA.items()
        ]
    )


def _apply_overrides(df: pl.DataFrame, overrides: pl.DataFrame) -> pl.DataFrame:
    """Override rows replace every parsed row for the same (season, team, role)."""
    if overrides.height == 0:
        return df
    key = ["season", "team", "role"]
    ov = overrides.filter(
        pl.col("season").is_in(df["season"].unique().to_list()) | (df.height == 0)
    )
    if ov.height == 0:
        return df
    keep = df.join(ov.select(key).unique(), on=key, how="anti")
    return pl.concat([keep, ov.with_columns(pl.lit("override").alias("flags"))], how="vertical")
