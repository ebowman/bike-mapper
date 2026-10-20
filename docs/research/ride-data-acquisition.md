# Ride data acquisition: Eric's own ride history (Garmin Connect / Strava)

## Question

Stop detection (dhy.6) and the stop-model calibration that follows need raw per-second ride
recordings — ideally the original FIT files with recorded speed, not re-sampled GPX. Where does
Eric's history live, how much of it is outdoor road riding, under what terms may it be pulled,
and is the recording resolution good enough (1 s "every second" vs Garmin "smart recording")?

## Sources evaluated

| name | URL | license | access method | coverage | resolution/granularity | cost |
|------|-----|---------|---------------|----------|------------------------|------|
| Garmin Connect — in-page activity list | `https://connect.garmin.com/gc-api/activitylist-service/activities/search/activities?start=N&limit=100&activityType=cycling` | Own data. Garmin Terms of Use (https://www.garmin.com/en-US/legal/terms-of-use/, "License to Access the Site"): Site and Content for "personal and non-commercial use"; listed violation: "Using any process, whether automated or manual, that accesses, copies, or scrapes content from the Site through any means not purposely made available through the Site". This endpoint is the one the Connect activity-list page itself calls. | `fetch()` from the authenticated connect.garmin.com tab via chrome-devtools MCP `evaluate_script`; `credentials:'include'` + the page's `connect-csrf-token` meta header. Nothing is replayed outside the browser. | all of Eric's cycling activities (971, 2020-04 → 2026-10), newest first, 100/page | summary row per activity (~130 fields: id, type, start, distance, duration, device, hasPolyline, power/HR aggregates) | free |
| Garmin Connect — original file ("Export Original" button) | `https://connect.garmin.com/gc-api/download-service/files/activity/<activityId>` | as above; same call the UI's *Export Original* menu item makes | as above; response is `application/x-zip-compressed` containing `<id>_ACTIVITY.fit`; ArrayBuffer → base64 inside the page, unzipped in Python | every activity with a file; 86/86 outdoor requested → 86 OK, 0 failures | original FIT: 1 s records on the Edge 840 (see hands-on) | free |
| Garmin — Account Management Center (official export) | https://www.garmin.com/account/datamanagement (cited by the Garmin Connect Privacy Policy, https://www.garmin.com/en-US/privacy/connect/policy/, "Manage Your Data": "a self-service portal … to allow you to access, export, correct, or delete your data at any time") | explicit, the ToS-clean route | interactive request; archive arrives by e-mail (hours–days) | full account | original FIT files | free |
| Strava — per-activity export | `https://www.strava.com/activities/<id>/export_original` (also `/export_gpx`, `/export_tcx`), documented at https://support.strava.com/hc/en-us/articles/216918437-Exporting-your-Data-and-Bulk-Export | Own Content (Strava Terms §5: "You will remain the owner of intellectual property rights … in your Content"). **But** Strava Terms (https://www.strava.com/legal/terms): "Automated access to or collection of data from the Services—by any means, including data mining, robots, screen scraping, scripts, or similar data-gathering tools or software such as browser extensions and crawlers—is prohibited. This prohibition applies regardless of whether you are logged into a Strava account". | manual click per activity is fine; a scripted loop over `export_original` is *not* ToS-clean — not used | Strava mirrors the same Garmin uploads | as uploaded | free |
| Strava — bulk export (official) | Settings → My Account → "Download your account" → Request archive (support article above); privacy policy "Access and Portability" (https://www.strava.com/legal/privacy): "To download your data, including your activity files, follow the instructions here" | explicit | interactive request; zip by e-mail (hours–days) | full account incl. original activity files | as uploaded | free |

Decision: Garmin Connect, in-page, from Eric's own authenticated session, paced at ≤ 1 request/s.
Strava was not needed (Eric's rides are recorded on a Garmin Edge and land in Connect first),
and scripted Strava pulls are ruled out by Strava's terms.

## Hands-on check

**Procedure (reproducible).** Eric logged in to https://connect.garmin.com/app/activities himself;
the agent never saw or typed credentials, and no cookie/token was written anywhere.

1. `evaluate_script pageId=1 sourcePath=scripts/garmin_browser_pull.js` installs `window.gcPull`
   (`listPages`, `downloadBatch`) in the tab. Requests use the page's own `fetch()` with
   `credentials:'include'` and the `connect-csrf-token` header read from the page's meta tag.
   ≥ 1 s between requests, 30 s back-off on HTTP 429 (never triggered).
2. `evaluate_script function="async () => gcPull.listPages(0, 10)" filePath=data/rides/_batches/list_000.json`
   — 10 pages of 100 exhausted the account (971 activities, `done: true`) in one call.
3. `evaluate_script function="async () => gcPull.downloadBatch([ids…])" filePath=data/rides/_batches/batch_NNN.json`
   — 9 calls of ≤ 10 ids, each entry `{id, status, contentType, bytes, b64}`.
4. `uv run scripts/rides_unpack.py` — decodes, unzips, writes `data/rides/<id>.fit` (skips ids
   already on disk) and rebuilds `data/rides/index.json`
   (`activityId, activityName, startTimeGMT, startTimeLocal, distance_m, duration_s, typeKey,
   deviceId, manufacturer, hasPolyline, downloaded, file[, reason]`).
5. `uv run scripts/rides_inspect.py [--sample 3]` — fitdecode pass over every file.

All of `data/rides/` is gitignored; `git status --porcelain data/rides/` is empty.

**Counts (2026-10-20).**

| | activities | km |
|---|---:|---:|
| total cycling in Garmin Connect, 2020-04-30 → 2026-10-19 | 971 | 21 884 |
| `indoor_cycling` (878) + `virtual_ride` (7) — excluded, `downloaded:false, reason:"indoor"` | 885 | 18 164 |
| **outdoor** (`road_biking` 66 + generic `cycling` 20), 2020-11-11 → 2026-10-19 | **86** | **3 720** (174 h, 608 437 record messages) |
| outdoor originals downloaded | 86 / 86 | failures: 0 |
| remaining beyond the 500-ride cap | 0 | — |

Outdoor rides by year: 2020: 2 (11 km) · 2021: 1 (36 km) · 2024: 2 (11 km) · 2025: 14 (660 km) ·
2026: 67 (3 002 km). Median ride 38 km; 64 rides ≥ 20 km; 3 are < 1 km (accidental starts /
an indoor class mis-typed as `cycling`). Mostly County Dublin; also Berlin/Brandenburg, Attica
(Greece), Slovenia and the Dutch coast.

**The history is modest: 86 outdoor rides (83 with GPS), concentrated in 2025–2026.** Above the
"< 50 rides" alarm threshold, but dhy.6 / dhy.11 should still treat this as one rider's sample
and lean on OSM public traces for breadth.

**Devices (from the FIT `file_id` message).**

| recorder | files | notes |
|---|---:|---|
| Garmin Edge 840 (`garmin/edge_840`, Connect deviceId 3611336881) | 68 | all 2026 rides and most of 2025 |
| third-party app upload (`manufacturer=development`, product 29558: 15; product 26731: 3; Connect shows `DEVELOPMENT`, deviceId 0) | 18 | 2020–2025 phone/app recordings synced into Connect; includes 3 duplicate pairs/triples of the same ride uploaded by two apps (2025-05-25 ×3, 2025-08-01 ×2) and 2 files with no `record` messages at all |

**3-file sanity check** (`uv run scripts/rides_inspect.py --sample 3`; seed not recorded — a seeded rerun picks different files, the figures below are for the three IDs listed): 23811299967,
23287019919, 23911443905 — all Edge 840, 13 019 / 10 072 / 6 939 records, median interval 1.0 s,
speed and position present on 100 % of records.

**Recording interval, all 86 files** (`uv run scripts/rides_inspect.py`):

| | files |
|---|---:|
| median record interval ≤ 2 s ("every second" recording) | 83 |
| median record interval > 2 s (smart recording) | 1 (20271114668, third-party upload, median 3 s) |
| no record messages (empty indoor/manual entries) | 2 (20030508907, 20070525554) |
| records carrying speed | 608 247 / 608 437 (99.97 %) |
| records carrying position | 608 032 / 608 437 (83 files; the 3 without position are the 2 empty files and a 9-second accidental start) |

Every Edge 840 file records at 1 s — smart recording is off on Eric's unit. The share of
timestamp gaps > 2 s is 0–2 % on Edge files and up to 55 % on the third-party uploads
(20271114668, 20070587031, 20070586418, 20271116194). Important for dhy.6: on the Edge files the
> 2 s gaps are each bracketed by `event: timer stop_all / start` messages (e.g. 22749695683:
30 gaps > 2 s, 32 stop_all events, 1 572 s of paused time, longest 713 s), i.e. **auto-pause is
on and stops appear as timestamp gaps + timer events, not as runs of zero-speed records**. The
stop detector must use both signals.

## Verdict

Usable with caveats. Garmin Connect's own in-page endpoints deliver the original 1 s FIT files
for every outdoor ride, with speed on every record, under Eric's own login and at a polite rate;
the pull is reproducible (`scripts/garmin_browser_pull.js` + `scripts/rides_unpack.py`) and
resume-safe. Caveats: (1) the sample is small — 86 outdoor rides / 3 720 km, 78 % of it from
2026 — so stop statistics will be noisy and Dublin-centric; (2) auto-pause means stationary time
is encoded as gaps/timer events, which the dhy.6 parser must honour; (3) the 18 third-party
uploads are lower quality (one smart-recorded, two empty, five duplicates) and should be
de-duplicated or dropped; (4) scripted pulling sits in a grey zone of Garmin's site terms
(same endpoint as the UI button, own data, low rate) — the unambiguous route is the Account
Management Center export, which should be requested once if this data is ever redistributed.

## Open questions for Eric

- Does Strava hold outdoor rides that never reached Garmin Connect (pre-2020, phone-recorded)?
  If yes, request the official Strava bulk export (Settings → My Account → Download your
  account) rather than scripting `export_original`.
- Which apps produced the `development/29558` and `development/26731` uploads (2020–2025)? Keep
  one copy per ride, or drop them and use only the Edge 840 files?
- Is Edge auto-pause intentional? Leaving it on is fine for the stop model as long as dhy.6
  reads timer events; turning it off would give explicit zero-speed dwell records in future rides.
- Should we request the Garmin Account Management Center archive as the archival copy
  (arrives by e-mail), so the in-page pull is only a convenience?
