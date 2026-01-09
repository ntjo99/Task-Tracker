import tkinter as tk
import json
import os
import re

DEFAULT_SETTINGS = {
    "workDayStart": "09:00",
    "workDayEnd": "17:00",
    "minRecordedMinutes": 1,
    "roundToHours": False,
    "mainWindowWidth": 400,
    "mainWindowHeight": 400
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

def openSettings(app):
    settingsPath = os.path.join(app.getBaseDir(), "settings.json")

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
        settings["mainWindowWidth"] = w
        settings["mainWindowHeight"] = h

        with open(settingsPath, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)

        app.settings = settings
        app.minSegmentSeconds = int(m * 60)
        app.workDayStart = start
        app.workDayEnd = end
        app.roundToHours = bool(settings["roundToHours"])

        win.destroy()

    settings = loadSettings(settingsPath)

    win = tk.Toplevel(app.root)
    win.title("Settings")
    win.configure(bg=app.bgColor)
    win.resizable(False, False)
    win.transient(app.root)
    win.grab_set()
    win.lift()
    win.focus_force()

    w = 460
    h = 350
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

    card = tk.Frame(win, bg=app.cardColor)
    card.pack(fill="both", expand=True, padx=14, pady=(0, 10))
    card.columnconfigure(0, weight=1)
    card.columnconfigure(1, weight=0)

    row = 0

    workStartLabel = tk.Label(
        card,
        text="Work day start (HH:MM):",
        font=("Segoe UI", 10),
        fg=app.textColor,
        bg=app.cardColor,
        anchor="w"
    )
    workStartLabel.grid(row=row, column=0, sticky="w", padx=12, pady=(12, 6))

    workStartVar = tk.StringVar(value=str(settings.get("workDayStart", "09:00")))
    workStartEntry = tk.Entry(
        card,
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
        card,
        text="Work day end (HH:MM):",
        font=("Segoe UI", 10),
        fg=app.textColor,
        bg=app.cardColor,
        anchor="w"
    )
    workEndLabel.grid(row=row, column=0, sticky="w", padx=12, pady=6)

    workEndVar = tk.StringVar(value=str(settings.get("workDayEnd", "17:00")))
    workEndEntry = tk.Entry(
        card,
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
        card,
        text="Minimum time recorded (minutes):",
        font=("Segoe UI", 10),
        fg=app.textColor,
        bg=app.cardColor,
        anchor="w"
    )
    minMinutesLabel.grid(row=row, column=0, sticky="w", padx=12, pady=6)

    minMinutesVar = tk.StringVar(value=str(settings.get("minRecordedMinutes", 1)))
    minMinutesEntry = tk.Entry(
        card,
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
        card,
        text="Main window width (px):",
        font=("Segoe UI", 10),
        fg=app.textColor,
        bg=app.cardColor,
        anchor="w"
    )
    mainWidthLabel.grid(row=row, column=0, sticky="w", padx=12, pady=6)

    mainWidthVar = tk.StringVar(value=str(settings.get("mainWindowWidth", 400)))
    mainWidthEntry = tk.Entry(
        card,
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
        card,
        text="Main window height (px):",
        font=("Segoe UI", 10),
        fg=app.textColor,
        bg=app.cardColor,
        anchor="w"
    )
    mainHeightLabel.grid(row=row, column=0, sticky="w", padx=12, pady=6)

    mainHeightVar = tk.StringVar(value=str(settings.get("mainWindowHeight", 400)))
    mainHeightEntry = tk.Entry(
        card,
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
        card,
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

    btnFrame = tk.Frame(win, bg=app.bgColor)
    btnFrame.pack(fill="x", padx=14, pady=(0, 12))

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
