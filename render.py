#!/usr/bin/env python3
"""
Rebuilds every page from a snapshot produced by refresh.py.

    index.html          Giants vs Bills - the headline view
    schedule.html       both featured clubs, full season
    league.html         all 32 clubs, all 8 divisions
    team/<abbr>.html    one page per club, all 32

index.html is built from index.template.html, whose data regions are marked
<!--NAME--> ... <!--/NAME-->. Everything outside those markers - the written
weekly brief above all - is left exactly as written. The other pages are
generated whole from page.template.html.
"""

import os, re, json
from datetime import datetime
from zoneinfo import ZoneInfo

# Must be a real zone, not a fixed offset: the season crosses the DST
# boundary on 1 November, and a hardcoded -4 puts every winter kickoff an
# hour late.
NY = ZoneInfo("America/New_York")

FEATURED = {"NYG": ("Giants", "g"), "BUF": ("Bills", "b")}
DIV_ORDER = ["AFC East", "AFC North", "AFC South", "AFC West",
             "NFC East", "NFC North", "NFC South", "NFC West"]

# (stat key, label, higher-is-better)
COMPARE = [
    ("totalPointsPerGame",    "Points per game",        True),
    ("netYardsPerGame",       "Total yards per game",   True),
    ("netPassingYardsPerGame","Passing yards per game", True),
    ("rushingYardsPerGame",   "Rushing yards per game", True),
    ("yardsPerRushAttempt",   "Yards per carry",        True),
    ("completionPct",         "Completion %",           True),
    ("thirdDownConvPct",      "Third down %",           True),
    ("firstDowns",            "First downs",            True),
    ("totalTakeaways",        "Takeaways",              True),
    ("totalPenaltyYards",     "Penalty yards",          False),
]

TEAM_PANELS = [
    ("Offence", [("totalPointsPerGame", "Points per game"),
                 ("netYardsPerGame", "Total yards per game"),
                 ("netPassingYardsPerGame", "Passing yards per game"),
                 ("rushingYardsPerGame", "Rushing yards per game"),
                 ("yardsPerRushAttempt", "Yards per carry"),
                 ("completionPct", "Completion %")]),
    ("Situational", [("thirdDownConvPct", "Third down %"),
                     ("fourthDownConvPct", "Fourth down %"),
                     ("firstDowns", "First downs"),
                     ("firstDownsRushing", "First downs rushing"),
                     ("firstDownsPassing", "First downs passing"),
                     ("totalPenaltyYards", "Penalty yards")]),
    ("Ball security and defence", [("totalTakeaways", "Takeaways"),
                                   ("turnOverDifferential", "Turnover differential"),
                                   ("interceptions", "Interceptions"),
                                   ("fumblesRecovered", "Fumbles recovered"),
                                   ("fumblesLost", "Fumbles lost")]),
]


# ------------------------------------------------------------- helpers
def when(iso, time_valid=True):
    """Late-season kickoffs are not fixed until the league flexes them. ESPN
    flags those timeValid false and parks them at midnight; showing that as a
    real kickoff would be wrong."""
    d = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(NY)
    if not time_valid:
        return d.strftime("%a %b %-d"), "time TBD"
    return d.strftime("%a %b %-d"), d.strftime("%-I:%M %p")


def ordinal(n):
    return f"{n}{'th' if 11 <= n % 100 <= 13 else {1:'st',2:'nd',3:'rd'}.get(n % 10,'th')}"


def num(v):
    if v is None:
        return "—"
    f = float(v)
    return str(int(f)) if f == int(f) else f"{f:.1f}"


def stat(snap, ab, key):
    return snap.get("teamStats", {}).get(ab, {}).get(key)


def rec(t):
    return f"{t['w']}–{t['l']}" + (f"–{t['t']}" if t.get("t") else "")


def team_href(ab):
    return f"/team/{ab.lower()}"


def swap(html, marker, content):
    return re.sub(f"<!--{marker}-->.*?<!--/{marker}-->",
                  f"<!--{marker}-->{content}<!--/{marker}-->", html, flags=re.S)


NAV = [("/", "Head to head"), ("/schedule", "Schedules"),
       ("/parlay", "Parlay"), ("/league", "Every division")]


def nav(current):
    """Cloudflare Pages strips .html and 308-redirects anything that keeps it,
    so link the extensionless paths and save every click a round trip."""
    return '<div class="nav">' + "".join(
        f'<a href="{h}"{" class=\"on\"" if h == current else ""}>{t}</a>'
        for h, t in NAV) + "</div>"


# ------------------------------------------------------------- index parts
def records(snap):
    out = []
    for ab, (name, _) in FEATURED.items():
        t = snap["teams"][ab]
        done = [g for g in t["games"] if g["completed"]]
        last = done[-1] if done else None
        tail = (f" · {last['myScore']}–{last['oppScore']} "
                f"{'vs' if last['home'] else 'at'} {last['opp']}") if last else ""
        out.append(f'<div>{name.upper()}<b>{rec(t)}</b>'
                   f'{ordinal(t["divRank"])} in {t["div"]}{tail}</div>')
    return "".join(out)


def next_games(snap):
    out = []
    for ab, (name, cls) in FEATURED.items():
        t = snap["teams"][ab]
        g = next((x for x in t["games"] if not x["completed"]), None)
        if not g:
            out.append(f'<div class="ng {cls}"><div class="ngl">{name}</div>'
                       f'<div class="ngo">Season complete</div></div>')
            continue
        day, tm = when(g["date"], g.get("timeValid", True))
        p = g.get("winProb")
        prob = (f'<div class="ngp"><b>{p}%</b><span>win probability</span></div>'
                if p else '<div class="ngp"><b>—</b><span>no figure published</span></div>')
        out.append(
            f'<div class="ng {cls}"><div class="ngl">{name} · next</div>'
            f'<div class="ngo">{"vs" if g["home"] else "at"} '
            f'<a href="{team_href(g["opp"])}">{g["opp"]}</a></div>'
            f'<div class="ngd">Week {g["week"]} · {day} · {tm}</div>{prob}</div>')
    return "".join(out)


def tally(snap):
    a, b = list(FEATURED)
    wins = {a: 0, b: 0}
    for key, _, higher in COMPARE:
        sa, sb = stat(snap, a, key), stat(snap, b, key)
        if not sa or not sb:
            continue
        va, vb = float(sa["value"]), float(sb["value"])
        if va == vb:
            continue
        winner = a if ((va > vb) == higher) else b
        wins[winner] += 1
    n = sum(wins.values())
    return (f'<div style="text-align:right"><div class="big" style="color:var(--g)">{wins[a]}</div>'
            f'<div class="lbl">Giants lead</div></div>'
            f'<div class="lbl" style="opacity:.5">of {n} categories</div>'
            f'<div style="text-align:left"><div class="big" style="color:var(--b)">{wins[b]}</div>'
            f'<div class="lbl">Bills lead</div></div>')


def compare_bars(snap):
    """Emits the markup the page's existing CSS expects: a .cb block per
    category, with .cbl carrying the two numbers and .cbr the two bars
    growing outward from the centre. The winning side gets the glow class
    (gw / bw) and its number gets .win."""
    a, b = list(FEATURED)
    rows = []
    for key, label, higher in COMPARE:
        sa, sb = stat(snap, a, key), stat(snap, b, key)
        if not sa or not sb:
            continue
        va, vb = float(sa["value"]), float(sb["value"])
        top = max(va, vb) or 1
        wa, wb = va / top * 100, vb / top * 100
        lead_a = va != vb and ((va > vb) == higher)
        lead_b = va != vb and ((vb > va) == higher)
        rows.append(
            '<div class="cb">'
            f'<div class="cbl"><span class="{"win" if lead_a else ""}">{num(va)}</span>'
            f'<b>{label}</b>'
            f'<span class="{"win" if lead_b else ""}">{num(vb)}</span></div>'
            f'<div class="cbr"><div class="lft">'
            f'<i style="width:{wa:.1f}%" class="{"gw" if lead_a else "g"}"></i></div>'
            f'<div class="rgt">'
            f'<i style="width:{wb:.1f}%" class="{"bw" if lead_b else "b"}"></i></div>'
            "</div></div>")
    return "".join(rows)



# ------------------------------------------------------------- prop model
# Every probability in this block is COMPUTED. The feed carries the line a
# sportsbook set but no price, so there is no market-implied probability to
# read off - it has to be modelled.
#
# Method: treat the over/under line as the median outcome, which is what a
# book's line approximates, then put a log-normal around it. Log-normal
# because yardage is non-negative and right-skewed: a receiver's ceiling is
# far above his median, his floor is zero.
#
#     median = line          ->  mu = ln(line)
#     spread from CV         ->  sigma = sqrt(ln(1 + CV^2))
#     P(X >= t)              =  1 - Phi((ln t - mu) / sigma)
#
# The CV per stat type is a typical NFL game-to-game figure, not this
# player's own variance - one game into a season there isn't enough history
# to measure it. That is the weakest assumption here and the page says so.
import math

STAT_CV = {"pass_yds": 0.30, "rush_yds": 0.50, "rec_yds": 0.60,
           "rec": 0.40, "pass_att": 0.20, "rush_att": 0.35}

# Stats that are a small COUNT rather than a total. A quarterback's passing
# touchdowns sit at 1 or 2, and a log-normal around a 1.5 line is the wrong
# shape for that - it is a continuous, right-skewed curve being asked about
# whole numbers. Poisson is the distribution for counts, and it needs no
# variance assumption at all: the mean fixes the spread. One less invented
# parameter.
COUNT_STATS = {"pass_td"}
STAT_LABEL = {"pass_yds": "Passing yards", "rush_yds": "Rushing yards",
              "rec_yds": "Receiving yards", "rec": "Receptions",
              "pass_att": "Passing attempts", "rush_att": "Rushing attempts",
              "pass_td": "Passing touchdowns"}


def norm_cdf(z):
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def poisson_at_least(k, lam):
    """P(X >= k) for a Poisson count. Sums the tail directly; k is tiny here."""
    if lam <= 0 or k <= 0:
        return None
    # P(X >= k) = 1 - P(X <= k-1)
    cum = 0.0
    term = math.exp(-lam)
    for i in range(0, int(k)):
        if i:
            term *= lam / i
        cum += term
    return max(0.001, min(0.999, 1 - cum))


def model_prob(line, threshold, cv, stat=None):
    """P(stat >= threshold) given the book's line as the middle.

    Counts go through Poisson, totals through a log-normal. Both return None
    for a threshold of zero, because "0 or more" is a certainty and not a
    prediction - and the caller must handle that rather than multiply it.
    """
    if not line or line <= 0 or threshold <= 0:
        return None
    if stat in COUNT_STATS:
        # A 1.5 line means the book sits between 1 and 2; the implied mean is
        # the line itself, which is the convention for an over/under on a count.
        return poisson_at_least(threshold, line)
    if not cv:
        return None
    sigma = math.sqrt(math.log(1 + cv * cv))
    mu = math.log(line)
    return max(0.001, min(0.999, 1 - norm_cdf((math.log(threshold) - mu) / sigma)))


def player_props(snap):
    """One row per player stat, with a few thresholds off the book's ladder."""
    out = []
    for eid, players in snap.get("props", {}).items():
        g = snap["games"].get(eid)
        if not g or not players:
            continue
        for aid, stats in players.items():
            a = snap.get("athletes", {}).get(aid)
            if not a:
                continue
            for key, v in stats.items():
                line = v.get("line")
                if not line:
                    continue
                cv = STAT_CV.get(key, 0.4)
                is_count = key in COUNT_STATS
                ladder = [t for t in v.get("ladder", []) if t > 0]
                # A handful of rungs spread either side of the line.
                #
                # The multipliers must be filtered to positive values. A line of
                # 0.5 — ordinary for receptions or touchdowns — gives
                # round(0.5 * 0.6) = 0, and a threshold of zero is meaningless:
                # "0 or more receptions" is certain, not a prediction. model_prob
                # rightly returns None for it, and multiplying that None by 100
                # is what took the whole rebuild down on 17 September.
                if ladder:
                    picks = sorted(set(
                        [min(ladder, key=lambda t: abs(t - line * m))
                         for m in (0.6, 0.8, 1.0, 1.25, 1.5)]))
                elif is_count:
                    # whole numbers either side of the line: 1.5 -> 1, 2, 3
                    lo = max(1, int(math.floor(line)))
                    picks = [lo, lo + 1, lo + 2]
                else:
                    picks = sorted(set(
                        t for t in (round(line * m) for m in (0.6, 0.8, 1.0, 1.25, 1.5))
                        if t > 0))

                # Belt and braces: a None from model_prob drops its rung rather
                # than crashing the page. One unusable threshold should never
                # cost the site a day and a half of updates.
                rungs = []
                for t in picks:
                    p = model_prob(line, t, cv, key)
                    if p is None:
                        continue
                    rungs.append({"t": t, "p": round(p * 100, 1)})
                if not rungs:
                    continue          # nothing sensible to offer on this stat

                out.append({
                    "eid": eid, "aid": aid, "name": a["name"], "pos": a["pos"],
                    "stat": key, "label": STAT_LABEL.get(key, key),
                    "line": line, "cv": cv,
                    "match": f"{g['away']['abbr']} at {g['home']['abbr']}",
                    "rungs": rungs,
                })
    out.sort(key=lambda r: (r["name"], r["label"]))
    return out


def current_week(snap):
    """Earliest week still holding unplayed games."""
    left = [g["week"] for g in snap["games"].values() if not g["completed"]]
    return min(left) if left else None


def parlay(snap):
    """An interactive combined-probability picker for the current week.

    This is the one section of the site that computes rather than reports.
    Multiplying the legs is correct arithmetic for independent events, and
    separate games in the same week are near enough independent - but the
    inputs are ESPN's published figures and the multiplication is ours, so
    the page says so plainly. No payouts, no odds, no implied returns:
    the point is the probability and how quickly it falls away.
    """
    wk = current_week(snap)
    if not wk:
        return "<p class='lede'>The regular season is over.</p>"

    games = sorted([g for g in snap["games"].values()
                    if g["week"] == wk and g.get("prob")],
                   key=lambda x: x["date"])
    if not games:
        return "<p class='lede'>No published probabilities for this week yet.</p>"

    rows = []
    for g in games:
        h, a = g["home"], g["away"]
        ph, pa = g["prob"]["home"], g["prob"]["away"]
        day, tm = when(g["date"], g.get("timeValid", True))
        pre_a = "NYG" if a["abbr"] == "NYG" else ("BUF" if a["abbr"] == "BUF" else "")
        pre_h = "NYG" if h["abbr"] == "NYG" else ("BUF" if h["abbr"] == "BUF" else "")
        sel_a = " on" if pre_a else ""
        sel_h = " on" if pre_h else ""
        rows.append(
            f'<div class="pg"><div class="pgd">{day} · {tm}</div>'
            f'<button class="leg{sel_a}" data-p="{pa}" data-t="{a["abbr"]}">'
            f'<span class="lt">{a["abbr"]}</span><span class="lp">{pa}%</span></button>'
            f'<span class="pat">at</span>'
            f'<button class="leg{sel_h}" data-p="{ph}" data-t="{h["abbr"]}">'
            f'<span class="lt">{h["abbr"]}</span><span class="lp">{ph}%</span></button>'
            "</div>")

    return (
        f'<div class="parlay">'
        f'<div class="pout"><div class="pbig" id="pOut">—</div>'
        f'<div class="plbl">chance all <span id="pN">0</span> hit</div>'
        f'<div class="pnote" id="pList">Pick a side in any game below.</div></div>'
        f'<div class="pgames"><div class="ngl">Week {wk} · tap a team to add or drop it</div>'
        f'{"".join(rows)}</div></div>'
        '<script>(function(){'
        'var legs=function(){return [].slice.call(document.querySelectorAll(".leg.on"))};'
        'function calc(){var L=legs();var p=1;var names=[];'
        'L.forEach(function(b){p*=parseFloat(b.dataset.p)/100;names.push(b.dataset.t)});'
        'var o=document.getElementById("pOut");'
        'document.getElementById("pN").textContent=L.length;'
        'if(!L.length){o.textContent="—";'
        'document.getElementById("pList").textContent="Pick a side in any game below.";return}'
        'var pct=p*100;'
        'o.textContent=pct>=10?pct.toFixed(1)+"%":(pct>=1?pct.toFixed(2)+"%":pct.toFixed(3)+"%");'
        'document.getElementById("pList").textContent=names.join(" + ");}'
        'document.querySelectorAll(".leg").forEach(function(b){'
        'b.addEventListener("click",function(){'
        'var sib=b.parentNode.querySelectorAll(".leg");'
        'if(b.classList.contains("on")){b.classList.remove("on")}'
        'else{sib.forEach(function(x){x.classList.remove("on")});b.classList.add("on")}'
        'calc()})});calc();})();</script>')



def with_support(snap, rows):
    """Attach what the player has actually produced to each modelled row.

    The probability column and the production column are independent of each
    other by construction: the first comes from the book's line, the second
    from games played. Where they disagree is the only place this page has
    anything to say that the line does not already say.
    """
    logs = snap.get("gamelogs", {})
    for r in rows:
        series = logs.get(r["aid"], {}).get(r["stat"]) or []
        if series:
            r["games"] = len(series)
            r["avg"] = round(sum(series) / len(series), 1)
            r["best"] = max(series)
            # how the player's average sits against the line, as a ratio
            r["edge"] = round((r["avg"] - r["line"]) / r["line"] * 100, 1) if r["line"] else None
            for x in r["rungs"]:
                x["cleared"] = sum(1 for v in series if v >= x["t"])
        else:
            r["games"] = 0
            r["avg"] = r["best"] = r["edge"] = None
    return rows


def shortlist(snap, rows, n=6):
    """The rungs worth a second look.

    Deliberately NOT 'highest probability'. The model puts the median at the
    book's line, so the highest probability is always the lowest threshold,
    for every player, always - sorting by it would just say 'take the
    smallest number in every row' and would carry no information.

    This ranks on the one thing the model does not already know: whether the
    player has actually been clearing that number. Score is the modelled
    probability weighted by how often he has cleared it, with a penalty while
    the sample is small, so early-season rows cannot dominate on one game.
    """
    scored = []
    for r in rows:
        if not r.get("games"):
            continue
        for x in r["rungs"]:
            hit_rate = x["cleared"] / r["games"]
            # shrink toward the modelled probability when games are few
            w = r["games"] / (r["games"] + 4.0)
            blended = (1 - w) * (x["p"] / 100) + w * hit_rate
            # only interesting if the player is actually clearing it
            if x["cleared"] == 0:
                continue
            scored.append({**r, "t": x["t"], "p": x["p"],
                           "cleared": x["cleared"], "hit": round(hit_rate * 100),
                           "score": round(blended * 100, 1)})
    scored.sort(key=lambda s: (-s["score"], -s["p"]))
    # at most one row per player so a single hot player cannot fill the list
    seen, out = set(), []
    for s in scored:
        if (s["aid"], s["stat"]) in seen:
            continue
        seen.add((s["aid"], s["stat"]))
        out.append(s)
        if len(out) >= n:
            break
    return out


def injury_for(snap, aid, name):
    """The player's listed status, if the league report carries one.

    NOT priced in — it cannot be. The book's line already reflects it and
    there is no way to separate the two. This exists so the page can SAY it,
    rather than quietly offering a receiver who is listed doubtful.
    """
    inj = snap.get("injuries") or {}
    return inj.get(str(aid)) or inj.get((name or "").strip().lower())


def best_per_game(snap, rows, per_game=1):
    """The pick worth a look in EACH game, rather than six across the week.

    Same ranking as the shortlist — production the model does not already
    know — but resolved per fixture, because that is how anyone actually
    uses this: they are looking at one game.

    A player carrying an injury status is never the suggestion. The model
    cannot price a hamstring, so the honest move is to step around it rather
    than recommend into it.
    """
    by_game = {}
    for r in rows:
        if not r.get("games"):
            continue
        if injury_for(snap, r.get("aid"), r.get("name")):
            continue                      # not our call to make on a doubtful player
        for x in r["rungs"]:
            if not x.get("cleared"):
                continue
            hit = x["cleared"] / r["games"]
            w = r["games"] / (r["games"] + 4.0)
            score = round(((1 - w) * (x["p"] / 100) + w * hit) * 100, 1)
            by_game.setdefault(r["eid"], []).append(
                {**r, "t": x["t"], "p": x["p"], "cleared": x["cleared"], "score": score})

    out = {}
    for eid, cands in by_game.items():
        cands.sort(key=lambda c: (-c["score"], -c["p"]))
        seen, keep = set(), []
        for c in cands:
            if c["aid"] in seen:
                continue
            seen.add(c["aid"])
            keep.append(c)
            if len(keep) >= per_game:
                break
        out[eid] = keep
    return out


def parlay_page(snap):
    """The parlay tab, grouped by game.

    Two kinds of number live here and they are kept visibly apart: the winner
    probability is ESPN's published figure, the player numbers are modelled
    from a sportsbook line. Grouping by game is what makes it usable during a
    slate - you look at the game that is on, not at a flat list of everyone.
    """
    wk = current_week(snap)
    if not wk:
        return "<p class='lede'>The regular season is over.</p>"

    games = sorted([g for g in snap["games"].values()
                    if g["week"] == wk and g.get("prob")], key=lambda x: x["date"])
    props = with_support(snap, player_props(snap))
    picks = shortlist(snap, props)
    best = best_per_game(snap, props)
    by_game = {}
    for p in props:
        by_game.setdefault(p["eid"], []).append(p)

    cards = []
    for g in games:
        h, a = g["home"], g["away"]
        ph, pa = g["prob"]["home"], g["prob"]["away"]
        day, tm = when(g["date"], g.get("timeValid", True))
        on_a = " on" if a["abbr"] in FEATURED else ""
        on_h = " on" if h["abbr"] in FEATURED else ""
        mine = " mine" if (a["abbr"] in FEATURED or h["abbr"] in FEATURED) else ""

        rows = by_game.get(g["id"], [])
        bypl = {}
        for p in rows:
            bypl.setdefault((p["name"], p["pos"]), []).append(p)

        pick = (best.get(g["id"]) or [None])[0]
        pick_html = ""
        if pick:
            pick_html = (
                f'<div class="gpick"><span class="gpl">Worth a look</span>'
                f'<span class="gpn">{pick["name"]} — {pick["t"]:.0f}+ {pick["label"].lower()}</span>'
                f'<span class="gpm">{pick["p"]}% modelled · cleared it '
                f'{pick["cleared"]}/{pick["games"]}</span>'
                f'<button class="leg gpb" data-p="{pick["p"]}" '
                f'data-t="{pick["name"].split()[-1]} {pick["t"]:.0f}+ {pick["label"].split()[-1]}">'
                f'<span class="lt">add</span><span class="lp">{pick["p"]}%</span></button></div>')

        players = ""
        for (name, pos), stats in bypl.items():
            blocks = ""
            for s in stats:
                rungs = "".join(
                    f'<button class="leg rung" data-p="{x["p"]}" '
                    f'data-t="{name.split()[-1]} {x["t"]:.0f}+ {s["label"].split()[-1]}">'
                    f'<span class="lt">{x["t"]:.0f}+</span>'
                    f'<span class="lp">{x["p"]}%</span></button>'
                    for x in s["rungs"])
                if s.get("games"):
                    d = s.get("edge") or 0
                    prod = (f'<span class="psact">{s["avg"]:g} avg over {s["games"]} '
                            f'game{"s" if s["games"] != 1 else ""} · '
                            f'<b class="{"up" if d > 0 else "dn"}">{abs(d):.0f}% '
                            f'{"above" if d > 0 else "below"} the line</b></span>')
                else:
                    prod = '<span class="psact">no games logged yet</span>'
                blocks += (f'<div class="pstat"><div class="psl">{s["label"]}'
                           f'<span class="psline">line {s["line"]:g}</span></div>'
                           f'<div class="psrow">{prod}</div>'
                           f'<div class="rungs">{rungs}</div></div>')
            inj = injury_for(snap, (stats[0] or {}).get("aid"), name)
            injchip = ""
            if inj:
                sev = "out" if inj["status"] in ("Out", "Injured Reserve", "Doubtful") else "q"
                injchip = (f'<span class="injc {sev}">{inj["status"]}'
                           + (f' · {inj["type"]}' if inj.get("type") else '') + '</span>')
            players += (f'<div class="pplayer{" hurt" if inj else ""}"><div class="ppn">{name}'
                        f'<span class="ppp">{injchip or pos}</span></div>{blocks}</div>')

        if not players:
            players = ('<div class="noprops">No player lines posted for this game yet. '
                       'Books put them up nearer kickoff.</div>')

        cards.append(
            f'<div class="gcard{mine}" data-game="{g["id"]}">'
            f'<div class="gch"><span class="gcd">{day} · {tm}</span>'
            f'<span class="gcp">{len(rows)} player line{"s" if len(rows) != 1 else ""}</span></div>'
            f'<div class="pg"><span class="pgw">Winner</span>'
            f'<button class="leg{on_a}" data-p="{pa}" data-t="{a["abbr"]} win">'
            f'<span class="lt">{a["abbr"]}</span><span class="lp">{pa}%</span></button>'
            f'<span class="pat">at</span>'
            f'<button class="leg{on_h}" data-p="{ph}" data-t="{h["abbr"]} win">'
            f'<span class="lt">{h["abbr"]}</span><span class="lp">{ph}%</span></button></div>'
            f'<div class="gcbody">{pick_html}{players}</div></div>')

    tabs = "".join(
        f'<button class="gtab{" mine" if (g["home"]["abbr"] in FEATURED or g["away"]["abbr"] in FEATURED) else ""}" '
        f'data-game="{g["id"]}">{g["away"]["abbr"]} at {g["home"]["abbr"]}'
        f'<span class="gtn">{len(by_game.get(g["id"], []))}</span></button>'
        for g in games)

    if picks:
        n_games = max((p["games"] for p in picks), default=0)
        slcards = "".join(
            f'<div class="sl"><div class="sln">{p["name"]}'
            f'<span class="slp">{p["pos"]}</span></div>'
            f'<div class="slt">{p["t"]:.0f}+ {p["label"].lower()}</div>'
            f'<div class="slm"><span><b>{p["p"]}%</b>modelled</span>'
            f'<span><b>{p["avg"]:g}</b>his average</span>'
            f'<span><b>{p["cleared"]}/{p["games"]}</b>cleared it</span></div>'
            f'<button class="leg slbtn" data-p="{p["p"]}" '
            f'data-t="{p["name"].split()[-1]} {p["t"]:.0f}+ {p["label"].split()[-1]}">'
            f'<span class="lt">add</span><span class="lp">{p["p"]}%</span></button></div>'
            for p in picks)
        short_html = (
            '<h2>Best chances <span class="thru">ranked on production, not on the '
            'model</span></h2>'
            '<div class="knows"><b>What this model does not know.</b> '
        'It has no injury data feeding the numbers, no matchup, no defence faced, no weather '
        'and no depth chart. The percentages are the sportsbook&rsquo;s own line spread across '
        'thresholds — the book has priced all of that in, but we are not computing any of it. '
        'Nor is a player&rsquo;s own history in the probability: the spread comes from a '
        'generic league figure per stat, not from him. His record only affects the ORDER of the '
        'suggestions below. Injury statuses are shown where the league lists one, and a player '
        'carrying one is never suggested.</div>'
        '<p class="lede"><b>Read this before trusting the order.</b> Ranking by the '
            'modelled probability alone would be circular - the model puts the median at '
            'the book&rsquo;s line, so the highest probability is always the lowest '
            'threshold, for every player, every time. That says nothing about who is '
            'likely to beat their number. These rank instead on the one thing the model '
            'does not know: whether the player has actually been clearing it. With '
            f'{n_games} game{"s" if n_games != 1 else ""} played that evidence is thin and '
            'the order still leans mostly on the model - it starts meaning something '
            'around week six. A shortlist to look at, not a verdict.</p>'
            f'<div class="slgrid">{slcards}</div>')
    else:
        short_html = ""

    missing = sum(1 for eid, pl in snap.get("props", {}).items() if not pl)
    total = len(snap.get("props", {})) or len(games)
    note = (f'<p class="lede">{missing} of this week&rsquo;s {total} games have no player '
            'lines yet. Books post them game by game as kickoff nears; they appear here '
            'on the next refresh after that.</p>') if missing else ""

    return (
        '<div class="parlay">'
        '<div class="pout"><div class="pbig" id="pOut">-</div>'
        '<div class="plbl">chance all <span id="pN">0</span> hit</div>'
        '<div class="pnote" id="pList">Pick anything below.</div>'
        '<button class="pclear" id="pClear">Clear all</button></div>'
        '<div class="pcol">'
        f'{short_html}'
        f'<h2>By game <span class="thru">week {wk}</span></h2>'
        '<p class="lede">Winner probabilities are ESPN&rsquo;s published figures. Player '
        'numbers are modelled from the sportsbook line. Pick a game to narrow the list.</p>'
        f'{note}'
        f'<div class="gtabs"><button class="gtab on" data-game="all">All games</button>{tabs}</div>'
        f'<div class="gcards">{"".join(cards)}</div>'
        '</div></div>'
        '<script>(function(){'
        'function calc(){var L=[].slice.call(document.querySelectorAll(".leg.on"));'
        'var p=1,names=[];L.forEach(function(b){p*=parseFloat(b.dataset.p)/100;'
        'names.push(b.dataset.t)});'
        'var o=document.getElementById("pOut");'
        'document.getElementById("pN").textContent=L.length;'
        'if(!L.length){o.textContent="-";'
        'document.getElementById("pList").textContent="Pick anything below.";return}'
        'var pct=p*100;'
        'o.textContent=pct>=10?pct.toFixed(1)+"%":(pct>=1?pct.toFixed(2)+"%":pct.toFixed(3)+"%");'
        'document.getElementById("pList").textContent=names.join(" + ");}'
        'document.querySelectorAll(".leg").forEach(function(b){'
        'b.addEventListener("click",function(){'
        'var box=b.closest(".pg")||b.closest(".pstat");'
        'if(b.classList.contains("on")){b.classList.remove("on")}'
        'else{if(box){box.querySelectorAll(".leg").forEach(function(x){'
        'x.classList.remove("on")})}b.classList.add("on")}calc()})});'
        'document.getElementById("pClear").addEventListener("click",function(){'
        'document.querySelectorAll(".leg.on").forEach(function(b){b.classList.remove("on")});'
        'calc()});'
        'document.querySelectorAll(".gtab").forEach(function(t){'
        't.addEventListener("click",function(){'
        'document.querySelectorAll(".gtab").forEach(function(x){x.classList.remove("on")});'
        't.classList.add("on");var g=t.dataset.game;'
        'document.querySelectorAll(".gcard").forEach(function(c){'
        'c.style.display=(g==="all"||c.dataset.game===g)?"":"none"})})});'
        'calc();})();</script>')


def home_divisions(snap):
    cols = []
    for ab, (name, cls) in FEATURED.items():
        t = snap["teams"][ab]
        rows = snap["divisions"].get(t["div"], [])
        tied = [r for r in rows if r["w"] == t["w"] and r["l"] == t["l"] and r["abbr"] != ab]
        if tied and t["divRank"] == 1:
            note = (f"{name} lead on the tiebreaker — level on record with "
                    + ", ".join(r["name"].split()[-1] for r in tied) + ".")
        elif tied:
            ahead = [r for r in rows if r["divRank"] < t["divRank"]]
            note = (f"{name} sit {ordinal(t['divRank'])} at {rec(t)}, behind "
                    + ", ".join(r["name"].split()[-1] for r in ahead) + " on the tiebreaker.")
        else:
            note = f"{name} sit {ordinal(t['divRank'])} in the division at {rec(t)}."
        cols.append(f'<div class="dcol {cls}"><div class="wh">{t["div"]}</div>'
                    f'{div_rows(rows)}<div class="dnote">{note}</div></div>')
    return "".join(cols)


def div_rows(rows, show_seed=False):
    out = ""
    for r in rows:
        tag = f' me {FEATURED[r["abbr"]][1]}' if r["abbr"] in FEATURED else ""
        seed = f'<span class="cr">#{r["confSeed"]}</span>' if show_seed else ""
        out += (f'<div class="dr{tag}"><span class="pos">{r["divRank"]}</span>'
                f'<span class="dn"><a href="{team_href(r["abbr"])}">{r["name"]}</a></span>'
                f'<span class="wl">{r["w"]}–{r["l"]}'
                + (f'–{r["t"]}' if r.get("t") else "") + f'</span>{seed}</div>')
    return out


# ------------------------------------------------------------- shared parts
def schedule_column(snap, ab, cls=None, heading=None):
    t = snap["teams"][ab]
    cls = cls or FEATURED.get(ab, ("", "n"))[1]
    rows = []
    for g in t["games"]:
        if t.get("bye") and g["week"] == t["bye"] + 1:
            rows.append(f'<div class="sg bye"><span class="wk">{t["bye"]}</span>'
                        f'<span class="opp">Bye week</span></div>')
        day, tm = when(g["date"], g.get("timeValid", True))
        loc = "vs" if g["home"] else "@"
        opp = f'<a href="{team_href(g["opp"])}">{g["opp"]}</a>'
        if g["completed"]:
            won = int(g["myScore"]) > int(g["oppScore"])
            rows.append(
                f'<div class="sg done"><span class="wk">{g["week"]}</span>'
                f'<span class="opp"><i>{loc}</i>{opp}</span>'
                f'<span class="res {"w" if won else "l"}">{"W" if won else "L"} '
                f'{g["myScore"]}–{g["oppScore"]}</span>'
                f'<span class="pr final">final</span></div>')
        else:
            p = g.get("winProb")
            cell = (f'<span class="pv">{p}%</span>'
                    f'<span class="pbar"><i style="width:{p}%"></i></span>') if p \
                else '<span class="pv na">—</span>'
            rows.append(
                f'<div class="sg"><span class="wk">{g["week"]}</span>'
                f'<span class="opp"><i>{loc}</i>{opp}</span>'
                f'<span class="when">{day} · {tm}</span>'
                f'<span class="pr">{cell}</span></div>')
    head = heading or f"{t['name']} · full season"
    return (f'<div class="scol {cls}"><div class="sh">{head}</div>'
            f'<div class="skey"><span>wk</span><span>opponent</span>'
            f'<span>kickoff</span><span>win prob</span></div>{"".join(rows)}</div>')


def stat_panels(snap, ab):
    out = []
    for title, keys in TEAM_PANELS:
        rows = ""
        for key, label in keys:
            s = stat(snap, ab, key)
            if not s:
                continue
            r = s.get("rank")
            cls = "good" if r and r <= 8 else ("bad" if r and r >= 25 else "")
            badge = f'<span class="rk {cls}">#{r}</span>' if r else ""
            rows += (f'<div class="str"><span class="stl">{label}</span>'
                     f'<span class="stv">{num(s["value"])}</span>{badge}</div>')
        if rows:
            out.append(f'<div class="spanel"><div class="sph">{title}</div>{rows}</div>')
    return "".join(out)


# ------------------------------------------------------------- page build
def build(snap, site_dir):
    # Date only, deliberately. With a time in it every run produced a different
    # file, so the workflow's "commit only if something changed" guard never
    # held and the repo took a commit every night regardless.
    stamp = datetime.fromisoformat(snap["builtAt"]).strftime("%-d %B %Y")
    asof = next((g["prob"]["asOf"] for g in snap["games"].values() if g.get("prob")), None)
    written = 0

    # ---- index
    tpl = open(os.path.join(site_dir, "index.template.html"), encoding="utf-8").read()
    out = swap(tpl, "NAV", nav("/"))
    out = swap(out, "RECORDS", records(snap))
    out = swap(out, "NEXTGAMES", next_games(snap))
    out = swap(out, "TALLY", tally(snap))
    out = swap(out, "COMPARE", compare_bars(snap))
    out = swap(out, "DIVISIONS", home_divisions(snap))
    out = swap(out, "STAMP", f"Updated {stamp}")
    open(os.path.join(site_dir, "index.html"), "w", encoding="utf-8").write(out)
    written += 1

    shell = open(os.path.join(site_dir, "page.template.html"), encoding="utf-8").read()

    def page(path, on, title, h1, sub, body):
        depth = path.count("/")
        s = swap(shell, "NAV", nav(on))
        s = (s.replace("<!--TITLE-->", title).replace("<!--H1-->", h1)
              .replace("<!--SUB-->", sub).replace("<!--BODY-->", body))
        full = os.path.join(site_dir, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        open(full, "w", encoding="utf-8").write(s)

    # ---- schedules (the two featured clubs)
    cols = "".join(schedule_column(snap, ab) for ab in FEATURED)
    page("schedule.html", "/schedule", "Full season schedules", "Full season",
         "Every game for both clubs, with published win probabilities for "
         "what hasn&rsquo;t been played.",
         '<p class="lede">Every remaining game carries a win probability published by '
         "ESPN&rsquo;s model, refreshed each morning. Completed games show the result "
         "instead. Nothing here is estimated by this site.</p>"
         f'<div class="scheds">{cols}</div>'
         f'<p class="lede" style="margin-top:18px">Probabilities as published '
         f'{asof or "—"}. Rebuilt {stamp}.</p>')
    written += 1

    # ---- parlay
    page("parlay.html", "/parlay", "Parlay probability", "Parlay probability",
         "Combine this week&rsquo;s outcomes and see what the odds of all of them "
         "actually are.", parlay_page(snap))
    written += 1

    # ---- league
    dcols = "".join(
        f'<div class="dcol"><div class="wh">{d}</div>'
        f'{div_rows(snap["divisions"][d], show_seed=True)}</div>'
        for d in DIV_ORDER if d in snap["divisions"])
    page("league.html", "/league", "Every division", "Every division",
         "All thirty-two clubs. Pick any of them for its own page.",
         '<p class="lede">All thirty-two clubs, all eight divisions. The number on the '
         "right is the conference seed. Records this early swing the seeding wildly — "
         "the order starts meaning something around October. Every club name opens its "
         "own page.</p>"
         f'<div class="divs four">{dcols}</div>'
         f'<p class="lede" style="margin-top:18px">Rebuilt {stamp}.</p>')
    written += 1

    # ---- one page per club
    for ab, t in sorted(snap["teams"].items()):
        nxt = next((g for g in t["games"] if not g["completed"]), None)
        if nxt:
            day, tm = when(nxt["date"], nxt.get("timeValid", True))
            p = nxt.get("winProb")
            nxt_html = (
                f'<div class="tnext"><div class="ngl">Next · week {nxt["week"]}</div>'
                f'<div class="ngo">{"vs" if nxt["home"] else "at"} '
                f'<a href="{team_href(nxt["opp"])}">{nxt["oppName"]}</a></div>'
                f'<div class="ngd">{day} · {tm}</div>'
                + (f'<div class="ngp"><b>{p}%</b><span>win probability</span></div>'
                   if p else "") + "</div>")
        else:
            nxt_html = ""

        done = [g for g in t["games"] if g["completed"]]
        pf_pa = (f'<div class="tmeta"><span><b>{t["pf"]}</b>points for</span>'
                 f'<span><b>{t["pa"]}</b>against</span>'
                 f'<span><b>{t["pd"] or "—"}</b>differential</span>'
                 f'<span><b>{t["streak"] or "—"}</b>streak</span>'
                 f'<span><b>{len(done)}</b>played</span></div>')

        body = (
            f'<div class="tgrid">{nxt_html}'
            f'<div class="tstand"><div class="ngl">Standing</div>'
            f'<div class="ngo">{ordinal(t["divRank"])} in {t["div"]}</div>'
            f'<div class="ngd">{t["conf"]} seed #{t["confSeed"]} · record {rec(t)}</div>'
            f'</div></div>'
            f'{pf_pa}'
            f'<h2>Season statistics <span class="thru">value · league rank</span></h2>'
            f'<p class="lede">Rank is out of 32. Green is top eight, red is bottom eight.</p>'
            f'<div class="spanels">{stat_panels(snap, ab)}</div>'
            f'<h2>Full season</h2>'
            f'<div class="scheds one">{schedule_column(snap, ab, "n", "Schedule")}</div>'
            f'<h2>{t["div"]}</h2>'
            f'<div class="divs one">'
            f'<div class="dcol">{div_rows(snap["divisions"][t["div"]], show_seed=True)}</div></div>'
            f'<p class="lede" style="margin-top:18px">Rebuilt {stamp}.</p>')

        page(f"team/{ab.lower()}.html", None, f"{t['name']} — 2026 season",
             t["name"], f"{rec(t)} · {ordinal(t['divRank'])} in {t['div']}", body)
        written += 1

    return written


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    snap = json.load(open(os.path.join(here, "snapshots", "latest.json")))
    print("rebuilt", build(snap, here), "pages")
