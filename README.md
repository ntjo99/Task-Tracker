# Task Tracker

Simple desktop task timing with local history and optional Hour Timesheet sync.

## Features
- Task timing: start a task by clicking it, switch tasks at any time, and stop the active task by clicking it again.
- Retro clock-in: add recent missed time to a selected task.
- Fix Recent: move the currently selected recent block to another task or charge code.
- History: view saved daily summaries and pay-period rollups.
- Day editing: edit a saved day by dragging, resizing, creating, or deleting timeline blocks.
- Groups: group related tasks for cleaner history summaries and shared color families.
- Settings: configure work hours, rounding, colors, groups, and timesheet options.
- Hour Timesheet integration: optional punch in/out and charge-code syncing.
- Charge codes: map tasks or groups to charge codes and sync final saved day totals.
- Local persistence: tasks, history, groups, and charge-code data are stored locally.

## Data
- Normal runtime data lives in `%LOCALAPPDATA%\Task Tracker`.
- Source testing can use a local folder through the dev switches in `timesheet.py`.

## Build
```powershell
pyinstaller --clean timesheet.spec
```

Installer packaging is in `setup.iss`.
