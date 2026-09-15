# bills.finecarerx.com

    /                 Giants vs Bills - the headline view
    /schedule         both clubs, full season, with win probabilities
    /league           all 32 clubs, all 8 divisions
    /team/<abbr>      one page per club, all 32 (e.g. /team/buf, /team/kc)

Everything is rebuilt nightly from ESPN's public JSON feeds.

## How a run works

`refresh.py` pulls the league, writes `snapshots/YYYY-MM-DD.json`, then
`render.py` rebuilds all 35 pages from that snapshot. About 280 requests,
roughly 15 seconds.

     18  scoreboard          all 272 games, results and fixtures
      1  standings           all 32 records, division order, conference seed
      1  byteam statistics   all 32 clubs, 93 stats each, with league ranks
   ~256  predictor           published win probability per unplayed game

There is no server, so the schedule lives in
`.github/workflows/refresh.yml` - 07:40 UTC daily, plus a manual trigger
from the Actions tab. It commits only when something changed, and the push
is what makes Cloudflare Pages redeploy.

## When the feed breaks

These endpoints are undocumented and will break eventually.

  * Fetch fails      -> yesterday's pages stay up, exit 0, reason logged.
  * Data implausible -> refuses to publish, keeps yesterday's pages.

The guard checks game count, division count, team count, and that team
stats are actually populated rather than merely present. Both paths are
tested. Same failure several nights running means the feed changed shape
and the parser needs a look.

## Editing pages

`index.html` is generated from `index.template.html`. Only marked regions
are replaced:

    <!--NAV-->  <!--RECORDS-->  <!--NEXTGAMES-->
    <!--TALLY-->  <!--COMPARE-->  <!--DIVISIONS-->  <!--STAMP-->

Everything outside them is left as written. **The weekly brief is the one
part that does not refresh itself** - it is prose, and a template would
read like a robot wrote it. Rewrite it each Tuesday in
`index.template.html`. Never edit `index.html`; a refresh overwrites it.

`schedule.html`, `league.html` and `team/*.html` are generated whole from
`page.template.html`. Don't hand-edit them.

## Four things that were wrong, worth not reintroducing

**Timezone.** The season crosses the DST boundary on 1 November. A fixed
-4 offset puts every kickoff from Week 9 onward an hour late. `render.py`
uses the real `America/New_York` zone. Never swap it for an offset.

**Unset kickoffs.** The league flexes late-season games. ESPN parks those
at midnight with `timeValid: false`; they render "time TBD" rather than a
midnight kickoff that isn't real.

**Stat names.** Each team's stat category carries values, totals and ranks
but NO names - those live in a top-level glossary, matched by category and
position. Zipping against `cat["names"]` silently yields nothing, which is
what this did for a while: 32 clubs, zero stats, no error.

**Marker nesting.** Template markers must wrap a div's contents exactly.
An over-wide region once swallowed the block after it, so rebuilding one
section deleted another. `render.py` has no opinion about this - the
template has to be right.

## Win probabilities

Published by ESPN's FPI model, refreshed each morning. The site displays
them and computes nothing of its own. Played games show the result.

## Division position, early season

Division order is the order ESPN returns clubs in. At 1-0 with no
head-to-head and no division games played, the NFL's tiebreakers have
almost nothing to work with, and ESPN's own feeds don't always agree with
each other. Treat position as soft until October.

## Not yet done

Player statistics. The rosters, per-player lines and cross-team
leaderboards were frozen at Week 1, so they were removed rather than left
to go stale. Adding them back means pulling box scores per completed game
and accumulating across the season.

## Data source

Undocumented ESPN endpoints. No key, no terms, no support, no SLA. Fine
for a fan page; not a supported API. If it goes for good, a paid feed
(SportsDataIO, API-Sports, roughly $20-50/month) covers the same ground:
swap the fetch functions in `refresh.py` and leave `render.py` alone.

Names and records only. No logos, no team marks.
