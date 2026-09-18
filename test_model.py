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

print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
