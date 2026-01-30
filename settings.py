import tkinter as tk
import json
import os
import re
import sys

def resourcePath(relPath):
	if hasattr(sys, "_MEIPASS"):
		return os.path.join(sys._MEIPASS, relPath)
	return relPath

DEFAULT_SETTINGS = {
    "workDayStart": "09:00",
    "workDayEnd": "17:00",
    "minRecordedMinutes": 1,
    "roundToHours": False,
    "mainWindowWidth": 400,
    "mainWindowHeight": 400,
    "useTimesheetFunctions": True,
    "autoChargeCodes": True
}

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
    settingsPath = os.path.join(app.getBaseDir(), "settings.json")
    dataFile = app.realPath if hasattr(app, "realPath") else os.path.join(app.getBaseDir(), "tasks.jsonl")

    def parseTimeHHMM(s, fallback):
        s = (s or "").strip()
        if not re.fullmatch(r"\d{2}:\d{2}", s):
            return fallback
        hh = int(s[0:2])
        mm = int(s[3:5])
        if hh < 0 or hh > 23 or mm < 0 or mm > 59:
            return fallback
        return s

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
        settings["mainWindowWidth"] = w
        settings["mainWindowHeight"] = h

        with open(settingsPath, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)

        # Write charge code mappings to JSONL
        updateChargeCodesInJsonl(dataFile, chargeCodeChunks, chargeCodeVars)

        app.settings = settings
        app.minSegmentSeconds = int(m * 60)
        app.workDayStart = start
        app.workDayEnd = end
        app.roundToHours = bool(settings["roundToHours"])
        app.useTimesheetFunctions = bool(settings["useTimesheetFunctions"])
        app.autoChargeCodes = bool(settings["autoChargeCodes"])
        app.baseWidth = w
        app.baseHeight = h

        win.destroy()

    settings = loadSettings(settingsPath)
    chargeCodes = loadChargeCodesFromJsonl(dataFile)
    groupChargeCodeMap = dict(settings.get("groupChargeCodeMap", {}))

    win = tk.Toplevel(app.root)
    win.title("Settings")
    win.configure(bg=app.bgColor)
    win.resizable(True, True)
    win.transient(app.root)
    win.grab_set()
    win.lift()
    win.focus_force()
    win.iconbitmap(resourcePath("hourglass.ico"))

    w = 1000
    h = 550
    app.root.update_idletasks()
    rx = app.root.winfo_rootx()
    ry = app.root.winfo_rooty()
    rw = app.root.winfo_width()
    rh = app.root.winfo_height()
    x = rx + (rw - w) // 2
    y = ry + (rh - h) // 2
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

    # Create notebook/tabs for organization
    mainFrame = tk.Frame(win, bg=app.bgColor)
    mainFrame.pack(fill="both", expand=True, padx=14, pady=(0, 10))
    mainFrame.columnconfigure(0, weight=1)
    mainFrame.rowconfigure(0, weight=1)

    # Tab 1: General settings
    generalFrame = tk.Frame(mainFrame, bg=app.cardColor)
    generalFrame.pack(fill="both", expand=True, side="left", padx=(0, 6))
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
        bg="#2c313a",
        fg=app.textColor,
        insertbackground=app.textColor,
        relief="flat",
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
        bg="#2c313a",
        fg=app.textColor,
        insertbackground=app.textColor,
        relief="flat",
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
        bg="#2c313a",
        fg=app.textColor,
        insertbackground=app.textColor,
        relief="flat",
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
        bg="#2c313a",
        fg=app.textColor,
        insertbackground=app.textColor,
        relief="flat",
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
        bg="#2c313a",
        fg=app.textColor,
        insertbackground=app.textColor,
        relief="flat",
        width=10
    )
    mainHeightEntry.grid(row=row, column=1, sticky="e", padx=12, pady=6)

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

    # Tab 2: Charge Code Mapping
    chargeFrame = tk.Frame(mainFrame, bg=app.cardColor)
    chargeFrame.pack(fill="both", expand=True, side="right", padx=(6, 0))
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

    # Collect all charge code chunks
    chargeCodeChunks = loadChargeCodesFromJsonl(dataFile)

    # Build table with one row per chunk
    if chargeCodeChunks:
        chargeCodeVars = {}
        
        for chunkIdx, chunkCodes in enumerate(chargeCodeChunks):
            # Create a frame for this row
            rowFrame = tk.Frame(tableFrame, bg=app.cardColor)
            rowFrame.grid(row=chunkIdx, column=0, columnspan=2, sticky="ew", padx=0, pady=6)
            rowFrame.columnconfigure(0, weight=1)
            rowFrame.columnconfigure(1, weight=0)
            
            # Left side: display all code names
            codeNamesText = " | ".join([code.get("chargeCodeName", "") for code in chunkCodes])
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
            
            # Determine current group for this chunk by looking at groupKey
            currentGroup = ""
            groupKey = ""
            # We need to find the original groupKey - scan the file
            try:
                with open(dataFile, "r", encoding="utf-8") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        try:
                            obj = json.loads(line.strip())
                            if obj.get("type") == "chargeCode" and obj.get("chunkIndex") == chunkIdx:
                                groupKey = obj.get("groupKey", "")
                                break
                        except:
                            pass
            except:
                pass
            
            if groupKey:
                currentGroup = groupKey
            
            # Right side: single dropdown for the chunk
            chunkVar = tk.StringVar(value=currentGroup)
            chargeDrop = tk.OptionMenu(
                rowFrame,
                chunkVar,
                *taskGroupOptions
            )
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
            
            # Store the var for this chunk
            chargeCodeVars[chunkIdx] = chunkVar

        tableFrame.update_idletasks()
        scrollCanvas.config(scrollregion=scrollCanvas.bbox("all"))
    else:
        noCodesLabel = tk.Label(
            tableFrame,
            text="No charge codes found in data file",
            font=("Segoe UI", 9),
            fg="#999999",
            bg=app.cardColor
        )
        noCodesLabel.pack(padx=12, pady=12)

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
        settings["mainWindowWidth"] = w
        settings["mainWindowHeight"] = h

        with open(settingsPath, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)

        # Write charge code mappings to JSONL
        updateChargeCodesInJsonl(dataFile, chargeCodeChunks, chargeCodeVars)

        app.settings = settings
        app.minSegmentSeconds = int(m * 60)
        app.workDayStart = start
        app.workDayEnd = end
        app.roundToHours = bool(settings["roundToHours"])
        app.useTimesheetFunctions = bool(settings["useTimesheetFunctions"])
        app.autoChargeCodes = bool(settings["autoChargeCodes"])
        app.baseWidth = w
        app.baseHeight = h

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
    cancelBtn.pack(side="right", padx=(0, 8))

    win.bind("<Escape>", lambda e: win.destroy())
    workStartEntry.focus_set()

def updateChargeCodesInJsonl(dataFile, chargeCodeChunks, chargeCodeVars):
    """Update the JSONL file with charge code groupKey assignments"""
    if not os.path.exists(dataFile):
        return
    
    try:
        # Read all lines, preserving non-chargeCode entries
        lines = []
        with open(dataFile, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("//"):
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    lines.append(raw.rstrip("\n"))
                    continue
                
                if obj.get("type") != "chargeCode":
                    lines.append(raw.rstrip("\n"))
                # skip chargeCode lines, we'll rebuild them below
        
        # Rebuild chargeCode lines with updated groupKey
        newLines = []
        for line in lines:
            newLines.append(line)
        
        # Add updated chargeCode entries
        for chunkIdx, chunk in enumerate(chargeCodeChunks):
            groupKey = chargeCodeVars.get(chunkIdx, tk.StringVar()).get().strip()
            
            if not groupKey or groupKey == "<None>":
                groupKey = ""
            
            # Rebuild the chargeCodes array
            codesToWrite = []
            for code in chunk:
                codesToWrite.append({
                    "chargeCodeId": code.get("chargeCodeId"),
                    "chargeCodeName": code.get("chargeCodeName"),
                    "type": code.get("type"),
                    "hierarchicalName": code.get("hierarchicalName", ""),
                    "children": code.get("children", False),
                    "leave": code.get("leave", False)
                })
            
            chargeCodeObj = {
                "type": "chargeCode",
                "groupKey": groupKey,
                "chunkIndex": chunkIdx,
                "chargeCodes": codesToWrite
            }
            newLines.append(json.dumps(chargeCodeObj, ensure_ascii=False, separators=(',', ':')))
        
        # Write back to file
        with open(dataFile, "w", encoding="utf-8") as f:
            for line in newLines:
                f.write(line + "\n")
    
    except Exception as e:
        print(f"Error updating charge codes in JSONL: {e}")
        import traceback
        traceback.print_exc()
