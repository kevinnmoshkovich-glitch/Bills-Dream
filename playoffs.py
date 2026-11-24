#!/usr/bin/env python3
"""The playoff race: who is in, who is alive, who is out, and what the Giants need.

Built from the same nightly snapshot as every other page. Nothing is fetched here.

HOW THE ODDS ARE MADE
  Every game still to be played carries a published win probability (ESPN's model,
  already in the snapshot). The rest of the season is played out RUNS times with
  those probabilities, the league's seeding rules are applied to each finished
  season, and the share of seasons a club makes the field is its playoff chance.
  The random seed is the snapshot's date, so the same snapshot always draws the
  same page (the nightly job commits only when something changed).

WHAT IS SIMPLIFIED, said on the page too
  * No simulated ties (about 1 game in 300 ends in one).
  * Tiebreakers run in the league's order - head to head, division record (inside a
    division), conference record, strength of victory, strength of schedule - but
    the "common games" step is skipped, and anything still level after that goes to
    points difference so far.
  * A probability does not move inside a run: a club that wins in Week 13 is not
    treated as stronger in Week 14.

"Officially in" and "officially out" are never guessed from the runs. They come
only from the letters the league publishes (carried in the snapshot as `clinch`).
"""
import random
from collections import defaultdict

RUNS = 20000
SPOTS = 7


def pct(w, l, t=0):
    g = w + l + t
    return (w + 0.5 * t) / g if g else 0.0


class League:
    """The season so far, as arrays indexed by club number."""

    def __init__(self, snap):
        teams = snap["teams"]
        self.abbrs = sorted(teams)
        self.ix = {a: i for i, a in enumerate(self.abbrs)}
        n = len(self.abbrs)
        self.n = n
        self.conf = [teams[a]["conf"] for a in self.abbrs]
        self.div = [teams[a]["div"] for a in self.abbrs]
        self.name = [teams[a]["name"] for a in self.abbrs]
        self.w = [0] * n; self.l = [0] * n; self.t = [0] * n
        self.dw = [0] * n; self.dl = [0] * n; self.dt = [0] * n
        self.cw = [0] * n; self.cl = [0] * n; self.ct = [0] * n
        self.pd = [0] * n
        self.h2h = defaultdict(float)      # (a, b) -> wins by a over b (a tie counts half each)
        self.h2hg = defaultdict(int)       # (a, b) -> games between them
        self.beaten = [[] for _ in range(n)]
        self.opps = [[] for _ in range(n)]  # every opponent on the schedule, played or not
        self.left = []                      # games still to play
        for gid, g in sorted(snap["games"].items(), key=lambda kv: (kv[1].get("date") or "", kv[0])):
            h, a = self.ix.get(g["home"]["abbr"]), self.ix.get(g["away"]["abbr"])
            if h is None or a is None:
                continue
            self.opps[h].append(a); self.opps[a].append(h)
            same_div = self.div[h] == self.div[a]
            same_conf = self.conf[h] == self.conf[a]
            if g.get("completed"):
                hs, as_ = int(g["home"].get("score") or 0), int(g["away"].get("score") or 0)
                self.pd[h] += hs - as_; self.pd[a] += as_ - hs
                self.h2hg[(h, a)] += 1; self.h2hg[(a, h)] += 1
                if hs == as_:
                    for x, y in ((h, a), (a, h)):
                        self.t[x] += 1; self.h2h[(x, y)] += 0.5
                        if same_div: self.dt[x] += 1
                        if same_conf: self.ct[x] += 1
                else:
                    win, lose = (h, a) if hs > as_ else (a, h)
                    self.w[win] += 1; self.l[lose] += 1
                    self.h2h[(win, lose)] += 1
                    self.beaten[win].append(lose)
                    if same_div: self.dw[win] += 1; self.dl[lose] += 1
                    if same_conf: self.cw[win] += 1; self.cl[lose] += 1
            else:
                p = g.get("prob") or {}
                ph, pa = float(p.get("home") or 50), float(p.get("away") or 50)
                self.left.append({"id": gid, "week": g.get("week"), "date": g.get("date"),
                                  "timeValid": g.get("timeValid", True), "h": h, "a": a,
                                  "p": ph / (ph + pa) if ph + pa else 0.5,
                                  "div": same_div, "conf": same_conf, "has_prob": bool(p)})
        self.divs = defaultdict(list)
        for i in range(n):
            self.divs[(self.conf[i], self.div[i])].append(i)


class Season:
    """One finished (or current) season: the records plus the tie-break lookups."""

    def __init__(self, lg, w, l, dw, dl, cw, cl, wins):
        self.lg = lg
        self.w, self.l, self.dw, self.dl, self.cw, self.cl = w, l, dw, dl, cw, cl
        self.wins = wins            # extra results: list of (winner, loser)
        self._x = None
        self._pct = [pct(w[i], l[i], lg.t[i]) for i in range(lg.n)]

    def _extra(self):
        if self._x is None:
            x = defaultdict(int); g = defaultdict(int); b = defaultdict(list)
            for win, lose in self.wins:
                x[(win, lose)] += 1; g[(win, lose)] += 1; g[(lose, win)] += 1; b[win].append(lose)
            self._x = (x, g, b)
        return self._x

    def p(self, i): return self._pct[i]
    def divp(self, i): return pct(self.dw[i], self.dl[i], self.lg.dt[i])
    def confp(self, i): return pct(self.cw[i], self.cl[i], self.lg.ct[i])

    def h2h(self, i, group):
        x, g, _ = self._extra(); lg = self.lg
        won = games = 0.0
        for j in group:
            if j == i: continue
            won += lg.h2h.get((i, j), 0) + x.get((i, j), 0)
            games += lg.h2hg.get((i, j), 0) + g.get((i, j), 0)
        return (won / games) if games else None

    def sov(self, i):
        _, _, b = self._extra()
        beaten = self.lg.beaten[i] + b.get(i, [])
        if not beaten: return 0.0
        return sum(self.w[j] + 0.5 * self.lg.t[j] for j in beaten) / max(1, sum(self.w[j] + self.l[j] + self.lg.t[j] for j in beaten))

    def sos(self, i):
        o = self.lg.opps[i]
        return sum(self.w[j] + 0.5 * self.lg.t[j] for j in o) / max(1, sum(self.w[j] + self.l[j] + self.lg.t[j] for j in o))

    # ---- the league's "pick the best of the tied clubs, then start over" procedure
    def _top(self, group, in_division):
        if len(group) == 1:
            return group[0]
        steps = []
        hh = {i: self.h2h(i, group) for i in group}
        if in_division:
            if all(v is not None for v in hh.values()): steps.append(hh)
            steps.append({i: self.divp(i) for i in group})
        else:
            # across divisions head-to-head only counts as a sweep: one club beat all the others, or lost to all
            if len(group) == 2:
                if all(v is not None for v in hh.values()): steps.append(hh)
            elif all(v is not None for v in hh.values()):
                best = [i for i in group if hh[i] == 1.0]
                worst = [i for i in group if hh[i] == 0.0]
                if len(best) == 1:
                    return best[0]
                if len(worst) == 1 and len(group) > 2:
                    return self._top([i for i in group if i != worst[0]], in_division)
        steps.append({i: self.confp(i) for i in group})
        steps.append(None)   # strength of victory, worked out only if it is reached
        steps.append(False)  # strength of schedule
        for s in steps:
            if s is None: s = {i: round(self.sov(i), 6) for i in group}
            elif s is False: s = {i: round(self.sos(i), 6) for i in group}
            m = max(s.values())
            keep = [i for i in group if s[i] == m]
            if len(keep) == 1:
                return keep[0]
            if len(keep) < len(group):
                return self._top(keep, in_division)
        return max(group, key=lambda i: (self.lg.pd[i], -i))

    def order(self, group, in_division):
        """Best first."""
        left = sorted(group, key=lambda i: -self._pct[i])
        out = []
        while left:
            m = self._pct[left[0]]
            tied = [i for i in left if abs(self._pct[i] - m) < 1e-9]
            if len(tied) == 1:
                pick = tied[0]
            elif in_division:
                pick = self._top(tied, True)
            else:
                # one club per division first: the best-placed of each division's tied clubs
                reps = {}
                for i in tied:
                    d = self.lg.div[i]
                    if d not in reps or self.divrank[i] < self.divrank[reps[d]]:
                        reps[d] = i
                pick = self._top(list(reps.values()), False)
            out.append(pick); left.remove(pick)
        return out

    def seed(self, conf):
        """The conference, best first: four division winners, then everyone else."""
        lg = self.lg
        self.divrank = {}
        winners, rest = [], []
        for (c, d), clubs in lg.divs.items():
            if c != conf: continue
            o = self.order(clubs, True)
            for r, i in enumerate(o): self.divrank[i] = r
            winners.append(o[0]); rest += o[1:]
        return self.order(winners, False) + self.order(rest, False), set(winners)


def current(lg):
    return Season(lg, lg.w, lg.l, lg.dw, lg.dl, lg.cw, lg.cl, [])


def simulate(snap, runs=RUNS, seed=None):
    lg = League(snap)
    rng = random.Random(seed if seed is not None else str(snap.get("builtAt", ""))[:10])
    n = lg.n
    made = [0] * n; divw = [0] * n; bye = [0] * n
    seeds = [[0] * 17 for _ in range(n)]
    wins_sum = [0] * n
    final_w = [defaultdict(int) for _ in range(n)]     # final wins -> runs
    made_at = [defaultdict(int) for _ in range(n)]     # final wins -> runs in which they made it
    # for every game left: runs the home side won, and for every club, playoff runs given each result
    g_home = [0] * len(lg.left)
    g_made = [[[0] * n, [0] * n] for _ in lg.left]      # [home won][club], [away won][club]
    left = lg.left
    for _ in range(runs):
        w = lg.w[:]; l = lg.l[:]; dw = lg.dw[:]; dl = lg.dl[:]; cw = lg.cw[:]; cl = lg.cl[:]
        res = []; outcome = []
        for g in left:
            home = rng.random() < g["p"]
            win, lose = (g["h"], g["a"]) if home else (g["a"], g["h"])
            w[win] += 1; l[lose] += 1
            if g["div"]: dw[win] += 1; dl[lose] += 1
            if g["conf"]: cw[win] += 1; cl[lose] += 1
            res.append((win, lose)); outcome.append(home)
        s = Season(lg, w, l, dw, dl, cw, cl, res)
        inn = [False] * n
        for conf in ("AFC", "NFC"):
            order, winners = s.seed(conf)
            for pos, i in enumerate(order):
                seeds[i][pos + 1] += 1
                if pos < SPOTS: made[i] += 1; inn[i] = True
            for i in winners: divw[i] += 1
            bye[order[0]] += 1
        for i in range(n):
            wins_sum[i] += w[i]
            final_w[i][w[i]] += 1
            if inn[i]: made_at[i][w[i]] += 1
        for k, home in enumerate(outcome):
            if home: g_home[k] += 1
            row = g_made[k][0 if home else 1]
            for i in range(n):
                if inn[i]: row[i] += 1
    return {"lg": lg, "runs": runs, "made": made, "div": divw, "bye": bye, "seeds": seeds,
            "avg_w": [x / runs for x in wins_sum], "final_w": final_w, "made_at": made_at,
            "g_home": g_home, "g_made": g_made}


def swing(sim, club):
    """For each game left: this club's playoff chance if the home side wins, and if the away side wins."""
    i = sim["lg"].ix[club]; out = []
    for k, g in enumerate(sim["lg"].left):
        hw = sim["g_home"][k]; aw = sim["runs"] - hw
        out.append({"game": g,
                    "if_home": sim["g_made"][k][0][i] / hw if hw else None,
                    "if_away": sim["g_made"][k][1][i] / aw if aw else None})
    return out


# =====================================================================
# What is official: the league's letters, plus plain arithmetic that cannot be wrong
# =====================================================================
LETTERS = {"x": "in", "y": "in", "z": "in", "*": "in", "e": "out"}
LETTER_WORDS = {"x": "clinched a playoff place", "y": "clinched the division",
                "z": "clinched a first-round bye", "*": "clinched the top seed",
                "e": "eliminated"}


def official(snap, lg):
    """club number -> ("in" | "out", why). Only what is certain."""
    out = {}
    for rows in snap.get("divisions", {}).values():
        for r in rows:
            c = str(r.get("clinch") or "").strip().lower()[:1]
            if c in LETTERS and r.get("abbr") in lg.ix:
                out[lg.ix[r["abbr"]]] = (LETTERS[c], LETTER_WORDS[c])
    left = [0] * lg.n
    for g in lg.left:
        left[g["h"]] += 1; left[g["a"]] += 1
    lo = [2 * lg.w[i] + lg.t[i] for i in range(lg.n)]          # in half-wins: lose out
    hi = [lo[i] + 2 * left[i] for i in range(lg.n)]            # win out
    for i in range(lg.n):
        if i in out:
            continue
        mates = [j for j in lg.divs[(lg.conf[i], lg.div[i])] if j != i]
        conf = [j for j in range(lg.n) if lg.conf[j] == lg.conf[i] and j != i]
        if all(hi[j] < lo[i] for j in mates):
            out[i] = ("in", "cannot be caught in the division"); continue
        if sum(1 for j in conf if hi[j] >= lo[i]) <= 2:
            out[i] = ("in", "cannot fall out of the top seven"); continue
        ahead = [j for j in conf if lo[j] > hi[i]]              # certain to finish above
        if any(j in mates for j in ahead) and len(ahead) - len({lg.div[j] for j in ahead}) >= 3:
            out[i] = ("out", "cannot reach the division or a wild card")
    return out, left


# =====================================================================
# The page
# =====================================================================
from datetime import datetime
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
SHORT = lambda name: name.split()[-1]


def _day(g):
    d = datetime.fromisoformat(g["date"].replace("Z", "+00:00")).astimezone(NY)
    return d.strftime("%a %b %-d")


def _pc(n, total, alive=True):
    """A share of the runs as words a fan reads. Never a flat 0 or 100 unless it is official."""
    if total <= 0: return "—"
    v = 100.0 * n / total
    if n == 0: return "&lt;0.1%" if alive else "0%"
    if n == total: return "&gt;99.9%"
    if v < 0.1: return "&lt;0.1%"
    if v > 99.9: return "&gt;99.9%"
    return f"{v:.0f}%" if 10 <= v <= 90 else f"{v:.1f}%"


def _rec(lg, i, w=None, l=None):
    w = lg.w[i] if w is None else w; l = lg.l[i] if l is None else l
    return f"{w}–{l}" + (f"–{lg.t[i]}" if lg.t[i] else "")


def _sub(w, l, t):
    return f"{w}–{l}" + (f"–{t}" if t else "")


def _a(lg, i, short=True):
    return f'<a href="/team/{lg.abbrs[i].lower()}">{SHORT(lg.name[i]) if short else lg.name[i]}</a>'


CSS = """<style>
.wrap:has(.po){max-width:1620px}
.po{--in:#39d98a;--pos:#5b8cff;--chase:#f2b84b;--long:#8d9bb8;--out:#ff6b5a}
.po a{color:inherit;text-decoration:none;border-bottom:1px solid rgba(255,255,255,.16)} .po a:hover{border-bottom-color:var(--g)}
.po h2{margin:34px 0 6px} .po h2:first-child{margin-top:0} .po .lede{margin:0 0 14px;max-width:86ch}
.po .card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:14px;min-width:0}
.po .card.g{border-top:3px solid var(--g)} .po .card.b{border-top:3px solid var(--b)}
.po .ch{font-family:'Barlow Condensed';font-size:19px;font-weight:800;letter-spacing:.04em;text-transform:uppercase;margin:0 0 2px}
.po .cs{font-size:11.5px;color:var(--mut);margin:0 0 10px;line-height:1.45}
.po .mono{font-family:'IBM Plex Mono'}
.po .tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-bottom:8px}
.po .tile{background:var(--panel);border:1px solid var(--line);border-top:3px solid var(--g);border-radius:14px;padding:14px 16px;min-width:0}
.po .tile.b{border-top-color:var(--b)}
.po .tile i{display:block;font-style:normal;font-size:10px;letter-spacing:.11em;text-transform:uppercase;color:var(--mut)}
.po .tile b{display:block;font-family:'Barlow Condensed';font-size:44px;font-weight:900;line-height:1.05;margin:2px 0}
.po .tile span{font-size:11.5px;color:var(--mut);line-height:1.4;display:block}
.po .cols{display:grid;gap:14px;align-items:start}
.po .c21{grid-template-columns:minmax(0,2.3fr) minmax(0,1fr)}
.po .c3{grid-template-columns:minmax(0,1.5fr) minmax(0,1fr) minmax(0,1fr)}
.po .c4{grid-template-columns:repeat(4,minmax(0,1fr))}
.po .auto{grid-template-columns:repeat(auto-fit,minmax(280px,1fr))}
.po .c22{grid-template-columns:minmax(0,1.45fr) minmax(0,1fr)}
.po .tw{overflow-x:auto}
.po table{border-collapse:collapse;width:100%;font-size:12.5px}
.po th{font-size:9.5px;letter-spacing:.1em;text-transform:uppercase;color:var(--mut);font-weight:700;text-align:right;padding:4px 6px 7px;white-space:nowrap}
.po th.l,.po td.l{text-align:left} .po td.l{white-space:normal}
.po td{padding:8px 6px;border-top:1px solid var(--line);text-align:right;white-space:nowrap;color:#c6d5f2}
.po td.n{font-family:'IBM Plex Mono';color:#fff}
.po td.club{font-weight:700;color:#fff}
.po tr.me.g td{background:rgba(91,140,255,.14)} .po tr.me.b td{background:rgba(255,107,90,.14)}
.po tr.grp td{border-top:0;padding:16px 6px 5px;text-align:left;font-size:10.5px;letter-spacing:.12em;text-transform:uppercase;font-weight:800}
.po tr.grp:first-child td{padding-top:2px}
.po tr.grp small{font-weight:600;letter-spacing:.02em;text-transform:none;color:var(--mut);font-size:11.5px;margin-left:8px}
.po .s-in{color:var(--in)} .po .s-pos{color:var(--pos)} .po .s-chase{color:var(--chase)} .po .s-long{color:var(--long)} .po .s-out{color:var(--out)}
.po .tag{display:inline-block;border:1px solid currentColor;border-radius:999px;padding:1px 8px;font-size:10px;letter-spacing:.06em;text-transform:uppercase;font-weight:700}
.po .seed{font-family:'Barlow Condensed';font-size:17px;font-weight:900;color:var(--mut);text-align:center;width:26px}
.po .bar{display:inline-block;vertical-align:middle;width:74px;height:6px;border-radius:3px;background:rgba(255,255,255,.09);overflow:hidden;margin-left:8px}
.po .bar i{display:block;height:100%;border-radius:3px;background:var(--mut)}
.po tr.me.g .bar i,.po .g .bar i{background:var(--g)} .po tr.me.b .bar i,.po .b .bar i{background:var(--b)}
.po .dv{font-size:9px;letter-spacing:.08em;text-transform:uppercase;color:var(--chase);border:1px solid currentColor;border-radius:4px;padding:0 4px;margin-left:6px}
.po .bk{display:grid;grid-template-columns:26px 1fr auto;gap:8px;align-items:center;padding:8px 4px;border-top:1px solid var(--line);font-size:13px}
.po .bk.me{background:rgba(91,140,255,.14);border-radius:8px;font-weight:700}
.po .bk.meb{background:rgba(255,107,90,.14);border-radius:8px;font-weight:700}
.po .bk .r{font-family:'IBM Plex Mono';color:#fff}
.po .bkh{font-size:10px;letter-spacing:.12em;text-transform:uppercase;color:var(--mut);font-weight:800;margin:14px 0 4px}
.po .mu{display:flex;justify-content:space-between;gap:8px;padding:8px 4px;border-top:1px solid var(--line);font-size:13px}
.po .mu b{font-family:'Barlow Condensed';font-size:15px;color:var(--mut);margin-right:6px}
.po .up{color:var(--in)} .po .dn{color:var(--out)}
.po .root{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:4px 12px;padding:10px 4px;border-top:1px solid var(--line);font-size:13px;align-items:center}
.po .root b{color:#fff} .po .root span{color:var(--mut);font-size:11.5px}
.po .root .n{font-family:'IBM Plex Mono';color:var(--in);font-size:14px}
.po .how{columns:2 380px;column-gap:28px;font-size:12.5px;color:var(--mut);line-height:1.6}
.po .how p{margin:0 0 10px;break-inside:avoid} .po .how b{color:#c6d5f2}
.po .jump{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0 0}
.po .jump a{border:1px solid var(--line);border-radius:999px;padding:7px 13px;font-size:11px;letter-spacing:.07em;text-transform:uppercase;color:var(--mut)}
.po .jump a:hover{color:#fff;border-color:var(--g)}
@media(max-width:1250px){.po .c4{grid-template-columns:repeat(2,minmax(0,1fr))}.po .c3{grid-template-columns:1fr 1fr}.po .c3>:first-child{grid-column:1/-1}}
@media(max-width:900px){.po .bar{width:44px}.po .c21,.po .c22,.po .c3,.po .c4{grid-template-columns:1fr}.po .tile b{font-size:36px}}
</style>"""


def _picture(snap, sim, conf, feat, cls):
    """The depth chart for one conference, and the bracket as it stands today."""
    lg = sim["lg"]; runs = sim["runs"]
    off, left = sim["official"], sim["left"]
    seed_now = {lg.ix[r["abbr"]]: r.get("confSeed") or 99
                for rows in snap["divisions"].values() for r in rows if r["abbr"] in lg.ix}
    clubs = sorted((i for i in range(lg.n) if lg.conf[i] == conf), key=lambda i: seed_now.get(i, 99))

    def group(i):
        o = off.get(i)
        if o: return o[0]
        if seed_now.get(i, 99) <= SPOTS: return "pos"
        return "long" if sim["made"][i] * 100 < runs else "chase"

    heads = {"in": ("Officially in", "the place is theirs whatever happens"),
             "pos": ("In a playoff spot today", "would play if the season ended now, nothing is safe yet"),
             "chase": ("In the hunt", "outside the seven today, with a real way in"),
             "long": ("Still alive, barely", "not eliminated, but in fewer than 1 of every 100 played-out seasons"),
             "out": ("Knocked out", "officially eliminated")}
    rows = ""
    for key in ("in", "pos", "chase", "long", "out"):
        members = [i for i in clubs if group(i) == key]
        title, note = heads[key]
        if not members:
            if key in ("in", "out"):
                rows += (f'<tr class="grp"><td colspan="10" class="s-{key}">{title}'
                         f'<small>nobody yet</small></td></tr>')
            continue
        rows += f'<tr class="grp"><td colspan="10" class="s-{key}">{title}<small>{note}</small></td></tr>'
        for i in members:
            alive = key != "out"
            me = f' class="me {cls}"' if lg.abbrs[i] == feat else ""
            p = 100.0 * sim["made"][i] / runs
            why = off.get(i)
            rows += (
                f'<tr{me}><td class="seed">{seed_now.get(i, "")}</td>'
                f'<td class="l club">{_a(lg, i, False)}'
                + (f' <span class="tag s-{key}">{why[1]}</span>' if why else "") + '</td>'
                f'<td class="n">{_rec(lg, i)}</td>'
                f'<td class="n">{_sub(lg.dw[i], lg.dl[i], lg.dt[i])}</td>'
                f'<td class="n">{_sub(lg.cw[i], lg.cl[i], lg.ct[i])}</td>'
                f'<td class="n">{_pc(sim["made"][i], runs, alive)}<span class="bar"><i style="width:{p:.1f}%"></i></span></td>'
                f'<td class="n">{_pc(sim["div"][i], runs, alive)}</td>'
                f'<td class="n">{_pc(sim["bye"][i], runs, alive)}</td>'
                f'<td class="n">{sim["avg_w"][i]:.1f}</td>'
                f'<td class="n">{left[i]}</td></tr>')
    table = ('<div class="tw"><table><tr><th>Seed</th><th class="l">Club</th><th>Record</th><th>Division</th>'
             '<th>Conference</th><th>Make the playoffs</th><th>Win division</th><th>Top seed</th>'
             f'<th>Projected wins</th><th>Games left</th></tr>{rows}</table></div>')

    by_seed = {seed_now[i]: i for i in clubs if i in seed_now}
    def line(s):
        i = by_seed.get(s)
        if i is None: return ""
        mine = lg.abbrs[i] == feat
        return (f'<div class="bk{(" me" if cls == "g" else " meb") if mine else ""}"><span class="seed">{s}</span>'
                f'<span>{_a(lg, i, False)}</span><span class="r">{_rec(lg, i)}</span></div>')
    def match(a, b):
        x, y = by_seed.get(a), by_seed.get(b)
        if x is None or y is None: return ""
        return (f'<div class="mu"><span><b>{b}</b>{_a(lg, y)} at <b>{a}</b>{_a(lg, x)}</span></div>')
    bracket = (
        f'<div class="card {cls}"><div class="ch">If the season ended today</div>'
        f'<div class="cs">{conf} seeds as the league lists them this morning.</div>'
        + "".join(line(s) for s in range(1, 8))
        + '<div class="bkh">First round</div>'
        + (f'<div class="mu"><span><b>1</b>{_a(lg, by_seed[1])} rest, with a bye</span></div>' if 1 in by_seed else "")
        + match(2, 7) + match(3, 6) + match(4, 5)
        + '<div class="bkh">First three out</div>' + "".join(line(s) for s in (8, 9, 10)) + '</div>')
    return table, bracket


def _schedule_card(snap, sim, ab, cls="", note=""):
    lg = sim["lg"]; i = lg.ix[ab]; runs = sim["runs"]; t = snap["teams"][ab]
    rows = ""
    for g in t["games"]:
        if g["completed"]: continue
        o = lg.ix.get(g["opp"])
        p = g.get("winProb")
        div = '<span class="dv">division</span>' if o is not None and lg.div[o] == lg.div[i] and lg.conf[o] == lg.conf[i] else ""
        rows += (f'<tr><td class="seed">{g["week"]}</td>'
                 f'<td class="l">{"vs" if g["home"] else "at"} {_a(lg, o) if o is not None else g["opp"]}'
                 f' <span class="mono" style="color:var(--mut);font-size:11px">{_rec(lg, o) if o is not None else ""}</span>{div}</td>'
                 f'<td class="n">{f"{p:.0f}%" if p else "—"}'
                 f'<span class="bar" style="width:46px"><i style="width:{p or 0}%"></i></span></td></tr>')
    return (f'<div class="card {cls}"><div class="ch">{_a(lg, i, False)}</div>'
            f'<div class="cs"><span class="mono" style="color:#fff">{_rec(lg, i)}</span> · '
            f'playoffs {_pc(sim["made"][i], runs)} · division {_pc(sim["div"][i], runs)} · '
            f'projected {sim["avg_w"][i]:.1f} wins{note}</div>'
            f'<div class="tw"><table><tr><th>Wk</th><th class="l">Opponent</th><th>Chance to win</th></tr>'
            f'{rows}</table></div></div>')


def run(snap, runs=RUNS):
    sim = simulate(snap, runs)
    sim["official"], sim["left"] = official(snap, sim["lg"])
    return sim


def body(snap, sim, stamp=""):
    lg = sim["lg"]; runs = sim["runs"]
    G, B = lg.ix["NYG"], lg.ix["BUF"]
    gt = snap["teams"]["NYG"]

    def tiles(i, cls, who):
        best = max(range(1, 17), key=lambda s: sim["seeds"][i][s])
        o = sim["official"].get(i)
        return (
            f'<div class="tile {cls}"><i>{who} · make the playoffs</i><b>{_pc(sim["made"][i], runs)}</b>'
            f'<span>{("Official: " + o[1]) if o else "of the played-out seasons"}</span></div>'
            f'<div class="tile {cls}"><i>{who} · win the {lg.div[i]}</i><b>{_pc(sim["div"][i], runs)}</b>'
            f'<span>{_rec(lg, i)} now, {sim["left"][i]} games left</span></div>'
            f'<div class="tile {cls}"><i>{who} · projected finish</i><b>{sim["avg_w"][i]:.1f} wins</b>'
            f'<span>most often the {best}{"st" if best == 1 else "nd" if best == 2 else "rd" if best == 3 else "th"} seed'
            f'{"" if best <= SPOTS else ", outside the seven"} · top seed {_pc(sim["bye"][i], runs)}</span></div>')

    # ---- the Giants' own games: chance to win, and what each result does
    sw = {s["game"]["id"]: s for s in swing(sim, "NYG")}
    grows = ""
    for g in gt["games"]:
        if g["completed"]: continue
        s = sw.get(str(g["id"])); o = lg.ix[g["opp"]]
        if not s: continue
        win, lose = (s["if_home"], s["if_away"]) if g["home"] else (s["if_away"], s["if_home"])
        p = g.get("winProb")
        div = '<span class="dv">division</span>' if lg.div[o] == lg.div[G] else ""
        f = lambda v: "—" if v is None else f"{100 * v:.0f}%"
        grows += (f'<tr><td class="seed">{g["week"]}</td>'
                  f'<td class="l club">{"vs" if g["home"] else "at"} {_a(lg, o, False)} '
                  f'<span class="mono" style="color:var(--mut);font-size:11px;font-weight:400">{_rec(lg, o)}</span>{div}</td>'
                  f'<td class="l">{_day(g)}</td>'
                  f'<td class="n">{f"{p:.0f}%" if p else "—"}<span class="bar"><i style="width:{p or 0}%"></i></span></td>'
                  f'<td class="n up">{f(win)}</td><td class="n dn">{f(lose)}</td></tr>')
    road = (f'<div class="card g"><div class="ch">The seven games left</div>'
            f'<div class="cs">Chance to win is the published number. The last two columns are the Giants&rsquo; playoff '
            f'chance in the seasons where they won that game, and where they lost it.</div>'
            f'<div class="tw"><table><tr><th>Wk</th><th class="l">Opponent</th><th class="l">Date</th>'
            f'<th>Chance to win</th><th>Playoffs if they win</th><th>If they lose</th></tr>{grows}</table></div></div>')

    # ---- by final record
    fr = ""
    for w in sorted(sim["final_w"][G], reverse=True):
        n = sim["final_w"][G][w]
        if n * 200 < runs: continue                       # under 1 season in 200: too few to read
        m = sim["made_at"][G][w]
        l = lg.w[G] + lg.l[G] + sim["left"][G] - w
        fr += (f'<tr><td class="l club mono">{_rec(lg, G, w, l)}</td>'
               f'<td class="n">{100 * n / runs:.0f}%</td>'
               f'<td class="n">{_pc(m, n)}<span class="bar"><i style="width:{100 * m / n:.0f}%"></i></span></td></tr>')
    byrec = (f'<div class="card g"><div class="ch">What record gets them in</div>'
             f'<div class="cs">How often they finish on each record, and how often that record was enough.</div>'
             f'<div class="tw"><table><tr><th class="l">Finish</th><th>How likely</th><th>Playoffs at that record</th></tr>'
             f'{fr}</table></div></div>')

    # ---- where they land
    sd = ""
    for s in range(1, 8):
        n = sim["seeds"][G][s]
        sd += (f'<tr><td class="l club">{s}{"st" if s == 1 else "nd" if s == 2 else "rd" if s == 3 else "th"} seed'
               f'<span style="color:var(--mut);font-weight:400"> · {"division winner, bye" if s == 1 else "division winner, home game" if s <= 4 else "wild card, on the road"}</span></td>'
               f'<td class="n">{_pc(n, runs)}<span class="bar"><i style="width:{100 * n / runs:.0f}%"></i></span></td></tr>')
    miss = runs - sim["made"][G]
    sd += (f'<tr><td class="l club">Miss the playoffs</td>'
           f'<td class="n">{_pc(miss, runs)}<span class="bar"><i style="width:{100 * miss / runs:.0f}%;background:var(--out)"></i></span></td></tr>')
    wc = sim["made"][G] - sim["div"][G]
    land = (f'<div class="card g"><div class="ch">Where they land</div>'
            f'<div class="cs">Two ways in: win the division ({_pc(sim["div"][G], runs)}) or take a wild card '
            f'({_pc(wc, runs)}).</div><div class="tw"><table>{sd}</table></div></div>')

    # ---- this week: who to pull for
    wk = min((g["week"] for g in lg.left), default=None)
    picks = []
    for s in swing(sim, "NYG"):
        g = s["game"]
        if g["week"] != wk or G in (g["h"], g["a"]) or s["if_home"] is None or s["if_away"] is None: continue
        d = s["if_home"] - s["if_away"]
        if abs(d) < 0.02: continue
        good, bad = (g["h"], g["a"]) if d > 0 else (g["a"], g["h"])
        picks.append((abs(d), good, bad, g, max(s["if_home"], s["if_away"]), min(s["if_home"], s["if_away"])))
    picks.sort(key=lambda x: -x[0])
    root = "".join(
        f'<div class="root"><div><b>{SHORT(lg.name[good])}</b> over {SHORT(lg.name[bad])}'
        f'<br><span>{_day(g)} · {SHORT(lg.name[g["a"]])} at {SHORT(lg.name[g["h"]])} · '
        f'Giants {100 * hi:.0f}% if it goes their way, {100 * lo:.0f}% if not</span></div>'
        f'<div class="n">+{100 * d:.0f} pts</div></div>'
        for d, good, bad, g, hi, lo in picks[:8])
    rooting = (f'<div class="card g"><div class="ch">Week {wk}: who to pull for</div>'
               f'<div class="cs">Other games this week, ranked by how much the result moves the Giants&rsquo; playoff chance. '
               f'Games that move it by less than 2 points are left off.</div>'
               + (root or '<div class="cs">No other game this week moves the Giants by 2 points either way.</div>')
               + '</div>') if wk is not None else ""

    # ---- division rivals and the other clubs still to play
    east = [r["abbr"] for r in snap["divisions"].get(gt["div"], [])]
    east_cards = "".join(_schedule_card(snap, sim, ab, "g" if ab == "NYG" else "") for ab in east)
    east_set = set(east)
    others = []
    for g in gt["games"]:
        if not g["completed"] and g["opp"] not in east_set and g["opp"] not in others:
            others.append(g["opp"])
    def wkof(ab):
        return next(g["week"] for g in gt["games"] if g["opp"] == ab and not g["completed"])
    other_cards = "".join(_schedule_card(snap, sim, ab, "", f' · plays the Giants in week {wkof(ab)}') for ab in others)

    nfc_table, nfc_bracket = _picture(snap, sim, "NFC", "NYG", "g")
    afc_table, afc_bracket = _picture(snap, sim, "AFC", "BUF", "b")
    bills = "".join(_schedule_card(snap, sim, ab, "b" if ab == "BUF" else "")
                    for ab in [r["abbr"] for r in snap["divisions"].get(snap["teams"]["BUF"]["div"], [])])

    asof = next((g["prob"].get("asOf") for g in snap["games"].values() if g.get("prob")), None)
    return (
        CSS + '<div class="po">'
        f'<div class="tiles">{tiles(G, "g", "Giants")}{tiles(B, "b", "Bills")}</div>'
        '<div class="jump"><a href="#nfc">NFC picture</a><a href="#giants">How the Giants get in</a>'
        '<a href="#east">NFC East run-in</a><a href="#opp">Who they still play</a>'
        '<a href="#afc">AFC and the Bills</a><a href="#how">How this is worked out</a></div>'

        '<h2 id="nfc">The NFC picture</h2>'
        '<p class="lede">Seven clubs go through: the four division winners, then the three best of everyone else. '
        'A club is only listed as officially in or knocked out when that is certain. Everything in between is a chance, '
        'from playing out the rest of the season many thousands of times.</p>'
        f'<div class="cols c21"><div class="card g">{nfc_table}</div>{nfc_bracket}</div>'

        '<h2 id="giants">How the Giants get in</h2>'
        f'<p class="lede">{gt["name"]} are {_rec(lg, G)}, {gt["divRank"]}{"st" if gt["divRank"] == 1 else "nd" if gt["divRank"] == 2 else "rd" if gt["divRank"] == 3 else "th"} '
        f'in the {gt["div"]} and the {gt["confSeed"]}{"st" if gt["confSeed"] == 1 else "nd" if gt["confSeed"] == 2 else "rd" if gt["confSeed"] == 3 else "th"} seed today.</p>'
        f'<div class="cols c22">{road}{byrec}</div>'
        f'<div class="cols c22" style="margin-top:14px">{rooting}{land}</div>'

        f'<h2 id="east">The {gt["div"]} run-in</h2>'
        '<p class="lede">What each club in the division still has to play, with its chance to win each game.</p>'
        f'<div class="cols c4">{east_cards}</div>'

        '<h2 id="opp">Who the Giants still play, and what those clubs have left</h2>'
        '<p class="lede">The clubs outside the division still on the Giants&rsquo; schedule. A club with nothing to play for '
        'late in the year is a different opponent from one fighting for a seed.</p>'
        f'<div class="cols auto">{other_cards}</div>'

        '<h2 id="afc">The AFC, and the Bills</h2>'
        '<p class="lede">The same picture for the other conference.</p>'
        f'<div class="cols c21"><div class="card b">{afc_table}</div>{afc_bracket}</div>'
        f'<div class="cols c4" style="margin-top:14px">{bills}</div>'

        '<h2 id="how">How this is worked out</h2><div class="how">'
        f'<p><b>The chances.</b> Every game still to be played has a win probability published by ESPN&rsquo;s model. '
        f'The rest of the season is played out {runs:,} times with those numbers, the league&rsquo;s seeding rules are applied '
        f'to each finished season, and a club&rsquo;s chance is the share of those seasons it got in.</p>'
        '<p><b>Officially in, knocked out.</b> Never taken from the played-out seasons. A club is marked only when the league '
        'has marked it, or when plain arithmetic leaves no other result.</p>'
        '<p><b>Tiebreakers.</b> Applied in the league&rsquo;s order: head to head, division record, conference record, '
        'strength of victory, strength of schedule. The &ldquo;common games&rdquo; step is not applied, so a very tight tie '
        'can fall differently from the league&rsquo;s own answer.</p>'
        '<p><b>What it does not know.</b> Injuries, a hot streak, or a club resting players in Week 18. A win this week does not '
        'make a club stronger next week in these numbers. No simulated game ends in a tie.</p>'
        '<p><b>Seeds shown as &ldquo;today&rdquo;</b> are the league&rsquo;s own, as published. '
        'The &ldquo;if they win&rdquo; columns carry about a point of noise either way.</p>'
        f'<p>Probabilities as published {asof or "—"}. Rebuilt {stamp}.</p></div></div>')


def home_strip(snap, sim):
    """Two tiles for the home page."""
    lg = sim["lg"]; runs = sim["runs"]
    def one(ab, who, col):
        i = lg.ix[ab]
        return (f'<a href="/playoffs" style="flex:1 1 260px;min-width:0;display:block;text-decoration:none;color:inherit;'
                f'background:var(--panel);border:1px solid var(--line);border-top:3px solid var({col});border-radius:14px;padding:14px 16px">'
                f'<div style="font-size:10px;letter-spacing:.11em;text-transform:uppercase;color:var(--mut)">{who} · playoff race</div>'
                f'<div style="font-family:\'Barlow Condensed\';font-size:40px;font-weight:900;line-height:1.05">{_pc(sim["made"][i], runs)}'
                f'<span style="font-size:15px;color:var(--mut);font-weight:700;letter-spacing:.04em"> to make the playoffs</span></div>'
                f'<div style="font-size:12px;color:var(--mut)">Win the {lg.div[i]} {_pc(sim["div"][i], runs)} · '
                f'top seed {_pc(sim["bye"][i], runs)} · projected {sim["avg_w"][i]:.1f} wins · see the whole race →</div></a>')
    return ('<div style="display:flex;flex-wrap:wrap;gap:14px;margin-bottom:22px">'
            + one("NYG", "Giants", "--g") + one("BUF", "Bills", "--b") + '</div>')
