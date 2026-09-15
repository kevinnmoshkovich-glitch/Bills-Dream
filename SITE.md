# Giants vs Bills — season statistics

Three pages, rebuilt nightly from ESPN's public JSON feeds.

    index.html      head-to-head, next games, both home divisions
    schedule.html   all 34 games, with published win probabilities
    league.html     all 32 clubs, all 8 divisions

## Deploying

Copy the folder to the web root. It is plain static HTML — no server
runtime, no database, no build step.

    rsync -av site/ user@host:/var/www/gbstats/

## Keeping it current

    40 3 * * *  /usr/bin/python3 /var/www/gbstats/refresh.py >> /var/log/gbstats.log 2>&1

3:40am, after the late games have settled. One run takes about three
seconds and makes roughly forty requests.

`refresh.py` pulls the data and writes `snapshots/YYYY-MM-DD.json`, then
`render.py` rebuilds the three pages from it. Snapshots are kept, so you
can always see what the site said on a given day.

## What happens when the feed breaks

These endpoints are undocumented. They will break eventually.

  * Fetch fails    → yesterday's pages stay up, exit 0, reason logged.
  * Data looks wrong (a team with under 16 games, fewer than 8 divisions,
    no team stats) → refuses to publish, keeps yesterday's pages.

The site never goes blank or half-empty because a feed had a bad night.
Both paths are tested. If the log shows the same failure several nights
running, the feed has changed shape and the parser needs a look.

## Editing the pages

`index.html` is generated from `index.template.html`. Only the marked
regions are replaced:

    <!--RECORDS-->      hero record strip
    <!--NEXTGAMES-->    next-game cards
    <!--DIVISIONS-->    the two home divisions
    <!--STAMP-->        update timestamp

Everything outside those markers — the written weekly brief above all —
is left exactly as you wrote it. Edit the template, never index.html; a
refresh overwrites index.html.

`schedule.html` and `league.html` are generated whole from
`page.template.html`. Don't hand-edit them.

## Two things that were wrong and are worth not reintroducing

**Timezone.** The season crosses the DST boundary on 1 November. A fixed
-4 offset puts every kickoff from Week 9 onward an hour late. `render.py`
uses the real `America/New_York` zone. Don't replace it with an offset.

**Unset kickoffs.** The league flexes late-season games, so Week 18 has no
real time yet. ESPN parks those at midnight and flags them `timeValid:
false`. Those render as "time TBD" rather than a midnight kickoff.

## Win probabilities

Published by ESPN's FPI model and refreshed each morning; the site
displays them and computes nothing of its own. Games already played show
the result instead.

## Division position, early season

Division order comes from the order ESPN returns clubs in. At 1-0 with no
head-to-head and no division games played, the NFL's tiebreakers have
almost nothing to work with, and ESPN's own feeds don't always agree with
each other on who leads. Treat the position as soft until October.

## Data source

Undocumented ESPN endpoints. No key, no terms of use, no support, no SLA.
Fine for a fan page; it is not a supported API and could change without
notice. If it goes away for good, a paid feed (SportsDataIO, API-Sports;
roughly $20-50/month) covers the same ground — swap the fetch functions in
`refresh.py` and leave `render.py` alone.

Names and records only. No logos, no team marks.
