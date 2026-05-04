# Agent Informatics and Logic Index

This document is a navigation map for future agents. It explains where logic lives, what state matters, and which functions are responsible for each decision path.

Last updated: 2026-04-21

## 1) Fast Intent Map

If the task is about X, start in Y:

- Live timing behavior (start/switch/stop task): `timesheet.py` -> `startTask`, `_closeActiveSegment`, `_recordSegment`
- Retroactive clock-in / recent-time reassignment: `timesheet.py` -> `retroClockIn`, `reassignRecentTime`, `_askTaskAndMinutes`, `_currentSelectedWindowStart`
- Daily save behavior: `timesheet.py` -> `endDay`, `_saveTimelineForDate`
- Cross-day split behavior: `timesheet.py` -> `_rolloverIfNeeded`, `_processRolloverPunchesAndPosts`
- App close save behavior: `timesheet.py` -> `onClose`
- Charge code sync behavior: `timesheet.py` -> `_queueChargeCodePost`, `updateLoop`, `postChargeCodeHours`, `_buildChargeCodePostingPlan`
- Timesheet API transport/details: `posting.py`
- History summaries/charts UI: `openHistory.py`
- Day timeline editor behavior: `openEdit.py`
- Settings and charge code pull/write: `settings.py`
- Installer metadata: `setup.iss`, `version_info.txt`


## 2) File Responsibilities

- `timesheet.py`
  - Main application runtime, state machine, persistence, punch/post orchestration.
  - Also owns dev-mode data-dir override (`DEV_MODE`, `DEV_DATA_DIR`, `DATA_DIR_OVERRIDE`) and the top-bar retro/fix actions.
- `openHistory.py`
  - History window, pay period grouping, summary rendering, timeline chart interactions.
- `openEdit.py`
  - Day-level timeline edit modal (create/move/resize/delete segments).
- `settings.py`
  - Settings modal, color and group settings, charge-code pull/update, env writing.
- `posting.py`
  - HTTP/session/cookie helpers for Hour Timesheet endpoints.
- `tasks.jsonl`
  - Primary persisted task/group/history/charge-code data store.
  - Runtime location depends on `getDataDir()`:
    - normal install: `%LOCALAPPDATA%\Task Tracker`
    - source testing with `DEV_MODE = True`: repo working directory (`DEV_DATA_DIR`, currently `"."`)


## 3) Runtime State Model (`TaskTrackerApp`)

Key mutable fields:

- `tasks: Dict[str, float]`
  - Accumulated seconds by task for current in-memory day session.
- `currentTask: Optional[str]`
  - Active selected task row.
- `currentStart: Optional[float]`
  - Epoch seconds when current task became active.
- `unassignedStart: Optional[float]`, `unassignedSeconds: float`
  - Untasked timing state.
- `dayTimeline: List[segment]`
  - Segments collected for the currently unsaved day.
- `history: Dict[YYYY-MM-DD, {summary, timeline}]`
  - Cached in-memory history map loaded from JSONL.
- `hasUnsavedTime: bool`
  - Guard for close/save prompts.
- `activeDayKey: YYYY-MM-DD`
  - Tracked day context used during rollover split processing.
- `DEV_MODE`, `DEV_DATA_DIR`, `DATA_DIR_OVERRIDE`
  - Data-dir / safety switches that change where the app reads-writes state and whether live posting is allowed.
- `timesheetDateKey: YYYY-MM-DD`
  - Tracks which date the current posting session / `timesheetId` is bound to.
- `_timesheetSessionLock`
  - Serializes punch/session/post work so remote session state is not raced by parallel threads.
- `_pendingChargePosts: List[{taskSecondsSnapshot, dateKey}]`
  - Queue consumed by `updateLoop` for charge code posting.

Segment shape:

```json
{
  "task": "Task Name",
  "start": "YYYY-MM-DDTHH:MM:SS",
  "end": "YYYY-MM-DDTHH:MM:SS"
}
```


## 4) Persistence Model (`tasks.jsonl`)

Record types:

- `{"type":"task","name":"..."}`
- `{"type":"group","task":"...","group":"..."}`
- `{"type":"chargeCode", ...}`
- `{"type":"history","date":"YYYY-MM-DD","summary":"...","timeline":[...]}`

Writers:

- `sync_task_group_section` writes task/group ordering while preserving history/chargeCode.
- `append_history_entry` replaces one day history record and rewrites file safely.
- `rewrite_data_file` full rewrite path (tasks/groups/history + preserved chargeCode/other).

Rule:

- Timeline is source-of-truth for computed summary in all modern save flows.
- Append saves now overlay incoming timeline segments onto the saved day instead of blindly stacking overlapping blocks.


## 5) Core Decision Flows

### A) Task activation and segment creation

Path:

- `startTask(name)`
  - calls `_ensureCurrentDayContext(now)` first
  - closes prior active segment via `_closeActiveSegment(now)`
  - accumulates elapsed seconds into `tasks`
  - sets `currentTask/currentStart`
  - may trigger `punchIn()` on first task of day (`shouldPunchIn`)

### B) End Day (primary save trigger)

Path:

- `endDay()`
  - calls `_rolloverIfNeeded(now)` first
  - closes active segment
  - merge policy prompt (`append/overwrite/cancel`)
  - `_saveTimelineForDate(dayKey, dayTimeline, mergeChoice)` builds a merged save plan
  - `_postAfterPunchOut(postTaskSecondsSnapshot, dateKey=dayKey)` now syncs the final full-day mapped charge-code totals for that date
  - clears in-memory day session state

### B2) Retroactive time tools

Current design:

- `retroClockIn()`
  - opens a GUI task/minutes chooser
  - writes the chosen `[now-minutes, now]` window directly into `dayTimeline`
  - rebuilds `tasks` from timeline
  - keeps the chosen task active from `now`
  - may issue a backdated `punchIn()` only when this is the first tracked time of the day
- `reassignRecentTime()`
  - is intended as an active-selection tool, not a general arbitrary-past editor
  - uses `_currentSelectedWindowStart()` to find the currently selected contiguous trailing block for the active task
  - clamps allowed minutes to that active selected window
  - rewrites only that trailing range to another task / charge-code key

### C) Cross-day split logic

Current design decision:

- Cross-day check runs continuously in `updateLoop()`.
- `endDay()` and `onClose()` also invoke rollover handling before their save/exit logic.

Path:

- `_rolloverIfNeeded(now)`
  - while `activeDay < currentDay`:
    - close segment at `23:59:59` of prior day
    - continue active timer at `00:00:00` next day
    - save prior day via `_saveTimelineForDate`
    - if the in-memory timeline already starts with the saved history for that date, avoid appending that prefix again
    - collect rollover punch/post work items
  - show rollover toast
  - `_processRolloverPunchesAndPosts(items)`

Rollover punch/post item behavior:

- punch `OUT` for prior day
- punch `IN` for next day
- queue charge code sync for the final saved snapshot/dateKey of that split day

### D) Close app flow

Path:

- `onClose()`
  - calls `_rolloverIfNeeded(now)` first
  - optional save prompt
  - closes active segment and saves the active day key
  - punches out and posts charge codes for that saved day key
  - drains queued rollover charge-code posts before destroying the app

### E) Charge code posting queue

Path:

- `_queueChargeCodePost(snapshot, dateKey)` appends queue item
- `updateLoop()` drains `_pendingChargePosts` and calls:
  - `postChargeCodeHours(snapshot, dateKey=item.dateKey)`
- `postChargeCodeHours(...)` rebinds the posting session to `dateKey` before syncing when needed
- `postChargeCodeHours(...)` should use the charge-code cache for that exact `dateKey`, not only the latest JSONL refresh
- `postChargeCodeHours(...)` now treats the payload as a full-day sync:
  - posts every loaded charge-code key for that date
  - includes `0.0` writes so removed/reassigned codes get cleared remotely
  - relies on the remote API overwriting prior values for the same charge code/date
- remote punch/session/post work is serialized by `_timesheetSessionLock`

Reason:

- Multi-item queue prevents split-day posts from overwriting one another.


## 6) Timesheet Punch Integration

Main functions:

- `initializePunchSession(punchDateKey=None)`
- `punchIn(punchDt=None, silent=False, setBusy=False)`
- `punchOut(punchDt=None, silent=False, setBusy=True)`

Behavior notes:

- Explicit `punchDt` is used for rollover boundary punches.
- When `punchDt` is omitted, normal rounding-to-workday behavior may apply.
- `punchIn/punchOut` return thread handles; callers may `join()` when ordering matters.
- `initializePunchSession(...)` now also updates `timesheetDateKey`.
- `initializePunchSession(...)` also refreshes and caches charge-code models for that specific `timesheetDateKey`.
- `startTask`, `deleteTaskPrompt`, and `clearDayData` now use `_ensureCurrentDayContext(...)` so user actions cannot bypass midnight rollover.
- When `DEV_MODE` is enabled, `punchIn`, `punchOut`, `postChargeCodeHours`, and `validateEnvFile` all short-circuit to avoid touching live Hour Timesheet state.


## 7) History and Edit Coupling

- `openHistory.py` expects day timelines that are day-local.
- `openEdit.py` works in seconds since midnight (`0..86399`) for a specific `dayKey`.

Implication:

- Cross-day timeline segments should be split before persisting day records.
- Avoid storing a single segment that visually spans past midnight inside one `dayKey`.
- `restoreTodayTimeline()` also rebuilds visible task totals from the restored timeline, so current-day reopen state is timeline-derived.


## 8) Where to Change Common Requests

- "Change when rollover triggers"
  - `timesheet.py` -> `_ensureCurrentDayContext`, call sites of `_rolloverIfNeeded`
- "Change split boundary (23:59:59 vs 23:59)"
  - `timesheet.py` -> `_rolloverIfNeeded`
- "Change punch ordering or retries"
  - `timesheet.py` -> `_processRolloverPunchesAndPosts`
- "Change retroactive time UX/limits"
  - `timesheet.py` -> `_askTaskAndMinutes`, `retroClockIn`, `reassignRecentTime`, `_currentSelectedWindowStart`
- "Change append save overlap behavior"
  - `timesheet.py` -> `_overlayTimelineSegments`, `_buildTimelineSavePlan`
- "Change charge code sync / overwrite behavior"
  - `timesheet.py` -> `_queueChargeCodePost`, `updateLoop`, `postChargeCodeHours`, `_buildChargeCodePostingPlan`
- "Change summary rounding rules"
  - `timesheet.py` -> `_normalizeRoundedHours`
- "Change persistence rewrite behavior"
  - `timesheet.py` -> `append_history_entry`, `rewrite_data_file`
- "Change dev-vs-live data location"
  - `timesheet.py` -> `DEV_MODE`, `DEV_DATA_DIR`, `DATA_DIR_OVERRIDE`, `resolveDataDirOverride`, `getDataDir`


## 9) Invariants and Guardrails

- `dayTimeline` entries should have `end > start`.
- Day editor assumptions break if a day timeline contains true cross-midnight single segments.
- Rollover split must save prior day before resetting in-memory state.
- Charge-code queue should remain list-based, not single-item, when split days are possible.
- Any behavior that changes save triggers must be reviewed in both `endDay` and `onClose`.
- Retroactive edits should rewrite timeline ranges, not only mutate `currentStart`, otherwise task totals and later edit limits drift apart.
- `Fix Recent` should remain bounded to the active selected window; broader arbitrary-past edits belong in the day editor/history flow.


## 10) Minimal Validation Checklist

Use these before claiming rollover/charge-code behavior is correct:

1. Same-day session, single task, end day:
   - one history day record
   - one punch out
   - one full-day charge code sync for that date
2. Session crossing midnight then end day next morning:
   - prior day saved with end near `23:59:59`
   - current day saved from `00:00:00` onward
   - rollover `OUT` then `IN` punches executed
   - charge code syncs occur for both dates
3. Close without end day:
   - prior day is still split/saved/posted at midnight
   - current day close choice only affects the current day remainder
4. Retroactive clock in then fix recent:
   - retro block appears immediately in `dayTimeline`
   - visible task totals rebuild from timeline
   - `Fix Recent` max minutes reflect the current selected contiguous block, not only `now - currentStart`
