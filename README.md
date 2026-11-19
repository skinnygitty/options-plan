# Options plan

A scanner that runs on GitHub Actions twice each weekday, pulls free Yahoo Finance data, and publishes a
two-page site on GitHub Pages:
- **Tonight** (`index.html`): after the close, a trade plan per ticker with earnings context, call and put walls,
  unusual-flow lean, the Strat, and stop/targets sized for 3:1 to 4:1.
- **10:00 check** (`check.html`): after the first 30 minutes, which plans triggered, failed, or are still waiting.

Your Mac doesn't need to be on.

## Setup (once, about 10 minutes)
1. On github.com, create a **new, empty, public** repository (no README), e.g. `options-plan`.
2. On the Mac, unzip this folder, open Terminal, and run:
   ```
   cd ~/options-scanner && bash setup_github.sh
   ```
   Paste the repository URL when asked. (If you'd rather use GitHub Desktop: File > Add Local Repository,
   pick this folder, then Publish. Make sure the hidden `.github` folder is included.)
3. In the repository on github.com: **Settings > Pages > Source: Deploy from a branch > main, /docs > Save.**
4. **Actions** tab: if asked, click "I understand my workflows, enable them". Then **Options scanner > Run workflow**
   to get a first plan right away (choose "evening").
5. Your site: `https://<your-username>.github.io/options-plan/`. On your phone, open it in Safari, tap Share,
   then Add to Home Screen.

### Schedule
- Evening scan about **6:37 pm ET**, 10:00 check about **10:03 am ET**, Monday to Friday.
- GitHub runs schedules in UTC, so each job is listed for both daylight-saving and standard time;
  `ci_gate.py` runs the one that lands at the right New York time and skips the other.
- GitHub can start scheduled runs late when it's busy. The check accepts runs until 1 pm; the footer on each
  page shows when it was last updated.
- Each run commits its results, which keeps the repository active so GitHub doesn't pause the schedule.
- Run either one by hand at any time: **Actions > Options scanner > Run workflow**.

### Things to know
- **The site and repository are public.** GitHub Pages on a free account requires a public repository, and the
  site is visible to anyone who has the link. Pages are marked to stay out of search engines, but don't put
  anything private in the watchlist or events file.
- **Yahoo can rate-limit GitHub's servers.** The scanner backs off and retries, and the evening job has a second
  scheduled slot an hour later. If a run fails, it shows red in the Actions tab and the site keeps the previous
  plan. If this keeps happening, see "Run on the Mac instead" below.

## Changing what it scans
Edit these files on github.com (pencil icon) and commit; the next run picks them up.
- `watchlist.txt` — tickers to always scan. Recent earnings reporters are added automatically.
- `events.csv` — conferences, analyst days, FOMC, CPI, opex. Yahoo has no conference calendar,
  so add them here; anything within 14 days shows as a caution on the plan.
- Settings at the top of `nightly_scanner.py` (flow thresholds, DTE window, R:R minimum).


## How it decides
- **Post-earnings first.** Names 0–7 sessions after their earnings reaction are tagged POST-EARNINGS
  and sorted to the top: implied volatility has already collapsed, so options are cheaper.
  Names reporting in the next 10 days are listed separately as "avoid buying premium into."
- **Direction score:** earnings gap that is holding (+/-1.5) + weekly 21/72 EMA trend (+/-1)
  + unusual-flow lean (+/-1) + yesterday's flow confirmed as new positions by open interest (+/-1).
  ≥ +2 LONG, ≤ -2 SHORT, otherwise WATCH.
- **Walls:** call wall = strike above price with the most call gamma (resistance / target);
  put wall = strike below price with the most put gamma (support / stop anchor). OI-based walls shown too.
- **Plan:** trigger = hold above the reaction-day high (long) / below the low (short); stop beyond the
  opposite wall or reaction-day extreme; T1 = wall, T2 = next wall. If R:R < 3:1 it gives you the limit
  price that *would* make it 3:1, or says pass.
- **Option idea:** ~0.60-delta call/put, 21–60 DTE, ideally expiring before the next earnings, plus a
  debit spread with the short strike at the wall. Values are estimates (IV held constant).


## The Strat layer
- Candles on **D, 2D, 3D, 5D, 9D and W**. The 2D/3D/5D/9D candles are built from daily bars and anchored to the
  latest close, so each one is complete. TradingView anchors multi-day candles differently, so its 3D/5D/9D
  bars can split on other days — confirm the pattern on your chart before trading.
- Each candle is labeled 1 / 2U / 2D / 3 with its color. **Actionable signals** flagged: inside bar, hammer,
  shooter, failed 2U (2U red) / failed 2D (2D green), outside bar.
- **Combos detected:** 2-1-2 and 3-1-2 (continuation or reversal), 1-2-2 RevStrat, 3-2-2, 2-2 reversals
  (after a failed 2 or a hammer/shooter). Each comes with a trigger (break of the setup bar) and a stop
  (the other side of that bar), plus R:R to the walls.
- **Full timeframe continuity (FTFC):** last close vs the open of the current Quarter / Month / Week / Day.
  All green or all red adds ±0.5 to the score.
- **★ Best Strat entry:** 3:1 to target 1 comes first, then the highest timeframe, among triggers within
  1.5 daily ATRs.
- **Pre-entry checklist** on every plan: continuity, trigger in force, ≥3:1, no earnings before expiry,
  flow confirmed, don't chase gaps.


## The 10:00 am check
Runs after the first 30 minutes, once the open's volatility has settled. For each plan from last night:
- **Triggered**: price traded through the trigger and is holding. Valid entry; a break of the
  opening-range high (long) or low (short) adds confirmation.
- **Extended**: triggered but more than ½ ATR past it. Wait for a pullback.
- **Failed**: traded through the trigger, then fell back (a failed 2U or 2D). Skip unless it reclaims.
- **Waiting**: not triggered yet; set an alert at the trigger.
- **Stopped** / **At target**: plan is done for today.
It also shows today's candle so far (2U / 2D / 1 / 3 vs yesterday), the opening range as a shaded band on
the line, R:R from the current price, S&P and Nasdaq futures, early options flow from the first 30 minutes
(with live bid/ask, so the bought/sold lean is more reliable), and whether last night's unusual contracts
opened new positions according to the overnight open-interest update.



## Run on the Mac instead (fallback)
If Yahoo blocks GitHub's servers, the same code runs on your Mac and pushes the pages to GitHub:
1. `bash setup_mac.sh` (installs Python packages and schedules 6:30 pm and 10:00 am runs on the Mac).
2. `touch .push_from_mac` to turn on pushing to GitHub after each Mac run.
3. In `.github/workflows/scanner.yml`, delete the four `cron:` lines so the two don't both run.
To stop the Mac schedule: `launchctl unload ~/Library/LaunchAgents/com.optionsscanner.*.plist`

## Files
- `nightly_scanner.py`: scanning, levels, Strat, plans, 10:00 check
- `site_render.py`: the look of the two pages
- `.github/workflows/scanner.yml`, `ci_gate.py`: the GitHub schedule
- `docs/`: the published site; `reports/`: dated copies (30 days) and last night's plan; `snapshots/`: flow history

Not financial advice. Verify levels on your own charts before trading.
