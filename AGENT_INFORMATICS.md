# Agent Informatics and Logic Index

This document is a navigation map for future agents. It explains where logic lives, what state matters, and which functions are responsible for each decision path.

Last updated: 2026-03-30

## 1) Fast Intent Map

If the task is about X, start in Y:

- Live timing behavior (start/switch/stop task): `timesheet.py` -> `startTask`, `_closeActiveSegment`, `_recordSegment`
- Daily save behavior: `timesheet.py` -> `endDay`, `_saveTimelineForDate`
- Cross-day split behavior: `timesheet.py` -> `_rolloverIfNeeded`, `_processRolloverPunchesAndPosts`
- App close save behavior: `timesheet.py` -> `onClose`
- Charge code posting behavior: `timesheet.py` -> `_queueChargeCodePost`, `updateLoop`, `postChargeCodeHours`
- Timesheet API transport/details: `posting.py`
- History summaries/charts UI: `openHistory.py`
- Day timeline editor behavior: `openEdit.py`
- Settings and charge code pull/write: `settings.py`
- Installer metadata: `setup.iss`


## 2) File Responsibilities

- `timesheet.py`
  - Main application runtime, state machine, persistence, punch/post orchestration.
- `openHistory.py`
  - History window, pay period grouping, summary rendering, timeline chart interactions.
- `openEdit.py`
  - Day-level timeline edit modal (create/move/resize/delete segments).
- `settings.py`
  - Settings modal, color and group settings, charge-code pull/update, env writing.
- `posting.py`
  - HTTP/session/cookie helpers for Hour Timesheet endpoints.
- `tasks.jsonl` (in app data dir, not repo root at runtime)
  - Primary persisted task/group/history/charge-code data store.


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
  - `_postAfterPunchOut(postTaskSecondsSnapshot, dateKey=dayKey)` posts only the newly added portion on append saves
  - clears in-memory day session state

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
- queue charge code post only for the incremental snapshot/dateKey

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
- `postChargeCodeHours(...)` rebinds the posting session to `dateKey` before posting when needed
- `postChargeCodeHours(...)` should use the charge-code cache for that exact `dateKey`, not only the latest JSONL refresh
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


## 7) History and Edit Coupling

- `openHistory.py` expects day timelines that are day-local.
- `openEdit.py` works in seconds since midnight (`0..86399`) for a specific `dayKey`.

Implication:

- Cross-day timeline segments should be split before persisting day records.
- Avoid storing a single segment that visually spans past midnight inside one `dayKey`.


## 8) Where to Change Common Requests

- "Change when rollover triggers"
  - `timesheet.py` -> `_ensureCurrentDayContext`, call sites of `_rolloverIfNeeded`
- "Change split boundary (23:59:59 vs 23:59)"
  - `timesheet.py` -> `_rolloverIfNeeded`
- "Change punch ordering or retries"
  - `timesheet.py` -> `_processRolloverPunchesAndPosts`
- "Change charge code posting date mapping"
  - `timesheet.py` -> `_queueChargeCodePost`, `updateLoop`, `postChargeCodeHours`
- "Change summary rounding rules"
  - `timesheet.py` -> `_normalizeRoundedHours`
- "Change persistence rewrite behavior"
  - `timesheet.py` -> `append_history_entry`, `rewrite_data_file`


## 9) Invariants and Guardrails

- `dayTimeline` entries should have `end > start`.
- Day editor assumptions break if a day timeline contains true cross-midnight single segments.
- Rollover split must save prior day before resetting in-memory state.
- Charge-code queue should remain list-based, not single-item, when split days are possible.
- Any behavior that changes save triggers must be reviewed in both `endDay` and `onClose`.


## 10) Minimal Validation Checklist

Use these before claiming rollover/charge-code behavior is correct:

1. Same-day session, single task, end day:
   - one history day record
   - one punch out
   - one charge code post for that date
2. Session crossing midnight then end day next morning:
   - prior day saved with end near `23:59:59`
   - current day saved from `00:00:00` onward
   - rollover `OUT` then `IN` punches executed
   - charge code posts occur for both dates
3. Close without end day:
   - prior day is still split/saved/posted at midnight
   - current day close choice only affects the current day remainder
