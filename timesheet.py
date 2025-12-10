import tkinter as tk
from tkinter import messagebox
import time
import os
import sys
import json
from datetime import date, timedelta, datetime

class TaskTimerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Task Timer")

        self.bgColor = "#111315"
        self.cardColor = "#1e2227"
        self.accentColor = "#3f8cff"
        self.textColor = "#e5e5e5"
        self.activeColor = "#254a7a"

        self.baseWidth = 400
        self.baseHeight = 260
        self.rowHeight = 40

        self.root.configure(bg=self.bgColor)
        self.root.geometry(f"{self.baseWidth}x400")

        self.tasks = {}
        self.rows = {}
        self.currentTask = None
        self.currentStart = None
        self.history = {}
        self.groups = {}

        self.dragTaskName = None
        self.dragFromIndex = None
        self.dragCurrentIndex = None
        self.dragStartY = 0
        self.dragGhost = None

        self.hasEverSelectedTask = False
        self.unassignedSeconds = 0.0
        self.unassignedStart = None

        self.hasUnsavedTime = False

        self.dataFile = os.path.join(self.getBaseDir(), "tasks.json")

        self.dayTimeline = []
        self.minSegmentSeconds = 6 * 60

        self.buildUi()
        self.loadData()
        self.relayoutRows()
        self.updateLoop()

        self.root.bind("<Delete>", self.deleteSelected)
        self.root.protocol("WM_DELETE_WINDOW", self.onClose)

    def getBaseDir(self):
        return os.path.dirname(os.path.abspath(sys.argv[0]))

    def buildUi(self):
        topBar = tk.Frame(self.root, bg=self.bgColor)
        topBar.grid(row=0, column=0, columnspan=2, padx=12, pady=(10, 4), sticky="we")
        topBar.columnconfigure(0, weight=1)
        topBar.columnconfigure(1, weight=0)

        title = tk.Label(
            topBar,
            text="Task Timer",
            font=("Segoe UI", 18, "bold"),
            fg=self.textColor,
            bg=self.bgColor
        )
        title.grid(row=0, column=0, sticky="w")

        historyBtn = tk.Button(
            topBar,
            text="History",
            font=("Segoe UI", 10, "bold"),
            bg="#1b1f24",
            fg=self.textColor,
            activebackground="#2c3440",
            activeforeground=self.textColor,
            relief="flat",
            command=self.openHistory
        )
        historyBtn.grid(row=0, column=1, sticky="e", padx=(8, 0))

        subtitle = tk.Label(
            self.root,
            text="Click a task to switch · End Day for summary",
            font=("Segoe UI", 9),
            fg="#9099a6",
            bg=self.bgColor
        )
        subtitle.grid(row=1, column=0, columnspan=2, padx=12, pady=(0, 8), sticky="w")

        self.newTaskEntry = tk.Entry(
            self.root,
            font=("Segoe UI", 11),
            bg="#1b1f24",
            fg=self.textColor,
            insertbackground=self.textColor,
            relief="flat"
        )
        self.newTaskEntry.grid(row=2, column=0, padx=(12, 6), pady=6, sticky="we")
        self.newTaskEntry.bind("<Return>", self.onEntryReturn)

        self.addTaskButton = tk.Button(
            self.root,
            text="Add Task",
            font=("Segoe UI", 11, "bold"),
            bg=self.accentColor,
            fg="#ffffff",
            activebackground="#5b98ff",
            activeforeground="#ffffff",
            relief="flat",
            command=self.addTask
        )
        self.addTaskButton.grid(row=2, column=1, padx=(6, 12), pady=6, sticky="we")

        self.tasksFrame = tk.Frame(self.root, bg=self.bgColor)
        self.tasksFrame.grid(row=3, column=0, columnspan=2, padx=12, pady=(4, 6), sticky="nwe")
        self.tasksFrame.columnconfigure(0, weight=1)
        self.tasksFrame.columnconfigure(1, weight=0)

        self.endDayButton = tk.Button(
            self.root,
            text="End Day / Summary",
            font=("Segoe UI", 13, "bold"),
            bg=self.accentColor,
            fg="#ffffff",
            activebackground="#5b98ff",
            activeforeground="#ffffff",
            relief="flat",
            command=self.endDay,
            height=1
        )
        self.endDayButton.grid(row=4, column=0, columnspan=2, padx=12, pady=(4, 12), sticky="we")

        self.root.columnconfigure(0, weight=1)

    def onEntryReturn(self, event):
        self.addTask()
        return "break"

    def loadData(self):
        if not os.path.exists(self.dataFile):
            return
        try:
            with open(self.dataFile, "r", encoding="utf-8") as f:
                data = json.load(f)
            for name in data.get("tasks", []):
                self.createTaskRow(name)
            self.history = data.get("history", {})
            self.groups = data.get("groups", {}) or {}
        except Exception:
            self.history = {}

    def saveData(self):
        names = list(self.rows.keys())
        data = {
            "tasks": names,
            "history": self.history,
            "groups": self.groups
        }
        try:
            with open(self.dataFile, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def adjustWindowHeight(self):
        self.root.update_idletasks()
        width = self.root.winfo_width()
        if width <= 0:
            width = self.baseWidth
        count = len(self.rows)
        height = self.baseHeight + self.rowHeight * count + 20
        self.root.geometry(f"{width}x{height}")

    def createTaskRow(self, name):
        if name in self.rows:
            return

        rowIndex = len(self.rows)

        rowFrame = tk.Frame(self.tasksFrame, bg=self.cardColor)
        rowFrame.grid(row=rowIndex, column=0, sticky="we", pady=1)
        rowFrame.columnconfigure(0, weight=0)
        rowFrame.columnconfigure(1, weight=1)
        rowFrame.columnconfigure(2, weight=0)

        def onClick(event, n=name):
            self.startTask(n)

        handleLabel = tk.Label(
            rowFrame,
            text="≡",
            font=("Segoe UI", 14, "bold"),
            bg=self.cardColor,
            fg="#777777",
            anchor="center",
            width=3,
            height=1
        )
        handleLabel.grid(row=0, column=0, padx=(4, 6), pady=4, sticky="nsew")
        rowFrame.grid_rowconfigure(0, weight=1)
        rowFrame.grid_columnconfigure(0, weight=0)

        handleLabel.bind("<Button-1>", lambda e, n=name: self.startDrag(n, e))
        handleLabel.bind("<B1-Motion>", self.onDrag)
        handleLabel.bind("<ButtonRelease-1>", self.endDrag)

        rowFrame.bind("<Button-1>", onClick)

        nameLabel = tk.Label(
            rowFrame,
            text=name,
            font=("Segoe UI", 11, "bold"),
            bg=self.cardColor,
            fg=self.textColor,
            anchor="w"
        )
        nameLabel.grid(row=0, column=1, padx=(4, 6), pady=4, sticky="w")
        nameLabel.bind("<Button-1>", onClick)

        deleteBtn = tk.Button(
            rowFrame,
            text="×",
            font=("Segoe UI", 10, "bold"),
            bg=self.cardColor,
            fg="#ff6b6b",
            activebackground="#3a1f1f",
            activeforeground="#ffaaaa",
            relief="flat",
            bd=0,
            command=lambda n=name: self.deleteTaskPrompt(n)
        )
        deleteBtn.grid(row=0, column=2, padx=(4, 8), pady=4, sticky="ne")

        timeLabel = tk.Label(
            self.tasksFrame,
            text="0.00s",
            font=("Segoe UI", 11),
            fg="#c9d1d9",
            bg=self.bgColor,
            anchor="e"
        )
        timeLabel.grid(row=rowIndex, column=1, padx=(6, 0), pady=1, sticky="e")
        timeLabel.bind("<Button-1>", onClick)

        self.rows[name] = (rowFrame, nameLabel, timeLabel, deleteBtn)
        self.tasks[name] = self.tasks.get(name, 0.0)

    def relayoutRows(self):
        for i, name in enumerate(self.rows.keys()):
            rowFrame, nameLabel, timeLabel, deleteBtn = self.rows[name]
            rowFrame.grid_configure(row=i, column=0, sticky="we", pady=3)
            timeLabel.grid_configure(row=i, column=1, padx=(6, 0), pady=3, sticky="e")
        self.adjustWindowHeight()

    def addTask(self):
        name = self.newTaskEntry.get().strip()
        if not name:
            return
        if name in self.rows:
            self.newTaskEntry.delete(0, tk.END)
            return
        self.createTaskRow(name)
        self.relayoutRows()
        self.saveData()
        self.newTaskEntry.delete(0, tk.END)

    def startUnassigned(self, now=None):
        if not self.hasEverSelectedTask:
            return
        if now is None:
            now = time.time()
        if self.unassignedStart is None:
            self.unassignedStart = now
            self.hasUnsavedTime = True

    def stopUnassigned(self, now=None):
        if self.unassignedStart is None:
            return
        if now is None:
            now = time.time()
        self.unassignedSeconds += now - self.unassignedStart
        self.unassignedStart = None

    def _recordSegment(self, label, startTs, endTs):
        if not label or startTs is None or endTs is None:
            return
        duration = endTs - startTs
        if duration <= 0 or duration < self.minSegmentSeconds:
            return
        startIso = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(startTs))
        endIso = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(endTs))
        self.dayTimeline.append({
            "task": label,
            "start": startIso,
            "end": endIso
        })

    def _closeActiveSegment(self, now=None):
        if now is None:
            now = time.time()
        if self.currentTask is not None and self.currentStart is not None:
            self._recordSegment(self.currentTask, self.currentStart, now)
        elif self.unassignedStart is not None:
            self._recordSegment("Untasked", self.unassignedStart, now)

    def startTask(self, name):
        now = time.time()

        if self.dragTaskName is not None:
            return

        self._closeActiveSegment(now)

        if self.currentTask == name:
            if self.currentStart is not None:
                elapsed = now - self.currentStart
                self.tasks[self.currentTask] = self.tasks.get(self.currentTask, 0.0) + elapsed
            self.currentTask = None
            self.currentStart = None
            self.startUnassigned(now)
            self.hasUnsavedTime = True
            self.refreshRowStyles()
            return

        if self.currentTask is not None and self.currentStart is not None:
            elapsed = now - self.currentStart
            self.tasks[self.currentTask] = self.tasks.get(self.currentTask, 0.0) + elapsed
            self.currentTask = None
            self.currentStart = None

        self.stopUnassigned(now)

        self.hasEverSelectedTask = True
        self.currentTask = name
        self.currentStart = now
        self.hasUnsavedTime = True
        self.refreshRowStyles()

    def refreshRowStyles(self):
        for name, (rowFrame, nameLabel, timeLabel, deleteBtn) in self.rows.items():
            if name == self.dragTaskName:
                bg = "#2a2f37"
                bd = 2
                relief = "raised"
            elif name == self.currentTask:
                bg = self.activeColor
                bd = 0
                relief = "flat"
            else:
                bg = self.cardColor
                bd = 0
                relief = "flat"
            rowFrame.config(bg=bg, bd=bd, relief=relief)
            nameLabel.config(bg=bg)
            deleteBtn.config(bg=bg)

    def deleteTaskPrompt(self, name):
        if name not in self.rows:
            return
        if not messagebox.askyesno("Delete Task", f"Delete task '{name}'? This does not remove past summaries."):
            return

        now = time.time()

        if self.currentTask == name and self.currentStart is not None:
            self._closeActiveSegment(now)
            elapsed = now - self.currentStart
            self.tasks[name] = self.tasks.get(name, 0.0) + elapsed
            self.currentTask = None
            self.currentStart = None
            self.startUnassigned(now)

        rowFrame, nameLabel, timeLabel, deleteBtn = self.rows[name]
        rowFrame.destroy()
        timeLabel.destroy()
        del self.rows[name]
        if name in self.tasks:
            del self.tasks[name]

        self.relayoutRows()
        self.saveData()

    def deleteSelected(self, event=None):
        if self.currentTask is not None:
            self.deleteTaskPrompt(self.currentTask)

    def updateLoop(self):
        for name, baseSeconds in self.tasks.items():
            extra = 0.0
            if name == self.currentTask and self.currentStart is not None:
                extra = time.time() - self.currentStart
            total = baseSeconds + extra
            if total < 60:
                text = f"{total:05.2f}s"
            else:
                s = int(total)
                h = s // 3600
                m = (s % 3600) // 60
                sec = s % 60
                text = f"{h}:{m:02d}:{sec:02d}"
            if name in self.rows:
                _, _, timeLabel, _ = self.rows[name]
                timeLabel.config(text=text)
        self.root.after(50, self.updateLoop)

    def _parseSummaryText(self, text):
        agg = {}
        total = 0.0
        for line in text.splitlines():
            if ":" not in line:
                continue
            name, rest = line.split(":", 1)
            name = name.strip()
            rest = rest.strip()
            if not rest:
                continue
            token = rest.split()[0]
            try:
                hours = float(token)
            except ValueError:
                continue
            if name.lower() == "total":
                continue
            agg[name] = agg.get(name, 0.0) + hours
            total += hours
        return agg, total

    def _groupAggregates(self, taskAgg):
        grouped = {}
        for task, hours in taskAgg.items():
            group = self.groups.get(task)
            if not group:
                continue
            grouped[group] = grouped.get(group, 0.0) + hours
        return grouped

    def _mergeSummaryForDate(self, dateKey, newSummary, allowSkip=False):
        existingEntry = self.history.get(dateKey)
        if not existingEntry:
            return newSummary, "new"

        if isinstance(existingEntry, dict):
            existingText = existingEntry.get("summary", "") or ""
        else:
            existingText = existingEntry or ""

        dialog = tk.Toplevel(self.root)
        dialog.title("Existing summary")
        dialog.configure(bg=self.bgColor)
        dialog.resizable(False, False)

        dialog.transient(self.root)
        dialog.grab_set()
        dialog.lift()
        dialog.focus_force()

        dialog.attributes("-topmost", True)
        dialog.after(100, lambda: dialog.attributes("-topmost", False))

        msg = tk.Label(
            dialog,
            text="A summary already exists for this date.\n\nChoose what to do:",
            font=("Segoe UI", 10),
            fg=self.textColor,
            bg=self.bgColor,
            justify="left"
        )
        msg.pack(padx=16, pady=(12, 8), anchor="w")

        choice = {"value": None}

        btnFrame = tk.Frame(dialog, bg=self.bgColor)
        btnFrame.pack(padx=16, pady=(0, 12), anchor="e")

        def setChoice(v):
            choice["value"] = v
            dialog.destroy()

        appendBtn = tk.Button(
            btnFrame,
            text="Append",
            font=("Segoe UI", 9, "bold"),
            bg="#1b1f24",
            fg=self.textColor,
            activebackground="#2c3440",
            activeforeground=self.textColor,
            relief="flat",
            command=lambda: setChoice("append")
        )
        appendBtn.grid(row=0, column=0, padx=4)

        overwriteBtn = tk.Button(
            btnFrame,
            text="Overwrite",
            font=("Segoe UI", 9, "bold"),
            bg="#1b1f24",
            fg=self.textColor,
            activebackground="#2c3440",
            activeforeground=self.textColor,
            relief="flat",
            command=lambda: setChoice("overwrite")
        )
        overwriteBtn.grid(row=0, column=1, padx=4)

        if allowSkip:
            skipBtn = tk.Button(
                btnFrame,
                text="Close without saving",
                font=("Segoe UI", 9, "bold"),
                bg="#1b1f24",
                fg=self.textColor,
                activebackground="#2c3440",
                activeforeground=self.textColor,
                relief="flat",
                command=lambda: setChoice("skip")
            )
            skipBtn.grid(row=0, column=2, padx=4)

            cancelBtn = tk.Button(
                btnFrame,
                text="Cancel",
                font=("Segoe UI", 9),
                bg="#1b1f24",
                fg=self.textColor,
                activebackground="#2c3440",
                activeforeground=self.textColor,
                relief="flat",
                command=lambda: setChoice("cancel")
            )
            cancelBtn.grid(row=0, column=3, padx=4)
        else:
            cancelBtn = tk.Button(
                btnFrame,
                text="Cancel",
                font=("Segoe UI", 9),
                bg="#1b1f24",
                fg=self.textColor,
                activebackground="#2c3440",
                activeforeground=self.textColor,
                relief="flat",
                command=lambda: setChoice("cancel")
            )
            cancelBtn.grid(row=0, column=2, padx=4)

        dialog.bind("<Escape>", lambda e: setChoice("cancel"))

        self.root.update_idletasks()
        rx = self.root.winfo_rootx()
        ry = self.root.winfo_rooty()
        rw = self.root.winfo_width()
        rh = self.root.winfo_height()
        dw = 420
        dh = 140
        x = rx + (rw - dw) // 2
        y = ry + (rh - dh) // 2
        dialog.geometry(f"{dw}x{dh}+{x}+{y}")

        dialog.wait_window()

        if choice["value"] in (None, "cancel"):
            return None, "cancel"
        if choice["value"] == "skip":
            return "__SKIP__", "skip"
        if choice["value"] == "overwrite":
            return newSummary, "overwrite"

        newAgg, _ = self._parseSummaryText(newSummary)
        oldAgg, _ = self._parseSummaryText(existingText)

        combined = dict(oldAgg)
        for name, hours in newAgg.items():
            combined[name] = combined.get(name, 0.0) + hours

        totalHours = sum(combined.values())
        lines = []
        for name, hours in sorted(combined.items(), key=lambda kv: kv[0].lower()):
            lines.append(f"{name}: {hours} h")
        lines.append(f"Total: {totalHours} h")
        return "\n".join(lines), "append"

    def endDay(self):
        now = time.time()

        self._closeActiveSegment(now)

        if self.currentTask is not None and self.currentStart is not None:
            elapsed = now - self.currentStart
            self.tasks[self.currentTask] = self.tasks.get(self.currentTask, 0.0) + elapsed
            self.currentTask = None
            self.currentStart = None
            self.refreshRowStyles()

        self.stopUnassigned(now)

        if not self.tasks and self.unassignedSeconds <= 0:
            messagebox.showinfo("Summary", "No tasks for today.")
            return

        lines = []
        totalHours = 0.0

        for name, seconds in self.tasks.items():
            hours = seconds / 3600.0
            rounded = round(hours, 1)
            totalHours += rounded
            lines.append(f"{name}: {rounded:.1f} h")

        if self.unassignedSeconds > 0:
            unHours = self.unassignedSeconds / 3600.0
            unRounded = round(unHours, 1)
            totalHours += unRounded
            lines.append(f"Untasked: {unRounded:.1f} h")

        lines.append(f"Total: {totalHours:.1f} h")
        summary = "\n".join(lines)

        todayKey = date.today().isoformat()
        merged, choice = self._mergeSummaryForDate(todayKey, summary)
        if merged is None:
            return

        existingEntry = self.history.get(todayKey)
        existingTimeline = []
        if isinstance(existingEntry, dict):
            existingTimeline = existingEntry.get("timeline", []) or []

        if choice == "append" and existingTimeline:
            timeline = existingTimeline + list(self.dayTimeline)
        else:
            timeline = list(self.dayTimeline)

        self.history[todayKey] = {
            "summary": merged,
            "timeline": timeline
        }
        self.saveData()
        self.dayTimeline = []

        self.root.clipboard_clear()
        self.root.clipboard_append(merged)
        messagebox.showinfo("Summary (copied to clipboard)", merged)

        self.hasUnsavedTime = False

    def createDragGhost(self, name):
        if name not in self.rows:
            return
        rowFrame, nameLabel, timeLabel, deleteBtn = self.rows[name]

        self.root.update_idletasks()
        h = rowFrame.winfo_height() or self.rowHeight
        w = self.tasksFrame.winfo_width() - 4
        y = rowFrame.winfo_y()

        ghost = tk.Frame(self.tasksFrame, bg=self.cardColor, bd=2, relief="ridge")
        ghost.place(x=0, y=y, width=w, height=h)

        label = tk.Label(
            ghost,
            text=name,
            font=("Segoe UI", 11, "bold"),
            bg=self.cardColor,
            fg=self.textColor,
            anchor="w"
        )
        label.pack(fill="both", padx=10, pady=8)

        self.dragGhost = ghost

    def startDrag(self, name, event):
        self.dragTaskName = name
        names = list(self.rows.keys())
        try:
            idx = names.index(name)
        except ValueError:
            self.dragFromIndex = None
            self.dragCurrentIndex = None
            return
        self.dragFromIndex = idx
        self.dragCurrentIndex = idx
        self.dragStartY = event.y_root

        self.createDragGhost(name)
        self.refreshRowStyles()

    def onDrag(self, event):
        if self.dragTaskName is None or self.dragFromIndex is None:
            return
        if self.dragGhost is None:
            return

        tasksTop = self.tasksFrame.winfo_rooty()
        tasksHeight = self.tasksFrame.winfo_height()
        yInside = event.y_root - tasksTop

        self.dragGhost.update_idletasks()
        gh = self.dragGhost.winfo_height() or self.rowHeight
        newY = max(0, min(yInside - gh / 2, tasksHeight - gh))
        self.dragGhost.place_configure(y=newY)

        names = list(self.rows.keys())
        if not names:
            return

        targetIndex = len(names) - 1
        for i, n in enumerate(names):
            rowFrame, _, _, _ = self.rows[n]
            top = rowFrame.winfo_rooty()
            bottom = top + rowFrame.winfo_height()
            mid = (top + bottom) / 2
            if event.y_root < mid:
                targetIndex = i
                break

        try:
            oldPos = names.index(self.dragTaskName)
        except ValueError:
            return

        if targetIndex == oldPos:
            return

        names.pop(oldPos)
        names.insert(targetIndex, self.dragTaskName)

        newRows = {}
        for n in names:
            newRows[n] = self.rows[n]
        self.rows = newRows

        self.dragCurrentIndex = targetIndex
        self.relayoutRows()

    def onClose(self):
        now = time.time()

        self._closeActiveSegment(now)

        if self.currentTask is not None and self.currentStart is not None:
            elapsed = now - self.currentStart
            self.tasks[self.currentTask] = self.tasks.get(self.currentTask, 0.0) + elapsed
            self.currentTask = None
            self.currentStart = None
            self.refreshRowStyles()

        self.stopUnassigned(now)

        if self.hasUnsavedTime:
            lines = []
            totalHours = 0.0

            for name, seconds in self.tasks.items():
                hours = seconds / 3600.0
                totalHours += hours
                lines.append(f"{name}: {hours} h")

            if self.unassignedSeconds > 0:
                unHours = self.unassignedSeconds / 3600.0
                totalHours += unHours
                lines.append(f"Untasked: {unHours} h")

            lines.append(f"Total: {totalHours} h")
            summary = "\n".join(lines)

            todayKey = date.today().isoformat()
            merged, choice = self._mergeSummaryForDate(todayKey, summary, allowSkip=True)

            if merged is None or choice == "cancel":
                return

            if merged == "__SKIP__" or choice == "skip":
                self.hasUnsavedTime = False
                self.dayTimeline = []
                self.root.destroy()
                return

            existingEntry = self.history.get(todayKey)
            existingTimeline = []
            if isinstance(existingEntry, dict):
                existingTimeline = existingEntry.get("timeline", []) or []

            if choice == "append" and existingTimeline:
                timeline = existingTimeline + list(self.dayTimeline)
            else:
                timeline = list(self.dayTimeline)

            self.history[todayKey] = {
                "summary": merged,
                "timeline": timeline
            }
            self.saveData()
            self.hasUnsavedTime = False
            self.dayTimeline = []

        self.root.destroy()

    def endDrag(self, event):
        if self.dragGhost is not None:
            self.dragGhost.destroy()
            self.dragGhost = None

        if self.dragTaskName is None:
            return
        self.dragTaskName = None
        self.dragFromIndex = None
        self.dragCurrentIndex = None
        self.dragStartY = 0
        self.refreshRowStyles()
        self.saveData()

    def openHistory(self):
        self.loadData()
        if not self.history:
            messagebox.showinfo("History", "No summaries saved yet.")
            return

        anchorStart = date(2025, 11, 29)
        ppMap = {}

        for dStr in self.history.keys():
            try:
                d = date.fromisoformat(dStr)
            except ValueError:
                continue
            offset = (d - anchorStart).days
            idx = offset // 14
            ppStart = anchorStart + timedelta(days=idx * 14)
            ppEnd = ppStart + timedelta(days=13)
            key = (ppStart, ppEnd)
            if key not in ppMap:
                ppMap[key] = []
            ppMap[key].append(dStr)

        if not ppMap:
            messagebox.showinfo("History", "No valid dated summaries.")
            return

        periods = []
        for (start, end), days in ppMap.items():
            daysSorted = sorted(days, reverse=True)
            periods.append({
                "start": start,
                "end": end,
                "days": daysSorted
            })
        periods.sort(key=lambda p: p["start"], reverse=True)

        def parseDaySummary(dayStr):
            entry = self.history.get(dayStr, "")
            if isinstance(entry, dict):
                summary = entry.get("summary", "") or ""
            else:
                summary = entry or ""
            agg = {}
            total = 0.0
            for line in summary.splitlines():
                if ":" not in line:
                    continue
                name, rest = line.split(":", 1)
                name = name.strip()
                rest = rest.strip()
                if not rest:
                    continue
                numToken = rest.split()[0]
                try:
                    hours = float(numToken)
                except ValueError:
                    continue
                if name.lower() == "total":
                    continue
                agg[name] = agg.get(name, 0.0) + hours
                total += hours
            return agg, total

        def collectAllTasks():
            names = set()
            for entry in self.history.values():
                if isinstance(entry, dict):
                    summary = entry.get("summary", "") or ""
                else:
                    summary = entry or ""
                for line in summary.splitlines():
                    if ":" not in line:
                        continue
                    name, _ = line.split(":", 1)
                    name = name.strip()
                    if not name or name.lower() == "total":
                        continue
                    names.add(name)
            return sorted(names)

        for p in periods:
            agg = {}
            total = 0.0
            for dStr in p["days"]:
                dayAgg, dayTotal = parseDaySummary(dStr)
                for k, v in dayAgg.items():
                    agg[k] = agg.get(k, 0.0) + v
                total += dayTotal
            p["agg"] = agg
            p["total"] = total

        histWin = tk.Toplevel(self.root)
        histWin.title("History")
        histWin.configure(bg=self.bgColor)
        histWin.withdraw()

        dw, dh = 900, 500

        self.root.update_idletasks()
        rx = self.root.winfo_rootx()
        ry = self.root.winfo_rooty()
        rw = self.root.winfo_width()
        rh = self.root.winfo_height()

        x = rx + (rw - dw) // 2
        y = ry + (rh - dh) // 2
        histWin.geometry(f"{dw}x{dh}+{x}+{y}")

        histWin.deiconify()
        histWin.transient(self.root)
        histWin.lift()
        histWin.focus_force()
        histWin.attributes("-topmost", True)
        histWin.after(100, lambda: histWin.attributes("-topmost", False))

        histWin.columnconfigure(0, weight=0)
        histWin.columnconfigure(1, weight=0)
        histWin.columnconfigure(2, weight=1)
        histWin.columnconfigure(3, weight=0)
        histWin.rowconfigure(0, weight=1)
        histWin.rowconfigure(1, weight=0)

        ppFrame = tk.Frame(histWin, bg=self.bgColor)
        ppFrame.grid(row=0, column=0, padx=8, pady=8, sticky="ns")
        ppLabel = tk.Label(
            ppFrame,
            text="Pay Periods",
            font=("Segoe UI", 10, "bold"),
            fg=self.textColor,
            bg=self.bgColor
        )
        ppLabel.pack(anchor="w")

        ppListbox = tk.Listbox(
            ppFrame,
            height=1,
            width=20,
            bg="#1b1f24",
            fg=self.textColor,
            selectbackground=self.accentColor,
            selectforeground="#ffffff",
            borderwidth=0,
            highlightthickness=0,
            font=("Segoe UI", 10)
        )
        ppListbox.pack(fill="both", expand=True, pady=(4, 0))

        for p in periods:
            start = p["start"]
            end = p["end"]
            label = f"{start.strftime('%b %d')} – {end.strftime('%b %d, %Y')}"
            ppListbox.insert(tk.END, label)

        dayFrame = tk.Frame(histWin, bg=self.bgColor)
        dayFrame.grid(row=0, column=1, padx=8, pady=8, sticky="ns")
        dayLabel = tk.Label(
            dayFrame,
            text="Days",
            font=("Segoe UI", 10, "bold"),
            fg=self.textColor,
            bg=self.bgColor
        )
        dayLabel.pack(anchor="w")

        dayListbox = tk.Listbox(
            dayFrame,
            height=14,
            width=14,
            bg="#1b1f24",
            fg=self.textColor,
            selectbackground=self.accentColor,
            selectforeground="#ffffff",
            borderwidth=0,
            highlightthickness=0,
            font=("Segoe UI", 10)
        )
        dayListbox.pack(fill="both", expand=True, pady=(4, 0))

        textFrame = tk.Frame(histWin, bg=self.bgColor)
        textFrame.grid(row=0, column=2, padx=(0, 8), pady=8, sticky="nsew")
        textFrame.rowconfigure(0, weight=0)
        textFrame.rowconfigure(1, weight=1)
        textFrame.rowconfigure(2, weight=0)
        textFrame.rowconfigure(3, weight=1)
        textFrame.columnconfigure(0, weight=2)
        textFrame.columnconfigure(1, weight=1)

        daySummaryLabel = tk.Label(
            textFrame,
            text="Daily Summary",
            font=("Segoe UI", 10, "bold"),
            fg=self.textColor,
            bg=self.bgColor
        )
        daySummaryLabel.grid(row=0, column=0, sticky="w")

        timelineLabel = tk.Label(
            textFrame,
            text="Timeline",
            font=("Segoe UI", 10, "bold"),
            fg=self.textColor,
            bg=self.bgColor
        )
        timelineLabel.grid(row=0, column=1, sticky="w")

        daySummaryBox = tk.Text(
            textFrame,
            bg="#1b1f24",
            fg=self.textColor,
            wrap="word",
            borderwidth=0,
            highlightthickness=0,
            font=("Segoe UI", 10)
        )
        daySummaryBox.grid(row=1, column=0, sticky="nsew", pady=(4, 8))

        timelineCanvas = tk.Canvas(
            textFrame,
            bg="#1b1f24",
            highlightthickness=0
        )
        timelineCanvas.grid(row=1, column=1, sticky="nsew", padx=(8, 0), pady=(4, 8))
        rectTaskMap = {}
        tooltip = {"win": None, "item": None}

        ppSummaryLabel = tk.Label(
            textFrame,
            text="Pay Period Overview",
            font=("Segoe UI", 10, "bold"),
            fg=self.textColor,
            bg=self.bgColor
        )
        ppSummaryLabel.grid(row=2, column=0, columnspan=2, sticky="w")

        ppSummaryBox = tk.Text(
            textFrame,
            bg="#1b1f24",
            fg=self.textColor,
            wrap="word",
            borderwidth=0,
            highlightthickness=0,
            font=("Segoe UI", 10)
        )
        ppSummaryBox.grid(row=3, column=0, columnspan=2, sticky="nsew", pady=(4, 0))
        ppPieCanvas = tk.Canvas(
            textFrame,
            bg="#1b1f24",
            highlightthickness=0
        )
        ppPieCanvas.grid(row=3, column=1, sticky="nsew", padx=(8, 0), pady=(4, 0))
        pieSlices = {}
        pieTooltip = {"win": None, "item": None}
        ppColorMap = {}

        groupingFrame = tk.Frame(histWin, bg=self.bgColor)
        groupingFrame.grid(row=0, column=3, padx=(0, 8), pady=8, sticky="ns")

        groupingLabel = tk.Label(
            groupingFrame,
            text="Task Groups",
            font=("Segoe UI", 10, "bold"),
            fg=self.textColor,
            bg=self.bgColor
        )
        groupingLabel.pack(anchor="w")

        taskListbox = tk.Listbox(
            groupingFrame,
            height=16,
            width=26,
            bg="#1b1f24",
            fg=self.textColor,
            selectbackground=self.accentColor,
            selectforeground="#ffffff",
            borderwidth=0,
            highlightthickness=0,
            font=("Segoe UI", 10),
            selectmode=tk.EXTENDED
        )
        taskListbox.pack(fill="both", expand=True, pady=(4, 8))

        groupEntry = tk.Entry(
            groupingFrame,
            font=("Segoe UI", 10),
            bg="#1b1f24",
            fg=self.textColor,
            insertbackground=self.textColor,
            relief="flat"
        )
        groupEntry.pack(fill="x", pady=(0, 6))

        groupBtnFrame = tk.Frame(groupingFrame, bg=self.bgColor)
        groupBtnFrame.pack(anchor="e")

        setGroupBtn = tk.Button(
            groupBtnFrame,
            text="Set Group",
            font=("Segoe UI", 9, "bold"),
            bg="#1b1f24",
            fg=self.textColor,
            activebackground="#2c3440",
            activeforeground=self.textColor,
            relief="flat"
        )
        setGroupBtn.grid(row=0, column=0, padx=4)

        clearGroupBtn = tk.Button(
            groupBtnFrame,
            text="Clear Group",
            font=("Segoe UI", 9),
            bg="#1b1f24",
            fg=self.textColor,
            activebackground="#2c3440",
            activeforeground=self.textColor,
            relief="flat"
        )
        clearGroupBtn.grid(row=0, column=1, padx=4)

        current = {"ppIndex": 0}
        allTasks = collectAllTasks()
        taskNames = list(allTasks)

        def formatLines(total, taskAgg):
            lines = [f"Total: {total:.1f} h"]

            grouped = {}
            ungrouped = {}
            for task, hours in taskAgg.items():
                group = self.groups.get(task)
                if group:
                    grouped.setdefault(group, []).append((task, hours))
                else:
                    ungrouped[task] = hours

            groupItems = []
            for g, ths in grouped.items():
                gHours = sum(h for _, h in ths)
                groupItems.append((g, gHours, ths))

            for g, gHours, ths in sorted(groupItems, key=lambda kv: kv[1], reverse=True):
                lines.append(f"{g}: {gHours:.1f} h")
                for t, h in sorted(ths, key=lambda kv: kv[1], reverse=True):
                    lines.append(f"  {t}: {h:.1f} h")

            for t, h in sorted(ungrouped.items(), key=lambda kv: kv[1], reverse=True):
                lines.append(f"{t}: {h:.1f} h")

            return lines

        listItems = []
        groupedTasks = {}

        def refreshTaskList():
            nonlocal taskNames, listItems, groupedTasks
            taskNames = collectAllTasks()
            listItems = []
            groupedTasks = {}

            for name in taskNames:
                g = self.groups.get(name)
                if g:
                    groupedTasks.setdefault(g, []).append(name)

            ungrouped = [name for name in taskNames if not self.groups.get(name)]

            taskListbox.delete(0, tk.END)

            for groupName in sorted(groupedTasks.keys()):
                listItems.append(("group", groupName))
                taskListbox.insert(tk.END, groupName)
                for task in sorted(groupedTasks[groupName]):
                    listItems.append(("task", task))
                    taskListbox.insert(tk.END, f"  {task}")

            for task in sorted(ungrouped):
                listItems.append(("task", task))
                taskListbox.insert(tk.END, task)

        def selectedTaskNames():
            sel = taskListbox.curselection()
            if not sel:
                return []
            selected = []
            seen = set()
            for idx in sel:
                if idx >= len(listItems):
                    continue
                itemType, value = listItems[idx]
                if itemType == "task":
                    if value not in seen:
                        selected.append(value)
                        seen.add(value)
                else:
                    for task in groupedTasks.get(value, []):
                        if task not in seen:
                            selected.append(task)
                            seen.add(task)
            return selected

        def groupForSelection():
            sel = taskListbox.curselection()
            if not sel:
                return None

            groupsFound = set()
            hasUngrouped = False

            for idx in sel:
                if idx >= len(listItems):
                    continue
                itemType, value = listItems[idx]
                if itemType == "group":
                    groupsFound.add(value)
                else:
                    g = self.groups.get(value, "")
                    if g:
                        groupsFound.add(g)
                    else:
                        hasUngrouped = True

            if len(groupsFound) == 1 and not hasUngrouped:
                return next(iter(groupsFound))
            if not groupsFound and hasUngrouped:
                return ""
            return None

        def drawPayPeriodPie(total, taskAgg):
            nonlocal pieSlices, ppColorMap

            ppPieCanvas.delete("all")
            pieSlices = {}
            ppColorMap = {}

            if total <= 0 or not taskAgg:
                return

            ppPieCanvas.update_idletasks()
            w = ppPieCanvas.winfo_width() or 160
            h = ppPieCanvas.winfo_height() or 160

            size = min(w, h) - 20
            if size <= 0:
                return

            cx = w / 2
            cy = h / 2
            r = size / 2

            items = sorted(taskAgg.items(), key=lambda kv: kv[1], reverse=True)

            colorFamilies = [
                {"base": "#3f8cff", "shades": ["#60a5fa", "#1d4ed8", "#93c5fd"]},  # blue
                {"base": "#10b981", "shades": ["#34d399", "#047857", "#6ee7b7"]},  # green
                {"base": "#f97316", "shades": ["#fb923c", "#c2410c", "#fed7aa"]},  # orange
                {"base": "#e11d48", "shades": ["#fb7185", "#9f1239", "#fecdd3"]},  # red
                {"base": "#8b5cf6", "shades": ["#a855f7", "#6d28d9", "#ddd6fe"]},  # purple
                {"base": "#06b6d4", "shades": ["#0ea5e9", "#0891b2", "#bae6fd"]},  # cyan
                {"base": "#facc15", "shades": ["#eab308", "#ca8a04", "#fef08a"]},  # yellow
                {"base": "#6366f1", "shades": ["#4f46e5", "#312e81", "#c7d2fe"]},  # indigo
            ]

            groups = {}
            ungrouped = []
            for name, hours in items:
                if hours <= 0:
                    continue
                g = self.groups.get(name)
                if g:
                    groups.setdefault(g, []).append(name)
                else:
                    ungrouped.append(name)

            groupNames = sorted(groups.keys())
            taskColor = {}

            # grouped tasks: same family, base + shades
            for idx, g in enumerate(groupNames):
                fam = colorFamilies[idx % len(colorFamilies)]
                shades = [fam["base"]] + fam["shades"]
                for i, taskName in enumerate(sorted(groups[g])):
                    c = shades[i % len(shades)]
                    taskColor[taskName] = c
                    ppColorMap[taskName] = c

            # ungrouped tasks: only main/base colors
            offset = len(groupNames)
            for j, taskName in enumerate(sorted(ungrouped)):
                fam = colorFamilies[(offset + j) % len(colorFamilies)]
                c = fam["base"]
                taskColor[taskName] = c
                ppColorMap[taskName] = c

            startAngle = 0.0
            for name, hours in items:
                if hours <= 0:
                    continue
                extent = 360.0 * (hours / total)
                color = taskColor.get(name, self.accentColor)
                labelText = f"{name} ({hours:.1f}h, {hours / total * 100:.0f}%)"

                item = ppPieCanvas.create_arc(
                    cx - r,
                    cy - r,
                    cx + r,
                    cy + r,
                    start=startAngle,
                    extent=extent,
                    fill=color,
                    outline="#111827"
                )
                pieSlices[item] = labelText
                startAngle += extent

        def showPieTooltip(event):
            items = ppPieCanvas.find_withtag("current")
            if not items:
                hidePieTooltip(event)
                return

            item = items[0]

            if item == pieTooltip["item"] and pieTooltip["win"] is not None:
                return

            labelText = pieSlices.get(item)
            if not labelText:
                hidePieTooltip(event)
                return

            if pieTooltip["win"] is not None:
                pieTooltip["win"].destroy()

            tw = tk.Toplevel(ppPieCanvas)
            tw.wm_overrideredirect(True)
            tw.configure(bg="#000000")

            x = event.x_root + 10
            y = event.y_root + 10
            tw.wm_geometry(f"+{x}+{y}")

            lbl = tk.Label(
                tw,
                text=labelText,
                bg="#111827",
                fg="#f9fafb",
                font=("Segoe UI", 8)
            )
            lbl.pack(ipadx=4, ipady=2)

            pieTooltip["win"] = tw
            pieTooltip["item"] = item

        def hidePieTooltip(event):
            if pieTooltip["win"] is not None:
                pieTooltip["win"].destroy()
                pieTooltip["win"] = None
            pieTooltip["item"] = None

        def showPayPeriodSummary():
            ppIdx = current["ppIndex"]
            if ppIdx < 0 or ppIdx >= len(periods):
                ppSummaryBox.delete("1.0", tk.END)
                ppPieCanvas.delete("all")
                return
            p = periods[ppIdx]
            agg = p.get("agg", {})
            total = p.get("total", 0.0)

            drawPayPeriodPie(total, agg)

            lines = formatLines(total, agg)

            ppSummaryBox.delete("1.0", tk.END)
            ppSummaryBox.insert(tk.END, "\n".join(lines))

            for name, color in ppColorMap.items():
                tagName = f"pp_{name}"
                try:
                    ppSummaryBox.tag_configure(tagName, foreground=color)
                except tk.TclError:
                    continue

                start = "1.0"
                pattern = f"{name}:"
                while True:
                    pos = ppSummaryBox.search(pattern, start, tk.END)
                    if not pos:
                        break
                    end = f"{pos}+{len(name)}c"
                    ppSummaryBox.tag_add(tagName, pos, end)
                    start = f"{end}+1c"

        def drawTimelineForDayKey(dayKey):
            nonlocal rectTaskMap

            rectTaskMap = {}
            timelineCanvas.delete("all")

            entry = self.history.get(dayKey)
            if isinstance(entry, dict):
                segments = entry.get("timeline") or []
            else:
                segments = []

            if not segments:
                return

            timelineCanvas.update_idletasks()
            width = timelineCanvas.winfo_width() or 260
            height = timelineCanvas.winfo_height() or 140

            marginLeft = 70
            marginRight = 10
            marginTop = 10
            marginBottom = 22

            areaTop = marginTop
            areaBottom = height - marginBottom
            if areaBottom <= areaTop:
                areaBottom = areaTop + 10

            tasks = sorted({(seg.get("task") or "Untasked") for seg in segments})
            nTasks = max(1, len(tasks))

            rowGap = 4
            totalHeight = areaBottom - areaTop
            rowHeight = max(6, (totalHeight - rowGap * (nTasks - 1)) / nTasks)

            taskToRow = {t: i for i, t in enumerate(tasks)}

            spanSec = 24 * 3600.0
            innerWidth = max(1, width - marginLeft - marginRight)

            palette = [
                self.accentColor,
                "#10b981",  # green
                "#f97316",  # orange
                "#e11d48",  # red/pink
                "#8b5cf6",  # purple
                "#06b6d4",  # cyan
                "#facc15",  # yellow
                "#6366f1",  # indigo
            ]
            colorMap = {}
            pi = 0
            for task in tasks:
                if task == "Untasked":
                    colorMap[task] = "#444c56"
                else:
                    colorMap[task] = palette[pi % len(palette)]
                    pi += 1

            for seg in segments:
                task = seg.get("task") or "Untasked"
                startStr = seg.get("start")
                endStr = seg.get("end")
                if not startStr or not endStr:
                    continue
                try:
                    startDt = datetime.fromisoformat(startStr)
                    endDt = datetime.fromisoformat(endStr)
                except Exception:
                    continue

                startSec = startDt.hour * 3600 + startDt.minute * 60 + startDt.second
                endSec = endDt.hour * 3600 + endDt.minute * 60 + endDt.second
                if endSec <= startSec:
                    continue

                rowIndex = taskToRow.get(task, 0)
                y1 = areaTop + rowIndex * (rowHeight + rowGap)
                y2 = y1 + rowHeight

                x1 = marginLeft + (startSec / spanSec) * innerWidth
                x2 = marginLeft + (endSec / spanSec) * innerWidth

                color = colorMap.get(task, self.accentColor)

                item = timelineCanvas.create_rectangle(
                    x1, y1, x2, y2,
                    fill=color,
                    outline=""
                )
                labelText = f"{task} {startDt.strftime('%H:%M')}–{endDt.strftime('%H:%M')}"
                rectTaskMap[item] = labelText

            for task, rowIndex in taskToRow.items():
                cy = areaTop + rowIndex * (rowHeight + rowGap) + rowHeight / 2
                timelineCanvas.create_text(
                    marginLeft - 6,
                    cy,
                    text=task,
                    anchor="e",
                    fill="#9ca3af",
                    font=("Segoe UI", 7)
                )

            axisY = areaBottom + 4
            tickY1 = axisY
            tickY2 = axisY + 4
            labelY = axisY + 10
            for hour in (0, 6, 12, 18, 24):
                x = marginLeft + (hour * 3600.0 / spanSec) * innerWidth
                timelineCanvas.create_line(x, tickY1, x, tickY2, fill="#6b7280")
                timelineCanvas.create_text(
                    x,
                    labelY,
                    text=f"{hour:02d}",
                    fill="#9ca3af",
                    font=("Segoe UI", 7)
                )

            legendY = marginTop
            legendX = marginLeft + innerWidth * 0.65
            for task in tasks:
                color = colorMap[task]
                timelineCanvas.create_rectangle(
                    legendX,
                    legendY,
                    legendX + 10,
                    legendY + 10,
                    fill=color,
                    outline=""
                )
                timelineCanvas.create_text(
                    legendX + 14,
                    legendY + 5,
                    text=task,
                    anchor="w",
                    fill="#9ca3af",
                    font=("Segoe UI", 7)
                )
                legendY += 14

        def showTooltip(event):
            items = timelineCanvas.find_withtag("current")
            if not items:
                hideTooltip(event)
                return

            item = items[0]

            if item == tooltip["item"] and tooltip["win"] is not None:
                return

            labelText = rectTaskMap.get(item)
            if not labelText:
                hideTooltip(event)
                return

            if tooltip["win"] is not None:
                tooltip["win"].destroy()

            tw = tk.Toplevel(timelineCanvas)
            tw.wm_overrideredirect(True)
            tw.configure(bg="#000000")

            x = event.x_root + 10
            y = event.y_root + 10
            tw.wm_geometry(f"+{x}+{y}")

            lbl = tk.Label(
                tw,
                text=labelText,
                bg="#111827",
                fg="#f9fafb",
                font=("Segoe UI", 8)
            )
            lbl.pack(ipadx=4, ipady=2)

            tooltip["win"] = tw
            tooltip["item"] = item

        def hideTooltip(event):
            if tooltip["win"] is not None:
                tooltip["win"].destroy()
                tooltip["win"] = None
            tooltip["item"] = None


        def showDaySummary(dayIdx):
            ppIdx = current["ppIndex"]
            if ppIdx < 0 or ppIdx >= len(periods):
                daySummaryBox.delete("1.0", tk.END)
                timelineCanvas.delete("all")
                return

            period = periods[ppIdx]
            if dayIdx < 0 or dayIdx >= len(period["days"]):
                daySummaryBox.delete("1.0", tk.END)
                timelineCanvas.delete("all")
                return

            dStr = period["days"][dayIdx]
            entry = self.history.get(dStr, "") or ""
            if isinstance(entry, dict):
                raw = entry.get("summary", "") or ""
            else:
                raw = entry

            taskAgg = {}
            total = 0.0
            for line in raw.splitlines():
                if ":" not in line:
                    continue
                name, rest = line.split(":", 1)
                name = name.strip()
                rest = rest.strip()
                if not rest:
                    continue
                token = rest.split()[0]
                try:
                    hours = float(token)
                except ValueError:
                    continue
                if name.lower() == "total":
                    continue
                taskAgg[name] = taskAgg.get(name, 0.0) + hours
                total += hours

            lines = formatLines(total, taskAgg)

            daySummaryBox.delete("1.0", tk.END)
            daySummaryBox.insert(tk.END, "\n".join(lines))
            drawTimelineForDayKey(dStr)

        def getSelectedDayIdx():
            sel = dayListbox.curselection()
            if not sel:
                return None
            return sel[0]

        def refreshDays():
            dayListbox.delete(0, tk.END)
            ppIdx = current["ppIndex"]
            if ppIdx < 0 or ppIdx >= len(periods):
                daySummaryBox.delete("1.0", tk.END)
                timelineCanvas.delete("all")
                return
            period = periods[ppIdx]
            for dStr in period["days"]:
                try:
                    d = date.fromisoformat(dStr)
                    label = d.strftime("%a %m-%d")
                except ValueError:
                    label = dStr
                dayListbox.insert(tk.END, label)
            showPayPeriodSummary()
            if period["days"]:
                dayListbox.selection_clear(0, tk.END)
                dayListbox.selection_set(0)
                showDaySummary(0)
            else:
                daySummaryBox.delete("1.0", tk.END)
                timelineCanvas.delete("all")

        def onPayPeriodSelect(event):
            sel = ppListbox.curselection()
            if not sel:
                return
            current["ppIndex"] = sel[0]
            refreshDays()

        def onDaySelect(event):
            sel = dayListbox.curselection()
            if not sel:
                return
            dayIdx = sel[0]
            showDaySummary(dayIdx)

        def onTaskSelect(event):
            g = groupForSelection()
            groupEntry.delete(0, tk.END)
            if g is None:
                return
            if g:
                groupEntry.insert(0, g)

        def setGroup():
            groupName = groupEntry.get().strip()
            if not groupName:
                return
            for task in selectedTaskNames():
                self.groups[task] = groupName
            self.saveData()
            refreshTaskList()
            showPayPeriodSummary()
            dayIdx = getSelectedDayIdx()
            if dayIdx is not None:
                showDaySummary(dayIdx)

        def clearGroup():
            changed = False
            for task in selectedTaskNames():
                if task in self.groups:
                    del self.groups[task]
                    changed = True
            if changed:
                self.saveData()
                refreshTaskList()
                showPayPeriodSummary()
                dayIdx = getSelectedDayIdx()
                if dayIdx is not None:
                    showDaySummary(dayIdx)

        ppListbox.bind("<<ListboxSelect>>", onPayPeriodSelect)
        ppPieCanvas.bind("<Motion>", showPieTooltip)
        ppPieCanvas.bind("<Leave>", hidePieTooltip)
        timelineCanvas.bind("<Motion>", showTooltip)
        timelineCanvas.bind("<Leave>", hideTooltip)
        dayListbox.bind("<<ListboxSelect>>", onDaySelect)
        taskListbox.bind("<<ListboxSelect>>", onTaskSelect)
        setGroupBtn.config(command=setGroup)
        clearGroupBtn.config(command=clearGroup)

        btnFrame = tk.Frame(histWin, bg=self.bgColor)
        btnFrame.grid(row=1, column=0, columnspan=4, padx=8, pady=(0, 8), sticky="e")

        closeBtn = tk.Button(
            btnFrame,
            text="Close",
            font=("Segoe UI", 10, "bold"),
            bg="#1b1f24",
            fg=self.textColor,
            activebackground="#2c3440",
            activeforeground=self.textColor,
            relief="flat",
            command=histWin.destroy
        )
        closeBtn.pack(anchor="e")

        histWin.bind("<Escape>", lambda e: histWin.destroy())

        if periods:
            ppListbox.selection_set(0)
            current["ppIndex"] = 0
            refreshDays()
            refreshTaskList()


if __name__ == "__main__":
    root = tk.Tk()
    app = TaskTimerApp(root)
    root.mainloop()
