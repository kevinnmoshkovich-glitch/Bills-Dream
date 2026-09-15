#!/usr/bin/env python3
"""
Giants vs Bills statistics site - nightly refresh.

Pulls the whole league from ESPN's public JSON feeds, writes a dated
snapshot, and rebuilds every page from it.

Cost of one run: roughly 280 requests, about 15 seconds.
  18  scoreboard requests   -> all 272 games, results and fixtures
   1  standings             -> all 32 records, division order, conference seed
   1  byteam statistics     -> all 32 clubs, 93 stats each, with league ranks
 ~256 predictor requests    -> published win probability per unplayed game

Design rules:
  * A failed fetch reuses the previous good snapshot. The site never goes
    blank because a feed had a bad night.
  * Every snapshot is kept, so you can see what the page said on any day.
  * Only published figures are rendered. Nothing is estimated here.

Schedule: see .github/workflows/refresh.yml (there is no server to cron).
"""

import json, os, sys, subprocess, shutil
import concurrent.futures as cf
from datetime import datetime
from zoneinfo import ZoneInfo

# ----------------------------------------------------------------- config
SITE_DIR  = os.path.dirname(os.path.abspath(__file__))
SNAP_DIR  = os.path.join(SITE_DIR, "snapshots")
LIVE_SNAP = os.path.join(SNAP_DIR, "latest.json")
SEASON    = 2026
FEATURED  = {"NYG": "Giants", "BUF": "Bills"}     # the two the front page is about
NY        = ZoneInfo("America/New_York")
TIMEOUT   = 20
WORKERS   = 8

API  = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"
V2   = "https://site.api.espn.com/apis/v2/sports/football/nfl"
WEB  = "https://site.web.api.espn.com/apis/common/v3/sports/football/nfl"
CORE = "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl"


def log(msg):
    print(f"[{datetime.now(NY):%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def get(url):
    """Fetch JSON with curl. urllib gets 403'd by these endpoints; curl does not."""
    r = subprocess.run(["curl", "-sS", "--max-time", str(TIMEOUT), url],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"curl failed ({r.returncode}): {r.stderr.strip()[:200]}")
    return json.loads(r.stdout)


def try_get(url):
    try:
        return get(url)
    except Exception:
        return None


# ----------------------------------------------------------------- fetch
def fetch_season_games():
    """Every game in the regular season, from 18 weekly scoreboard requests.

    Cheaper and more complete than 32 individual team schedules, and it
    carries results for the games already played.
    """
    def one_week(w):
        return w, try_get(f"{API}/scoreboard?seasontype=2&week={w}")

    games = {}
    with cf.ThreadPoolExecutor(WORKERS) as ex:
        for w, d in ex.map(one_week, range(1, 19)):
            if not d:
                continue
            for e in d.get("events", []):
                c = e["competitions"][0]
                st = c["status"]["type"]
                sides = {}
                for x in c["competitors"]:
                    sides[x.get("homeAway")] = {
                        "abbr": x["team"].get("abbreviation"),
                        "name": x["team"].get("displayName"),
                        "score": x.get("score"),
                    }
                if "home" not in sides or "away" not in sides:
                    continue
                games[e["id"]] = {
                    "id": e["id"], "week": w, "date": e["date"],
                    "timeValid": bool(c.get("timeValid", True)),
                    "completed": bool(st.get("completed")),
                    "state": st.get("state"),
                    "home": sides["home"], "away": sides["away"],
                    "venue": c.get("venue", {}).get("fullName"),
                    "bcast": ((c.get("broadcasts") or [{}])[0]
                              .get("media", {}).get("shortName")),
                }
    return games


def fetch_predictors(game_ids):
    """ESPN's published FPI win probability, one request per game."""
    def one(eid):
        d = try_get(f"{CORE}/events/{eid}/competitions/{eid}/predictor")
        if not d:
            return eid, None
        try:
            h = {s["name"]: s["value"] for s in d["homeTeam"]["statistics"]}
            a = {s["name"]: s["value"] for s in d["awayTeam"]["statistics"]}
            if "gameProjection" not in h:
                return eid, None
            return eid, {"home": round(h["gameProjection"], 1),
                         "away": round(a["gameProjection"], 1),
                         "quality": round(h.get("matchupQuality", 0), 1),
                         "asOf": d.get("lastModified")}
        except Exception:
            return eid, None

    with cf.ThreadPoolExecutor(WORKERS) as ex:
        return {eid: p for eid, p in ex.map(one, game_ids) if p}


def fetch_standings():
    """All 32 clubs grouped by division.

    The two rank fields are different things and easy to confuse:
      * division rank = the order ESPN returns entries in, already tiebroken.
                        There is no field for it.
      * playoffSeed   = seed within the conference, 1-16.
    The plain /standings endpoint returns an empty shell; level=3 carries
    the divisions.
    """
    d = get(f"{V2}/standings?season={SEASON}&level=3")
    divs, conf_of = {}, {}
    for conf in d.get("children", []):
        cname = conf.get("abbreviation") or conf.get("name", "")[:3]
        for div in conf.get("children", []):
            rows = []
            for i, entry in enumerate(div.get("standings", {}).get("entries", []), 1):
                s = {x["name"]: x for x in entry.get("stats", [])}
                num = lambda k: int(s.get(k, {}).get("value", 0) or 0)
                ab = entry["team"].get("abbreviation")
                rows.append({
                    "name": entry["team"].get("displayName"),
                    "abbr": ab,
                    "w": num("wins"), "l": num("losses"), "t": num("ties"),
                    "divRank": i,
                    "confSeed": num("playoffSeed"),
                    "pf": num("pointsFor"), "pa": num("pointsAgainst"),
                    "pd": s.get("pointDifferential", {}).get("displayValue", ""),
                    "streak": s.get("streak", {}).get("displayValue", ""),
                })
                conf_of[ab] = cname
            if rows:
                divs[div.get("name")] = rows
    return divs, conf_of


def fetch_team_stats():
    """Season stats with league ranks for every club, in one request.

    The shape is easy to get wrong. Each team's category carries values,
    totals and ranks but NO stat names - the names live in a top-level
    glossary, matched by category name and position. Zipping against
    cat["names"] silently yields nothing, which is what this used to do.
    """
    d = get(f"{WEB}/statistics/byteam?region=us&lang=en&contentorigin=espn"
            f"&season={SEASON}&seasontype=2&limit=50")

    glossary = {c.get("name"): {"names": c.get("names", []),
                                "labels": c.get("displayNames") or c.get("labels", [])}
                for c in d.get("categories", [])}

    out = {}
    for t in d.get("teams", []):
        ab = t.get("team", {}).get("abbreviation")
        if not ab:
            continue
        stats = {}
        for cat in t.get("categories", []):
            if str(cat.get("splitId")) != "0":          # 0 = own, else opponent
                continue
            g = glossary.get(cat.get("name"), {})
            names, labels = g.get("names", []), g.get("labels", [])
            vals, totals, ranks = (cat.get("values", []), cat.get("totals", []),
                                   cat.get("ranks", []))
            for i, n in enumerate(names):
                if i >= len(vals):
                    break
                stats[n] = {
                    "label": labels[i] if i < len(labels) else n,
                    "cat": cat.get("name"),
                    "value": vals[i],
                    "total": totals[i] if i < len(totals) else None,
                    "rank": int(ranks[i]) if i < len(ranks) and str(ranks[i]).isdigit() else None,
                }
        out[ab] = stats
    return out


# ----------------------------------------------------------------- assemble
def build_snapshot():
    snap = {"builtAt": datetime.now(NY).isoformat(), "season": SEASON}

    log("season games (18 scoreboard requests)")
    games = fetch_season_games()
    played = sum(1 for g in games.values() if g["completed"])
    log(f"  {len(games)} games, {played} played")

    unplayed = [gid for gid, g in games.items() if not g["completed"]]
    log(f"win probabilities for {len(unplayed)} unplayed games")
    probs = fetch_predictors(unplayed)
    log(f"  {len(probs)}/{len(unplayed)} returned")
    for gid, p in probs.items():
        games[gid]["prob"] = p
    snap["games"] = games

    log("standings")
    snap["divisions"], snap["conf"] = fetch_standings()

    log("team statistics")
    snap["teamStats"] = fetch_team_stats()

    # per-team index: the games each club plays, in week order, plus its bye
    teams = {}
    for div, rows in snap["divisions"].items():
        for r in rows:
            teams[r["abbr"]] = {"abbr": r["abbr"], "name": r["name"], "div": div,
                                "conf": snap["conf"].get(r["abbr"], ""),
                                "w": r["w"], "l": r["l"], "t": r["t"],
                                "divRank": r["divRank"], "confSeed": r["confSeed"],
                                "pf": r["pf"], "pa": r["pa"], "pd": r["pd"],
                                "streak": r["streak"], "games": []}
    for g in sorted(games.values(), key=lambda x: x["week"]):
        for side, other in (("home", "away"), ("away", "home")):
            ab = g[side]["abbr"]
            if ab not in teams:
                continue
            e = {"week": g["week"], "id": g["id"], "date": g["date"],
                 "timeValid": g["timeValid"], "home": side == "home",
                 "opp": g[other]["abbr"], "oppName": g[other]["name"],
                 "completed": g["completed"], "bcast": g.get("bcast")}
            if g["completed"]:
                e["myScore"], e["oppScore"] = g[side]["score"], g[other]["score"]
            if g.get("prob"):
                e["winProb"] = g["prob"]["home"] if side == "home" else g["prob"]["away"]
                e["oppProb"] = g["prob"]["away"] if side == "home" else g["prob"]["home"]
                e["probAsOf"] = g["prob"]["asOf"]
            teams[ab]["games"].append(e)
    for t in teams.values():
        weeks = {g["week"] for g in t["games"]}
        t["bye"] = next((w for w in range(1, 19) if w not in weeks), None)
    snap["teams"] = teams
    snap["featured"] = list(FEATURED)
    return snap


def sanity(snap):
    """Refuse to publish an obviously broken pull."""
    p = []
    if len(snap.get("games", {})) < 250:
        p.append(f"only {len(snap.get('games', {}))} games")
    if len(snap.get("divisions", {})) < 8:
        p.append(f"only {len(snap.get('divisions', {}))} divisions")
    if len(snap.get("teams", {})) < 32:
        p.append(f"only {len(snap.get('teams', {}))} teams")
    # an empty dict per team used to slip through a mere truthiness check
    ts = snap.get("teamStats", {})
    thin = [a for a, s in ts.items() if len(s) < 20]
    if len(ts) < 32:
        p.append(f"team stats for only {len(ts)} clubs")
    elif thin:
        p.append(f"team stats look empty for {len(thin)} clubs ({', '.join(thin[:4])})")
    for ab in FEATURED:
        if len(snap.get("teams", {}).get(ab, {}).get("games", [])) < 16:
            p.append(f"{ab} has under 16 games")
    return p


# ----------------------------------------------------------------- main
def main():
    os.makedirs(SNAP_DIR, exist_ok=True)
    try:
        snap = build_snapshot()
    except Exception as e:
        log(f"FETCH FAILED: {e}")
        if os.path.exists(LIVE_SNAP):
            log("keeping yesterday's pages. Site stays up.")
            return 0
        log("no previous snapshot to fall back on.")
        return 1

    problems = sanity(snap)
    if problems:
        log("REFUSING TO PUBLISH: " + "; ".join(problems))
        if os.path.exists(LIVE_SNAP):
            log("keeping yesterday's pages.")
            return 0
        return 1

    stamp = datetime.now(NY).strftime("%Y-%m-%d")
    dated = os.path.join(SNAP_DIR, f"{stamp}.json")
    json.dump(snap, open(dated, "w"))
    shutil.copy(dated, LIVE_SNAP)
    log(f"snapshot saved: {dated} ({os.path.getsize(dated)//1024} KB)")

    import render
    n = render.build(snap, SITE_DIR)
    log(f"rebuilt {n} pages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
