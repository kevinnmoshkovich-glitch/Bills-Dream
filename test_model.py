#!/usr/bin/env python3
"""Rules the nightly rebuild depends on. Run: python3 test_model.py"""
import sys, json, render

fails = []
def check(name, cond, detail=''):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{'' if cond else '  <- '+str(detail)}")
    if not cond: fails.append(name)

print("model_prob refuses a meaningless threshold")
check("zero threshold returns None", render.model_prob(0.5, 0, 0.4) is None)
check("negative threshold returns None", render.model_prob(10, -1, 0.4) is None)
check("zero line returns None", render.model_prob(0, 5, 0.4) is None)
check("None line returns None", render.model_prob(None, 5, 0.4) is None)

print("\ncalibration: 50% at the line, by construction")
for line in (0.5, 3.5, 61.5, 266.5):
    p = render.model_prob(line, line, 0.4)
    check(f"line {line} -> ~50%", abs(p*100 - 50) < 0.1, round(p*100, 2))

print("\nthe 17 September crash: a 0.5 line produces no zero rungs")
for line in (0.5, 1.5, 2.5, 4.5):
    picks = sorted(set(t for t in (round(line*m) for m in (0.6,0.8,1.0,1.25,1.5)) if t > 0))
    check(f"line {line} picks all positive", all(t > 0 for t in picks) and len(picks) > 0, picks)
    check(f"line {line} every rung priceable",
          all(render.model_prob(line, t, 0.4) is not None for t in picks))

print("\nplayer_props survives a snapshot full of small lines")
snap = {
    "games": {"1": {"week": 2, "completed": False,
                    "home": {"abbr": "BUF"}, "away": {"abbr": "DET"},
                    "date": "2026-09-18T00:15Z", "prob": {"home": 67.1, "away": 32.6, "asOf": "x"}}},
    "athletes": {"a1": {"name": "Test Player", "pos": "WR"}},
    "props": {"1": {"a1": {
        "rec":      {"line": 0.5},          # the killer
        "rec_yds":  {"line": 1.5},
        "rush_yds": {"line": 0.5, "ladder": []},
        "pass_yds": {"line": 266.5, "ladder": [200.0, 250.0, 300.0]},
    }}},
    "gamelogs": {}, "teams": {}, "divisions": {},
}
try:
    rows = render.player_props(snap)
    check("player_props did not raise", True)
    check("every rung has a real probability",
          all(r["p"] is not None for row in rows for r in row["rungs"]))
    check("no zero thresholds survived",
          all(r["t"] > 0 for row in rows for r in row["rungs"]))
    check("stats with nothing sensible are dropped, not left empty",
          all(len(row["rungs"]) > 0 for row in rows))
    print(f"        ({len(rows)} rows built from 4 stats)")
except Exception as e:
    check("player_props did not raise", False, f"{type(e).__name__}: {e}")

print("\nwith_support tolerates a player with no game log")
try:
    rows = render.with_support(snap, render.player_props(snap))
    check("no crash on missing gamelog", all(r.get("games") == 0 for r in rows))
    check("shortlist skips players with no production",
          render.shortlist(snap, rows) == [])
except Exception as e:
    check("with_support did not raise", False, f"{type(e).__name__}: {e}")

print("\nplayoff race: the played-out seasons")
import os, playoffs
_snap = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "snapshots", "latest.json")))
a = playoffs.simulate(_snap, runs=300); b = playoffs.simulate(_snap, runs=300)
check("same snapshot draws the same numbers", a["made"] == b["made"] and a["seeds"] == b["seeds"])
lg = a["lg"]
for conf in ("AFC", "NFC"):
    ids = [i for i in range(lg.n) if lg.conf[i] == conf]
    check(f"{conf}: exactly seven clubs go through in every season", sum(a["made"][i] for i in ids) == 7 * 300)
    check(f"{conf}: exactly four division winners in every season", sum(a["div"][i] for i in ids) == 4 * 300)
    check(f"{conf}: one top seed in every season", sum(a["bye"][i] for i in ids) == 300)
check("a division winner always makes the playoffs", all(a["div"][i] <= a["made"][i] for i in range(lg.n)))

print("\nplayoff race: tiebreakers and what counts as official")
def _mini(results, left=()):
    """Two divisions of two, one conference. results: (home, away, home score, away score)."""
    teams = {ab: {"name": ab, "conf": "NFC", "div": d} for ab, d in
             (("AAA", "East"), ("BBB", "East"), ("CCC", "West"), ("DDD", "West"))}
    games = {}
    for n, (h, aw, hs, as_) in enumerate(results):
        games[f"d{n}"] = {"week": 1, "date": f"2026-09-{10+n:02d}T17:00Z", "completed": True,
                          "home": {"abbr": h, "score": hs}, "away": {"abbr": aw, "score": as_}}
    for n, (h, aw) in enumerate(left):
        games[f"l{n}"] = {"week": 9, "date": f"2026-12-{10+n:02d}T17:00Z", "completed": False,
                          "home": {"abbr": h}, "away": {"abbr": aw}, "prob": {"home": 50, "away": 50}}
    return {"teams": teams, "games": games, "divisions": {}, "builtAt": "2026-11-24"}
m = playoffs.League(_mini([("AAA", "BBB", 20, 10), ("BBB", "CCC", 20, 10), ("AAA", "DDD", 10, 20), ("CCC", "DDD", 20, 10)]))
order, winners = playoffs.current(m).seed("NFC")
check("level on record, the head-to-head winner takes the division", m.abbrs[order[0]] == "AAA" or "AAA" in [m.abbrs[i] for i in winners],
      [m.abbrs[i] for i in order])
check("AAA is ranked above BBB", [m.abbrs[i] for i in order].index("AAA") < [m.abbrs[i] for i in order].index("BBB"))
m2 = playoffs.League(_mini([("AAA", "BBB", 20, 10), ("AAA", "BBB", 20, 10), ("AAA", "CCC", 20, 10)], left=[("BBB", "CCC")]))
off, _ = playoffs.official({"divisions": {}}, m2)
check("a club that cannot be caught in its division is officially in", off.get(m2.ix["AAA"], ("",))[0] == "in", off)
check("nobody is called out while it can still get there", all(v[0] != "out" for v in off.values()), off)
off3, _ = playoffs.official({"divisions": {"x": [{"abbr": "BBB", "clinch": "e"}, {"abbr": "CCC", "clinch": "x"}]}}, m2)
check("the league's own letters are honoured", off3[m2.ix["BBB"]][0] == "out" and off3[m2.ix["CCC"]][0] == "in")
real_off, _ = playoffs.official(_snap, lg)
sim_all = playoffs.simulate(_snap, runs=2000)
check("no club marked officially out ever got in when the season was played out",
      all(sim_all["made"][i] == 0 for i, v in real_off.items() if v[0] == "out"))
check("no club marked officially in ever missed",
      all(sim_all["made"][i] == 2000 for i, v in real_off.items() if v[0] == "in"))

print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
