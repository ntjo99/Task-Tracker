import tkinter as tk
from tkinter import messagebox
import time
import os
import sys
import json
import tempfile
import threading
from datetime import date, timedelta, datetime
from openHistory import openHistory as openHistoryImpl
from settings import openSettings as openSettingsImpl, loadSettings as loadSettingsImpl


def resourcePath(relPath):
	candidates = []
	if getattr(sys, "frozen", False):
		exeDir = os.path.dirname(sys.executable)
		candidates.append(exeDir)
		candidates.append(os.path.join(exeDir, "_internal"))
	baseDir = getattr(sys, "_MEIPASS", None)
	if baseDir:
		candidates.append(baseDir)
	candidates.append(os.path.dirname(os.path.abspath(__file__)))

	for base in candidates:
		path = os.path.join(base, relPath)
		if os.path.exists(path):
			return path
	# Fall back to first candidate or relative path
	if candidates:
		return os.path.join(candidates[0], relPath)
	return relPath

def getBaseDir(self):
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def getDataDir(self):
    appData = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or os.path.expanduser("~")
    dataDir = os.path.join(appData, "Task Tracker")
    os.makedirs(dataDir, exist_ok=True)
    return dataDir

class TaskTrackerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Task Tracker")
        iconPath = resourcePath("hourglass.ico")
        if os.path.exists(iconPath):
            try:
                self.root.iconbitmap(iconPath)
            except Exception:
                pass

        os.environ["TaskTracker_DATA_DIR"] = self.getDataDir()
        self._posting = None

        self.settings = loadSettingsImpl(os.path.join(self.getDataDir(), "settings.json"))
        self.minSegmentSeconds = self.settings["minRecordedMinutes"] * 60
        self.workDayStart = self.settings["workDayStart"]
        self.workDayEnd = self.settings["workDayEnd"]
        self.roundToHours = self.settings["roundToHours"]
        self.useTimesheetFunctions = self.settings.get("useTimesheetFunctions", False)
        self.autoChargeCodes = self.settings.get("autoChargeCodes", False)


        self.bgColor = "#111315"
        self.cardColor = "#1e2227"
        self.accentColor = "#3f8cff"
        self.textColor = "#e5e5e5"
        self.activeColor = "#254a7a"

        self.baseWidth = int(self.settings.get("mainWindowWidth", 400))
        self.baseHeight = int(self.settings.get("mainWindowHeight", 400))
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
        self.punchSession = None
        self.employeeId = None
        self.timesheetId = None

        self.toastWindow = None
        self.toastTimer = None

        self.validateEnvFile()

        baseDir = self.getDataDir()
        self.realPath = os.path.join(baseDir, "tasks.jsonl")
        self.dataFile = self.realPath
        self.dayTimeline = []

        self.buildUi()
        self.loadData()
        self.restoreTodayTimeline()
        self.relayoutRows()
        self.updateLoop()

        self.root.bind("<Delete>", self.deleteSelected)
        self.root.bind("<g>", self.startGeneralTask)
        self.root.bind("<G>", self.startGeneralTask)
        self.root.protocol("WM_DELETE_WINDOW", self.onClose)

    def _getPosting(self, showToast=False):
        if self._posting is not None:
            return self._posting
        try:
            import importlib
            self._posting = importlib.import_module("posting")
            return self._posting
        except Exception as e:
            if showToast:
                self.showToast(f"Posting unavailable: {e}", error=True)
            return None

    def getBaseDir(self):
        return os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))

    def getDataDir(self):
        appData = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or os.path.expanduser("~")
        dataDir = os.path.join(appData, "Task Tracker")
        os.makedirs(dataDir, exist_ok=True)
        return dataDir

    def restoreTodayTimeline(self):
        """Restore timeline from today's saved entry if it exists"""
        todayKey = date.today().isoformat()
        entry = self.history.get(todayKey)
        if isinstance(entry, dict):
            timeline = entry.get("timeline", []) or []
            if timeline:
                self.dayTimeline = [dict(seg) for seg in timeline]

    def buildUi(self):
        topBar = tk.Frame(self.root, bg=self.bgColor)
        topBar.grid(row=0, column=0, columnspan=2, padx=12, pady=(10, 4), sticky="we")
        topBar.columnconfigure(0, weight=1)
        topBar.columnconfigure(1, weight=0)
        topBar.columnconfigure(2, weight=0)
        topBar.columnconfigure(3, weight=0)

        title = tk.Label(
            topBar,
            text="Task Tracker",
            font=("Segoe UI", 18, "bold"),
            fg=self.textColor,
            bg=self.bgColor
        )
        title.grid(row=0, column=0, sticky="w")

        settingsBtn = tk.Button(
            topBar,
            text="⚙",
            font=("Segoe UI", 10, "bold"),
            bg="#1b1f24",
            fg=self.textColor,
            activebackground="#2c3440",
            activeforeground=self.textColor,
            relief="flat",
            command=self.openSettings
        )
        settingsBtn.grid(row=0, column=1, sticky="e", padx=(6, 0))

        clearBtn = tk.Button(
            topBar,
            text="Clear",
            font=("Segoe UI", 10, "bold"),
            bg="#1b1f24",
            fg=self.textColor,
            activebackground="#2c3440",
            activeforeground=self.textColor,
            relief="flat",
            command=self.clearDayData
        )
        clearBtn.grid(row=0, column=2, sticky="e", padx=(6, 0))

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
        historyBtn.grid(row=0, column=3, sticky="e", padx=(8, 0))

        subtitle = tk.Label(
            self.root,
            text="Click a task to switch · End Day for summary",
            font=("Segoe UI", 9),
            fg="#9099a6",
            bg=self.bgColor
        )
        subtitle.grid(row=2, column=0, columnspan=2, padx=12, pady=(0, 8), sticky="w")

        self.newTaskEntry = tk.Entry(
            self.root,
            font=("Segoe UI", 11),
            bg="#2b3138",
            fg=self.textColor,
            insertbackground=self.textColor,
            relief="flat",
            highlightthickness=1,
            highlightbackground="#0b0e12",
            highlightcolor="#0b0e12",
            bd=0
        )
        self.newTaskEntry.grid(row=3, column=0, padx=(12, 6), pady=6, sticky="we")
        self.newTaskEntry.bind("<Return>", self.onEntryReturn)
        self._applyPlaceholder(self.newTaskEntry, "Add a task…")

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
        self.addTaskButton.grid(row=3, column=1, padx=(6, 12), pady=6, sticky="we")

        self.tasksFrame = tk.Frame(self.root, bg=self.bgColor)
        self.tasksFrame.grid(row=4, column=0, columnspan=2, padx=12, pady=(4, 6), sticky="nwe")
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
        self.endDayButton.grid(row=5, column=0, columnspan=2, padx=12, pady=(4, 12), sticky="we")

        self.root.columnconfigure(0, weight=1)

    def showToast(self, message, timeout=3000, error=False):
        if self.toastTimer is not None:
            self.root.after_cancel(self.toastTimer)
            self.toastTimer = None
        
        if self.toastWindow is not None:
            try:
                self.toastWindow.destroy()
            except:
                pass
            self.toastWindow = None
        
        self.toastWindow = tk.Toplevel(self.root)
        self.toastWindow.configure(bg=self.bgColor)
        self.toastWindow.attributes('-alpha', 0.9)
        self.toastWindow.attributes('-topmost', True)
        self.toastWindow.overrideredirect(True)
        
        bgColor = "#8b3333" if error else "#2a2f37"
        
        toastLabel = tk.Label(
            self.toastWindow,
            text=message,
            font=("Segoe UI", 10),
            fg="#ffffff",
            bg=bgColor,
            anchor="center",
            padx=20,
            pady=10
        )
        toastLabel.pack()
        
        self.root.update_idletasks()
        rx = self.root.winfo_rootx()
        ry = self.root.winfo_rooty()
        rw = self.root.winfo_width()
        
        self.toastWindow.update_idletasks()
        tw = self.toastWindow.winfo_width()
        
        x = rx + (rw - tw) // 2
        y = ry + 20
        
        self.toastWindow.geometry(f"+{x}+{y}")
        
        def dismissToast():
            try:
                if self.toastWindow is not None:
                    self.toastWindow.destroy()
                    self.toastWindow = None
            except:
                pass
            self.toastTimer = None
        
        self.toastTimer = self.root.after(timeout, dismissToast)

    def _applyPlaceholder(self, entry, text):
        placeholderColor = "#6b7280"
        normalColor = self.textColor

        def on_focus_in(_):
            if entry.get() == text and entry.cget("fg") == placeholderColor:
                entry.delete(0, tk.END)
                entry.config(fg=normalColor)

        def on_focus_out(_):
            if not entry.get().strip():
                entry.delete(0, tk.END)
                entry.insert(0, text)
                entry.config(fg=placeholderColor)

        entry.bind("<FocusIn>", on_focus_in, add="+")
        entry.bind("<FocusOut>", on_focus_out, add="+")
        on_focus_out(None)

    def onEntryReturn(self, event):
        self.addTask()
        return "break"

    def startGeneralTask(self, event=None):
        # Only trigger when the app window is focused and the user isn't typing in an entry.
        try:
            if self.root.focus_displayof() is None:
                return
            focused = self.root.focus_get()
            if isinstance(focused, tk.Entry):
                return
        except Exception:
            return
        name = "General"
        if name in self.rows:
            self.startTask(name)

    def loadData(self):
        if not os.path.exists(self.dataFile):
            return
        try:
            tasks_list = []
            groups = {}
            history = {}
            with open(self.dataFile, "r", encoding="utf-8") as f:
                is_jsonl = True
                for raw in f:
                    line = raw.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        # not JSONL -> fallback to full JSON
                        is_jsonl = False
                        break
                    t = obj.get("type")
                    if t == "task":
                        name = obj.get("name")
                        if name:
                            tasks_list.append(name)
                    elif t == "group":
                        task = obj.get("task")
                        grp = obj.get("group")
                        if task:
                            groups[task] = grp
                    elif t == "history":
                        d = obj.get("date")
                        if not d:
                            continue
                        entry = {}
                        entry["summary"] = obj.get("summary", "") or ""
                        entry["timeline"] = obj.get("timeline", []) or []
                        history[d] = entry
                if not is_jsonl:
                    # fallback: parse entire file as legacy JSON
                    f.seek(0)
                    data = json.load(f)
                    tasks_list = data.get("tasks", [])
                    history = data.get("history", {}) or {}
                    groups = data.get("groups", {}) or {}
            for name in tasks_list:
                self.createTaskRow(name)
            self.history = history
            self.groups = groups
        except Exception:
            self.history = {}

    def saveData(self):
        self.sync_task_group_section()
        return

    def sync_task_group_section(self):
        desired_tasks = list(self.rows.keys())
        desired_groups = dict(self.groups or {})

        dirpath = os.path.dirname(self.realPath) or self.getDataDir()
        try:
            os.makedirs(dirpath, exist_ok=True)
        except Exception:
            pass

        if not os.path.exists(self.realPath):
            try:
                with open(self.realPath, "w", encoding="utf-8") as f:
                    for name in desired_tasks:
                        f.write(json.dumps({"type": "task", "name": name}, ensure_ascii=False, separators=(',',':')) + "\n")
                    for t, g in desired_groups.items():
                        f.write(json.dumps({"type": "group", "task": t, "group": g}, ensure_ascii=False, separators=(',',':')) + "\n")
                self.dataFile = self.realPath
            except Exception:
                pass
            return

        tmp = None
        try:
            preserved_history = []
            preserved_chargeCodes = []
            preserved_other = []
            with open(self.realPath, "r", encoding="utf-8") as rf:
                for raw in rf:
                    line = raw.rstrip("\n")
                    if not line.strip():
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        preserved_other.append(line.strip())
                        continue
                    t = obj.get("type")
                    if t == "history":
                        preserved_history.append(obj)
                    elif t == "chargeCode":
                        preserved_chargeCodes.append(obj)
                    else:
                        continue

            tmp = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False, dir=dirpath)
            for name in desired_tasks:
                tmp.write(json.dumps({"type": "task", "name": name}, ensure_ascii=False, separators=(',',':')) + "\n")
            for t, g in desired_groups.items():
                tmp.write(json.dumps({"type": "group", "task": t, "group": g}, ensure_ascii=False, separators=(',',':')) + "\n")
            for obj in preserved_chargeCodes:
                tmp.write(json.dumps(obj, ensure_ascii=False, separators=(',',':')) + "\n")
            for obj in preserved_history:
                tmp.write(json.dumps(obj, ensure_ascii=False, separators=(',',':')) + "\n")
            for l in preserved_other:
                tmp.write(l + "\n")

            tmp.flush()
            tmp.close()
            os.replace(tmp.name, self.realPath)
            self.dataFile = self.realPath
        except Exception:
            try:
                if tmp is not None:
                    tmp.close()
                    if os.path.exists(tmp.name):
                        os.remove(tmp.name)
            except Exception:
                pass
            return

    def append_history_entry(self, dateKey, entry):
        dirpath = os.path.dirname(self.realPath) or self.getDataDir()
        try:
            os.makedirs(dirpath, exist_ok=True)
        except Exception:
            pass

        if isinstance(entry, dict):
            summary = entry.get("summary", "") or ""
            timeline = entry.get("timeline", []) or []
        else:
            summary = entry or ""
            timeline = []

        new_obj = {"type": "history", "date": dateKey, "summary": summary, "timeline": timeline}

        # If file doesn't exist, create and write tasks/groups then history.
        if not os.path.exists(self.realPath):
            try:
                with open(self.realPath, "w", encoding="utf-8") as f:
                    for name in list(self.rows.keys()):
                        f.write(json.dumps({"type": "task", "name": name}, ensure_ascii=False, separators=(',',':')) + "\n")
                    for t, g in (self.groups or {}).items():
                        f.write(json.dumps({"type": "group", "task": t, "group": g}, ensure_ascii=False, separators=(',',':')) + "\n")
                    f.write(json.dumps(new_obj, ensure_ascii=False, separators=(',',':')) + "\n")
                self.dataFile = self.realPath
            except Exception:
                pass
            return

        tmp = None
        try:
            preserved_history = []
            preserved_chargeCodes = []
            preserved_other = []
            with open(self.realPath, "r", encoding="utf-8") as rf:
                for raw in rf:
                    line = raw.rstrip("\n")
                    if not line.strip():
                        # skip blank lines for compactness
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        preserved_other.append(line.strip())
                        continue
                    if obj.get("type") == "history" and obj.get("date") == dateKey:
                        # skip existing history for this date (we will append the new one)
                        continue
                    if obj.get("type") == "history":
                        preserved_history.append(obj)
                    elif obj.get("type") == "chargeCode":
                        preserved_chargeCodes.append(obj)
                    else:
                        # skip other JSON (task/group) lines
                        continue

            tmp = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False, dir=dirpath)
            # write current tasks/groups fresh
            for name in list(self.rows.keys()):
                tmp.write(json.dumps({"type": "task", "name": name}, ensure_ascii=False, separators=(',',':')) + "\n")
            for t, g in (self.groups or {}).items():
                tmp.write(json.dumps({"type": "group", "task": t, "group": g}, ensure_ascii=False, separators=(',',':')) + "\n")
            # write preserved chargeCode lines
            for obj in preserved_chargeCodes:
                tmp.write(json.dumps(obj, ensure_ascii=False, separators=(',',':')) + "\n")
            # Append preserved history entries
            for obj in preserved_history:
                tmp.write(json.dumps(obj, ensure_ascii=False, separators=(',',':')) + "\n")
            # Append any non-JSON preserved lines trimmed
            for l in preserved_other:
                tmp.write(l + "\n")
            # Append the new history record at the end.
            tmp.write(json.dumps(new_obj, ensure_ascii=False, separators=(',',':')) + "\n")
            tmp.flush()
            tmp.close()
            os.replace(tmp.name, self.realPath)
            self.dataFile = self.realPath
        except Exception:
            try:
                if tmp is not None:
                    tmp.close()
                    if os.path.exists(tmp.name):
                        os.remove(tmp.name)
            except Exception:
                pass
            return

    def adjustWindowHeight(self):
        self.root.update_idletasks()
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

    def _roundTimelineEdgesToHour(self, timeline):
        if not self.roundToHours or not timeline:
            return timeline

        def parseIso(s):
            try:
                return datetime.fromisoformat(s)
            except Exception:
                return None

        def fmtIso(dtObj):
            return dtObj.strftime("%Y-%m-%dT%H:%M:%S")

        def parseHHMM(s, fallbackHour, fallbackMinute):
            try:
                parts = (s or "").split(":")
                if len(parts) != 2:
                    return fallbackHour, fallbackMinute
                return int(parts[0]), int(parts[1])
            except Exception:
                return fallbackHour, fallbackMinute

        first = timeline[0]
        last = timeline[-1]

        firstStart = parseIso(first.get("start"))
        lastEnd = parseIso(last.get("end"))

        if firstStart is None or lastEnd is None:
            return timeline

        workStartHour, workStartMinute = parseHHMM(self.workDayStart, 9, 0)
        workEndHour, workEndMinute = parseHHMM(self.workDayEnd, 17, 0)

        day = firstStart.date()
        workStart = datetime(day.year, day.month, day.day, workStartHour, workStartMinute, 0)
        workEnd = datetime(day.year, day.month, day.day, workEndHour, workEndMinute, 0)
        
        if abs((firstStart - workStart).total_seconds()) <= 5 * 60:
            first["start"] = fmtIso(workStart)

        if abs((lastEnd - workEnd).total_seconds()) <= 5 * 60:
            last["end"] = fmtIso(workEnd)

        return timeline

    def _closeActiveSegment(self, now=None):
        if now is None:
            now = time.time()
        if self.currentTask is not None and self.currentStart is not None:
            self._recordSegment(self.currentTask, self.currentStart, now)
        elif self.unassignedStart is not None:
            self._recordSegment("Untasked", self.unassignedStart, now)

    def initializePunchSession(self):
        try:
            posting = self._getPosting(showToast=True)
            if posting is None:
                return

            self.punchSession = posting.newSession()
            posting.primeCookies(self.punchSession)
            
            _, loginJson = posting.login(self.punchSession)
            
            self.employeeId = posting.extractEmployeeId(loginJson)
            
            posting.saveCookies(self.punchSession)
            
            timesheetData = posting.copyPreviousTimesheet(self.punchSession, date.today().isoformat())
            self.timesheetId = timesheetData["timesheetId"]
        except Exception as e:
            self.showToast(f"Login error: {str(e)}", timeout=5000, error=True)
            self.punchSession = None
            self.employeeId = None
            self.timesheetId = None

    def punchIn(self):
        if not self.useTimesheetFunctions:
            return

        def _punchInThread():
            try:
                posting = self._getPosting(showToast=True)
                if posting is None:
                    return

                self.initializePunchSession()

                if self.punchSession is None or self.employeeId is None:
                    return

                punchDt = datetime.now()
                if self.roundToHours:
                    try:
                        h, m = (self.workDayStart).split(":")
                        workStartDt = punchDt.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
                        if abs((punchDt - workStartDt).total_seconds()) <= 5 * 60:
                            punchDt = workStartDt
                    except Exception:
                        pass
                punchPayload = {
                    "id": "",
                    "punchDate": punchDt.strftime("%m/%d/%Y %I:%M %p"),
                    "type": "IN",
                    "employeeId": self.employeeId,
                    "timesheetPage": True,
                    "location": None,
                    "new": True
                }
                posting.postPunch(self.punchSession, punchPayload)
                self.showToast("Successfully clocked in!")
            except Exception as e:
                self.showToast(f"✗ Clock in failed: {e}", error=True)

        threading.Thread(target=_punchInThread, daemon=True).start()

    def punchOut(self):
        if not self.useTimesheetFunctions:
            return
        
        def _punchOutThread():
            try:
                posting = self._getPosting(showToast=True)
                if posting is None:
                    return

                self.initializePunchSession()

                if self.punchSession is None or self.employeeId is None:
                    return
                punchDt = datetime.now()
                if self.roundToHours:
                    try:
                        h, m = (self.workDayEnd).split(":")
                        workEndDt = punchDt.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
                        if abs((punchDt - workEndDt).total_seconds()) <= 5 * 60:
                            punchDt = workEndDt
                    except Exception:
                        pass
                punchPayload = {
                    "id": "",
                    "punchDate": punchDt.strftime("%m/%d/%Y %I:%M %p"),
                    "type": "OUT",
                    "employeeId": self.employeeId,
                    "revisionNumber": -1,
                    "chargeCodes": [],
                    "payType": None,
                    "noteModel": None,
                    "billable": False,
                    "date": None,
                    "timesheetPage": True,
                    "location": None,
                    "new": True
                }
                posting.postPunch(self.punchSession, punchPayload)
                self._punchOutSuccess = True
                
            except Exception as e:
                self._punchOutSuccess = False
        
        thread = threading.Thread(target=_punchOutThread, daemon=True)
        thread.start()
        return thread

    def postChargeCodeHours(self, taskSecondsSnapshot=None, dateKey=None):
        if not self.autoChargeCodes:
            return

        def job():
            try:
                posting = self._getPosting(showToast=True)
                if posting is None:
                    return

                if self.punchSession is None or self.employeeId is None:
                    self.initializePunchSession()

                if self.punchSession is None or self.employeeId is None:
                    self.showToast("Session not ready", error=True)
                    return

                chargeCodesByKey = self.loadChargeCodesFromJsonl()
                if not chargeCodesByKey:
                    self.showToast("No charge codes found", error=True)
                    return

                if dateKey:
                    try:
                        dateStr = datetime.strptime(dateKey, "%Y-%m-%d").strftime("%m/%d/%Y")
                    except Exception:
                        dateStr = date.today().strftime("%m/%d/%Y")
                else:
                    dateStr = date.today().strftime("%m/%d/%Y")

                if isinstance(taskSecondsSnapshot, dict):
                    taskSeconds = dict(taskSecondsSnapshot)
                else:
                    taskSeconds = dict(self.tasks)
                    if self.currentTask and self.currentStart:
                        now = time.time()
                        taskSeconds[self.currentTask] = (
                            taskSeconds.get(self.currentTask, 0.0) + (now - self.currentStart)
                        )
                    if self.unassignedSeconds > 0:
                        taskSeconds["Untasked"] = (
                            taskSeconds.get("Untasked", 0.0) + self.unassignedSeconds
                        )

                hoursByKey = {key: 0.0 for key in chargeCodesByKey.keys()}

                for taskName, seconds in taskSeconds.items():
                    hours = round((seconds / 3600.0), 1)

                    if taskName in chargeCodesByKey:
                        hoursByKey[taskName] += hours
                    else:
                        groupName = self.groups.get(taskName)
                        if groupName in chargeCodesByKey:
                            hoursByKey[groupName] += hours

                # Normalize totals to match the rounded actual elapsed time.
                target_total = round(sum(taskSeconds.values()) / 3600.0, 1)
                current_total = round(sum(hoursByKey.values()), 1)
                diff = round(target_total - current_total, 1)
                if abs(diff) >= 0.05 and hoursByKey:
                    # Adjust the largest bucket to keep totals aligned.
                    max_key = max(hoursByKey.items(), key=lambda kv: kv[1])[0]
                    hoursByKey[max_key] = round(hoursByKey[max_key] + diff, 1)

                hadError = False
                for key, hours in hoursByKey.items():
                    try:
                        posting.postHoursWorked(
                            self.punchSession,
                            self.employeeId,
                            self.timesheetId,
                            chargeCodesByKey[key],
                            dateStr,
                            hours
                        )
                    except Exception:
                        hadError = True

                if hadError:
                    self.showToast("Posted charge codes (some failed)", error=True)
                else:
                    self.showToast("Successfully posted charge codes")

            except Exception:
                self.showToast("Error posting charge codes", error=True)

        threading.Thread(target=job, daemon=True).start()

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
            taskSecondsForSummary = dict(self.tasks)
            if self.unassignedSeconds > 0:
                taskSecondsForSummary["Untasked"] = (
                    taskSecondsForSummary.get("Untasked", 0.0) + self.unassignedSeconds
                )

            roundedHours, totalHours = self._normalizeRoundedHours(taskSecondsForSummary)
            lines = []
            for name, hours in sorted(roundedHours.items(), key=lambda kv: kv[0].lower()):
                lines.append(f"{name}: {hours:.1f} h")
            lines.append(f"Total: {totalHours:.1f} h")
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

            if choice == "append":
                timeline = existingTimeline + list(self.dayTimeline)
            else:
                timeline = list(self.dayTimeline)

            timeline = self._roundTimelineEdgesToHour(timeline)

            self.history[todayKey] = {
                "summary": merged,
                "timeline": timeline
            }
            # append only the day's summary to the jsonl log
            self.append_history_entry(todayKey, self.history[todayKey])

            taskSecondsSnapshot = dict(self.tasks)
            if self.currentTask and self.currentStart:
                now2 = time.time()
                taskSecondsSnapshot[self.currentTask] = (
                    taskSecondsSnapshot.get(self.currentTask, 0.0) + (now2 - self.currentStart)
                )

            if choice == "append" and existingEntry:
                if isinstance(existingEntry, dict):
                    existingText = existingEntry.get("summary", "") or ""
                else:
                    existingText = existingEntry or ""
                oldAgg, _ = self._parseSummaryText(existingText)
                for name, hours in oldAgg.items():
                    taskSecondsSnapshot[name] = taskSecondsSnapshot.get(name, 0.0) + (hours * 3600.0)

            if self.unassignedSeconds > 0:
                taskSecondsSnapshot["Untasked"] = (
                    taskSecondsSnapshot.get("Untasked", 0.0) + self.unassignedSeconds
                )
            
            # Punch out when closing with unsaved time
            punchThread = self.punchOut()
            if punchThread:
                punchThread.join()
            if self._punchOutSuccess:
                self.showToast("Successfully clocked out!")
            else:
                self.showToast(f"✗ Clock out failed!", error=True)
            self.postChargeCodeHours(taskSecondsSnapshot)
            
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
    
    def openSettings(self):
        return openSettingsImpl(self)

    def openHistory(self):
        return openHistoryImpl(self)

    def clearDayData(self):
        if not messagebox.askyesno("Clear Day", "Clear all times and timeline for today? This cannot be undone."):
            return
        
        now = time.time()
        
        if self.currentTask is not None and self.currentStart is not None:
            self.currentTask = None
            self.currentStart = None
        
        self.unassignedStart = None
        self.unassignedSeconds = 0.0
        
        for name in self.tasks.keys():
            self.tasks[name] = 0.0
        
        self.dayTimeline = []
        
        todayKey = date.today().isoformat()
        if todayKey in self.history:
            del self.history[todayKey]
        
        self.hasUnsavedTime = False
        self.refreshRowStyles()
        messagebox.showinfo("Cleared", "All times and timeline have been cleared.")

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
        
        shouldPunchIn = not any(self.tasks.values()) and self.unassignedSeconds == 0
        if shouldPunchIn:
            self.root.after(200, self.punchIn)

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

    def _normalizeRoundedHours(self, secondsByTask):
        if not secondsByTask:
            return {}, 0.0
        raw_total_hours = sum(secondsByTask.values()) / 3600.0
        target_total = round(raw_total_hours, 1)
        rounded = {t: round(sec / 3600.0, 1) for t, sec in secondsByTask.items()}
        current_total = round(sum(rounded.values()), 1)
        diff = round(target_total - current_total, 1)
        if abs(diff) >= 0.05:
            for name, _ in sorted(rounded.items(), key=lambda kv: kv[1], reverse=True):
                new_val = round(rounded[name] + diff, 1)
                if new_val >= 0:
                    rounded[name] = new_val
                    break
        return rounded, target_total

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
        iconPath = resourcePath("hourglass.ico")
        if os.path.exists(iconPath):
            try:
                dialog.iconbitmap(iconPath)
            except Exception:
                pass

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

        totalHours = 0.0
        lines = []
        for name, hours in sorted(combined.items(), key=lambda kv: kv[0].lower()):
            rounded = round(hours, 1)
            totalHours += rounded
            lines.append(f"{name}: {rounded:.1f} h")
        lines.append(f"Total: {totalHours:.1f} h")
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

        taskSecondsForSummary = dict(self.tasks)
        if self.unassignedSeconds > 0:
            taskSecondsForSummary["Untasked"] = (
                taskSecondsForSummary.get("Untasked", 0.0) + self.unassignedSeconds
            )

        roundedHours, totalHours = self._normalizeRoundedHours(taskSecondsForSummary)
        lines = []
        for name, hours in sorted(roundedHours.items(), key=lambda kv: kv[0].lower()):
            lines.append(f"{name}: {hours:.1f} h")
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

        if choice == "append":
            timeline = existingTimeline + list(self.dayTimeline)
        else:
            timeline = list(self.dayTimeline)

        timeline = self._roundTimelineEdgesToHour(timeline)

        self.history[todayKey] = {
            "summary": merged,
            "timeline": timeline
        }
        self.append_history_entry(todayKey, self.history[todayKey])
        
        taskSecondsSnapshot = dict(self.tasks)
        if choice == "append" and existingEntry:
            if isinstance(existingEntry, dict):
                existingText = existingEntry.get("summary", "") or ""
            else:
                existingText = existingEntry or ""
            oldAgg, _ = self._parseSummaryText(existingText)
            for name, hours in oldAgg.items():
                taskSecondsSnapshot[name] = taskSecondsSnapshot.get(name, 0.0) + (hours * 3600.0)

        if self.unassignedSeconds > 0:
            taskSecondsSnapshot["Untasked"] = (
                taskSecondsSnapshot.get("Untasked", 0.0) + self.unassignedSeconds
            )

        punchThread = self.punchOut()
        if punchThread:
            punchThread.join()
        self.postChargeCodeHours(taskSecondsSnapshot)
        
        # CLEAR session data after saving TODO: should this be a setting?
        self.dayTimeline = []
        self.tasks = {name: 0.0 for name in self.tasks.keys()}
        self.unassignedSeconds = 0.0
        self.unassignedStart = None
        self.currentTask = None
        self.currentStart = None
        self.hasUnsavedTime = False
        self.refreshRowStyles()

        messagebox.showinfo("Summary: ", merged)

    def loadChargeCodesFromJsonl(self):
        chargeCodesByKey = {}
        try:
            with open(self.dataFile, "r", encoding="utf-8") as f:
                for raw in f:
                    line = raw.strip()
                    if not line or line.startswith("//"):
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    
                    if obj.get("type") == "chargeCode":
                        groupKey = obj.get("groupKey", "").strip()
                        chargeCodes = obj.get("chargeCodes", [])
                        
                        if groupKey and chargeCodes:
                            chargeCodesByKey[groupKey] = chargeCodes
        except Exception as e:
            pass
        
        return chargeCodesByKey

    def validateEnvFile(self):
        if not self.useTimesheetFunctions and not self.autoChargeCodes:
            return
        envPath = os.path.join(self.getDataDir(), "posting.env")
        
        required = ["BASE_URL", "EMAIL", "PASSWORD"]
        missing = []
        
        if not os.path.exists(envPath):
            missing = required
        else:
            try:
                with open(envPath, "r", encoding="utf-8") as f:
                    content = f.read()
                for key in required:
                    if f"{key}=" not in content:
                        missing.append(key)
                    else:
                        # Check if value is actually set (not just empty)
                        for line in content.split("\n"):
                            if line.startswith(f"{key}="):
                                value = line.split("=", 1)[1].strip()
                                if not value:
                                    missing.append(key)
                                break
            except Exception:
                missing = required
        
        if missing:
            msg = "Missing posting.env configuration:\n" + ", ".join(missing)
            self.showToast(msg, timeout=5000, error=True)

if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()

    app = TaskTrackerApp(root)

    root.update_idletasks()
    w = max(app.baseWidth, root.winfo_reqwidth())
    h = root.winfo_reqheight()
    root.geometry(f"{w}x{h}")

    root.deiconify()
    root.mainloop()
