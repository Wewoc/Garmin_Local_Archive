# Garmin account data export — structure guide

> **Disclaimer.** This guide is a working basis for GLA. It describes what was observed in the exports examined so far; it makes no claim to correctness, completeness or validity for other accounts, devices or Garmin versions, and Garmin may change the export format at any time without notice. It is not an official Garmin document, and this project is not affiliated with or endorsed by Garmin; product and company names belong to their owners. The project licence covers this text only, not Garmin's marks, software or any user's data. Provided as-is, see the project README for the full disclaimer.

> **Privacy.** A Garmin export contains personal data: the account e-mail address (also in many file names), order and address data, saved routes with GPS coordinates, device identifiers and the complete health history. Do not post an export or excerpts of it. This guide describes structure only; examples show key names and types, never values.

**Status:** first version, 2026-10-21, revised 2026-10-22 (method and sources added, section 11), based on one export (see Basis); expect corrections.
**Scope:** what the "Export Your Data" ZIP of a Garmin account contains, how the files are laid out, what the fields mean, and how the export differs from the Garmin Connect API data GLA archives. It is a structure guide, not a statement about any one archive.
**Basis:** GLA 1.7.6.1; one export examined (obtained October 2026, one account, several devices). Field names and fill rates in this guide come from that export. The export covers about eight years of history. **Numbers are rounded guide values from that one export, not exact counts and not typical values for other accounts. Counts are given per year (or per day) of history, or as shares, because totals depend on how old an account is; multiply by the age of your own account. Yearly averages hide uneven years.** Other sources are marked Public or Community.
**Not covered:** the account/shop/consent files of the export (customer, orders, events, profile, reminders, consent history, device and content lists): they hold personal data and nothing for the archive. The FIT protocol itself (see Garmin's public FIT documentation).

Evidence levels used in every table. **Public** = stated on Garmin's public FIT documentation pages. **Seen** = observed in one export (a single account with several devices); other accounts and other Garmin export versions can differ. **Community** = stated by a third-party project or forum, not verified here; the third party's licence does not by itself show that the information is independent of Garmin's software. **Assumed** = inference, not checked. Reading rules ("read it as …") are derived from observations; Garmin does not state them.

> I found no official, comprehensive schema reference for the internal JSON files of the account export (searched 2026-10-21: only forum posts, guides by third parties and Garmin's public FIT pages). Everything below the Public level is reverse-engineered with claude-code from exports. How the statements were obtained, and which third-party sources were used, is stated in section 11.

---

## 1. What the export is

- Requested in the account data management page of the Garmin account ("Export Your Data"); the download link arrives by e-mail. A forum post quotes the account page as promising typically about two days and up to 30 days, depending on load and data volume; the post is several years old, the current wording may differ, and Garmin's own page needs a login and was not checked (links in section 11). *Community.*
- A ZIP with top-level folders. The relevant one is `DI_CONNECT/`; others (`IT_ORDERS`, `IT_GLOBAL_EVENT`, `IT_CONSENT_HISTORY`, `DI_LIVETRACK`, `DI_MEDIA_GDPR_SERVICE`, `DI_CONNECT_IQ`, `customer_data`, `IT_DEVICE_AND_CONTENT`) hold account data. *Seen.*
- Folder and file names differ between sources and exports (for example `DI-Connect-Uploaded-Files`, as in the observed export, against `DI-Connect-Fitness-Uploaded-Files`, named in a forum thread, see section 11). A reader must match on file-name patterns and content, not on exact paths. *Community, Seen.*

## 2. Container layout (`DI_CONNECT/`)

| Folder | Content | Evidence |
|---|---|---|
| `DI-Connect-Aggregator/` | Daily aggregates (`UDSFile_*`), hydration log (`HydrationLogFile_*`) | Seen |
| `DI-Connect-Wellness/` | Sleep (`*_sleepData.json`), heart-rate events (`*_AbnormalHrEvents.json`), health status (`*_healthStatusData.json`), body metrics (`*_userBioMetrics.json`, `*_fitnessAgeData.json`, `*_bioMetrics_latest.json`, `*_userBioMetricProfileData.json`), zones (`*_heartRateZones.json`, `*_powerZones.json`) | Seen |
| `DI-Connect-Metrics/` | Training metrics (`MetricsMaxMetData_*`, `TrainingHistory_*`, `TrainingReadinessDTO_*`, `MetricsAcuteTrainingLoad_*`, `EnduranceScore_*`, `HillScore_*`, `MetricsHeatAltitudeAcclimation_*`, `RunRacePredictions_*`), plus a `LhaBackup` ZIP | Seen |
| `DI-Connect-Fitness/` | Activity summaries (`*_summarizedActivities.json`), `gear`, `personalRecord`, `workout`, `trainingPlan`, `weekly_training_report`, a `PrimaryTrainingBackup` ZIP | Seen |
| `DI-Connect-Uploaded-Files/` | Nested ZIPs (`UploadedFiles_*_PartN.zip`) containing the FIT files | Seen |
| `DI-Connect-Routing/` | Saved courses (`*_courses_*.json`) | Seen |
| `DI-Connect-Device/` | `*_DeviceBackups.json` and a device backup ZIP | Seen |
| `DI-Connect-User/`, `DI-GOLF/` | Profile and settings, golf equipment | Seen, not covered |

**File families.** One family is split into several files by date range (about three months per file in the observed export). The names carry two dates and, in several families, the numeric account id (`YYYY-MM-DD_YYYY-MM-DD_<account id>_sleepData.json`). Some names (activities, gear, workout, courses) contain the account e-mail address. A tool must never store or log the names. *Seen.*

**Nested archives.** The FIT files are in ZIPs inside the export ZIP (a few parts in the observed export, about 4,500 FIT files per year of history, which is about 12 per day and about 30 MB per year unpacked). The file names inside are upload ids, not activity ids. *Seen.*

## 3. Reading conventions

| Topic | Rule | Evidence |
|---|---|---|
| Date of a row | Four shapes occur: an ISO string `YYYY-MM-DD` (`calendarDate` in daily files), an ISO datetime string (`asOfDateGmt`, `metaData.calendarDate`), an integer of epoch milliseconds (`calendarDate` in `HillScore`, `EnduranceScore`, `MetricsAcuteTrainingLoad`), and a list of numbers `[year, month, day, hour, minute, second]` in GMT (time fields of body-battery events in `UDSFile`). The key name is not a reliable hint. The epoch-millisecond `calendarDate` is a date label at 00:00 UTC; the `timestamp` of the same row can fall on the neighbouring day, so take the date from `calendarDate`. | Seen |
| Time zone | Fields ending in `GMT`/`Gmt` are UTC, `Local` are wall-clock time of the user. A day's window is given as four fields in the daily aggregate (`wellnessStart/EndTimeGmt`, `wellnessStart/EndTimeLocal`). | Seen |
| Rows | A file is a JSON array. `summarizedActivities` is an array of wrappers, each with a list under `summarizedActivitiesExport`. `weekly_training_report` is a wrapper around a list too. | Seen |
| Several rows per day | Possible (training metrics and VO2max have more than one row for some days, sometimes with different values). A day-level comparison must say which row it uses. | Seen |
| Which day a row belongs to | A night of sleep belongs to the local day of waking up. A pulse-alert event belongs to its local day. A body-battery event belongs to the day that contains its update time, not necessarily its start (an event that begins the evening before belongs to the day of waking). | Seen |
| Device | Most metric files carry `deviceId`; the daily aggregate and sleep files do not. The serial number in the first message (`file_id`) of every FIT file is the same number as that `deviceId`, so monitoring and sleep files identify the device that recorded their day. | Seen |
| Units | Durations in seconds (sleep, stress) or milliseconds (`durationInMilliseconds`), distances in metres, **floors as metres** (`floorsAscendedInMeters`, not a floor count). | Seen |
| Scaling | In FIT files, HRV values are stored multiplied by 128. | Seen: after dividing by 128 all 45 values of the compared night equalled the API's; the same factor is reported by a third-party project (section 11) |
| Empty values | A key can be present with `null` (for example sleep durations on nights without data). A fill rate of 100 % for a key does not mean usable values. | Seen |

## 4. JSON file families (health and activity related)

Fill rates are for the observed export and are only a hint of what is typically present.

| Family | One row is | Date key | Notable fields (fill rate) | Evidence |
|---|---|---|---|---|
| `UDSFile` | one day | `calendarDate` (string) | steps, goal, calories (`total`, `active`, `bmr`), distance, intensity minutes, floors (metres), `minHeartRate`, `maxHeartRate`, `restingHeartRate` (see 7), `currentDayRestingHeartRate`, `allDayStress` (dict), `bodyBattery`, `respiration`, `averageSpo2Value`, `lowestSpo2Value`, `abnormalHeartRateAlertsCount`; flags `includes*` | Seen |
| `sleepData` | one night | `calendarDate` | window timestamps, `deepSleepSeconds`, `lightSleepSeconds`, `remSleepSeconds`, `awakeSleepSeconds`, `unmeasurableSeconds` (about 70 %); `sleepScores`, `spo2SleepSummary`, `averageRespiration`, `avgSleepStress`, `breathingDisruptionSeverity`, `napList` (about 20 %) | Seen |
| `TrainingReadinessDTO` | one day | `calendarDate` (string) | `level`, `score`, factor percentages and feedback texts, `recoveryTime`, `hrvWeeklyAverage` | Seen |
| `MetricsMaxMetData` | one measurement | `calendarDate` (string) | `vo2MaxValue` (whole number), `deviceId`, `maxMetCategory`, `sport`, `subSport` (about 50 %) | Seen |
| `TrainingHistory` | one status entry (a day can have several, with and without sport) | `calendarDate` (string) | `trainingStatus` (text; the API's counterpart is a numeric code), `fitnessLevelTrend`, `weeklyTrainingLoadSum`, `loadTunnelMin/Max` (about 60 %) | Seen |
| `MetricsAcuteTrainingLoad` | one day | `calendarDate` (epoch ms) | `acwrPercent`, `acwrStatus`, `dailyTrainingLoadAcute/Chronic`, `dailyAcuteChronicWorkloadRatio` | Seen |
| `EnduranceScore`, `HillScore` | one day | `calendarDate` (epoch ms) | `overallScore`, `classification`, contributors; hill: classification ids | Seen |
| `MetricsHeatAltitudeAcclimation` | one day | `calendarDate` (string) | acclimation percentages and timestamps | Seen |
| `RunRacePredictions` | one day | `calendarDate` (string) | `raceTime5K/10K/Half/Marathon` | Seen |
| `healthStatusData` | one day | `calendarDate` | `outliersCount`, `createTimestampUTC`, `updateTimestampUTC`, `metrics[]`: `type` (HRV, HR, SPO2, SKIN_TEMP_C, RESPIRATION), `value` (missing in about a fifth of the metrics), `baselineLowerLimit/UpperLimit`, `percentage`, `status` (for example `IN_RANGE`), `feedbackKey` | Seen |
| `AbnormalHrEvents` | one event | `calendarDate`, `abnormalHrEventGMT` | `abnormalHrThresholdValue`, `abnormalHrValue`, `deviceId` | Seen |
| `HydrationLogFile` | one entry | `calendarDate` | `valueInML`, `estimatedSweatLossInML`, `hydrationSource`, `activityId` | Seen |
| `fitnessAgeData` | one measurement | `asOfDateGmt` | bio age fields, `biometricVo2Max`, BMI, `rhr` | Seen |
| `userBioMetrics` | one change event | `metaData.calendarDate` | `weight.*` (about 10 %), `vo2MaxRunning` (about 90 %), height | Seen |
| `summarizedActivities` | one activity | `startTimeGmt`/`startTimeLocal` (epoch ms, numeric) | `activityId`, name, sport, duration, distance, heart rate, `deviceId`, `timeZoneId`, `courseId`, `hrTimeInZone_*` | Seen |
| `gear`, `personalRecord`, `courses` | equipment with `gearActivityDTOs`, records with `activityId`, saved routes | various | link to activities through `activityId`/`courseId` | Seen |

## 5. FIT files

FIT files hold the high-resolution data and the original activity files. The type is the number in field 0 of the first message (`file_id`). Garmin's public page on FIT file types lists only 4 activity, 5 workout and 6 course (link in section 11); the other types below were identified from their content, so their names are **working names** of this guide. Message numbers are the numeric identifiers observed in the files; the names given to types and messages are working labels of this guide, not Garmin terminology. A meaning is given only where it was established from export data (compared with API values in the GLA spike); otherwise the entry says "not interpreted".

| Type | Working name | Files per year (rough) | Content | Evidence |
|---|---|---|---|---|
| 4 | activity | about 60 (very uneven, depends on how active the user was) | one activity: records, laps, session summary, device information | Public, Seen |
| 32 | all-day monitoring | about 1,700 (about 5 per day) | heart rate (message 55, field 27), stress and body battery (227), respiration (297, only in part of the files) | Seen: heart rate very close to the API's (high correlation, small average deviation); body battery nearly identical; stress similar but not the same signal (moderate correlation); respiration plausible (moderate correlation) |
| 49 | sleep | about 1,400 (about 4 per day) | sleep stages (message 275; all checked segments equal to the API's) and a further message (274) whose content looks like movement data (not compared with API values) | Seen |
| 44 | metrics | about 700 (very uneven, from under 100 to over 1,500 in single years) | mixed: readiness (messages 369 and 284), race predictions (339), sleep score (330 and 384); further messages not interpreted | Seen (values equal to the API's on the checked day), partly not interpreted |
| 68 | HRV | about 370 per year of occurrence (about 1 per day) | HRV summary (370) and HRV values (371, value / 128) | Seen: all checked values equal to the API's |
| 58 | 1-minute records | about 1,200 per year of occurrence (about 3 per day) | one message (318) with several hundred entries per file; not step counts | Seen, not interpreted |
| 41 | unknown | about 1,000 in total; the invalid timestamp rules out a per-year value | one message (217); `time_created` is invalid | Seen, not interpreted |
| 79 | unknown | about 370 per year of occurrence (about 1 per day) | messages 470 and 471 | Seen, not interpreted |
| 35 | rare type | a single file | header messages only | Seen, not interpreted |
| 72, 74 | rare types | one file each | header messages and, in the type 72 file, a few further messages | Seen, not interpreted |

Message numbers that occur in the files of types 32, 41, 44, 49, 58, 68 and 79 of the observed export and are not described above (numbers only, not interpreted here): 12, 21, 22, 23, 24, 35, 49, 103, 162, 188, 211, 229, 232, 233, 241, 269, 273, 276, 279, 281, 294, 346, 355, 356, 357, 378, 382, 402, 403, 404, 407, 408, 410, 412, 430, 484, 521. The list was taken from a count over all FIT files of that export, not from any Garmin document. A decoder must tolerate messages it does not know.

Rates are rounded and for one export; the type is read from the first message of each file. "Per year of occurrence" means per year in which the type exists at all: the types 68, 58 and 79 appear only in the last year and a half or so of the observed history, so their yearly rates are not averages over the whole history.

## 6. Export against API data

The account export is a separate representation of account data. Its coverage and field semantics differ from those of the Connect API. For the same day they are often equal, sometimes not.

| Topic | Export | API | Evidence |
|---|---|---|---|
| Resting heart rate | `restingHeartRate` in the daily aggregate is the **7-day average**; the day value is `currentDayRestingHeartRate` | `restingHeartRate` is the day value; the 7-day average is `lastSevenDaysAvgRestingHeartRate` | Seen |
| Stress | daily aggregate with averages and durations per phase (total, awake, asleep); no intraday series in the JSON | intraday `stressValuesArray` when the device recorded it; the day average is `avgStressLevel` where the export aggregate says `averageStressLevel` | Seen |
| Sleep | stage durations and a window; scores only where the device produced them | richer daily DTO (window flags, REM data, more timestamps) | Seen |
| Intraday heart rate | FIT monitoring records every 60 s in the sample day | records every 120 s on the same day (about twice as many values in the export) | Seen (one day) |
| VO2max | whole numbers; several rows for days with several measurements | decimal values; for such days the API holds the highest value of the day (rounded) | Seen |
| Race predictions | one row per day with a date | the endpoint returns the **current** prediction whatever day is requested | Seen |
| Activity files | the original FIT files | the original download is byte-identical (all checked samples) | Seen |
| Activity summary | at least as rich as the API's activity JSON | | Seen |
| Training status history | `TrainingHistory` status entries as text; a day can have several, because the status is updated during the day | `training_status` per day as a numeric code; the same days appear in both, and the codes agree with the text on nearly all days that have one entry | Seen |
| Warning fields | pulse-alert counter, breathing-disruption severity, acute-load status and body-battery events in the daily files | the same fields in the API data (daily stats, sleep, training status, body battery); equal on every compared day | Seen |
| Single pulse-alert events, health status | `AbnormalHrEvents`, `healthStatusData` | no method found in the unofficial Python wrapper GLA uses, and no such key in the archived API data | Seen (export only) |
| Measurements the device never took | absent or `null` | absent or `null` | Seen |

Rule of thumb. The export is a **second source for the same day, not a superset**. In the observed export every daily aggregate field that GLA takes over (steps, goal, calories, distance, intensity minutes, minimum and maximum heart rate, stress average and maximum) equalled the API value on every compared day (about five years of days; floors within one by rounding); only the stress durations per phase exist in the export alone. For VO2max all days of the export were already in the API-fed archive. Treat each family as unknown until its unique days have been counted against the archive.

## 7. Quirks that cost time

Each item: what is wrong with the obvious reading, and how it was seen. GLA-specific consequences are in the GLA docs, not here. Items 4, 5, 15 and 19 contain reading rules; those are derived from the observations, not stated by Garmin.

**JSON files**

1. **Resting heart rate.** `restingHeartRate` in `UDSFile` is the 7-day average; the day value is `currentDayRestingHeartRate`. Against the API on the same days: the first equals `lastSevenDaysAvgRestingHeartRate` on practically every compared day, the second equals the API's day value on every compared day (about five years of days). *Seen.*
2. **Sleep placeholder window.** For nights without recorded sleep the file can hold only a window flagged `UNCONFIRMED` whose length is exactly 5.0 hours (roughly a quarter of all days of the observed history, in one stretch of about three years). It is a placeholder, not a measurement; a duration must not be derived from it. *Seen.*
3. **Off-wrist nights.** `sleepWindowConfirmationType` can be `OFF_WRIST` with all phase values 0 where the API has empty values. *Seen.*
4. **Sleep duration is not a field.** It has to be computed. Summing deep, light and REM differs from the API's "window minus awake" by about a minute on a few days (rounding of the phases). *Seen.*
5. **Local timestamps in activities.** `startTimeLocal` is a wall-clock time stored as an epoch value (observation); read it as if it were UTC to get the local date (reading rule). The observed export uses milliseconds; GLA's reader also accepts seconds (a value above 10^10 counts as milliseconds). *Seen.*
6. **Day windows on daylight-saving days.** The four window fields of the daily aggregate (`wellnessStart/EndTime…`) are wrong on most spring and autumn transition days in the observed export (roughly two thirds): the end offset stands at the start as well, or the window is 24 hours long. The offset at the end of a window was right in every case examined. *Seen.*
7. **Date types differ between families** (string against epoch milliseconds), and the same key name can have either. *Seen.*
8. **Floors are metres.** `floorsAscendedInMeters` is a length (about 3 m per floor), not a count. *Seen.*
9. **Several rows for one day** with different values occur in metric files; a day-level comparison must say which row it takes. For VO2max the API holds the highest value of the day (rounded). *Seen.*
10. **Present key, no value.** Keys with `null`, empty lists or only a version marker are common (for example `bodyBattery` in the daily aggregate carries only `bodyBatteryVersion` on many days). Presence of a key proves nothing; count filled values. *Seen.*
11. **Field availability varies.** The observed `TrainingReadinessDTO` has a `score` that is almost always filled (943 of 947 entries in the observed export), while GLA's reader did not store it before v1.7.6.5 (a code comment there said the export has none). Read the file, not older notes. *Seen.*
12. **Defensive reading.** A list may contain entries that are not objects, and ranges of neighbouring files may overlap so that one day appears twice. *Assumed* (GLA skips non-objects with a warning; for training readiness the entry with the latest `timestamp` wins, for the other kinds the last entry read). In the observed export the several readiness rows of a day lie inside one file, in ascending order of `timestamp` (250 of 593 days, up to 8 rows); the six dates found in two files hold identical rows. *Seen.*

**FIT files**

13. **File names are upload ids.** The date has to come from the content (`file_id.time_created`, or the records). *Seen.*
14. **Duplicates.** The same file can occur twice (about one per year of history in the observed export, which is about 2 in 10,000 files), and the same second can carry another value in two files (about two seconds per year of history). Decide by a stable rule (for example the earlier `time_created`, then the content hash), not by reading order. *Seen.*
15. **Timestamps.** FIT times are UTC seconds since 1989-12-31 (confirmed in the GLA spike by matching timestamps with the API's); a 16-bit timestamp must be completed from the last full one (nearest distance modulo 65,536, reading rule). The plain rule "a smaller value means roll-over" moves a record that lies a minute out of order by 18 hours (rare in the observed export). *Seen.*
16. **Records without a heart rate.** Records with heart rate 0 occur and are not measurements (about 1,200 samples per year of history in the observed export); about 150,000 monitoring records per year (about 400 per day) carry no heart rate because they hold other metrics. *Seen.*
17. **Container limits.** The export ZIP contains ZIPs (two levels in the observed export); the largest FIT file was a few hundred KB; compressed timestamp headers did not occur in any of the files checked (all files of the observed history). Read in memory with size and depth limits. *Seen.*
18. **Names carry the account e-mail address** in several families. A tool must neither store nor log them. *Seen.*

**Days and devices**

19. **Which day a row belongs to.** Do not take the date from a timestamp when the row has a date field, and do not assume start time decides the day: a night belongs to the day of waking, a body-battery event to the day of its update time, an epoch-millisecond `calendarDate` is a label at 00:00 UTC (see section 3). *Seen.*
20. **Two devices on one day.** A day can have monitoring files from two devices (worn in parallel, or a change on that day), and there can be days without any device file. One device per day is therefore not always right, and a missing device should stay unknown. *Seen.*

## 8. How GLA uses the export (GLA-specific, version-bound)

This section describes the GLA software, not the export format. Valid for GLA 1.7.6.8; check the current docs for later versions.

- The JSON phase of the bulk import reads `UDSFile`, `sleepData`, `TrainingReadinessDTO`, `summarizedActivities` and, since v1.7.6.7, `healthStatusData` and `AbnormalHrEvents` and writes the day values to `bulk/aggregates`; the raw originals go to `bulk/source` (by hash).
- Since v1.7.6.7 the JSON files of the families `gear`, `personalRecord`, `courses` and the zone files (`heartRateZones`, `powerZones`) are kept unchanged in `bulk/source` and nothing is read from them. The file-name patterns of `gear`, `personalRecord` and `courses` come from the folder listing in section 2 and have not been checked against a sample; the zone files were. A file that matches none of the patterns is only counted (inventory in the import result: counts per kind and the folders of the unknown files, never a file name). A JSON file over 64 MB is skipped.
- Since v1.7.6.8 the import compares, for seven fields both sources deliver (steps, resting, minimum and maximum heart rate, stress average, sleep duration as the sum of deep, light and REM seconds, floors), every day of the export with the API day in `raw/` and prints per field how many days are equal, added by the export or differing (tolerances: sleep 60 s, floors 1). It overwrites and stores nothing; it runs only when an export is imported. On the observed archive about 2,840 compared days gave, per field, at most two differing days (the last day of the export and one older day) and, for sleep, three days added by the export; the paths that carry the comparison differ between the sources (the stress average is `averageStressLevel` in the export and `avgStressLevel` in the API day; the pulse extremes of an API day are in `user_summary`).
- The heart-rate phase reads the FIT files, keeps the originals in `bulk/source` and writes the heart-rate series per day to `bulk/raw`.
- Since v1.7.6.5 the day values in `bulk/aggregates` can be built again from the JSON originals in `bulk/source` without the export (a step of the sync, preview first); the kind of each original is found from its content (see `detect_kind` in `REFERENCE_GARMIN.md`).
- Files and fields not read today include `MetricsMaxMetData`, `TrainingHistory`, the Endurance, Hill, acclimation and prediction files, and warning fields inside the files that are read. `healthStatusData` and `AbnormalHrEvents` are stored (v1.7.6.7) but no query, dashboard or export reads them yet.

## 9. Open points

- Yearly rates are averages over the observed history and hide uneven years (activities and type 44 vary strongly between years).
- Fill rates and examples from one export only; a second export (other account, other devices) is needed to separate "device-dependent" from "Garmin-wide".
- Evidence for the community statements (folder names, delivery time) is second-hand.
- The meaning of FIT types 41, 58 (beyond "1-minute records") and 79, and of the message numbers listed in section 5, is not interpreted.
- Names of the working types are not confirmed by any Garmin source.
- The numeric codes of the API's training status were matched to the export's text values by how often they occur together, not from a Garmin source.
- The provenance of conventions reported by third-party projects (the HRV factor, the sleep stage codes) has not been traced to a public source; here they stand on the comparison with API values.

## 10. Reporting differences

If your export looks different (other folders, other file patterns, other keys, other FIT types), open an issue and describe the **structure only**: file-name patterns with the dates, numbers and e-mail part replaced (`D`, `N`, `<mail>`), top-level folder names, key names with their JSON type and a rough fill rate, FIT file types with rough counts, and the month you obtained the export. Never attach files, values, names, ids or coordinates. A script that produces such a structure listing is not part of GLA yet.

## 11. Method and sources

How the statements in this guide were obtained. Evidence levels are defined at the top.

- **Own analysis of one export** (*Seen*). Folder layout, file families, keys, fill rates, FIT file types and message numbers were read from one export with scripts written for the purpose (a small FIT reader without a library, JSON walkers). Counts and rates come from these runs.
- **Comparison with API data** (*Seen*, with the comparison named). Where a day exists in the export and in the Garmin Connect API data that GLA archives, the values were compared (exact equality or correlation, as stated). A meaning is given to a FIT message only where such a comparison supports it; every other message number is listed as not interpreted.
- **Garmin's public pages** (*Public*). Only the statement of this page is marked Public: FIT file types 4 activity, 5 workout, 6 course, and the `type` field of the `file_id` message. <https://developer.garmin.com/fit/articles/file-types/file_types.html> (read 2026-10-22).
- **Third-party sources** (*Community*), each named. Pages that were not opened are not cited.
  - garmin-local-mcp, <https://github.com/anup-shesh/garmin-local-mcp> (MIT licence). Used to cross-check two facts, the HRV factor 128 and the sleep stage codes; both were then confirmed against API values. No text, list or code was taken.
  - Garmin Connect forum threads (read 2026-10-22; posts several years old): <https://forums.garmin.com/apps-software/mobile-apps-web/f/garmin-connect-web/227203/how-do-i-batch-export-all-of-my-historical-data-not-just-one-activity-at-a-time> quotes the account page's delivery estimate; <https://forums.garmin.com/apps-software/mobile-apps-web/f/garmin-connect-web/275263/data-export-garmin-connect> names the folder `DI-Connect-Fitness-Uploaded-Files`.
- **What this guide does not do.** It does not reproduce Garmin FIT SDK source code, comments or documentation. Names of FIT file types are working names derived from content, and a message number carries a meaning only on the grounds above. Names and numbers may coincide with those in Garmin's public documentation or software; that does not imply endorsement by Garmin.
- **Updating.** A new statement is added with its evidence level and, for Community, a named source that was opened and whose licence was checked.
