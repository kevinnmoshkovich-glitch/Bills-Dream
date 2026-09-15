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


NAV = [("/", "Head to head"), ("/schedule", "Schedules"), ("/league", "Every division")]


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
    stamp = datetime.fromisoformat(snap["builtAt"]).strftime("%-d %B %Y, %-I:%M %p")
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
    out = swap(out, "PARLAY", parlay(snap))
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
