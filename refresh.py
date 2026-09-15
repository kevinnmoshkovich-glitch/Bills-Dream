#!/usr/bin/env python3
"""
Giants vs Bills statistics site - nightly refresh.

Re-pulls every figure from ESPN's public JSON feeds, writes a dated snapshot,
and rebuilds index.html / schedule.html / league.html from it.

Design rules:
  * If a fetch fails, the previous good snapshot is reused. The site never
    goes blank because a feed had a bad night.
  * Every snapshot is kept, so you can always see what the page said on a
    given day.
  * Low request volume: about 40 requests, once a night.
  * Only published figures are rendered. Nothing on the page is estimated
    by this script.

Cron (3:40am daily, after all games have settled):
    40 3 * * *  /usr/bin/python3 /var/www/gbstats/refresh.py >> /var/log/gbstats.log 2>&1
"""

import json, os, sys, subprocess, shutil
import concurrent.futures as cf
from datetime import datetime, timezone, timedelta

# ----------------------------------------------------------------- config
SITE_DIR  = os.path.dirname(os.path.abspath(__file__))
SNAP_DIR  = os.path.join(SITE_DIR, "snapshots")
LIVE_SNAP = os.path.join(SNAP_DIR, "latest.json")
SEASON    = 2026
TEAMS     = {"NYG": "Giants", "BUF": "Bills"}
NY        = timezone(timedelta(hours=-4))          # US Eastern
TIMEOUT   = 20

API  = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"
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


# ----------------------------------------------------------------- fetch
def fetch_schedule(abbr):
    d = get(f"{API}/teams/{abbr.lower()}/schedule")
    games = []
    for e in d.get("events", []):
        c = e["competitions"][0]
        me = next(x for x in c["competitors"] if x["team"]["abbreviation"] == abbr)
        op = next(x for x in c["competitors"] if x["team"]["abbreviation"] != abbr)
        st = c["status"]["type"]
        score = lambda x: x.get("score", {}).get("displayValue") if isinstance(x.get("score"), dict) else x.get("score")
        games.append({
            "week": e.get("week", {}).get("number"),
            "id": e["id"],
            "date": e["date"],
            "home": me.get("homeAway") == "home",
            "opp": op["team"]["abbreviation"],
            "oppName": op["team"].get("displayName"),
            "completed": bool(st.get("completed")),
            "timeValid": bool(c.get("timeValid", True)),
            "myScore": score(me),
            "oppScore": score(op),
            "venue": c.get("venue", {}).get("fullName"),
            "bcast": (c.get("broadcasts") or [{}])[0].get("media", {}).get("shortName") if c.get("broadcasts") else None,
        })
    return sorted(games, key=lambda g: g["week"] or 0)


def fetch_predictor(event_id):
    """ESPN's published FPI win probability for one game. Returns None if absent."""
    try:
        d = get(f"{CORE}/events/{event_id}/competitions/{event_id}/predictor")
        h = {s["name"]: s["value"] for s in d["homeTeam"]["statistics"]}
        a = {s["name"]: s["value"] for s in d["awayTeam"]["statistics"]}
        if "gameProjection" not in h:
            return None
        return {"home": round(h["gameProjection"], 1),
                "away": round(a["gameProjection"], 1),
                "quality": round(h.get("matchupQuality", 0), 1),
                "lastMod": d.get("lastModified")}
    except Exception as e:
        log(f"  predictor {event_id}: {e}")
        return None


def fetch_standings():
    """All 32 clubs grouped by division.

    Note the two rank fields are different things and are easy to confuse:
      * division rank  = the order ESPN returns the entries in, already
                         tiebroken. There is no field for it.
      * playoffSeed    = the club's seed within its conference, 1-16.
    The plain /standings endpoint returns an empty shell; level=3 is the one
    that carries the divisions.
    """
    d = get(f"https://site.api.espn.com/apis/v2/sports/football/nfl/standings"
            f"?season={SEASON}&level=3")
    divs = {}
    for conf in d.get("children", []):
        for div in conf.get("children", []):
            rows = []
            for i, entry in enumerate(div.get("standings", {}).get("entries", []), 1):
                s = {x["name"]: x for x in entry.get("stats", [])}
                num = lambda k: int(s.get(k, {}).get("value", 0) or 0)
                rows.append({
                    "name": entry["team"].get("displayName"),
                    "abbr": entry["team"].get("abbreviation"),
                    "w": num("wins"), "l": num("losses"), "t": num("ties"),
                    "divRank": i,
                    "confSeed": num("playoffSeed"),
                    "pd": s.get("pointDifferential", {}).get("displayValue", ""),
                })
            if rows:
                divs[div.get("name")] = rows
    return divs


def fetch_team_stats():
    d = get(f"{WEB}/statistics/byteam?region=us&lang=en&contentorigin=espn"
            f"&season={SEASON}&seasontype=2&limit=50")
    glossary = {}
    for cat in d.get("categories", []):
        for n, lbl in zip(cat.get("names", []), cat.get("displayNames", cat.get("labels", []))):
            glossary[n] = lbl
    out = {}
    for t in d.get("teams", []):
        ab = t.get("team", {}).get("abbreviation")
        if ab not in TEAMS:
            continue
        stats = {}
        for cat in t.get("categories", []):
            if str(cat.get("splitId")) != "0":       # splitId 0 = own stats
                continue
            for n, v, r in zip(cat.get("names", []), cat.get("values", []), cat.get("ranks", [])):
                stats[n] = {"label": glossary.get(n, n), "value": v, "rank": r}
        out[ab] = stats
    return out


def build_snapshot():
    snap = {"builtAt": datetime.now(NY).isoformat(), "season": SEASON, "teams": {}}

    for ab in TEAMS:
        log(f"schedule {ab}")
        snap["teams"][ab] = {"games": fetch_schedule(ab)}

    pending = [(ab, g["week"], g["id"])
               for ab, t in snap["teams"].items()
               for g in t["games"] if not g["completed"]]
    log(f"predictor for {len(pending)} unplayed games")
    with cf.ThreadPoolExecutor(6) as ex:
        results = list(ex.map(lambda j: (j[0], j[1], fetch_predictor(j[2])), pending))
    probs = {(ab, wk): p for ab, wk, p in results}

    for ab, t in snap["teams"].items():
        for g in t["games"]:
            p = probs.get((ab, g["week"]))
            if p:
                g["winProb"] = p["home"] if g["home"] else p["away"]
                g["oppProb"] = p["away"] if g["home"] else p["home"]
                g["quality"] = p["quality"]
                g["probAsOf"] = p["lastMod"]

    got = sum(1 for g in (snap["teams"][a]["games"] for a in TEAMS) for g in g if g.get("winProb"))
    log(f"  {got}/{len(pending)} probabilities returned")

    log("standings")
    snap["divisions"] = fetch_standings()
    log("team stats")
    snap["teamStats"] = fetch_team_stats()

    # bye weeks fall out of the schedule as the missing number
    for ab, t in snap["teams"].items():
        weeks = {g["week"] for g in t["games"]}
        t["bye"] = next((w for w in range(1, 19) if w not in weeks), None)

    return snap


def sanity(snap):
    """Refuse to publish an obviously broken pull."""
    problems = []
    for ab in TEAMS:
        g = snap["teams"].get(ab, {}).get("games", [])
        if len(g) < 16:
            problems.append(f"{ab} has only {len(g)} games")
    if len(snap.get("divisions", {})) < 8:
        problems.append(f"only {len(snap.get('divisions', {}))} divisions")
    if not snap.get("teamStats"):
        problems.append("no team stats")
    return problems


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
    json.dump(snap, open(dated, "w"), indent=1)
    shutil.copy(dated, LIVE_SNAP)
    log(f"snapshot saved: {dated}")

    import render                       # render.py sits beside this file
    render.build(snap, SITE_DIR)
    log("pages rebuilt: index.html, schedule.html, league.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
