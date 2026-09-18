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

There is no server, so the schedules live in `.github/workflows/`. Both
commit only when something changed, and the push is what makes Cloudflare
Pages redeploy. Both can be triggered by hand from the Actions tab.

**Full refresh - 09:30 UTC daily.** Two constraints pin that time. ESPN's
FPI run publishes at 09:00 UTC, so anything earlier fetches yesterday's win
probabilities; this job ran at 07:40 for a while and did exactly that. And
the latest game of any slate ends around 04:00 UTC, so 09:30 is safely
after last night's results have settled. Verified by checking lastModified
across 40 predictor responses - all 09:00Z, one run a day.

**Lines refresh - 15:00, 19:00 and 23:00 UTC.** Sportsbook lines move all
day and are posted game by game as kickoff nears, so once daily is always
stale on them. `refresh.py --props-only` reuses the nightly snapshot and
replaces only the lines and gamelogs: about 30 requests instead of 280. It
refuses to publish if the lines come back empty when it had some before.

Both jobs share a `concurrency` group so they can never run into each
other and race on a push.

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

## The parlay tab

`/parlay` combines this week's outcomes into one probability. It is
deliberately split in two, because the halves are not the same kind of
number.

**Game outcomes** are ESPN's published win probabilities. Real.

**Player outcomes** are computed here. The feed carries the line a
sportsbook set but *no price*, so there is no market-implied probability to
read off - it has to be modelled. The method:

    median = the book's line     ->  mu    = ln(line)
    spread from a typical CV     ->  sigma = sqrt(ln(1 + CV^2))
    P(X >= t)                    =  1 - Phi((ln t - mu) / sigma)

Log-normal because yardage is non-negative and right-skewed: a receiver's
ceiling sits far above his median and his floor is zero. Treating the line
as the median is reasonable - that is roughly what a book sets it to be -
and the model returns 50% at the line by construction, which is the check
worth keeping.

The weak assumption is the spread. `STAT_CV` in `render.py` holds a typical
game-to-game coefficient of variation per stat type, not the player's own
variance, because one game into a season there is not enough history to
measure it. Revisit those numbers once there is a real sample. The page
says all of this in plain words; don't quietly drop that text.

Books post props game by game as kickoff nears, so early in the week most
games have no lines at all. The page says how many are missing rather than
looking broken.

`athletes.json` caches player id to name. Names don't change, so it makes
the nightly run nearly free after the first one.

### Best chances, and why it is not sorted by probability

Sorting the shortlist by the modelled probability would be circular. The
model puts the median at the book's line, so the highest probability is
always the lowest threshold - for every player, every time. A list built
that way would say "take the smallest number in every row" and would carry
no information about who is likely to beat their line.

So `shortlist()` ranks on the one thing the model does not already know:
whether the player has actually been clearing that number, from the
gamelogs. The score blends hit rate with the modelled probability and
shrinks toward the model while the sample is small:

    w       = games / (games + 4)
    score   = (1 - w) * modelled + w * hit_rate

At one game w is 0.2, so the ranking is still mostly the model and the page
says so. By about week six w passes 0.6 and production is doing the work.
Rows where the player has never cleared the threshold are dropped, and only
one row per player per stat is kept so one hot player cannot fill the list.

When there is a real sample, the other thing to do is replace the generic
`STAT_CV` with each player's own variance from his gamelog. That is the
single biggest improvement available to this model, and it is not possible
in September.


## The 17 September outage

The nightly rebuild died for a day and a half on a `TypeError: unsupported
operand type(s) for *: 'NoneType' and 'int'`.

Cause: `player_props` built its thresholds as `round(line * m)` when a player
had no milestone ladder. A line of **0.5** — ordinary for receptions or
touchdowns — gives `round(0.5 * 0.6) = 0`. `model_prob` correctly returns None
for a zero threshold, because "0 or more receptions" is a certainty rather than
a prediction. The caller then multiplied that None by 100.

It only appeared once the books posted the rest of the week's props: the run
before it had 169 players, the one that broke had 199. The extra thirty brought
the first 0.5 lines with them.

Two fixes, deliberately both:
  * thresholds are filtered to `> 0` before they are priced
  * a None from `model_prob` drops that rung instead of raising, and a stat
    left with no rungs is skipped entirely

`test_model.py` covers it and now runs as a step in BOTH workflows before the
rebuild, so a model that cannot price its own thresholds fails the job rather
than the site.

The fallback worked exactly as intended throughout: every failed run kept the
previous day's pages, so the site stayed up and stale rather than going blank.
Stale is the correct failure here — but three consecutive red runs is the
signal to look, and nothing was watching for it.
