import tkinter as tk
from tkinter import messagebox
import time
import os
import sys
import json
import tempfile
import threading
import hashlib
import colorsys
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
        self.reviewBeforePost = bool(self.settings.get("reviewBeforePost", False))
        self.colorPalettePreset = str(self.settings.get("colorPalettePreset", "vibrant") or "vibrant")
        self.selectedTaskUsesColor = bool(self.settings.get("selectedTaskUsesColor", True))
        self.taskColorOverrides = self._normalizeColorMap(
            self.settings.get("taskColorOverrides", self.settings.get("taskColors", {}))
        )
        self.groupColorOverrides = self._normalizeColorMap(
            self.settings.get("groupColorOverrides", self.settings.get("groupColorBases", {}))
        )


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
        self.timesheetDateKey = None

        self.toastWindow = None
        self.toastTimer = None
        self._busyCount = 0
        self._nextStatusRefreshTs = 0.0
        self._cachedChargeCodesByKey = {}
        self._cachedChargeCodesTs = 0.0
        self._pendingChargePosts = []
        self._pendingChargePostLock = threading.Lock()
        self._timesheetSessionLock = threading.RLock()
        self._punchInSuccess = False
        self._punchOutSuccess = False

        self.validateEnvFile()

        baseDir = self.getDataDir()
        self.realPath = os.path.join(baseDir, "tasks.jsonl")
        self.dataFile = self.realPath
        self.dayTimeline = []
        self.activeDayKey = date.today().isoformat()

        self.buildUi()
        self.loadData()
        self.restoreTodayTimeline()
        self.relayoutRows()
        self.updateLoop()

        self.root.bind("<Delete>", self.deleteSelected)
        self.root.bind("<KeyPress>", self.startGeneralTask)
        self.root.protocol("WM_DELETE_WINDOW", self.onClose)

    def _clamp01(self, x):
        try:
            return max(0.0, min(1.0, float(x)))
        except Exception:
            return 0.0

    def _sanitizeHexColor(self, value, fallback=None):
        if isinstance(value, str):
            s = value.strip()
            if len(s) == 7 and s.startswith("#"):
                hexpart = s[1:]
                if all(c in "0123456789abcdefABCDEF" for c in hexpart):
                    return "#" + hexpart.lower()
        return fallback

    def _normalizeColorMap(self, mapping):
        if not isinstance(mapping, dict):
            return {}
        out = {}
        for k, v in mapping.items():
            if not isinstance(k, str):
                continue
            key = k.strip()
            if not key:
                continue
            c = self._sanitizeHexColor(v)
            if c:
                out[key] = c
        return out

    def _canonicalKey(self, value):
        if value is None:
            return ""
        return str(value).strip().casefold()

    def _lookupOverrideColor(self, mapping, key):
        if not isinstance(mapping, dict):
            return None
        if key in mapping:
            return mapping.get(key)
        target = self._canonicalKey(key)
        if not target:
            return None
        for k, v in mapping.items():
            if self._canonicalKey(k) == target:
                return v
        return None

    def _lookupGroupForTask(self, groupsMap, taskName):
        if not isinstance(groupsMap, dict):
            return ""
        if taskName in groupsMap:
            return str(groupsMap.get(taskName) or "").strip()
        target = self._canonicalKey(taskName)
        if not target:
            return ""
        for k, v in groupsMap.items():
            if self._canonicalKey(k) == target:
                return str(v or "").strip()
        return ""

    def _hexToRgb01(self, hexColor):
        c = self._sanitizeHexColor(hexColor, "#000000")
        return (int(c[1:3], 16) / 255.0, int(c[3:5], 16) / 255.0, int(c[5:7], 16) / 255.0)

    def _rgb01ToHex(self, r, g, b):
        ri = int(round(self._clamp01(r) * 255))
        gi = int(round(self._clamp01(g) * 255))
        bi = int(round(self._clamp01(b) * 255))
        return f"#{ri:02x}{gi:02x}{bi:02x}"

    def _mixHex(self, c1, c2, t):
        t = self._clamp01(t)
        r1, g1, b1 = self._hexToRgb01(c1)
        r2, g2, b2 = self._hexToRgb01(c2)
        return self._rgb01ToHex(r1 + (r2 - r1) * t, g1 + (g2 - g1) * t, b1 + (b2 - b1) * t)

    def _rgbDistance(self, c1, c2):
        r1, g1, b1 = self._hexToRgb01(c1)
        r2, g2, b2 = self._hexToRgb01(c2)
        dr = (r1 - r2) * 255.0
        dg = (g1 - g2) * 255.0
        db = (b1 - b2) * 255.0
        return (dr * dr + dg * dg + db * db) ** 0.5

    def _stableInt(self, text):
        if not isinstance(text, str):
            text = str(text)
        return int(hashlib.md5(text.encode("utf-8")).hexdigest()[:8], 16)

    def _presetSpec(self, presetName):
        p = str(presetName or "vibrant").strip().lower()
        specs = {
            "vibrant": {"sat": 0.78, "light": 0.52, "shade_span": 0.34},
            "muted": {"sat": 0.48, "light": 0.56, "shade_span": 0.28},
            "bold": {"sat": 0.88, "light": 0.48, "shade_span": 0.40},
            "colorblind": {"sat": 0.68, "light": 0.50, "shade_span": 0.32},
            "colorblind-safe": {"sat": 0.68, "light": 0.50, "shade_span": 0.32},
            "classic": {"sat": 0.76, "light": 0.52, "shade_span": 0.30},
            "default": {"sat": 0.78, "light": 0.52, "shade_span": 0.34},
        }
        return specs.get(p, specs["vibrant"])

    def _autoBaseColor(self, key, presetName, usedBaseColors):
        p = str(presetName or "vibrant").strip().lower()
        if p == "classic":
            classic_bases = [
                "#3f8cff", "#10b981", "#f97316", "#e11d48",
                "#8b5cf6", "#06b6d4", "#facc15", "#6366f1"
            ]
            return classic_bases[self._stableInt(key) % len(classic_bases)]

        spec = self._presetSpec(presetName)
        sat = self._clamp01(spec["sat"])
        light = self._clamp01(spec["light"])
        phi = 0.61803398875
        seed = (self._stableInt(key) % 1000003) / 1000003.0

        candidates = []
        for i in range(36):
            h = (seed + i * phi) % 1.0
            jitter = (((self._stableInt(f"{key}:{i}") % 17) - 8) / 1000.0)
            h = (h + jitter) % 1.0
            r, g, b = colorsys.hls_to_rgb(h, light, sat)
            candidates.append(self._rgb01ToHex(r, g, b))

        if not usedBaseColors:
            return candidates[0]

        best = candidates[0]
        bestMinDist = -1.0
        for c in candidates:
            minDist = min(self._rgbDistance(c, u) for u in usedBaseColors)
            if minDist > bestMinDist:
                bestMinDist = minDist
                best = c
            if minDist >= 90.0:
                return c
        return best

    def _taskShadeFromGroupBase(self, baseHex, taskName, presetName):
        p = str(presetName or "vibrant").strip().lower()
        if p == "classic":
            shades = [
                baseHex,
                self._mixHex(baseHex, "#ffffff", 0.24),
                self._mixHex(baseHex, "#000000", 0.22),
                self._mixHex(baseHex, "#ffffff", 0.38),
            ]
            return shades[self._stableInt(f"classic-shade:{taskName}") % len(shades)]

        spec = self._presetSpec(presetName)
        base_r, base_g, base_b = self._hexToRgb01(baseHex)
        h, l, s = colorsys.rgb_to_hls(base_r, base_g, base_b)

        # Deterministic but high-variance offsets, so tasks in the same group
        # remain clearly distinct without requiring period-dependent ordering.
        l_seed = (self._stableInt(f"shade-l:{taskName}") % 1000003) / 1000003.0 - 0.5
        h_seed = (self._stableInt(f"shade-h:{taskName}") % 1000003) / 1000003.0 - 0.5
        s_seed = (self._stableInt(f"shade-s:{taskName}") % 1000003) / 1000003.0 - 0.5

        l_span = max(0.36, min(0.66, spec["shade_span"] + 0.30))
        h_span = 0.30
        s_span = 0.34

        l2 = self._clamp01(max(0.16, min(0.90, l + l_seed * l_span)))
        h2 = (h + h_seed * h_span) % 1.0
        s2 = self._clamp01(max(0.22, min(0.98, s + s_seed * s_span)))

        r, g, b = colorsys.hls_to_rgb(h2, l2, s2)
        return self._rgb01ToHex(r, g, b)

    def _deterministicBaseColor(self, key, presetName):
        return self._autoBaseColor(key, presetName, [])

    def _shadeSeries(self, baseHex, count, presetName):
        count = max(1, int(count))
        if count == 1:
            return [baseHex]

        spec = self._presetSpec(presetName)
        base_r, base_g, base_b = self._hexToRgb01(baseHex)
        h, l, s = colorsys.rgb_to_hls(base_r, base_g, base_b)
        span = max(0.20, min(0.48, spec["shade_span"] + min(0.10, 0.01 * count)))
        start = -span / 2.0
        step = span / (count - 1)

        shades = []
        for i in range(count):
            shift = start + i * step
            li = self._clamp01(max(0.22, min(0.82, l + shift)))
            si = self._clamp01(max(0.32, min(0.92, s + (0.05 if i % 2 == 0 else -0.05))))
            hi = (h + ((i % 3) - 1) * 0.01) % 1.0 if count >= 7 else h
            r, g, b = colorsys.hls_to_rgb(hi, li, si)
            shades.append(self._rgb01ToHex(r, g, b))
        return shades

    def _applyColorSettingsFromSettings(self):
        self.colorPalettePreset = str(self.settings.get("colorPalettePreset", "vibrant") or "vibrant")
        self.selectedTaskUsesColor = bool(self.settings.get("selectedTaskUsesColor", True))
        self.taskColorOverrides = self._normalizeColorMap(
            self.settings.get("taskColorOverrides", self.settings.get("taskColors", {}))
        )
        self.groupColorOverrides = self._normalizeColorMap(
            self.settings.get("groupColorOverrides", self.settings.get("groupColorBases", {}))
        )

    def _ensureColorSettingsConsistency(self):
        self.settings["colorPalettePreset"] = self.colorPalettePreset
        self.settings["selectedTaskUsesColor"] = bool(self.selectedTaskUsesColor)
        self.settings["taskColorOverrides"] = dict(self.taskColorOverrides)
        self.settings["groupColorOverrides"] = dict(self.groupColorOverrides)
        # Backward-compatible aliases.
        self.settings["taskColors"] = dict(self.taskColorOverrides)
        self.settings["groupColorBases"] = dict(self.groupColorOverrides)

    def buildTaskColorMap(self, taskHours=None, groupsOverride=None, taskColorOverrides=None, groupColorOverrides=None, presetName=None):
        if not isinstance(taskHours, dict):
            taskHours = {}

        groupsMap = groupsOverride if isinstance(groupsOverride, dict) else (self.groups or {})
        taskOverrides = self._normalizeColorMap(taskColorOverrides if taskColorOverrides is not None else self.taskColorOverrides)
        groupOverrides = self._normalizeColorMap(groupColorOverrides if groupColorOverrides is not None else self.groupColorOverrides)
        preset = presetName or self.colorPalettePreset or "vibrant"

        taskNames = []
        seen = set()
        for name, hours in taskHours.items():
            try:
                hv = float(hours)
            except Exception:
                continue
            if hv <= 0.0:
                continue
            if name in seen:
                continue
            seen.add(name)
            taskNames.append(name)

        groupToTasks = {}
        for taskName in taskNames:
            if taskName == "Untasked":
                continue
            grp = self._lookupGroupForTask(groupsMap, taskName)
            if grp:
                groupToTasks.setdefault(grp, []).append(taskName)

        groupTaskColors = {}
        for grp, tasks in groupToTasks.items():
            groupBase = self._lookupOverrideColor(groupOverrides, grp) or self._deterministicBaseColor(
                f"group:{self._canonicalKey(grp)}",
                preset
            )

            ordered = sorted(tasks, key=lambda t: self._stableInt(f"group-order:{self._canonicalKey(grp)}:{self._canonicalKey(t)}"))
            shades = self._shadeSeries(groupBase, len(ordered), preset)

            for i, taskName in enumerate(ordered):
                groupTaskColors[taskName] = shades[i]

        result = {}
        for taskName in taskNames:
            if taskName == "Untasked":
                result[taskName] = "#444c56"
                continue

            manualTask = self._lookupOverrideColor(taskOverrides, taskName)
            if manualTask:
                result[taskName] = manualTask
                continue

            if taskName in groupTaskColors:
                result[taskName] = groupTaskColors[taskName]
                continue

            result[taskName] = self._deterministicBaseColor(
                f"task:{self._canonicalKey(taskName)}",
                preset
            )

        return result


    def getTaskDisplayColor(self, taskName):
        if taskName == "Untasked":
            return "#444c56"
        colorMap = self.buildTaskColorMap({taskName: 1.0})
        return colorMap.get(taskName, self.accentColor)

    def _renameSummaryTaskLabel(self, summaryText, oldName, newName):
        if not isinstance(summaryText, str) or not summaryText:
            return summaryText, False

        changed = False
        out = []
        for line in summaryText.splitlines():
            if ":" not in line:
                out.append(line)
                continue
            left, right = line.split(":", 1)
            if left.strip() != oldName:
                out.append(line)
                continue

            lead_ws_len = len(left) - len(left.lstrip())
            trail_ws_len = len(left) - len(left.rstrip())
            lead = left[:lead_ws_len]
            trail = left[len(left) - trail_ws_len:] if trail_ws_len > 0 else ""
            out.append(f"{lead}{newName}{trail}:{right}")
            changed = True

        newText = "\n".join(out)
        if summaryText.endswith("\n"):
            newText += "\n"
        return newText, changed

    def _renameTaskInHistory(self, oldName, newName):
        changed = False
        for dayKey, entry in list(self.history.items()):
            if isinstance(entry, dict):
                entryChanged = False
                summary = entry.get("summary", "") or ""
                newSummary, summaryChanged = self._renameSummaryTaskLabel(summary, oldName, newName)
                if summaryChanged:
                    entry["summary"] = newSummary
                    entryChanged = True

                timeline = entry.get("timeline", []) or []
                timelineChanged = False
                for seg in timeline:
                    if isinstance(seg, dict) and seg.get("task") == oldName:
                        seg["task"] = newName
                        timelineChanged = True
                if timelineChanged:
                    entry["timeline"] = timeline
                    entryChanged = True

                if entryChanged:
                    self.history[dayKey] = entry
                    changed = True
            elif isinstance(entry, str):
                newSummary, summaryChanged = self._renameSummaryTaskLabel(entry, oldName, newName)
                if summaryChanged:
                    self.history[dayKey] = newSummary
                    changed = True
        return changed

    def renameTask(self, oldName, newName, persist=True):
        oldName = (oldName or "").strip()
        newName = (newName or "").strip()
        if not oldName or not newName:
            return False, "Task name is required."
        if oldName == newName:
            return True, ""
        if oldName not in self.rows:
            return False, f"Task '{oldName}' does not exist."
        if newName in self.rows:
            return False, f"Task '{newName}' already exists."

        names = list(self.rows.keys())
        newOrder = [newName if n == oldName else n for n in names]

        priorTasks = dict(self.tasks)
        movedSeconds = priorTasks.get(oldName, 0.0)
        if oldName in priorTasks:
            del priorTasks[oldName]
        priorTasks[newName] = movedSeconds

        groupKey = oldName if oldName in self.groups else None
        if groupKey is None:
            for k in list(self.groups.keys()):
                if self._canonicalKey(k) == self._canonicalKey(oldName):
                    groupKey = k
                    break
        if groupKey is not None:
            self.groups[newName] = self.groups.pop(groupKey)

        if self.currentTask == oldName:
            self.currentTask = newName

        for seg in self.dayTimeline:
            if isinstance(seg, dict) and seg.get("task") == oldName:
                seg["task"] = newName

        overrideKey = oldName if oldName in self.taskColorOverrides else None
        if overrideKey is None:
            for k in list(self.taskColorOverrides.keys()):
                if self._canonicalKey(k) == self._canonicalKey(oldName):
                    overrideKey = k
                    break
        if overrideKey is not None:
            self.taskColorOverrides[newName] = self.taskColorOverrides.pop(overrideKey)

        self._renameTaskInHistory(oldName, newName)
        self._ensureColorSettingsConsistency()

        for rowFrame, _, timeLabel, _ in self.rows.values():
            try:
                rowFrame.destroy()
            except Exception:
                pass
            try:
                timeLabel.destroy()
            except Exception:
                pass

        self.rows = {}
        self.tasks = {}
        for n in newOrder:
            self.tasks[n] = float(priorTasks.get(n, 0.0))
            self.createTaskRow(n)

        self.relayoutRows()
        self.refreshRowStyles()
        if persist:
            if not self.rewrite_data_file():
                self.saveData()
        return True, ""

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
        self._styleButton(settingsBtn)
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
        self._styleButton(clearBtn)
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
        self._styleButton(historyBtn)
        historyBtn.grid(row=0, column=3, sticky="e", padx=(8, 0))

        subtitle = tk.Label(
            self.root,
            text="Click a task to switch · End Day for summary",
            font=("Segoe UI", 9),
            fg="#9099a6",
            bg=self.bgColor
        )
        subtitle.grid(row=2, column=0, columnspan=2, padx=12, pady=(0, 8), sticky="w")

        self.sessionStatusLabel = tk.Label(
            self.root,
            text="Status: Idle · Total 0.0h",
            font=("Segoe UI", 9),
            fg="#9ca3af",
            bg=self.bgColor,
            anchor="w"
        )
        self.sessionStatusLabel.grid(row=1, column=0, columnspan=2, padx=12, pady=(0, 2), sticky="we")

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
        self._styleButton(self.addTaskButton, hover_bg="#5b98ff")
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
        self._styleButton(self.endDayButton, hover_bg="#5b98ff")
        self.endDayButton.grid(row=5, column=0, columnspan=2, padx=12, pady=(4, 12), sticky="we")

        self.root.columnconfigure(0, weight=1)

    def _queueUi(self, callback):
        try:
            if threading.current_thread() is threading.main_thread():
                callback()
            else:
                self.root.after(0, callback)
        except Exception:
            pass

    def showToast(self, message, timeout=3000, error=False):
        if threading.current_thread() is not threading.main_thread():
            self._queueUi(lambda: self.showToast(message, timeout=timeout, error=error))
            return

        if self.toastTimer is not None:
            try:
                self.root.after_cancel(self.toastTimer)
            except Exception:
                pass
            self.toastTimer = None
        
        if self.toastWindow is not None:
            try:
                self.toastWindow.destroy()
            except:
                pass
            self.toastWindow = None
        
        toastWindow = tk.Toplevel(self.root)
        toastWindow.configure(bg=self.bgColor)
        toastWindow.attributes('-alpha', 0.9)
        toastWindow.attributes('-topmost', True)
        toastWindow.overrideredirect(True)
        self.toastWindow = toastWindow
        
        bgColor = "#8b3333" if error else "#2a2f37"
        
        toastLabel = tk.Label(
            toastWindow,
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
        
        toastWindow.update_idletasks()
        tw = toastWindow.winfo_width()
        
        x = rx + (rw - tw) // 2
        y = ry + 20
        
        toastWindow.geometry(f"+{x}+{y}")
        
        def dismissToast():
            try:
                if self.toastWindow is toastWindow:
                    self.toastWindow.destroy()
                    self.toastWindow = None
            except:
                pass
            if self.toastTimer == timerId:
                self.toastTimer = None
        
        timerId = self.root.after(timeout, dismissToast)
        self.toastTimer = timerId

    def _setBusy(self, active=True):
        if active:
            self._busyCount += 1
        else:
            self._busyCount = max(0, self._busyCount - 1)

        cursor = "wait" if self._busyCount > 0 else ""
        try:
            self.root.config(cursor=cursor)
            for w in self.root.winfo_children():
                try:
                    w.config(cursor=cursor)
                except Exception:
                    pass
            self.root.update_idletasks()
        except Exception:
            pass

    def _styleButton(self, btn, hover_bg=None):
        normal_bg = btn.cget("bg")
        hover = hover_bg or btn.cget("activebackground") or normal_bg
        btn.config(cursor="hand2")
        btn.bind("<Enter>", lambda e: btn.config(bg=hover), add="+")
        btn.bind("<Leave>", lambda e: btn.config(bg=normal_bg), add="+")

    def _bindTaskRowHover(self, taskName, rowFrame, nameLabel, deleteBtn, handleLabel, timeLabel):
        def apply_hover():
            if self.dragTaskName is not None or self.currentTask == taskName:
                return
            try:
                taskColor = self.getTaskDisplayColor(taskName)
                hover_bg = self._mixHex(self.cardColor, taskColor, 0.08)
            except Exception:
                hover_bg = "#262c33"
            rowFrame.config(bg=hover_bg)
            nameLabel.config(bg=hover_bg)
            deleteBtn.config(bg=hover_bg)

        def clear_hover():
            self.refreshRowStyles()

        for widget in (rowFrame, nameLabel, timeLabel):
            widget.config(cursor="hand2")
            widget.bind("<Enter>", lambda e: apply_hover(), add="+")
            widget.bind("<Leave>", lambda e: clear_hover(), add="+")

        handleLabel.config(cursor="fleur")
        handleLabel.bind("<Enter>", lambda e: apply_hover(), add="+")
        handleLabel.bind("<Leave>", lambda e: clear_hover(), add="+")
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
        # Global letter hotkey: start the highest-ordered task whose name starts with that letter.
        try:
            if self.root.focus_displayof() is None:
                return
            focused = self.root.focus_get()
            if isinstance(focused, tk.Entry):
                return
        except Exception:
            return

        if event is None:
            return

        try:
            state = int(getattr(event, "state", 0) or 0)
        except Exception:
            state = 0

        # Ignore modified key presses so app shortcuts like Ctrl+K still work.
        if (state & 0x0004) or (state & 0x0008) or (state & 0x20000):
            return

        ch = str(getattr(event, "char", "") or "")
        if len(ch) != 1 or not ch.isalpha():
            return

        targetLetter = ch.casefold()
        for name in reversed(list(self.rows.keys())):
            taskName = str(name or "").strip()
            if not taskName:
                continue
            if taskName[0].casefold() == targetLetter:
                self.startTask(name)
                return "break"

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

    def rewrite_data_file(self):
        desired_tasks = list(self.rows.keys())
        desired_groups = dict(self.groups or {})

        dirpath = os.path.dirname(self.realPath) or self.getDataDir()
        try:
            os.makedirs(dirpath, exist_ok=True)
        except Exception:
            pass

        preserved_chargeCodes = []
        preserved_other = []

        if os.path.exists(self.realPath):
            try:
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
                        if t == "chargeCode":
                            preserved_chargeCodes.append(obj)
                        elif t in ("task", "group", "history"):
                            continue
                        else:
                            preserved_other.append(line.strip())
            except Exception:
                return False

        history_items = []
        for dayKey in sorted(self.history.keys()):
            entry = self.history.get(dayKey)
            if isinstance(entry, dict):
                summary = entry.get("summary", "") or ""
                timeline = entry.get("timeline", []) or []
            else:
                summary = entry or ""
                timeline = []
            history_items.append({
                "type": "history",
                "date": dayKey,
                "summary": summary,
                "timeline": timeline
            })

        tmp = None
        try:
            tmp = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False, dir=dirpath)
            for name in desired_tasks:
                tmp.write(json.dumps({"type": "task", "name": name}, ensure_ascii=False, separators=(',',':')) + "\n")
            for t, g in desired_groups.items():
                tmp.write(json.dumps({"type": "group", "task": t, "group": g}, ensure_ascii=False, separators=(',',':')) + "\n")
            for obj in preserved_chargeCodes:
                tmp.write(json.dumps(obj, ensure_ascii=False, separators=(',',':')) + "\n")
            for obj in history_items:
                tmp.write(json.dumps(obj, ensure_ascii=False, separators=(',',':')) + "\n")
            for line in preserved_other:
                tmp.write(line + "\n")
            tmp.flush()
            tmp.close()
            os.replace(tmp.name, self.realPath)
            self.dataFile = self.realPath
            return True
        except Exception:
            try:
                if tmp is not None:
                    tmp.close()
                    if os.path.exists(tmp.name):
                        os.remove(tmp.name)
            except Exception:
                pass
            return False

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
        # Keep runtime resizing consistent with initial load sizing logic.
        width = max(int(self.baseWidth), int(self.root.winfo_reqwidth()))
        height = int(self.root.winfo_reqheight())
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
        self._styleButton(deleteBtn)
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

        self._bindTaskRowHover(name, rowFrame, nameLabel, deleteBtn, handleLabel, timeLabel)
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

    def _currentDateKey(self, nowTs=None):
        if nowTs is None:
            return date.today().isoformat()
        try:
            return datetime.fromtimestamp(nowTs).date().isoformat()
        except Exception:
            return date.today().isoformat()

    def _syncIdleActiveDayKey(self, now=None):
        if now is None:
            now = time.time()

        if self.currentTask is not None or self.currentStart is not None:
            return
        if self.unassignedStart is not None:
            return
        if bool(self.hasUnsavedTime):
            return
        if float(self.unassignedSeconds or 0.0) > 0.0:
            return
        if any(float(seconds or 0.0) > 0.0 for seconds in self.tasks.values()):
            return
        if self.dayTimeline:
            return

        self.activeDayKey = self._currentDateKey(now)

    def _ensureCurrentDayContext(self, now=None):
        if now is None:
            now = time.time()
        self._rolloverIfNeeded(now)
        self._syncIdleActiveDayKey(now)
        return now

    def _saveTimelineForDate(self, dateKey, sourceTimeline, mergeChoice="append"):
        incomingTimeline = list(sourceTimeline or [])
        existingEntry = self.history.get(dateKey)
        existingTimeline = []
        if isinstance(existingEntry, dict):
            existingTimeline = existingEntry.get("timeline", []) or []

        if mergeChoice == "append":
            timeline = list(existingTimeline) + incomingTimeline
        else:
            timeline = incomingTimeline

        timeline = self._roundTimelineEdgesToHour(timeline)
        taskSecondsSnapshot = self._collectTaskSecondsFromTimeline(timeline)
        summary = self._buildSummaryFromTaskSeconds(taskSecondsSnapshot)

        entry = {
            "summary": summary,
            "timeline": timeline
        }
        self.history[dateKey] = entry
        self.append_history_entry(dateKey, entry)
        return taskSecondsSnapshot

    def _resetDaySessionState(self):
        self.dayTimeline = []
        self.tasks = {name: 0.0 for name in self.tasks.keys()}
        self.unassignedSeconds = 0.0

    def _showRolloverToast(self, splitDates):
        dates = [d for d in (splitDates or []) if d]
        if not dates:
            return
        try:
            if len(dates) == 1:
                nextDay = (date.fromisoformat(dates[0]) + timedelta(days=1)).isoformat()
                self.showToast(
                    f"Session crossed midnight: saved {dates[0]}, continued on {nextDay} (auto punch split applied).",
                    timeout=3000
                )
            else:
                self.showToast(
                    f"Session crossed midnight: auto-split across {len(dates)} day transitions with punch rollover.",
                    timeout=3000
                )
        except Exception:
            pass

    def _processRolloverPunchesAndPosts(self, rolloverItems):
        items = [x for x in (rolloverItems or []) if isinstance(x, dict)]
        if not items:
            return

        if not self.useTimesheetFunctions:
            for item in items:
                dayKey = item.get("dayKey")
                snapshot = item.get("taskSecondsSnapshot")
                self._queueChargeCodePost(snapshot, dateKey=dayKey)
            return

        self._setBusy(True)
        try:
            for item in items:
                outDt = item.get("outDt")
                inDt = item.get("inDt")
                dayKey = item.get("dayKey")
                snapshot = item.get("taskSecondsSnapshot")

                outThread = self.punchOut(punchDt=outDt, silent=True, setBusy=False)
                if outThread:
                    try:
                        outThread.join()
                    except Exception:
                        pass
                if not bool(getattr(self, "_punchOutSuccess", False)):
                    self.showToast(f"Auto punch rollover failed (OUT {dayKey}).", timeout=5000, error=True)
                    continue

                inThread = self.punchIn(punchDt=inDt, silent=True, setBusy=False)
                if inThread:
                    try:
                        inThread.join()
                    except Exception:
                        pass
                if not bool(getattr(self, "_punchInSuccess", False)):
                    self.showToast(f"Auto punch rollover failed (IN {dayKey}).", timeout=5000, error=True)

                self._queueChargeCodePost(snapshot, dateKey=dayKey)
        finally:
            self._setBusy(False)

    def _rolloverIfNeeded(self, now=None):
        if now is None:
            now = time.time()

        currentDayKey = self._currentDateKey(now)
        activeDayKey = getattr(self, "activeDayKey", None)
        if not activeDayKey:
            self.activeDayKey = currentDayKey
            return

        try:
            activeDay = date.fromisoformat(activeDayKey)
            currentDay = date.fromisoformat(currentDayKey)
        except Exception:
            self.activeDayKey = currentDayKey
            return

        splitDates = []
        rolloverItems = []
        while activeDay < currentDay:
            nextDay = activeDay + timedelta(days=1)
            endOfActiveDayDt = datetime(activeDay.year, activeDay.month, activeDay.day, 23, 59, 59)
            midnightDt = datetime(nextDay.year, nextDay.month, nextDay.day, 0, 0, 0)
            endOfActiveDayTs = endOfActiveDayDt.timestamp()
            midnightTs = midnightDt.timestamp()

            if self.hasUnsavedTime:
                self._closeActiveSegment(endOfActiveDayTs)

                if self.currentTask is not None and self.currentStart is not None:
                    elapsed = max(0.0, endOfActiveDayTs - self.currentStart)
                    if elapsed > 0:
                        self.tasks[self.currentTask] = self.tasks.get(self.currentTask, 0.0) + elapsed
                    self.currentStart = midnightTs
                elif self.unassignedStart is not None:
                    elapsed = max(0.0, endOfActiveDayTs - self.unassignedStart)
                    self.unassignedSeconds += elapsed
                    self.unassignedStart = midnightTs

                dayKey = activeDay.isoformat()
                taskSecondsSnapshot = self._saveTimelineForDate(dayKey, self.dayTimeline, mergeChoice="append")
                splitDates.append(dayKey)
                rolloverItems.append({
                    "dayKey": dayKey,
                    "taskSecondsSnapshot": taskSecondsSnapshot,
                    "outDt": endOfActiveDayDt,
                    "inDt": midnightDt,
                })
                self._resetDaySessionState()
                self.hasUnsavedTime = bool(
                    (self.currentTask is not None and self.currentStart is not None)
                    or self.unassignedStart is not None
                )

            activeDay = nextDay

        self.activeDayKey = currentDay.isoformat()
        self._showRolloverToast(splitDates)
        self._processRolloverPunchesAndPosts(rolloverItems)

    def _closeActiveSegment(self, now=None):
        if now is None:
            now = time.time()
        if self.currentTask is not None and self.currentStart is not None:
            self._recordSegment(self.currentTask, self.currentStart, now)
        elif self.unassignedStart is not None:
            self._recordSegment("Untasked", self.unassignedStart, now)

    def initializePunchSession(self, punchDateKey=None):
        with self._timesheetSessionLock:
            try:
                posting = self._getPosting(showToast=True)
                if posting is None:
                    return

                self.punchSession = posting.newSession()
                posting.primeCookies(self.punchSession)
                
                _, loginJson = posting.login(self.punchSession)
                
                self.employeeId = posting.extractEmployeeId(loginJson)
                
                posting.saveCookies(self.punchSession)

                targetDateKey = str(punchDateKey or date.today().isoformat())
                timesheetData = posting.copyPreviousTimesheet(self.punchSession, targetDateKey)
                self.timesheetId = timesheetData["timesheetId"]
                self.timesheetDateKey = targetDateKey
            except Exception as e:
                self.showToast(f"Login error: {str(e)}", timeout=5000, error=True)
                self.punchSession = None
                self.employeeId = None
                self.timesheetId = None
                self.timesheetDateKey = None

    def punchIn(self, punchDt=None, silent=False, setBusy=False):
        if not self.useTimesheetFunctions:
            return
        self._punchInSuccess = False

        def _punchInThread():
            try:
                self._punchInSuccess = False
                if setBusy:
                    self.root.after(0, lambda: self._setBusy(True))
                if not silent:
                    self.root.after(0, lambda: self.showToast("Clocking in…", timeout=1500))
                with self._timesheetSessionLock:
                    posting = self._getPosting(showToast=True)
                    if posting is None:
                        return

                    ts = punchDt if isinstance(punchDt, datetime) else datetime.now()
                    self.initializePunchSession(ts.date().isoformat())

                    if self.punchSession is None or self.employeeId is None:
                        return

                    if punchDt is None and self.roundToHours:
                        try:
                            h, m = (self.workDayStart).split(":")
                            workStartDt = ts.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
                            if abs((ts - workStartDt).total_seconds()) <= 5 * 60:
                                ts = workStartDt
                        except Exception:
                            pass
                    punchPayload = {
                        "id": "",
                        "punchDate": ts.strftime("%m/%d/%Y %I:%M %p"),
                        "type": "IN",
                        "employeeId": self.employeeId,
                        "timesheetPage": True,
                        "location": None,
                        "new": True
                    }
                    posting.postPunch(self.punchSession, punchPayload)
                self._punchInSuccess = True
                if not silent:
                    self.showToast("Successfully clocked in!")
            except Exception as e:
                self._punchInSuccess = False
                if not silent:
                    self.showToast(f"✗ Clock in failed: {e}", error=True)
            finally:
                if setBusy:
                    self.root.after(0, lambda: self._setBusy(False))

        thread = threading.Thread(target=_punchInThread, daemon=True)
        thread.start()
        return thread

    def punchOut(self, punchDt=None, silent=False, setBusy=True):
        if not self.useTimesheetFunctions:
            return
        self._punchOutSuccess = False
        
        def _punchOutThread():
            try:
                self._punchOutSuccess = False
                if setBusy:
                    self.root.after(0, lambda: self._setBusy(True))
                if not silent:
                    self.root.after(0, lambda: self.showToast("Clocking out…", timeout=1500))
                with self._timesheetSessionLock:
                    posting = self._getPosting(showToast=True)
                    if posting is None:
                        return

                    ts = punchDt if isinstance(punchDt, datetime) else datetime.now()
                    self.initializePunchSession(ts.date().isoformat())

                    if self.punchSession is None or self.employeeId is None:
                        return
                    if punchDt is None and self.roundToHours:
                        try:
                            h, m = (self.workDayEnd).split(":")
                            workEndDt = ts.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
                            if abs((ts - workEndDt).total_seconds()) <= 5 * 60:
                                ts = workEndDt
                        except Exception:
                            pass
                    punchPayload = {
                        "id": "",
                        "punchDate": ts.strftime("%m/%d/%Y %I:%M %p"),
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
            finally:
                if setBusy:
                    self.root.after(0, lambda: self._setBusy(False))
        
        thread = threading.Thread(target=_punchOutThread, daemon=True)
        thread.start()
        return thread

    def _postAfterPunchOut(self, taskSecondsSnapshot, dateKey=None):
        punchThread = self.punchOut()
        if not punchThread:
            self._queueChargeCodePost(taskSecondsSnapshot, dateKey=dateKey)
            return

        def _waitAndPost():
            try:
                punchThread.join()
            except Exception:
                pass

            if not bool(getattr(self, "_punchOutSuccess", False)):
                self.showToast("Clock out failed. Charge codes were not posted.", timeout=5000, error=True)
                return
            self._queueChargeCodePost(taskSecondsSnapshot, dateKey=dateKey)

        threading.Thread(target=_waitAndPost, daemon=True).start()

    def _queueChargeCodePost(self, taskSecondsSnapshot, dateKey=None):
        snapshot = dict(taskSecondsSnapshot or {})
        item = {
            "taskSecondsSnapshot": snapshot,
            "dateKey": dateKey if dateKey else None,
        }
        try:
            with self._pendingChargePostLock:
                self._pendingChargePosts.append(item)
        except Exception:
            self._pendingChargePosts.append(item)

    def _popPendingChargePosts(self):
        pendingPosts = []
        try:
            with self._pendingChargePostLock:
                if self._pendingChargePosts:
                    pendingPosts = list(self._pendingChargePosts)
                    self._pendingChargePosts = []
        except Exception:
            pendingPosts = list(getattr(self, "_pendingChargePosts", []) or [])
            self._pendingChargePosts = []
        return pendingPosts

    def postChargeCodeHours(self, taskSecondsSnapshot=None, dateKey=None, spawnThread=True):
        if not self.autoChargeCodes:
            return

        chargeCodesByKey = self.loadChargeCodesFromJsonl()
        if not chargeCodesByKey:
            self.showToast("No charge codes found", error=True)
            return

        targetDateKey = date.today().isoformat()
        if dateKey:
            try:
                parsedDate = datetime.strptime(dateKey, "%Y-%m-%d")
                targetDateKey = parsedDate.date().isoformat()
                dateStr = parsedDate.strftime("%m/%d/%Y")
            except Exception:
                dateStr = date.today().strftime("%m/%d/%Y")
        else:
            dateStr = date.today().strftime("%m/%d/%Y")

        plan = self._buildChargeCodePostingPlan(taskSecondsSnapshot, chargeCodesByKey)
        roundedTaskHours = dict(plan.get("roundedTaskHours", {}))
        if not roundedTaskHours:
            self.showToast("No task time to post")
            return

        if bool(getattr(self, "reviewBeforePost", False)):
            if not self._confirmChargeCodeReview(plan, dateStr):
                self.showToast("Charge code posting canceled")
                return

        def queueUi(callback):
            self._queueUi(callback)

        def job():
            try:
                queueUi(lambda: self._setBusy(True))
                queueUi(lambda: self.showToast("Posting charge codes...", timeout=1500))
                with self._timesheetSessionLock:
                    posting = self._getPosting(showToast=True)
                    if posting is None:
                        return

                    sessionDateKey = str(getattr(self, "timesheetDateKey", "") or "")
                    if (
                        self.punchSession is None
                        or self.employeeId is None
                        or self.timesheetId is None
                        or sessionDateKey != targetDateKey
                    ):
                        self.initializePunchSession(targetDateKey)

                    if self.punchSession is None or self.employeeId is None or self.timesheetId is None:
                        queueUi(lambda: self.showToast("Session not ready", error=True))
                        return

                    chargeCodesByKey = dict(plan.get("chargeCodesByKey", {}))
                    hoursByKey = dict(plan.get("hoursByKey", {}))
                    unmappedHours = float(plan.get("unmappedTotal", 0.0))
                    targetTotal = float(plan.get("targetTotal", 0.0))

                    hadError = False
                    for key, hours in hoursByKey.items():
                        if hours <= 0:
                            continue
                        hoursPayload = float(f"{hours:.1f}")
                        try:
                            posting.postHoursWorked(
                                self.punchSession,
                                self.employeeId,
                                self.timesheetId,
                                chargeCodesByKey[key],
                                dateStr,
                                hoursPayload
                            )
                        except Exception:
                            hadError = True

                mappedTotal = round(sum(hoursByKey.values()), 1)

                if hadError:
                    queueUi(lambda: self.showToast("Posted charge codes (some failed)", error=True))
                elif unmappedHours > 0:
                    queueUi(lambda: self.showToast(
                        f"Posted {mappedTotal:.1f}h charge codes ({unmappedHours:.1f}h unmapped, day total {targetTotal:.1f}h)",
                        timeout=5000,
                        error=True
                    ))
                else:
                    queueUi(lambda: self.showToast("Successfully posted charge codes"))

            except Exception:
                queueUi(lambda: self.showToast("Error posting charge codes", error=True))
            finally:
                queueUi(lambda: self._setBusy(False))

        if spawnThread:
            threading.Thread(target=job, daemon=True).start()
        else:
            job()

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
        self._rolloverIfNeeded(now)

        if self.hasUnsavedTime:
            closeChoice = messagebox.askyesnocancel(
                "Exit Task Tracker",
                "You have unsaved time.\n\n"
                "Yes: Save and post before exiting.\n"
                "No: Exit without saving/posting.\n"
                "Cancel: Keep the app open."
            )
            if closeChoice is None:
                return
            if closeChoice is False:
                self._popPendingChargePosts()
                self.hasUnsavedTime = False
                self.dayTimeline = []
                self.root.destroy()
                return

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
            dayKey = getattr(self, "activeDayKey", self._currentDateKey(now))
            choice = self._chooseMergeActionForDate(dayKey, allowSkip=True)
            if choice == "cancel":
                return

            if choice == "skip":
                for item in self._popPendingChargePosts():
                    if not isinstance(item, dict):
                        self.postChargeCodeHours(item, spawnThread=False)
                        continue
                    self.postChargeCodeHours(
                        item.get("taskSecondsSnapshot"),
                        dateKey=item.get("dateKey"),
                        spawnThread=False
                    )
                self.hasUnsavedTime = False
                self.dayTimeline = []
                self.root.destroy()
                return

            mergeChoice = "append" if choice == "append" else "overwrite"
            taskSecondsSnapshot = self._saveTimelineForDate(dayKey, self.dayTimeline, mergeChoice=mergeChoice)
            
            # Punch out when closing with unsaved time
            punchThread = self.punchOut()
            if punchThread:
                punchThread.join()
            if self._punchOutSuccess:
                self.showToast("Successfully clocked out!")
                self.postChargeCodeHours(taskSecondsSnapshot, dateKey=dayKey, spawnThread=False)
            else:
                messagebox.showerror(
                    "Clock out failed",
                    "Charge codes were not posted because clock out failed. The summary was still saved locally."
                )
            
            self.hasUnsavedTime = False
            self.dayTimeline = []

        for item in self._popPendingChargePosts():
            if not isinstance(item, dict):
                self.postChargeCodeHours(item, spawnThread=False)
                continue
            self.postChargeCodeHours(
                item.get("taskSecondsSnapshot"),
                dateKey=item.get("dateKey"),
                spawnThread=False
            )

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
        now = time.time()
        self._ensureCurrentDayContext(now)

        if not messagebox.askyesno("Clear Day", "Clear all times and timeline for today? This cannot be undone."):
            return

        if self.currentTask is not None and self.currentStart is not None:
            self.currentTask = None
            self.currentStart = None
        
        self.unassignedStart = None
        self.unassignedSeconds = 0.0
        
        for name in self.tasks.keys():
            self.tasks[name] = 0.0
        
        self.dayTimeline = []
        
        dayKey = getattr(self, "activeDayKey", self._currentDateKey(now))
        if dayKey in self.history:
            del self.history[dayKey]
        
        self.hasUnsavedTime = False
        self.activeDayKey = self._currentDateKey(now)
        self.refreshRowStyles()
        messagebox.showinfo("Cleared", "All times and timeline have been cleared.")

    def startTask(self, name):
        now = time.time()

        if self.dragTaskName is not None:
            return

        self._ensureCurrentDayContext(now)

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
                hi = "#6b7280"
                hi_t = 1
            elif name == self.currentTask:
                if bool(self.selectedTaskUsesColor):
                    taskColor = self.getTaskDisplayColor(name)
                    bg = self._mixHex(self.cardColor, taskColor, 0.20)
                else:
                    bg = self.activeColor
                bd = 0
                relief = "flat"
                hi = bg
                hi_t = 0
            else:
                bg = self.cardColor
                bd = 0
                relief = "flat"
                hi = self.cardColor
                hi_t = 0
            rowFrame.config(
                bg=bg,
                bd=bd,
                relief=relief,
                highlightthickness=hi_t,
                highlightbackground=hi,
                highlightcolor=hi
            )
            nameLabel.config(bg=bg)
            deleteBtn.config(bg=bg)

    def deleteTaskPrompt(self, name):
        if name not in self.rows:
            return

        now = time.time()
        self._ensureCurrentDayContext(now)

        if not messagebox.askyesno("Delete Task", f"Delete task '{name}'? This does not remove past summaries."):
            return

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
        if name in self.groups:
            del self.groups[name]
        if name in self.taskColorOverrides:
            del self.taskColorOverrides[name]
            self._ensureColorSettingsConsistency()

        self.relayoutRows()
        self.saveData()

    def deleteSelected(self, event=None):
        if self.currentTask is not None:
            self.deleteTaskPrompt(self.currentTask)

    def updateLoop(self):
        now = time.time()
        self._rolloverIfNeeded(now)
        self._syncIdleActiveDayKey(now)

        for item in self._popPendingChargePosts():
            if not isinstance(item, dict):
                self.postChargeCodeHours(item)
                continue
            self.postChargeCodeHours(
                item.get("taskSecondsSnapshot"),
                dateKey=item.get("dateKey")
            )

        for name, baseSeconds in self.tasks.items():
            extra = 0.0
            if name == self.currentTask and self.currentStart is not None:
                extra = now - self.currentStart
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
        self._updateSessionStatusStrip()
        self.root.after(50, self.updateLoop)

    def _collectTaskSecondsFromTimeline(self, timeline):
        agg = {}
        if not isinstance(timeline, list):
            return agg

        for seg in timeline:
            if not isinstance(seg, dict):
                continue
            taskName = str(seg.get("task", "")).strip()
            if not taskName:
                continue
            try:
                startDt = datetime.fromisoformat(seg.get("start", ""))
                endDt = datetime.fromisoformat(seg.get("end", ""))
            except Exception:
                continue
            duration = (endDt - startDt).total_seconds()
            if duration <= 0:
                continue
            agg[taskName] = agg.get(taskName, 0.0) + duration

        return agg

    def _buildSummaryFromTaskSeconds(self, taskSeconds):
        roundedHours, totalHours = self._normalizeRoundedHours(taskSeconds)
        lines = []
        for name, hours in sorted(roundedHours.items(), key=lambda kv: kv[0].lower()):
            lines.append(f"{name}: {hours:.1f} h")
        lines.append(f"Total: {totalHours:.1f} h")
        return "\n".join(lines)

    def _chooseMergeActionForDate(self, dateKey, allowSkip=False):
        existingEntry = self.history.get(dateKey)
        if not existingEntry:
            return "new"

        if allowSkip:
            choice = messagebox.askyesnocancel(
                "Existing summary",
                "A summary already exists for this date.\n\n"
                "Yes: Append\n"
                "No: Overwrite\n"
                "Cancel: More options"
            )
            if choice is None:
                skipChoice = messagebox.askyesno(
                    "Close without saving",
                    "Close without saving this summary?"
                )
                if skipChoice:
                    return "skip"
                return "cancel"
        else:
            choice = messagebox.askyesnocancel(
                "Existing summary",
                "A summary already exists for this date.\n\n"
                "Yes: Append\n"
                "No: Overwrite\n"
                "Cancel: Keep existing summary"
            )
            if choice is None:
                return "cancel"

        return "append" if choice else "overwrite"

    def _groupAggregates(self, taskAgg):
        grouped = {}
        for task, hours in taskAgg.items():
            group = self.groups.get(task)
            if not group:
                continue
            grouped[group] = grouped.get(group, 0.0) + hours
        return grouped

    def _collectTaskSecondsSnapshot(self):
        taskSeconds = dict(self.tasks)
        now = time.time()

        if self.currentTask and self.currentStart is not None:
            taskSeconds[self.currentTask] = (
                taskSeconds.get(self.currentTask, 0.0) + max(0.0, now - self.currentStart)
            )

        if self.unassignedStart is not None:
            taskSeconds["Untasked"] = (
                taskSeconds.get("Untasked", 0.0) + max(0.0, now - self.unassignedStart)
            )

        if self.unassignedSeconds > 0:
            taskSeconds["Untasked"] = (
                taskSeconds.get("Untasked", 0.0) + self.unassignedSeconds
            )

        return taskSeconds

    def _buildChargeCodePostingPlan(self, taskSecondsSnapshot=None, chargeCodesByKey=None):
        if isinstance(taskSecondsSnapshot, dict):
            taskSeconds = dict(taskSecondsSnapshot)
        else:
            taskSeconds = self._collectTaskSecondsSnapshot()

        roundedTaskHours, targetTotal = self._normalizeRoundedHours(taskSeconds)

        if chargeCodesByKey is None:
            chargeCodesByKey = self.loadChargeCodesFromJsonl()
        chargeCodesByKey = chargeCodesByKey or {}

        canonicalChargeKey = {
            self._canonicalKey(key): key for key in chargeCodesByKey.keys()
        }

        hoursByKey = {key: 0.0 for key in chargeCodesByKey.keys()}
        unmappedByTask = {}

        for taskName, hours in roundedTaskHours.items():
            chargeKey = canonicalChargeKey.get(self._canonicalKey(taskName))
            if chargeKey is None:
                groupName = self._lookupGroupForTask(self.groups, taskName)
                if groupName:
                    chargeKey = canonicalChargeKey.get(self._canonicalKey(groupName))

            if chargeKey is None:
                unmappedByTask[taskName] = round(unmappedByTask.get(taskName, 0.0) + hours, 1)
                continue

            hoursByKey[chargeKey] = round(hoursByKey.get(chargeKey, 0.0) + hours, 1)

        mappedTotal = round(sum(hoursByKey.values()), 1)
        unmappedTotal = round(sum(unmappedByTask.values()), 1)

        return {
            "taskSeconds": taskSeconds,
            "roundedTaskHours": roundedTaskHours,
            "targetTotal": round(targetTotal, 1),
            "chargeCodesByKey": chargeCodesByKey,
            "hoursByKey": hoursByKey,
            "mappedTotal": mappedTotal,
            "unmappedByTask": unmappedByTask,
            "unmappedTotal": unmappedTotal,
        }

    def _getChargeCodesCached(self, maxAgeSeconds=5.0):
        now = time.time()
        if now - float(self._cachedChargeCodesTs or 0.0) > float(maxAgeSeconds):
            self._cachedChargeCodesByKey = self.loadChargeCodesFromJsonl() or {}
            self._cachedChargeCodesTs = now
        return dict(self._cachedChargeCodesByKey or {})

    def _confirmChargeCodeReview(self, plan, dateStr):
        hoursByKey = dict(plan.get("hoursByKey", {}))
        unmappedByTask = dict(plan.get("unmappedByTask", {}))
        targetTotal = float(plan.get("targetTotal", 0.0))
        mappedTotal = float(plan.get("mappedTotal", 0.0))
        unmappedTotal = float(plan.get("unmappedTotal", 0.0))

        lines = [
            f"Date: {dateStr}",
            f"Rounded day total: {targetTotal:.1f} h",
            f"Mapped: {mappedTotal:.1f} h",
            f"Unmapped: {unmappedTotal:.1f} h",
            "",
            "Charge code posting:",
        ]

        for key, hours in sorted(hoursByKey.items(), key=lambda kv: kv[0].lower()):
            if hours <= 0:
                continue
            lines.append(f"  {key}: {hours:.1f} h")

        if unmappedByTask:
            lines.append("")
            lines.append("Unmapped tasks:")
            for task, hours in sorted(unmappedByTask.items(), key=lambda kv: kv[0].lower()):
                lines.append(f"  {task}: {hours:.1f} h")

        lines.append("")
        lines.append("Post charge codes now?")
        return messagebox.askyesno("Review Charge Codes", "\n".join(lines))

    def _updateSessionStatusStrip(self):
        if not hasattr(self, "sessionStatusLabel"):
            return

        now = time.time()
        if now < float(self._nextStatusRefreshTs or 0.0):
            return
        self._nextStatusRefreshTs = now + 0.8

        snapshot = self._collectTaskSecondsSnapshot()
        _, totalRounded = self._normalizeRoundedHours(snapshot)

        if self.currentTask and self.currentStart is not None:
            mode = f"Active"
        elif self.unassignedStart is not None:
            mode = "Active - Untasked"
        else:
            mode = "Idle"

        text = f"Status: {mode} · Total {totalRounded:.1f}h"
        fg = "#9ca3af"

        if self.autoChargeCodes:
            chargeCodesByKey = self._getChargeCodesCached(maxAgeSeconds=5.0)
            if chargeCodesByKey:
                plan = self._buildChargeCodePostingPlan(snapshot, chargeCodesByKey)
                unmapped = float(plan.get("unmappedTotal", 0.0))
                if unmapped > 0:
                    text += f" · Unmapped {unmapped:.1f}h"
                    fg = "#ffae7a"
                else:
                    text += " · All mapped"
            else:
                text += " · No charge codes loaded"
                fg = "#ffae7a"

        try:
            self.sessionStatusLabel.config(text=text, fg=fg)
        except Exception:
            pass

    def _normalizeRoundedHours(self, secondsByTask):
        if not isinstance(secondsByTask, dict) or not secondsByTask:
            return {}, 0.0

        rawHours = {}
        for name, seconds in secondsByTask.items():
            try:
                secVal = float(seconds)
            except Exception:
                continue
            if secVal <= 0:
                continue
            rawHours[name] = secVal / 3600.0

        if not rawHours:
            return {}, 0.0

        targetTenths = int(round(sum(rawHours.values()) * 10.0))
        if targetTenths <= 0:
            return {}, 0.0

        nearestTenths = {name: int(round(hours * 10.0)) for name, hours in rawHours.items()}

        minTenths = {name: 1 for name in rawHours.keys()}
        # If there are too many tiny tasks to honor a 0.1 floor for all, relax
        # smallest ones (prefer Untasked) down to 0.0 so totals can reconcile.
        if targetTenths < len(rawHours):
            overflow = len(rawHours) - targetTenths
            relaxOrder = sorted(
                rawHours.items(),
                key=lambda kv: (0 if kv[0] == "Untasked" else 1, kv[1], kv[0].lower())
            )
            for idx, (name, _) in enumerate(relaxOrder):
                if idx >= overflow:
                    break
                minTenths[name] = 0

        alloc = {name: max(minTenths[name], nearestTenths[name]) for name in rawHours.keys()}

        def reduceChoice(withinOne):
            candidates = []
            for name in alloc.keys():
                if alloc[name] <= minTenths[name]:
                    continue
                if withinOne and abs((alloc[name] - 1) - nearestTenths[name]) > 1:
                    continue
                rawTenths = rawHours[name] * 10.0
                afterErr = abs((alloc[name] - 1) - rawTenths)
                candidates.append((
                    0 if name == "Untasked" else 1,  # prefer reducing Untasked first
                    afterErr,                         # then minimize error from raw
                    -alloc[name],                    # then take larger buckets
                    name.lower(),
                    name
                ))
            if not candidates:
                return None
            candidates.sort()
            return candidates[0][-1]

        def increaseChoice(withinOne):
            candidates = []
            for name in alloc.keys():
                if withinOne and abs((alloc[name] + 1) - nearestTenths[name]) > 1:
                    continue
                rawTenths = rawHours[name] * 10.0
                afterErr = abs((alloc[name] + 1) - rawTenths)
                candidates.append((
                    1 if name == "Untasked" else 0,  # avoid inflating Untasked when possible
                    afterErr,                         # then minimize error from raw
                    name.lower(),
                    name
                ))
            if not candidates:
                return None
            candidates.sort()
            return candidates[0][-1]

        diff = targetTenths - sum(alloc.values())
        guard = 0
        while diff < 0 and guard < 20000:
            pick = reduceChoice(withinOne=True) or reduceChoice(withinOne=False)
            if pick is None:
                break
            alloc[pick] -= 1
            diff += 1
            guard += 1

        guard = 0
        while diff > 0 and guard < 20000:
            pick = increaseChoice(withinOne=True) or increaseChoice(withinOne=False)
            if pick is None:
                break
            alloc[pick] += 1
            diff -= 1
            guard += 1

        # Final safety: if negative diff remains, relax floors further.
        if diff < 0:
            relaxOrder = sorted(
                rawHours.items(),
                key=lambda kv: (0 if kv[0] == "Untasked" else 1, kv[1], kv[0].lower())
            )
            for name, _ in relaxOrder:
                while diff < 0 and alloc.get(name, 0) > 0:
                    alloc[name] -= 1
                    diff += 1
                if diff >= 0:
                    break

        rounded = {name: round(tenths / 10.0, 1) for name, tenths in alloc.items() if tenths > 0}
        targetTotal = round(targetTenths / 10.0, 1)
        return rounded, targetTotal

    def endDay(self):
        now = time.time()
        self._rolloverIfNeeded(now)

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

        dayKey = getattr(self, "activeDayKey", self._currentDateKey(now))
        choice = self._chooseMergeActionForDate(dayKey)
        if choice == "cancel":
            return

        mergeChoice = "append" if choice == "append" else "overwrite"
        taskSecondsSnapshot = self._saveTimelineForDate(dayKey, self.dayTimeline, mergeChoice=mergeChoice)
        merged = self.history.get(dayKey, {}).get("summary", "")

        self._postAfterPunchOut(taskSecondsSnapshot, dateKey=dayKey)
        
        # CLEAR session data after saving TODO: should this be a setting?
        self._resetDaySessionState()
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
    app.adjustWindowHeight()

    root.deiconify()
    root.mainloop()
