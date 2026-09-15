#!/usr/bin/env python3
"""
Rebuilds the site's pages from a snapshot produced by refresh.py.

schedule.html and league.html are generated whole.
index.html is built from index.template.html, whose data regions are marked:
    <!--RECORDS-->...<!--/RECORDS-->        hero record strip
    <!--NEXTGAMES-->...<!--/NEXTGAMES-->    next-game cards
    <!--DIVISIONS-->...<!--/DIVISIONS-->    the two home divisions
Everything between a marker pair is replaced. Anything outside them - the
written weekly brief above all - is left exactly as you wrote it.
"""

import os, re, json
from datetime import datetime
from zoneinfo import ZoneInfo

# Must be a real zone, not a fixed offset: the season crosses the DST boundary
# on 1 November, and a hardcoded -4 puts every winter kickoff an hour late.
NY = ZoneInfo("America/New_York")
TEAMS = {"NYG": ("Giants", "g", "NFC East"), "BUF": ("Bills", "b", "AFC East")}


def when(iso, time_valid=True):
    """Returns (day, time). Late-season kickoffs are not fixed until the league
    flexes them; ESPN flags those with timeValid false and parks them at
    midnight. Showing that midnight as a real kickoff would be wrong."""
    d = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(NY)
    if not time_valid:
        return d.strftime("%a %b %-d"), "time TBD"
    return d.strftime("%a %b %-d"), d.strftime("%-I:%M %p")


def ordinal(n):
    return f"{n}{'th' if 11 <= n % 100 <= 13 else {1:'st',2:'nd',3:'rd'}.get(n % 10, 'th')}"


# ------------------------------------------------------------- fragments
def records(snap):
    out = []
    for ab, (name, cls, div) in TEAMS.items():
        games = snap["teams"][ab]["games"]
        done = [g for g in games if g["completed"]]
        w = sum(1 for g in done if int(g["myScore"]) > int(g["oppScore"]))
        l = len(done) - w
        rank = next((r["divRank"] for r in snap["divisions"].get(div, [])
                     if r["abbr"] == ab), None)
        last = done[-1] if done else None
        tail = ""
        if last:
            tail = (f" · {last['myScore']}–{last['oppScore']} "
                    f"{'vs' if last['home'] else 'at'} {last['opp']}")
        place = f"{ordinal(rank)} in {div}" if rank else div
        out.append(f"<div>{name.upper()}<b>{w}–{l}</b>{place}{tail}</div>")
    return "".join(out)


def next_games(snap):
    out = []
    for ab, (name, cls, _) in TEAMS.items():
        g = next((x for x in snap["teams"][ab]["games"] if not x["completed"]), None)
        if not g:
            out.append(f'<div class="ng {cls}"><div class="ngl">{name}</div>'
                       f'<div class="ngo">Season complete</div></div>')
            continue
        day, tm = when(g["date"], g.get("timeValid", True))
        p = g.get("winProb")
        prob = (f'<div class="ngp"><b>{p}%</b><span>win probability</span></div>'
                if p else '<div class="ngp"><b>—</b><span>no figure published</span></div>')
        out.append(f'''<div class="ng {cls}"><div class="ngl">{name} · next</div>
      <div class="ngo">{'vs' if g['home'] else 'at'} {g['opp']}</div>
      <div class="ngd">Week {g['week']} · {day} · {tm}</div>
      {prob}</div>''')
    return "".join(out)


def division_rows(rows, conf, highlight=True):
    out = ""
    for r in rows:
        tag = ""
        if highlight and r["abbr"] in TEAMS:
            tag = " me " + TEAMS[r["abbr"]][1]
        rec = f'{r["w"]}–{r["l"]}' + (f'–{r["t"]}' if r.get("t") else "")
        out += (f'<div class="dr{tag}"><span class="pos">{r["divRank"]}</span>'
                f'<span class="dn">{r["name"]}</span>'
                f'<span class="wl">{rec}</span></div>')
    return out


def home_divisions(snap):
    cols = []
    for ab, (name, cls, div) in TEAMS.items():
        rows = snap["divisions"].get(div, [])
        conf = div.split()[0]
        note = ""
        me = next((r for r in rows if r["abbr"] == ab), None)
        if me:
            tied = [r for r in rows if r["w"] == me["w"] and r["l"] == me["l"] and r["abbr"] != ab]
            if tied and me["divRank"] == 1:
                note = f"{name} lead on the tiebreaker — level on record with " + \
                       ", ".join(r["name"].split()[-1] for r in tied) + "."
            elif tied:
                ahead = [r for r in rows if r["divRank"] < me["divRank"]]
                note = f"{name} sit {ordinal(me['divRank'])} at {me['w']}–{me['l']}, behind " + \
                       ", ".join(r["name"].split()[-1] for r in ahead) + " on the tiebreaker."
            else:
                note = f"{name} sit {ordinal(me['divRank'])} in the division at {me['w']}–{me['l']}."
        cols.append(f'<div class="dcol {cls}"><div class="wh">{div}</div>'
                    f'{division_rows(rows, conf)}<div class="dnote">{note}</div></div>')
    return "".join(cols)


def schedule_column(snap, ab):
    name, cls, _ = TEAMS[ab]
    t = snap["teams"][ab]
    bye = t.get("bye")
    rows = []
    for g in t["games"]:
        if bye and g["week"] == bye + 1:
            rows.append(f'<div class="sg bye"><span class="wk">{bye}</span>'
                        f'<span class="opp">Bye week</span></div>')
        day, tm = when(g["date"], g.get("timeValid", True))
        loc = "vs" if g["home"] else "@"
        if g["completed"]:
            won = int(g["myScore"]) > int(g["oppScore"])
            rows.append(f'''<div class="sg done"><span class="wk">{g['week']}</span>
              <span class="opp"><i>{loc}</i>{g['opp']}</span>
              <span class="res {'w' if won else 'l'}">{'W' if won else 'L'} {g['myScore']}–{g['oppScore']}</span>
              <span class="pr final">final</span></div>''')
        else:
            p = g.get("winProb")
            cell = (f'<span class="pv">{p}%</span>'
                    f'<span class="pbar"><i style="width:{p}%"></i></span>') if p \
                else '<span class="pv na">—</span>'
            rows.append(f'''<div class="sg"><span class="wk">{g['week']}</span>
              <span class="opp"><i>{loc}</i>{g['opp']}</span>
              <span class="when">{day} · {tm}</span>
              <span class="pr">{cell}</span></div>''')
    return (f'<div class="scol {cls}"><div class="sh">{name} · full season</div>'
            f'<div class="skey"><span>wk</span><span>opponent</span>'
            f'<span>kickoff</span><span>win prob</span></div>{"".join(rows)}</div>')


def all_divisions(snap):
    order = ["AFC East", "AFC North", "AFC South", "AFC West",
             "NFC East", "NFC North", "NFC South", "NFC West"]
    cols = []
    for div in order:
        rows = snap["divisions"].get(div, [])
        if not rows:
            continue
        cols.append(f'<div class="dcol"><div class="wh">{div}</div>'
                    f'{division_rows(rows, div.split()[0])}</div>')
    return "".join(cols)


# ------------------------------------------------------------- page build
def swap(html, marker, content):
    return re.sub(f"<!--{marker}-->.*?<!--/{marker}-->",
                  f"<!--{marker}-->{content}<!--/{marker}-->",
                  html, flags=re.S)


def build(snap, site_dir):
    stamp = datetime.fromisoformat(snap["builtAt"]).strftime("%-d %B %Y, %-I:%M %p")
    asof = next((g.get("probAsOf") for t in snap["teams"].values()
                 for g in t["games"] if g.get("probAsOf")), None)

    # index.html
    tpl_path = os.path.join(site_dir, "index.template.html")
    tpl = open(tpl_path, encoding="utf-8").read()
    out = swap(tpl, "RECORDS", records(snap))
    out = swap(out, "NEXTGAMES", next_games(snap))
    out = swap(out, "DIVISIONS", home_divisions(snap))
    out = swap(out, "STAMP", f"Updated {stamp}")
    open(os.path.join(site_dir, "index.html"), "w", encoding="utf-8").write(out)

    shell = open(os.path.join(site_dir, "page.template.html"), encoding="utf-8").read()

    sched_body = (
        '<p class="lede">Every remaining game carries a win probability published by '
        "ESPN's model, refreshed each morning. Completed games show the result instead. "
        "Nothing here is estimated by this site.</p>"
        f'<div class="scheds">{schedule_column(snap,"NYG")}{schedule_column(snap,"BUF")}</div>'
        f'<p class="lede" style="margin-top:18px">Probabilities as published '
        f'{asof or "—"}. Page rebuilt {stamp}.</p>')
    open(os.path.join(site_dir, "schedule.html"), "w", encoding="utf-8").write(
        shell.replace("<!--NAVON-->", "schedule.html")
             .replace("<!--TITLE-->", "Full season schedules")
             .replace("<!--H1-->", "Full season")
             .replace("<!--SUB-->", "Every game for both clubs, with published win "
                                    "probabilities for what hasn't been played.")
             .replace("<!--BODY-->", sched_body))

    league_body = (
        '<p class="lede">All thirty-two clubs, all eight divisions. Records this early '
        "swing the seeding wildly — the order starts meaning something around October.</p>"
        f'<div class="divs four">{all_divisions(snap)}</div>'
        f'<p class="lede" style="margin-top:18px">Rebuilt {stamp}.</p>')
    open(os.path.join(site_dir, "league.html"), "w", encoding="utf-8").write(
        shell.replace("<!--NAVON-->", "league.html")
             .replace("<!--TITLE-->", "Every division")
             .replace("<!--H1-->", "Every division")
             .replace("<!--SUB-->", "All thirty-two clubs.")
             .replace("<!--BODY-->", league_body))


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    snap = json.load(open(os.path.join(here, "snapshots", "latest.json")))
    build(snap, here)
    print("rebuilt from latest snapshot")
