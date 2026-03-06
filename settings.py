import tkinter as tk
from tkinter import messagebox, colorchooser
from tkinter import ttk
import json
import os
import re
import sys
import threading
from datetime import date

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

DEFAULT_SETTINGS = {
    "workDayStart": "09:00",
    "workDayEnd": "17:00",
    "minRecordedMinutes": 1,
    "roundToHours": False,
    "mainWindowWidth": 400,
    "mainWindowHeight": 400,
    "useTimesheetFunctions": False,
    "autoChargeCodes": False,
    "reviewBeforePost": False,
    "useDefaultBaseUrl": True,
    "colorPalettePreset": "classic",
    "selectedTaskUsesColor": True,
    "taskColorOverrides": {},
    "groupColorOverrides": {}
}

DEFAULT_BASE_URL = "https://nearspacelaunch.hourtimesheet.com"

def loadSettings(settingsPath):
    if not os.path.exists(settingsPath):
        return dict(DEFAULT_SETTINGS)
    try:
        with open(settingsPath, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return dict(DEFAULT_SETTINGS)
        merged = dict(DEFAULT_SETTINGS)
        merged.update(data)
        return merged
    except Exception:
        return dict(DEFAULT_SETTINGS)

def loadChargeCodesFromJsonl(dataFile):
    """Extract charge codes grouped by chunk from JSONL file"""
    chunks = []
    if not os.path.exists(dataFile):
        return chunks
    try:
        with open(dataFile, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("//"):
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if obj.get("type") == "chargeCode":
                    codes = obj.get("chargeCodes", [])
                    if codes:
                        chunks.append(codes)
    except Exception:
        pass
    return chunks

def openSettings(app):
    settingsPath = os.path.join(app.getDataDir(), "settings.json")
    dataFile = app.realPath if hasattr(app, "realPath") else os.path.join(app.getDataDir(), "tasks.jsonl")


    def parseTimeHHMM(s, fallback):
        s = (s or "").strip()
        if not re.fullmatch(r"\d{2}:\d{2}", s):
            return fallback
        hh = int(s[0:2])
        mm = int(s[3:5])
        if hh < 0 or hh > 23 or mm < 0 or mm > 59:
            return fallback
        return s

    settings = loadSettings(settingsPath)
    chargeCodes = loadChargeCodesFromJsonl(dataFile)

    def sanitizeHexColor(value):
        if not isinstance(value, str):
            return None
        s = value.strip()
        if len(s) != 7 or not s.startswith("#"):
            return None
        hexpart = s[1:]
        if not all(c in "0123456789abcdefABCDEF" for c in hexpart):
            return None
        return "#" + hexpart.lower()

    def normalizeColorMap(mapping):
        if not isinstance(mapping, dict):
            return {}
        out = {}
        for k, v in mapping.items():
            if not isinstance(k, str):
                continue
            key = k.strip()
            if not key:
                continue
            c = sanitizeHexColor(v)
            if c:
                out[key] = c
        return out

    def hex_to_rgb01(colorHex):
        c = sanitizeHexColor(colorHex)
        if not c:
            return None
        return (int(c[1:3], 16) / 255.0, int(c[3:5], 16) / 255.0, int(c[5:7], 16) / 255.0)

    def color_distance(c1, c2):
        a = hex_to_rgb01(c1)
        b = hex_to_rgb01(c2)
        if a is None or b is None:
            return 999.0
        dr = (a[0] - b[0]) * 255.0
        dg = (a[1] - b[1]) * 255.0
        db = (a[2] - b[2]) * 255.0
        return (dr * dr + dg * dg + db * db) ** 0.5

    taskColorOverrides = normalizeColorMap(
        settings.get("taskColorOverrides", settings.get("taskColors", {}))
    )
    groupColorOverrides = normalizeColorMap(
        settings.get("groupColorOverrides", settings.get("groupColorBases", {}))
    )
    originalTaskNames = set(app.rows.keys()) if hasattr(app, "rows") else set()
    workingTaskNames = list(originalTaskNames)
    workingGroupsByTask = dict(app.groups or {})
    pendingTaskRenames = {}

    win = tk.Toplevel(app.root)
    win.title("Settings")
    win.configure(bg=app.bgColor)
    win.resizable(True, True)
    win.transient(app.root)
    win.grab_set()
    win.lift()
    win.focus_force()
    iconPath = resourcePath("hourglass.ico")
    if os.path.exists(iconPath):
        try:
            win.iconbitmap(iconPath)
        except Exception:
            pass

    sw = win.winfo_screenwidth()
    sh = win.winfo_screenheight()

    w = min(1160, max(880, sw - 120))
    h = min(700, max(580, sh - 140))

    w = min(w, max(700, sw - 40))
    h = min(h, max(460, sh - 40))

    x = max(20, (sw - w) // 2)
    y = max(20, (sh - h) // 2)
    win.geometry(f"{w}x{h}+{x}+{y}")

    title = tk.Label(
        win,
        text="Settings",
        font=("Segoe UI", 14, "bold"),
        fg=app.textColor,
        bg=app.bgColor,
        anchor="w"
    )
    title.pack(fill="x", padx=14, pady=(12, 8))

    # Organize dense settings into tabs to reduce visual crowding.
    mainFrame = tk.Frame(win, bg=app.bgColor)
    mainFrame.pack(fill="both", expand=True, padx=14, pady=(0, 10))

    style = ttk.Style(win)
    try:
        style.theme_use("clam")
    except Exception:
        pass
    style.configure("TTKSettings.TNotebook", background=app.bgColor, borderwidth=0)
    style.configure(
        "TTKSettings.TNotebook.Tab",
        background="#1b1f24",
        foreground=app.textColor,
        padding=(12, 6)
    )
    style.map(
        "TTKSettings.TNotebook.Tab",
        background=[("selected", app.cardColor), ("active", "#2c3440")],
        foreground=[("selected", app.textColor), ("active", app.textColor)]
    )

    tabs = ttk.Notebook(mainFrame, style="TTKSettings.TNotebook")
    tabs.pack(fill="both", expand=True)

    # Tab 1: General settings
    generalFrame = tk.Frame(tabs, bg=app.cardColor)
    tabs.add(generalFrame, text="General")
    generalFrame.columnconfigure(0, weight=1)
    generalFrame.columnconfigure(1, weight=0)

    row = 0

    workStartLabel = tk.Label(
        generalFrame,
        text="Work day start (HH:MM):",
        font=("Segoe UI", 10),
        fg=app.textColor,
        bg=app.cardColor,
        anchor="w"
    )
    workStartLabel.grid(row=row, column=0, sticky="w", padx=12, pady=(12, 6))

    workStartVar = tk.StringVar(value=str(settings.get("workDayStart", "09:00")))
    workStartEntry = tk.Entry(
        generalFrame,
        textvariable=workStartVar,
        font=("Segoe UI", 10),
        bg="#2b3138",
        fg=app.textColor,
        insertbackground=app.textColor,
        relief="flat",
        highlightthickness=1,
        highlightbackground="#0b0e12",
        highlightcolor="#0b0e12",
        bd=0,
        width=10
    )
    workStartEntry.grid(row=row, column=1, sticky="e", padx=12, pady=(12, 6))

    row += 1

    workEndLabel = tk.Label(
        generalFrame,
        text="Work day end (HH:MM):",
        font=("Segoe UI", 10),
        fg=app.textColor,
        bg=app.cardColor,
        anchor="w"
    )
    workEndLabel.grid(row=row, column=0, sticky="w", padx=12, pady=6)

    workEndVar = tk.StringVar(value=str(settings.get("workDayEnd", "17:00")))
    workEndEntry = tk.Entry(
        generalFrame,
        textvariable=workEndVar,
        font=("Segoe UI", 10),
        bg="#2b3138",
        fg=app.textColor,
        insertbackground=app.textColor,
        relief="flat",
        highlightthickness=1,
        highlightbackground="#0b0e12",
        highlightcolor="#0b0e12",
        bd=0,
        width=10
    )
    workEndEntry.grid(row=row, column=1, sticky="e", padx=12, pady=6)

    row += 1

    minMinutesLabel = tk.Label(
        generalFrame,
        text="Minimum time recorded (minutes):",
        font=("Segoe UI", 10),
        fg=app.textColor,
        bg=app.cardColor,
        anchor="w"
    )
    minMinutesLabel.grid(row=row, column=0, sticky="w", padx=12, pady=6)

    minMinutesVar = tk.StringVar(value=str(settings.get("minRecordedMinutes", 1)))
    minMinutesEntry = tk.Entry(
        generalFrame,
        textvariable=minMinutesVar,
        font=("Segoe UI", 10),
        bg="#2b3138",
        fg=app.textColor,
        insertbackground=app.textColor,
        relief="flat",
        highlightthickness=1,
        highlightbackground="#0b0e12",
        highlightcolor="#0b0e12",
        bd=0,
        width=10
    )
    minMinutesEntry.grid(row=row, column=1, sticky="e", padx=12, pady=6)

    row += 1

    mainWidthLabel = tk.Label(
        generalFrame,
        text="Main window width (px):",
        font=("Segoe UI", 10),
        fg=app.textColor,
        bg=app.cardColor,
        anchor="w"
    )
    mainWidthLabel.grid(row=row, column=0, sticky="w", padx=12, pady=6)

    mainWidthVar = tk.StringVar(value=str(settings.get("mainWindowWidth", 400)))
    mainWidthEntry = tk.Entry(
        generalFrame,
        textvariable=mainWidthVar,
        font=("Segoe UI", 10),
        bg="#2b3138",
        fg=app.textColor,
        insertbackground=app.textColor,
        relief="flat",
        highlightthickness=1,
        highlightbackground="#0b0e12",
        highlightcolor="#0b0e12",
        bd=0,
        width=10
    )
    mainWidthEntry.grid(row=row, column=1, sticky="e", padx=12, pady=6)

    row += 1

    mainHeightLabel = tk.Label(
        generalFrame,
        text="Main window height (px):",
        font=("Segoe UI", 10),
        fg=app.textColor,
        bg=app.cardColor,
        anchor="w"
    )
    mainHeightLabel.grid(row=row, column=0, sticky="w", padx=12, pady=6)

    mainHeightVar = tk.StringVar(value=str(settings.get("mainWindowHeight", 400)))
    mainHeightEntry = tk.Entry(
        generalFrame,
        textvariable=mainHeightVar,
        font=("Segoe UI", 10),
        bg="#2b3138",
        fg=app.textColor,
        insertbackground=app.textColor,
        relief="flat",
        highlightthickness=1,
        highlightbackground="#0b0e12",
        highlightcolor="#0b0e12",
        bd=0,
        width=10
    )
    mainHeightEntry.grid(row=row, column=1, sticky="e", padx=12, pady=6)

    row += 1

    baseUrlLabel = tk.Label(
        generalFrame,
        text="Base URL:",
        font=("Segoe UI", 9),
        fg=app.textColor,
        bg=app.cardColor,
        anchor="w"
    )
    baseUrlLabel.grid(row=row, column=0, sticky="w", padx=12, pady=6)

    baseUrlVar = tk.StringVar(value="")
    baseUrlEntry = tk.Entry(
        generalFrame,
        textvariable=baseUrlVar,
        font=("Segoe UI", 9),
        bg="#2b3138",
        fg=app.textColor,
        insertbackground=app.textColor,
        relief="flat",
        highlightthickness=1,
        highlightbackground="#0b0e12",
        highlightcolor="#0b0e12",
        bd=0
    )
    baseUrlEntry.grid(row=row, column=1, sticky="ew", padx=12, pady=6)

    row += 1

    emailLabel = tk.Label(
        generalFrame,
        text="Email:",
        font=("Segoe UI", 9),
        fg=app.textColor,
        bg=app.cardColor,
        anchor="w"
    )
    emailLabel.grid(row=row, column=0, sticky="w", padx=12, pady=6)

    emailVar = tk.StringVar(value="")
    emailEntry = tk.Entry(
        generalFrame,
        textvariable=emailVar,
        font=("Segoe UI", 9),
        bg="#2b3138",
        fg=app.textColor,
        insertbackground=app.textColor,
        relief="flat",
        highlightthickness=1,
        highlightbackground="#0b0e12",
        highlightcolor="#0b0e12",
        bd=0
    )
    emailEntry.grid(row=row, column=1, sticky="ew", padx=12, pady=6)

    row += 1

    passwordLabel = tk.Label(
        generalFrame,
        text="Password:",
        font=("Segoe UI", 9),
        fg=app.textColor,
        bg=app.cardColor,
        anchor="w"
    )
    passwordLabel.grid(row=row, column=0, sticky="w", padx=12, pady=6)

    passwordVar = tk.StringVar(value="")
    passwordEntry = tk.Entry(
        generalFrame,
        textvariable=passwordVar,
        font=("Segoe UI", 9),
        bg="#2b3138",
        fg=app.textColor,
        insertbackground=app.textColor,
        relief="flat",
        highlightthickness=1,
        highlightbackground="#0b0e12",
        highlightcolor="#0b0e12",
        bd=0,
        show="*"
    )
    passwordEntry.grid(row=row, column=1, sticky="ew", padx=12, pady=6)

    row += 1

    useDefaultBaseUrlVar = tk.IntVar(value=1 if settings.get("useDefaultBaseUrl", True) else 0)
    def applyBaseUrlState():
        if useDefaultBaseUrlVar.get():
            baseUrlLabel.grid_remove()
            baseUrlEntry.grid_remove()
            baseUrlVar.set("")
        else:
            baseUrlLabel.grid()
            baseUrlEntry.grid()
            baseUrlEntry.config(
                state="normal",
                bg="#2b3138",
                fg=app.textColor,
                highlightbackground="#0b0e12",
                highlightcolor="#0b0e12"
            )
    useDefaultBaseUrlCb = tk.Checkbutton(
        generalFrame,
        text="Use default Base URL",
        variable=useDefaultBaseUrlVar,
        bg=app.cardColor,
        fg=app.textColor,
        activebackground=app.cardColor,
        activeforeground=app.textColor,
        selectcolor=app.cardColor,
        relief="flat",
        command=applyBaseUrlState
    )
    useDefaultBaseUrlCb.grid(row=row, column=0, columnspan=2, sticky="w", padx=12, pady=(0, 12))

    row += 1

    roundToHoursVar = tk.IntVar(value=1 if settings.get("roundToHours", False) else 0)
    roundCb = tk.Checkbutton(
        generalFrame,
        text="Round to hours",
        variable=roundToHoursVar,
        bg=app.cardColor,
        fg=app.textColor,
        activebackground=app.cardColor,
        activeforeground=app.textColor,
        selectcolor=app.cardColor,
        relief="flat"
    )
    roundCb.grid(row=row, column=0, columnspan=2, sticky="w", padx=12, pady=(10, 12))

    row += 1

    useTimesheetVar = tk.IntVar(value=1 if settings.get("useTimesheetFunctions", True) else 0)
    useTimesheetCb = tk.Checkbutton(
        generalFrame,
        text="Automatically punch in/out",
        variable=useTimesheetVar,
        bg=app.cardColor,
        fg=app.textColor,
        activebackground=app.cardColor,
        activeforeground=app.textColor,
        selectcolor=app.cardColor,
        relief="flat"
    )
    useTimesheetCb.grid(row=row, column=0, columnspan=2, sticky="w", padx=12, pady=(0, 12))

    row += 1

    autoChargeCodesVar = tk.IntVar(value=1 if settings.get("autoChargeCodes", True) else 0)
    autoChargeCodesCb = tk.Checkbutton(
        generalFrame,
        text="Auto charge codes",
        variable=autoChargeCodesVar,
        bg=app.cardColor,
        fg=app.textColor,
        activebackground=app.cardColor,
        activeforeground=app.textColor,
        selectcolor=app.cardColor,
        relief="flat"
    )
    autoChargeCodesCb.grid(row=row, column=0, columnspan=2, sticky="w", padx=12, pady=(0, 12))

    row += 1

    reviewBeforePostVar = tk.IntVar(value=1 if settings.get("reviewBeforePost", False) else 0)
    reviewBeforePostCb = tk.Checkbutton(
        generalFrame,
        text="Review before posting charge codes",
        variable=reviewBeforePostVar,
        bg=app.cardColor,
        fg=app.textColor,
        activebackground=app.cardColor,
        activeforeground=app.textColor,
        selectcolor=app.cardColor,
        relief="flat"
    )
    reviewBeforePostCb.grid(row=row, column=0, columnspan=2, sticky="w", padx=12, pady=(0, 12))

    # Tab 2: Tasks and colors
    paletteFrame = tk.Frame(tabs, bg=app.cardColor)
    tabs.add(paletteFrame, text="Tasks & Colors")
    paletteFrame.columnconfigure(0, weight=1)
    paletteFrame.rowconfigure(4, weight=1)

    paletteLabel = tk.Label(
        paletteFrame,
        text="Tasks and Colors",
        font=("Segoe UI", 10, "bold"),
        fg=app.textColor,
        bg=app.cardColor
    )
    paletteLabel.grid(row=0, column=0, sticky="w", padx=12, pady=(12, 6))

    palettePresetVar = tk.StringVar(value=str(settings.get("colorPalettePreset", "classic") or "classic").capitalize())
    selectedTaskUsesColorVar = tk.IntVar(value=1 if settings.get("selectedTaskUsesColor", True) else 0)

    presetRow = tk.Frame(paletteFrame, bg=app.cardColor)
    presetRow.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 6))
    presetRow.columnconfigure(1, weight=1)

    tk.Label(
        presetRow,
        text="Palette preset:",
        font=("Segoe UI", 9),
        fg=app.textColor,
        bg=app.cardColor
    ).grid(row=0, column=0, sticky="w")

    presetOptions = ["Classic", "Muted", "Bold", "Colorblind", "Vibrant"]
    presetDrop = tk.OptionMenu(presetRow, palettePresetVar, *presetOptions)
    presetDrop.grid(row=0, column=1, sticky="ew", padx=(8, 0))
    presetDrop.config(
        bg="#2c313a",
        fg=app.textColor,
        activebackground="#3f5a80",
        activeforeground=app.textColor,
        highlightthickness=0,
        bd=1,
        relief="solid"
    )

    selectedTaskTintCb = tk.Checkbutton(
        paletteFrame,
        text="Use task color on selected task row",
        variable=selectedTaskUsesColorVar,
        bg=app.cardColor,
        fg=app.textColor,
        activebackground=app.cardColor,
        activeforeground=app.textColor,
        selectcolor=app.cardColor,
        relief="flat"
    )
    selectedTaskTintCb.grid(row=2, column=0, sticky="w", padx=12, pady=(0, 6))

    targetsLabel = tk.Label(
        paletteFrame,
        text="Task and group color overrides (* = manual override)",
        font=("Segoe UI", 9),
        fg=app.textColor,
        bg=app.cardColor,
        anchor="w"
    )
    targetsLabel.grid(row=3, column=0, sticky="w", padx=12, pady=(0, 4))

    targetsOuter = tk.Frame(paletteFrame, bg=app.cardColor)
    targetsOuter.grid(row=4, column=0, sticky="nsew", padx=12, pady=(0, 8))
    targetsOuter.columnconfigure(0, weight=1)
    targetsOuter.rowconfigure(0, weight=1)

    targetsList = tk.Listbox(
        targetsOuter,
        height=14,
        bg="#1b1f24",
        fg=app.textColor,
        selectbackground=app.accentColor,
        selectforeground="#ffffff",
        borderwidth=0,
        highlightthickness=0,
        font=("Segoe UI", 10),
        selectmode=tk.BROWSE
    )
    targetsList.grid(row=0, column=0, sticky="nsew")
    targetsScroll = tk.Scrollbar(targetsOuter, orient="vertical", command=targetsList.yview)
    targetsScroll.grid(row=0, column=1, sticky="ns")
    targetsList.config(yscrollcommand=targetsScroll.set)

    controlsFrame = tk.Frame(paletteFrame, bg=app.cardColor)
    controlsFrame.grid(row=5, column=0, sticky="ew", padx=12, pady=(0, 12))
    controlsFrame.columnconfigure(0, weight=1)
    controlsFrame.columnconfigure(1, weight=1)
    controlsFrame.columnconfigure(2, weight=1)

    previewFrame = tk.Frame(controlsFrame, bg=app.cardColor)
    previewFrame.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 6))
    previewFrame.columnconfigure(1, weight=1)
    tk.Label(
        previewFrame,
        text="Preview:",
        font=("Segoe UI", 9),
        fg=app.textColor,
        bg=app.cardColor
    ).grid(row=0, column=0, sticky="w")
    previewSwatch = tk.Label(
        previewFrame,
        text="      ",
        font=("Segoe UI", 9),
        bg="#2b3138",
        fg=app.textColor,
        relief="solid",
        bd=1
    )
    previewSwatch.grid(row=0, column=1, sticky="w", padx=(8, 8))
    previewText = tk.Label(
        previewFrame,
        text="",
        font=("Segoe UI", 9),
        fg="#9ca3af",
        bg=app.cardColor
    )
    previewText.grid(row=0, column=2, sticky="w")

    renameVar = tk.StringVar(value="")
    renameEntry = tk.Entry(
        controlsFrame,
        textvariable=renameVar,
        font=("Segoe UI", 9),
        bg="#2b3138",
        fg=app.textColor,
        insertbackground=app.textColor,
        relief="flat",
        highlightthickness=1,
        highlightbackground="#0b0e12",
        highlightcolor="#0b0e12",
        bd=0
    )
    renameEntry.grid(row=1, column=0, sticky="ew", padx=(0, 6))

    renameBtn = tk.Button(
        controlsFrame,
        text="Rename Task",
        font=("Segoe UI", 9, "bold"),
        bg="#1b1f24",
        fg=app.textColor,
        activebackground="#2c3440",
        activeforeground=app.textColor,
        relief="flat"
    )
    renameBtn.grid(row=1, column=1, sticky="ew", padx=3)

    autoColorBtn = tk.Button(
        controlsFrame,
        text="Use Auto Color",
        font=("Segoe UI", 9),
        bg="#1b1f24",
        fg=app.textColor,
        activebackground="#2c3440",
        activeforeground=app.textColor,
        relief="flat"
    )
    autoColorBtn.grid(row=1, column=2, sticky="ew", padx=(6, 0))

    customColorBtn = tk.Button(
        controlsFrame,
        text="Pick Custom...",
        font=("Segoe UI", 9, "bold"),
        bg="#2b3138",
        fg=app.textColor,
        activebackground="#3a414a",
        activeforeground=app.textColor,
        relief="flat"
    )
    customColorBtn.grid(row=2, column=0, sticky="ew", pady=(6, 0), padx=(0, 6))

    clearOverridesBtn = tk.Button(
        controlsFrame,
        text="Clear All Overrides",
        font=("Segoe UI", 9),
        bg="#1b1f24",
        fg=app.textColor,
        activebackground="#2c3440",
        activeforeground=app.textColor,
        relief="flat"
    )
    clearOverridesBtn.grid(row=2, column=1, sticky="ew", pady=(6, 0), padx=3)

    swatchFrame = tk.Frame(controlsFrame, bg=app.cardColor)
    swatchFrame.grid(row=2, column=2, sticky="ew", pady=(6, 0), padx=(6, 0))
    for col in range(4):
        swatchFrame.columnconfigure(col, weight=1)

    colorTargets = []

    def sortedTasks():
        return sorted(set(workingTaskNames), key=lambda s: s.lower())

    def sortedGroups():
        groups = set()
        for t in sortedTasks():
            g = (workingGroupsByTask.get(t) or "").strip()
            if g:
                groups.add(g)
        return sorted(groups, key=lambda s: s.lower())

    def swatchesForPreset(presetName):
        p = str(presetName or "classic").strip().lower()

        if p == "muted":
            return [
                "#6486a8", "#5e9b88", "#ad8c6c", "#b57a88",
                "#8f8ac4", "#7a93a0", "#7f9b6a", "#a07aa6",
                "#9a8f6b", "#6f8ea3", "#8a7f73", "#6f7f9a",
            ]

        if p == "bold":
            return [
                "#236dff", "#04a86b", "#ff6d00", "#d6024f",
                "#6d28d9", "#008cb3", "#00b3a4", "#ff3d00",
                "#22c55e", "#f43f5e", "#a855f7", "#0ea5e9",
            ]

        if p == "colorblind":
            return [
                "#0072b2", "#009e73", "#e69f00", "#d55e00",
                "#cc79a7", "#56b4e9", "#000000", "#f0e442",
                "#326174", "#332288", "#88ccee", "#117733",
            ]

        if p == "vibrant":
            return [
            "#3f8cff", "#10b981", "#f97316", "#e11d48",
            "#8b5cf6", "#06b6d4", "#22c55e", "#f59e0b",
            "#ef4444", "#a78bfa", "#14b8a6", "#60a5fa",
        ]
        return [
            "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728",
            "#9467bd", "#8c564b", "#e377c2", "#7f7f7f",
            "#bcbd22", "#17becf", "#4c78a8", "#f58518",
        ]

        


    def buildPreviewColorMap(taskOverrides=None, groupOverrides=None):
        tasks = sortedTasks()
        hours = {}
        n = max(1, len(tasks))
        for idx, name in enumerate(tasks):
            hours[name] = float(n - idx)
        if taskOverrides is None:
            taskOverrides = taskColorOverrides
        if groupOverrides is None:
            groupOverrides = groupColorOverrides
        return app.buildTaskColorMap(
            taskHours=hours,
            groupsOverride=workingGroupsByTask,
            taskColorOverrides=taskOverrides,
            groupColorOverrides=groupOverrides,
            presetName=palettePresetVar.get().lower()
        )

    def selectedTarget():
        sel = targetsList.curselection()
        if not sel:
            return None, None
        idx = sel[0]
        if idx < 0 or idx >= len(colorTargets):
            return None, None
        return colorTargets[idx]

    def selectedColor():
        kind, name = selectedTarget()
        if not kind or not name:
            return None
        cmap = buildPreviewColorMap()
        if kind == "task":
            return cmap.get(name, app.accentColor)
        if kind == "group":
            if name in groupColorOverrides:
                return groupColorOverrides[name]
            tasks = [t for t in sortedTasks() if (workingGroupsByTask.get(t) or "").strip() == name]
            if tasks:
                return cmap.get(tasks[0], app.accentColor)
        return app.accentColor

    def nearest_color_conflict(kind, name, colorHex, previewMap):
        c = sanitizeHexColor(colorHex)
        if not c:
            return None

        best = None
        for taskName, taskColor in previewMap.items():
            tc = sanitizeHexColor(taskColor)
            if not tc:
                continue
            if kind == "task" and taskName == name:
                continue
            # For group edits, skip tasks inside the same group from closeness warning.
            if kind == "group":
                g = (workingGroupsByTask.get(taskName) or "").strip()
                if g == name:
                    continue
            d = color_distance(c, tc)
            if best is None or d < best[2]:
                best = ("task", taskName, d)
        return best

    def should_accept_color(kind, name, colorHex, previewMap):
        c = sanitizeHexColor(colorHex)
        if not c:
            return False

        conflict = nearest_color_conflict(kind, name, c, previewMap)
        if conflict and conflict[2] < 22.0:
            _, otherName, dist = conflict
            ok = messagebox.askyesno(
                "Similar Color",
                f"This color is very close to '{otherName}' (distance {dist:.1f}).\n\nApply anyway?"
            )
            if not ok:
                return False

        if color_distance(c, app.cardColor) < 28.0:
            ok = messagebox.askyesno(
                "Low Contrast Color",
                "This color is very close to the app background.\n\nApply anyway?"
            )
            if not ok:
                return False

        return True

    def refreshSwatches():
        for child in swatchFrame.winfo_children():
            child.destroy()
        swatches = swatchesForPreset(palettePresetVar.get().lower())
        for i, color in enumerate(swatches):
            btn = tk.Button(
                swatchFrame,
                text="",
                width=2,
                bg=color,
                activebackground=color,
                relief="flat",
                command=lambda c=color: applyManualColor(c)
            )
            btn.grid(row=i // 4, column=i % 4, padx=2, pady=2, sticky="ew")

    def refreshTargetList(selectKind=None, selectName=None):
        nonlocal colorTargets
        previous = selectedTarget()
        if selectKind is None and selectName is None:
            selectKind, selectName = previous

        colorTargets = []
        targetsList.delete(0, tk.END)

        for task in sortedTasks():
            mark = "*" if task in taskColorOverrides else " "
            colorTargets.append(("task", task))
            targetsList.insert(tk.END, f"T{mark} {task}")

        for group in sortedGroups():
            mark = "*" if group in groupColorOverrides else " "
            colorTargets.append(("group", group))
            targetsList.insert(tk.END, f"G{mark} {group}")

        if not colorTargets:
            return

        targetIdx = 0
        if selectKind and selectName:
            for idx, item in enumerate(colorTargets):
                if item == (selectKind, selectName):
                    targetIdx = idx
                    break
        targetsList.selection_clear(0, tk.END)
        targetsList.selection_set(targetIdx)

    def refreshSelectionState(_event=None):
        kind, name = selectedTarget()
        c = selectedColor()
        if c:
            previewSwatch.config(bg=c)
        else:
            previewSwatch.config(bg="#2b3138")

        if kind == "task" and name:
            renameEntry.config(state="normal")
            renameBtn.config(state="normal")
            renameVar.set(name)
            mode = "manual" if name in taskColorOverrides else "auto"
            previewText.config(text=f"{name} ({mode})")
        elif kind == "group" and name:
            renameEntry.config(state="disabled")
            renameBtn.config(state="disabled")
            renameVar.set("")
            mode = "manual" if name in groupColorOverrides else "auto"
            previewText.config(text=f"group {name} ({mode})")
        else:
            renameEntry.config(state="disabled")
            renameBtn.config(state="disabled")
            renameVar.set("")
            previewText.config(text="")

    def applyManualColor(colorHex):
        c = sanitizeHexColor(colorHex)
        if not c:
            return
        kind, name = selectedTarget()
        if not kind or not name:
            return

        nextTaskOverrides = dict(taskColorOverrides)
        nextGroupOverrides = dict(groupColorOverrides)

        if kind == "task":
            currentMap = buildPreviewColorMap()
            previousColor = sanitizeHexColor(currentMap.get(name))

            collisionTask = None
            collisionDist = None
            threshold = 22.0

            for taskName, color in currentMap.items():
                if taskName == name:
                    continue
                other = sanitizeHexColor(color)
                if not other:
                    continue
                d = color_distance(other, c)
                if collisionDist is None or d < collisionDist:
                    collisionDist = d
                    collisionTask = taskName

            nextTaskOverrides[name] = c

            if collisionTask and collisionDist is not None and collisionDist <= threshold and previousColor and previousColor != c:
                nextTaskOverrides[collisionTask] = previousColor
        elif kind == "group":
            nextGroupOverrides[name] = c


        previewAfter = buildPreviewColorMap(nextTaskOverrides, nextGroupOverrides)
        if not should_accept_color(kind, name, c, previewAfter):
            return

        taskColorOverrides.clear()
        taskColorOverrides.update(nextTaskOverrides)
        groupColorOverrides.clear()
        groupColorOverrides.update(nextGroupOverrides)

        refreshTargetList(kind, name)
        refreshSelectionState()

    def clearSelectedManualColor():
        kind, name = selectedTarget()
        if not kind or not name:
            return
        if kind == "task":
            taskColorOverrides.pop(name, None)
        elif kind == "group":
            groupColorOverrides.pop(name, None)
        refreshTargetList(kind, name)
        refreshSelectionState()

    def pickCustomColor():
        kind, name = selectedTarget()
        if not kind or not name:
            return
        initial = selectedColor() or app.accentColor
        _, picked = colorchooser.askcolor(color=initial, parent=win, title="Pick color")
        c = sanitizeHexColor(picked)
        if c:
            applyManualColor(c)

    def clearAllOverrides():
        taskColorOverrides.clear()
        groupColorOverrides.clear()
        refreshTargetList()
        refreshSelectionState()

    def renameSelectedTask():
        kind, oldName = selectedTarget()
        if kind != "task" or not oldName:
            return
        newName = (renameVar.get() or "").strip()
        if not newName:
            messagebox.showerror("Rename Task", "Task name cannot be empty.")
            return
        if newName == oldName:
            return
        if newName in set(sortedTasks()):
            messagebox.showerror("Rename Task", f"Task '{newName}' already exists.")
            return

        for idx, existing in enumerate(workingTaskNames):
            if existing == oldName:
                workingTaskNames[idx] = newName
                break

        if oldName in workingGroupsByTask:
            workingGroupsByTask[newName] = workingGroupsByTask.pop(oldName)

        if oldName in taskColorOverrides:
            taskColorOverrides[newName] = taskColorOverrides.pop(oldName)

        for src, dst in list(pendingTaskRenames.items()):
            if dst == oldName:
                pendingTaskRenames[src] = newName

        if oldName in pendingTaskRenames:
            pendingTaskRenames[oldName] = newName
        elif oldName in originalTaskNames:
            pendingTaskRenames[oldName] = newName

        for src in list(pendingTaskRenames.keys()):
            if pendingTaskRenames.get(src) == src:
                del pendingTaskRenames[src]

        refreshTargetList("task", newName)
        refreshSelectionState()

    renameBtn.config(command=renameSelectedTask)
    autoColorBtn.config(command=clearSelectedManualColor)
    customColorBtn.config(command=pickCustomColor)
    clearOverridesBtn.config(command=clearAllOverrides)
    palettePresetVar.trace_add("write", lambda *_: (refreshSwatches(), refreshSelectionState()))
    targetsList.bind("<<ListboxSelect>>", refreshSelectionState)

    refreshSwatches()
    refreshTargetList()
    refreshSelectionState()

    # Tab 3: Charge Code Mapping
    chargeFrame = tk.Frame(tabs, bg=app.cardColor)
    tabs.add(chargeFrame, text="Charge Codes")
    chargeFrame.columnconfigure(0, weight=1)
    chargeFrame.rowconfigure(1, weight=1)

    chargeLabel = tk.Label(
        chargeFrame,
        text="Charge Code Mappings",
        font=("Segoe UI", 10, "bold"),
        fg=app.textColor,
        bg=app.cardColor
    )
    chargeLabel.grid(row=0, column=0, sticky="w", padx=12, pady=(12, 6))

    # Scrollable canvas for charge code table
    scrollCanvas = tk.Canvas(chargeFrame, bg=app.cardColor, highlightthickness=0)
    scrollCanvas.grid(row=1, column=0, sticky="nsew", padx=12, pady=6)

    scrollbar = tk.Scrollbar(chargeFrame, orient="vertical", command=scrollCanvas.yview)
    scrollbar.grid(row=1, column=1, sticky="ns", padx=(0, 12), pady=6)
    scrollCanvas.config(yscrollcommand=scrollbar.set)

    tableFrame = tk.Frame(scrollCanvas, bg=app.cardColor)
    scrollCanvas.create_window((0, 0), window=tableFrame, anchor="nw")
    tableFrame.columnconfigure(0, weight=1)
    tableFrame.columnconfigure(1, weight=0)

    # Build list of all ungrouped tasks + all groups
    allGroups = sorted(set(app.groups.values())) if app.groups else []
    ungroupedTasks = sorted([t for t in app.rows.keys() if t not in app.groups]) if hasattr(app, "rows") else []
    taskGroupOptions = ["<None>"] + allGroups + ungroupedTasks

    chargeCodeVars = {}
    chargeCodeChunks = []
    removedChargeCodeIdxs = set()

    def readGroupKeyForChunk(chunkIdx):
        try:
            with open(dataFile, "r", encoding="utf-8") as f:
                for raw in f:
                    line = raw.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    if obj.get("type") == "chargeCode" and obj.get("chunkIndex") == chunkIdx:
                        return (obj.get("groupKey") or "").strip()
        except Exception:
            return ""
        return ""

    def rebuildChargeCodeTable():
        nonlocal chargeCodeChunks, chargeCodeVars

        previousSelections = {
            idx: (var.get() or "").strip()
            for idx, var in chargeCodeVars.items()
        }

        for child in tableFrame.winfo_children():
            child.destroy()

        chargeCodeVars = {}
        chargeCodeChunks = loadChargeCodesFromJsonl(dataFile)

        if not chargeCodeChunks:
            noCodesLabel = tk.Label(
                tableFrame,
                text="No charge codes found in data file",
                font=("Segoe UI", 9),
                fg="#999999",
                bg=app.cardColor
            )
            noCodesLabel.pack(padx=12, pady=12)

            tableFrame.update_idletasks()
            scrollCanvas.config(scrollregion=scrollCanvas.bbox("all"))
            return

        visibleRows = 0
        for chunkIdx, chunkCodes in enumerate(chargeCodeChunks):
            if chunkIdx in removedChargeCodeIdxs:
                continue

            rowFrame = tk.Frame(tableFrame, bg=app.cardColor)
            rowFrame.grid(row=visibleRows, column=0, columnspan=2, sticky="ew", padx=0, pady=6)
            rowFrame.columnconfigure(0, weight=1)
            rowFrame.columnconfigure(1, weight=0)
            rowFrame.columnconfigure(2, weight=0)

            codeNamesText = " | ".join([str(c.get("chargeCodeName") or "") for c in chunkCodes])            
            codesLabel = tk.Label(
                rowFrame,
                text=codeNamesText,
                font=("Segoe UI", 10),
                fg=app.textColor,
                bg=app.cardColor,
                anchor="w",
                wraplength=300
            )
            codesLabel.grid(row=0, column=0, sticky="w", padx=12, pady=6)

            currentGroup = previousSelections.get(chunkIdx)
            if currentGroup is None:
                currentGroup = readGroupKeyForChunk(chunkIdx)

            chunkVar = tk.StringVar(value=currentGroup)
            chargeDrop = tk.OptionMenu(rowFrame, chunkVar, *taskGroupOptions)
            chargeDrop.grid(row=0, column=1, sticky="ew", padx=12, pady=6)
            chargeDrop.config(
                bg="#2c313a",
                fg=app.textColor,
                activebackground="#3f5a80",
                activeforeground=app.textColor,
                highlightthickness=0,
                bd=1,
                relief="solid",
                width=20
            )

            chargeCodeVars[chunkIdx] = chunkVar
            visibleRows += 1

            removeBtn = tk.Button(
                rowFrame,
                text="-",
                font=("Segoe UI", 10, "bold"),
                bg=app.cardColor,
                fg="#d94a4a",
                activebackground=app.cardColor,
                activeforeground="#ff6a6a",
                relief="flat",
                bd=0,
                highlightthickness=0,
                takefocus=0,
                width=2,
                command=lambda idx=chunkIdx: markChargeCodeForRemoval(idx)
            )
            removeBtn.grid(row=0, column=2, sticky="e", padx=(20, 2), pady=6)
            removeBtn.config(cursor="hand2")

        if visibleRows == 0:
            noCodesLabel = tk.Label(
                tableFrame,
                text="All charge codes are marked for removal. Click Save to apply.",
                font=("Segoe UI", 9),
                fg="#999999",
                bg=app.cardColor
            )
            noCodesLabel.pack(padx=12, pady=12)

        tableFrame.update_idletasks()
        scrollCanvas.config(scrollregion=scrollCanvas.bbox("all"))

    def markChargeCodeForRemoval(chunkIdx):
        removedChargeCodeIdxs.add(chunkIdx)
        rebuildChargeCodeTable()

    def pullAndRefreshChargeCodes():
        if str(refreshBtn.cget("state")) == "disabled":
            return
        prev_text = refreshBtn.cget("text")
        refreshBtn.config(state="disabled")
        refreshBtn.config(text="Loading…")
        try:
            app.root.config(cursor="watch")
            app.root.update_idletasks()
        except Exception:
            pass
        def job():
            try:
                import posting
                s = posting.newSession()
                posting.primeCookies(s)
                posting.login(s)

                todayIso = date.today().isoformat()
                ts = posting.copyPreviousTimesheet(s, todayIso)
                models = ts.get("chargeCodeIDModels") or []
                if not models:
                    raise RuntimeError("No charge codes returned from copyPreviousTimesheet")

                posting.insertChargeCodesBetweenGroupAndHistory(dataFile, models)

                def _refresh_table():
                    removedChargeCodeIdxs.clear()
                    rebuildChargeCodeTable()

                win.after(0, _refresh_table)

                if hasattr(app, "showToast"):
                    app.showToast("Charge codes refreshed")


            except Exception as e:
                if hasattr(app, "showToast"):
                    win.after(0, lambda: app.showToast(f"Charge code refresh failed: {e}", timeout=6000, error=True))
                else:
                    win.after(0, lambda: messagebox.showerror("Charge code refresh failed", str(e)))
            finally:
                def _reset():
                    refreshBtn.config(state="normal")
                    refreshBtn.config(text=prev_text)
                    try:
                        app.root.config(cursor="")
                        app.root.update_idletasks()
                    except Exception:
                        pass
                win.after(0, _reset)

        threading.Thread(target=job, daemon=True).start()

    rebuildChargeCodeTable()

    refreshBtn = tk.Button(
        chargeFrame,
        text="Load Charge Codes",
        font=("Segoe UI", 9, "bold"),
        bg="#2b3138",
        fg=app.textColor,
        activebackground="#3a414a",
        activeforeground=app.textColor,
        relief="flat",
        command=pullAndRefreshChargeCodes
    )
    refreshBtn.grid(row=2, column=0, sticky="w", padx=12, pady=(6, 12))

    def style_btn(btn, hover_bg=None):
        normal_bg = btn.cget("bg")
        hover = hover_bg or btn.cget("activebackground") or normal_bg
        btn.config(cursor="hand2")
        btn.bind("<Enter>", lambda e: btn.config(bg=hover), add="+")
        btn.bind("<Leave>", lambda e: btn.config(bg=normal_bg), add="+")

    style_btn(refreshBtn)
    for b in (renameBtn, autoColorBtn, customColorBtn, clearOverridesBtn):
        style_btn(b)

    # Allow mouse wheel scrolling anywhere over the charge code panel.
    def _on_mousewheel(event):
        try:
            delta = int(-1 * (event.delta / 120))
        except Exception:
            delta = -1 if event.delta > 0 else 1
        scrollCanvas.yview_scroll(delta, "units")

    for widget in (chargeFrame, scrollCanvas, tableFrame):
        widget.bind("<MouseWheel>", _on_mousewheel)


    btnFrame = tk.Frame(win, bg=app.bgColor)
    btnFrame.pack(fill="x", padx=14, pady=(0, 12))

    def saveSettings():
        start = parseTimeHHMM(workStartVar.get(), settings.get("workDayStart", "09:00"))
        end = parseTimeHHMM(workEndVar.get(), settings.get("workDayEnd", "17:00"))

        try:
            m = int(minMinutesVar.get().strip())
            if m < 0:
                m = 0
        except Exception:
            m = int(settings.get("minRecordedMinutes", 1) or 1)

        try:
            w = int(mainWidthVar.get().strip())
        except Exception:
            w = int(settings.get("mainWindowWidth", 400) or 400)

        try:
            h = int(mainHeightVar.get().strip())
        except Exception:
            h = int(settings.get("mainWindowHeight", 400) or 400)

        w = max(250, w)
        h = max(250, h)

        settings["workDayStart"] = start
        settings["workDayEnd"] = end
        settings["minRecordedMinutes"] = m
        settings["roundToHours"] = bool(roundToHoursVar.get())
        settings["useTimesheetFunctions"] = bool(useTimesheetVar.get())
        settings["autoChargeCodes"] = bool(autoChargeCodesVar.get())
        settings["reviewBeforePost"] = bool(reviewBeforePostVar.get())
        settings["useDefaultBaseUrl"] = bool(useDefaultBaseUrlVar.get())
        settings["mainWindowWidth"] = w
        settings["mainWindowHeight"] = h
        settings["colorPalettePreset"] = str(palettePresetVar.get().lower() or "classic").strip().lower()
        settings["selectedTaskUsesColor"] = bool(selectedTaskUsesColorVar.get())

        cleanedTaskOverrides = normalizeColorMap(taskColorOverrides)
        cleanedGroupOverrides = normalizeColorMap(groupColorOverrides)
        settings["taskColorOverrides"] = dict(sorted(cleanedTaskOverrides.items(), key=lambda kv: kv[0].lower()))
        settings["groupColorOverrides"] = dict(sorted(cleanedGroupOverrides.items(), key=lambda kv: kv[0].lower()))
        # Backward-compatible aliases.
        settings["taskColors"] = dict(settings["taskColorOverrides"])
        settings["groupColorBases"] = dict(settings["groupColorOverrides"])

        renamePairs = [(src, dst) for src, dst in pendingTaskRenames.items() if src and dst and src != dst]
        renamePairs.sort(key=lambda kv: kv[0].lower())
        renamedAny = False
        for oldName, newName in renamePairs:
            ok, msg = app.renameTask(oldName, newName, persist=False)
            if not ok:
                messagebox.showerror("Rename Task", msg or f"Unable to rename '{oldName}' to '{newName}'.")
                return
            renamedAny = True

        if renamePairs:
            renameMap = dict(renamePairs)
            for _, var in chargeCodeVars.items():
                currentVal = (var.get() or "").strip()
                mapped = renameMap.get(currentVal)
                if mapped:
                    var.set(mapped)

        with open(settingsPath, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)

        # Write charge code mappings to JSONL
        updateChargeCodesInJsonl(dataFile, chargeCodeChunks, chargeCodeVars, removedChargeCodeIdxs)
        if renamedAny:
            if hasattr(app, "rewrite_data_file"):
                if not app.rewrite_data_file():
                    messagebox.showerror("Save Failed", "Renamed tasks were applied in memory, but history could not be rewritten to disk.")
                    return
            else:
                app.saveData()

        baseUrlVal = baseUrlVar.get().strip()
        emailVal = emailVar.get().strip()
        passwordVal = passwordVar.get().strip()

        if useDefaultBaseUrlVar.get():
            baseUrlVal = DEFAULT_BASE_URL

        if baseUrlVal or emailVal or passwordVal:
            updatePostingEnv(app.getDataDir(), baseUrlVal, emailVal, passwordVal)
            # Reload posting module to get updated env vars
            import importlib
            import posting
            importlib.reload(posting)

        app.settings = settings
        app.minSegmentSeconds = int(m * 60)
        app.workDayStart = start
        app.workDayEnd = end
        app.roundToHours = bool(settings["roundToHours"])
        app.useTimesheetFunctions = bool(settings["useTimesheetFunctions"])
        app.autoChargeCodes = bool(settings["autoChargeCodes"])
        app.reviewBeforePost = bool(settings.get("reviewBeforePost", False))
        app.baseWidth = w
        app.baseHeight = h
        app.colorPalettePreset = settings["colorPalettePreset"]
        app.selectedTaskUsesColor = bool(settings["selectedTaskUsesColor"])
        app.taskColorOverrides = dict(settings["taskColorOverrides"])
        app.groupColorOverrides = dict(settings["groupColorOverrides"])
        if hasattr(app, "_cachedChargeCodesTs"):
            app._cachedChargeCodesTs = 0.0
        if hasattr(app, "_ensureColorSettingsConsistency"):
            app._ensureColorSettingsConsistency()
        if hasattr(app, "refreshRowStyles"):
            app.refreshRowStyles()

        win.destroy()

    saveBtn = tk.Button(
        btnFrame,
        text="Save",
        font=("Segoe UI", 10, "bold"),
        bg=app.accentColor,
        fg="#ffffff",
        activebackground="#5b98ff",
        activeforeground="#ffffff",
        relief="flat",
        command=saveSettings
    )
    style_btn(saveBtn, hover_bg="#5b98ff")
    saveBtn.pack(side="right")

    cancelBtn = tk.Button(
        btnFrame,
        text="Cancel",
        font=("Segoe UI", 10),
        bg="#1b1f24",
        fg=app.textColor,
        activebackground="#2c3440",
        activeforeground=app.textColor,
        relief="flat",
        command=win.destroy
    )
    style_btn(cancelBtn)
    cancelBtn.pack(side="right", padx=(0, 8))

    win.bind("<Escape>", lambda e: win.destroy())
    workStartEntry.focus_set()

    applyBaseUrlState()


def updateChargeCodesInJsonl(dataFile, chargeCodeChunks, chargeCodeVars, removedChargeCodeIdxs=None):
    if not os.path.exists(dataFile):
        return

    tmpPath = dataFile + ".tmp"
    removedIdxs = set(removedChargeCodeIdxs or [])

    try:
        ccIdx = 0
        keptChunkIdx = 0

        with open(dataFile, "r", encoding="utf-8") as src, open(tmpPath, "w", encoding="utf-8") as dst:
            for raw in src:
                line = raw.strip()
                if not line or line.startswith("//"):
                    dst.write(raw)
                    continue

                try:
                    obj = json.loads(line)
                except Exception:
                    dst.write(raw)
                    continue

                if obj.get("type") != "chargeCode":
                    dst.write(raw)
                    continue

                if ccIdx in removedIdxs:
                    ccIdx += 1
                    continue

                groupKey = chargeCodeVars.get(ccIdx, tk.StringVar()).get().strip()
                if not groupKey or groupKey == "<None>":
                    groupKey = ""

                obj["groupKey"] = groupKey
                obj["chunkIndex"] = keptChunkIdx

                dst.write(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n")
                ccIdx += 1
                keptChunkIdx += 1

        os.replace(tmpPath, dataFile)

    except Exception as e:
        try:
            if os.path.exists(tmpPath):
                os.remove(tmpPath)
        except Exception:
            pass
        print(f"Error updating charge codes in JSONL: {e}")
        import traceback
        traceback.print_exc()

def updatePostingEnv(baseDir, baseUrl="", email="", password=""):
    """Update posting.env with provided credentials, keeping existing values if not provided"""
    try:
        os.makedirs(baseDir, exist_ok=True)
    except Exception:
        pass
    envPath = os.path.join(baseDir, "posting.env")
    
    # Load existing values
    existing = {"BASE_URL": "", "EMAIL": "", "PASSWORD": ""}
    if os.path.exists(envPath):
        try:
            with open(envPath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, val = line.split("=", 1)
                        key = key.strip()
                        val = val.strip()
                        if key in existing:
                            existing[key] = val
        except Exception:
            pass
    
    # Update with provided values (only if non-empty)
    if baseUrl:
        existing["BASE_URL"] = baseUrl
    if email:
        existing["EMAIL"] = email
    if password:
        existing["PASSWORD"] = password
    
    # Write back to file
    try:
        with open(envPath, "w", encoding="utf-8") as f:
            f.write(f"BASE_URL={existing['BASE_URL']}\n")
            f.write(f"EMAIL={existing['EMAIL']}\n")
            f.write(f"PASSWORD={existing['PASSWORD']}\n")
    except Exception:
        pass
