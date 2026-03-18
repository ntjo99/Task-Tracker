from datetime import date, timedelta, datetime
import tkinter as tk
from tkinter import messagebox, font as tkfont
import sys
import os
import openEdit

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

        def _parseTimeToSeconds(ts): # Need this so that I don't get timezone confusion
            try:
                tpart = ts.split("T", 1)[1]
            except IndexError:
                return None, None, None, None

            for sep in ("+", "-", "Z"):
                idx = tpart.find(sep)
                if idx > 0:
                    tpart = tpart[:idx]
                    break

            comps = tpart.split(":")
            if len(comps) < 2:
                return None, None, None, None

            h = int(comps[0])
            m = int(comps[1])
            s = int(comps[2]) if len(comps) > 2 else 0
            total = h * 3600 + m * 60 + s
            return h, m, s, total

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
            # Include all known tasks from the current task list.
            if hasattr(self, "rows") and isinstance(self.rows, dict):
                names.update(self.rows.keys())
            # Also include any tasks found in history summaries (for legacy/removed tasks).
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

        # Synthetic overview used only when the user explicitly asks for an
        # all-history stacked area chart.
        totalOverview = {"days": [], "agg": {}, "total": 0.0}

        def recomputeTotalOverview():
            agg = {}
            total = 0.0
            days = sorted({dStr for p in periods for dStr in p.get("days", [])})

            for dStr in days:
                dayAgg, dayTotal = parseDaySummary(dStr)
                for k, v in dayAgg.items():
                    agg[k] = agg.get(k, 0.0) + v
                total += dayTotal

            totalOverview["days"] = days
            totalOverview["agg"] = agg
            totalOverview["total"] = total

        recomputeTotalOverview()

        # helper to recompute period aggregates after edits
        def updatePeriods():
            nonlocal periods
            for p in periods:
                agg = {}
                total = 0.0
                for dStr in p.get("days", []):
                    dayAgg, dayTotal = parseDaySummary(dStr)
                    for k, v in dayAgg.items():
                        agg[k] = agg.get(k, 0.0) + v
                    total += dayTotal
                p["agg"] = agg
                p["total"] = total
            recomputeTotalOverview()
            # ensure UI shows recalculated data
            try:
                showPayPeriodSummary()
            except Exception:
                pass
            try:
                refreshTotalAreaWindow()
            except Exception:
                pass

        if getattr(self, "histWin", None) is not None and self.histWin.winfo_exists():
            histWin = self.histWin
            histWin.deiconify()
            histWin.lift()
            histWin.focus_force()
        else:
            histWin = tk.Toplevel(self.root)
            self.histWin = histWin
            histWin.withdraw()

            iconPath = resourcePath("hourglass.ico")
            if os.path.exists(iconPath):
                try:
                    histWin.iconbitmap(iconPath)
                except Exception:
                    pass
            histWin.title("History")
            histWin.configure(bg=self.bgColor)

            dw, dh = 1050, 620

            histWin.update_idletasks()
            sw = histWin.winfo_screenwidth()
            sh = histWin.winfo_screenheight()

            x = (sw - dw) // 2
            y = (sh - dh) // 2
            histWin.geometry(f"{dw}x{dh}+{x}+{y}")

            histWin.columnconfigure(0, weight=0)
            histWin.columnconfigure(1, weight=0)
            histWin.columnconfigure(2, weight=1)
            histWin.columnconfigure(3, weight=0)
            histWin.rowconfigure(0, weight=1)
            histWin.rowconfigure(1, weight=0)

            histWin.transient(self.root)

        histWin.deiconify()
        histWin.lift()
        histWin.focus_force()
        histWin.attributes("-topmost", True)
        histWin.after(100, lambda: histWin.attributes("-topmost", False))

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

        # control frame to hold timeline toggle and edit buttons
        timelineControlFrame = tk.Frame(textFrame, bg=self.bgColor)
        timelineControlFrame.grid(row=0, column=1, sticky="e")

        timelineModeBtn = tk.Button(
            timelineControlFrame,
            text="Stacked",
            font=("Segoe UI", 9, "bold"),
            bg="#1b1f24",
            fg=self.textColor,
            activebackground="#2c3440",
            activeforeground=self.textColor,
            relief="flat",
            command=lambda: toggleTimelineMode()
        )
        timelineModeBtn.pack(side="right")

        editDayBtn = tk.Button(
            timelineControlFrame,
            text="Edit",
            font=("Segoe UI", 9, "bold"),
            bg="#1b1f24",
            fg=self.textColor,
            activebackground="#2c3440",
            activeforeground=self.textColor,
            relief="flat",
            # pass the available task list so the editor can show a row for every task
            command=lambda: openEdit.open_day_editor(
                self, histWin, current.get("dayKey"), periods, current,
                showPayPeriodSummary, refreshDays, showDaySummary, ppColorMap,
                updatePeriods,
                sorted(set(list(self.rows.keys()) + list(allTasks)))
            )
        )
        editDayBtn.pack(side="right", padx=(0,10))

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
        ppSummaryLabel.grid(row=2, column=0, sticky="w")

        ppControlFrame = tk.Frame(textFrame, bg=self.bgColor)
        ppControlFrame.grid(row=2, column=1, sticky="e")

        ppChartModeBtn = tk.Button(
            ppControlFrame,
            text="Area",
            font=("Segoe UI", 9, "bold"),
            bg="#1b1f24",
            fg=self.textColor,
            activebackground="#2c3440",
            activeforeground=self.textColor,
            relief="flat"
        )
        ppChartModeBtn.pack(side="right")

        totalAreaBtn = tk.Button(
            ppControlFrame,
            text="Total Area",
            font=("Segoe UI", 9),
            bg="#1b1f24",
            fg=self.textColor,
            activebackground="#2c3440",
            activeforeground=self.textColor,
            relief="flat"
        )
        totalAreaBtn.pack(side="right", padx=(0, 8))

        ppSummaryBox = tk.Text(
            textFrame,
            bg="#1b1f24",
            fg=self.textColor,
            wrap="word",
            borderwidth=0,
            highlightthickness=0,
            font=("Segoe UI", 10)
        )
        ppSummaryBox.grid(row=3, column=0, sticky="nsew", pady=(4, 0))
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
            bg="#2b3138",
            fg=self.textColor,
            insertbackground=self.textColor,
            relief="flat",
            highlightthickness=1,
            highlightbackground="#0b0e12",
            highlightcolor="#0b0e12",
            bd=0
        )
        groupEntry.pack(fill="x", pady=(0, 6))

        def applyPlaceholder(entry, text):
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

        applyPlaceholder(groupEntry, "Group name…")

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

        def style_btn(btn, hover_bg=None):
            normal_bg = btn.cget("bg")
            hover = hover_bg or btn.cget("activebackground") or normal_bg
            btn.config(cursor="hand2")
            btn.bind("<Enter>", lambda e: btn.config(bg=hover), add="+")
            btn.bind("<Leave>", lambda e: btn.config(bg=normal_bg), add="+")

        for b in (timelineModeBtn, editDayBtn, ppChartModeBtn, totalAreaBtn, setGroupBtn, clearGroupBtn):
            style_btn(b)

        current = {"ppIndex": 0, "timelineMode": "gantt", "ppChartMode": "pie", "dayKey": None}
        allTasks = collectAllTasks()
        taskNames = list(allTasks)
        totalAreaState = {
            "win": None,
            "canvas": None,
            "legendCanvas": None,
            "summaryBox": None,
            "subtitleLabel": None,
            "labels": {},
            "tooltip": {"win": None, "item": None},
            "redrawJob": None
        }

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
            hasUngrouped = False;

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

        def computePayPeriodColorMap(taskAgg):
            nonlocal ppColorMap

            ppColorMap = self.buildTaskColorMap(taskAgg)
            return ppColorMap

        def drawPayPeriodPie(total, taskAgg):
            nonlocal pieSlices, ppColorMap

            ppPieCanvas.delete("all")
            pieSlices = {}

            if total <= 0 or not taskAgg:
                return

            if not ppColorMap:
                computePayPeriodColorMap(taskAgg)

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

            startAngle = 0.0
            for name, hours in items:
                if hours <= 0:
                    continue
                extent = 360.0 * (hours / total)
                color = ppColorMap.get(name, self.accentColor)
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

        def buildStackedAreaSeries(period, bucketSize=1, averageBuckets=False):
            days = sorted(period.get("days", []))
            if not days:
                return [], [], 0.0

            try:
                bucketSize = max(1, int(bucketSize))
            except Exception:
                bucketSize = 1

            seriesAgg = []
            seriesLabels = []
            maxSeriesTotal = 0.0

            for startIdx in range(0, len(days), bucketSize):
                bucketDays = days[startIdx:startIdx + bucketSize]
                bucketAgg = {}
                bucketTotal = 0.0

                for dStr in bucketDays:
                    dayAgg, dayTotal = parseDaySummary(dStr)
                    for k, v in dayAgg.items():
                        bucketAgg[k] = bucketAgg.get(k, 0.0) + v
                    bucketTotal += dayTotal

                divisor = float(len(bucketDays)) if averageBuckets and bucketDays else 1.0
                if divisor > 1.0:
                    for k in list(bucketAgg.keys()):
                        bucketAgg[k] = bucketAgg[k] / divisor
                    bucketTotal = bucketTotal / divisor

                maxSeriesTotal = max(maxSeriesTotal, bucketTotal)
                seriesAgg.append(bucketAgg)

                label = bucketDays[0]
                try:
                    parsed = [date.fromisoformat(d) for d in bucketDays]
                    if len(parsed) == 1:
                        label = parsed[0].strftime("%m-%d")
                    else:
                        mid = parsed[len(parsed) // 2]
                        label = mid.strftime("%m-%d")
                except ValueError:
                    pass
                seriesLabels.append(label)

            return seriesAgg, seriesLabels, maxSeriesTotal

        def computeAutoBucketSize(period, canvasWidth, targetPointSpacing=26.0):
            days = sorted(period.get("days", []))
            dayCount = len(days)
            if dayCount <= 1:
                return 1

            try:
                canvasWidth = float(canvasWidth)
            except Exception:
                canvasWidth = 240.0

            marginLeft = 28.0
            marginRight = 14.0
            plotW = max(1.0, canvasWidth - marginLeft - marginRight)
            maxPoints = max(2, int(plotW // max(12.0, float(targetPointSpacing))) + 1)

            if dayCount <= maxPoints:
                return min(dayCount, 3)

            return max(3, (dayCount + maxPoints - 1) // maxPoints)

        def softenSeriesPoints(points, subdivisions=5):
            if len(points) <= 1 or subdivisions <= 1:
                return list(points)

            softened = [points[0]]
            for i in range(len(points) - 1):
                x0, y0 = points[i]
                x1, y1 = points[i + 1]
                for step in range(1, subdivisions + 1):
                    t = step / float(subdivisions)
                    eased = t * t * (3.0 - 2.0 * t)
                    x = x0 + (x1 - x0) * t
                    y = y0 + (y1 - y0) * eased
                    softened.append((x, y))
            return softened

        def drawStackedArea(canvas, period, taskAgg, itemLabels, colorMap, minDayWidth=0.0, bucketSize=1, averageBuckets=False, softenCurves=False, curveSubdivisions=5):
            canvas.delete("all")
            itemLabels.clear()

            days = sorted(period.get("days", []))
            if not days or not taskAgg:
                canvas.update_idletasks()
                w = canvas.winfo_width() or 240
                h = canvas.winfo_height() or 160
                canvas.configure(scrollregion=(0, 0, w, h))
                return {"bucketSize": max(1, int(bucketSize)), "pointCount": 0, "dayCount": len(days)}

            perDayAgg, dayLabels, maxDayTotal = buildStackedAreaSeries(
                period,
                bucketSize=bucketSize,
                averageBuckets=averageBuckets
            )

            if maxDayTotal <= 0:
                return {"bucketSize": max(1, int(bucketSize)), "pointCount": len(perDayAgg), "dayCount": len(days)}

            tasksOrdered = [k for k, v in sorted(taskAgg.items(), key=lambda kv: kv[1], reverse=True) if v > 0]
            if not tasksOrdered:
                return {"bucketSize": max(1, int(bucketSize)), "pointCount": len(perDayAgg), "dayCount": len(days)}

            canvas.update_idletasks()
            w = canvas.winfo_width() or 240
            h = canvas.winfo_height() or 160

            marginLeft = 28
            marginRight = 14
            marginTop = 10
            marginBottom = 22

            left = marginLeft
            top = marginTop
            bottom = max(top + 1, h - marginBottom)
            visiblePlotW = max(1, w - marginLeft - marginRight)
            minPlotW = 0.0
            if minDayWidth > 0:
                minPlotW = minDayWidth if len(perDayAgg) == 1 else (len(perDayAgg) - 1) * minDayWidth
            plotW = max(1, visiblePlotW, int(round(minPlotW)))
            right = left + plotW
            plotH = max(1, bottom - top)
            canvas.configure(scrollregion=(0, 0, right + marginRight, h))

            n = len(perDayAgg)

            canvas.create_line(left, bottom, right, bottom, fill="#6b7280")

            if n == 1:
                barWidth = min(max(30.0, plotW * 0.25), 70.0)
                x1 = left + (plotW - barWidth) / 2.0
                x2 = x1 + barWidth

                y = bottom
                for i, task in enumerate(tasksOrdered):
                    v = float(perDayAgg[0].get(task, 0.0))
                    if v <= 0:
                        continue
                    hPx = int(round((v / maxDayTotal) * plotH))
                    hPx = max(1, min(hPx, int(round(y - top))))
                    y2 = y
                    y1 = max(top, y - hPx)

                    item = canvas.create_rectangle(
                        x1, y1, x2, y2,
                        fill=colorMap.get(task, self.accentColor),
                        outline=""
                    )
                    itemLabels[item] = f"{task} ({v:.1f}h)"
                    y = y1

                canvas.create_text(
                    left, bottom + 4,
                    text=dayLabels[0],
                    fill="#9ca3af",
                    anchor="nw",
                    font=("Segoe UI", 7)
                )
                return {"bucketSize": max(1, int(bucketSize)), "pointCount": 1, "dayCount": len(days)}

            xs = [left + (i / float(n - 1)) * plotW for i in range(n)]
            cumulative = [0.0 for _ in range(n)]

            for task in tasksOrdered:
                vals = [float(dayAgg.get(task, 0.0)) for dayAgg in perDayAgg]
                if sum(vals) <= 0:
                    continue

                topPts = []
                basePts = []
                for i in range(n):
                    base = cumulative[i]
                    topV = base + vals[i]

                    baseY = bottom - (base / maxDayTotal) * plotH
                    topY = bottom - (topV / maxDayTotal) * plotH

                    topPts.append((xs[i], topY))
                    basePts.append((xs[i], baseY))
                    cumulative[i] = topV

                points = []
                for x, y in topPts:
                    points.extend([x, y])
                for x, y in reversed(basePts):
                    points.extend([x, y])

                if softenCurves and len(topPts) >= 3:
                    smoothSteps = max(2, int(curveSubdivisions))
                    softenedTop = softenSeriesPoints(topPts, subdivisions=smoothSteps)
                    softenedBase = softenSeriesPoints(basePts, subdivisions=smoothSteps)
                    points = []
                    for x, y in softenedTop:
                        points.extend([x, y])
                    for x, y in reversed(softenedBase):
                        points.extend([x, y])

                color = colorMap.get(task, self.accentColor)
                item = canvas.create_polygon(points, fill=color, outline="")
                itemLabels[item] = f"{task} ({taskAgg.get(task, 0.0):.1f}h)"

            # choose label indices to avoid crowding; always include first and last
            label_spacing_px = 70  # desired min pixels between labels
            max_labels = max(2, min(n, int(plotW // label_spacing_px)))
            indices = {0, n - 1}
            if max_labels > 2 and n > 2:
                step_float = (n - 1) / (max_labels - 1)
                for k in range(1, max_labels - 1):
                    idx = int(round(k * step_float))
                    # keep within sensible interior range
                    idx = min(max(idx, 1), n - 2)
                    indices.add(idx)
            indices_list = sorted(indices)

            for idx in indices_list:
                x = xs[idx]
                # clamp to canvas bounds so text isn't clipped
                x = max(left + 2, min(x, left + plotW - 2))
                canvas.create_text(
                    x,
                    bottom + 4,
                    text=dayLabels[idx],
                    fill="#9ca3af",
                    anchor="n",
                    font=("Segoe UI", 7)
                )

            return {"bucketSize": max(1, int(bucketSize)), "pointCount": n, "dayCount": len(days)}

        def drawPayPeriodStackedArea(period, taskAgg):
            nonlocal pieSlices, ppColorMap

            pieSlices = {}
            if not ppColorMap:
                computePayPeriodColorMap(taskAgg)
            drawStackedArea(ppPieCanvas, period, taskAgg, pieSlices, ppColorMap)

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

        def hideTotalAreaTooltip(event=None):
            tooltipState = totalAreaState["tooltip"]
            if tooltipState["win"] is not None:
                tooltipState["win"].destroy()
                tooltipState["win"] = None
            tooltipState["item"] = None

        def showTotalAreaTooltip(event):
            canvas = totalAreaState.get("canvas")
            if canvas is None or not canvas.winfo_exists():
                return

            items = canvas.find_withtag("current")
            if not items:
                hideTotalAreaTooltip(event)
                return

            item = items[0]
            tooltipState = totalAreaState["tooltip"]

            if item == tooltipState["item"] and tooltipState["win"] is not None:
                return

            labelText = totalAreaState.get("labels", {}).get(item)
            if not labelText:
                hideTotalAreaTooltip(event)
                return

            if tooltipState["win"] is not None:
                tooltipState["win"].destroy()

            tw = tk.Toplevel(canvas)
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

            tooltipState["win"] = tw
            tooltipState["item"] = item

        def drawTotalAreaLegend(legendCanvas, taskAgg, colorMap):
            if legendCanvas is None or not legendCanvas.winfo_exists():
                return

            legendCanvas.delete("all")
            legendCanvas.update_idletasks()

            width = max(220, legendCanvas.winfo_width() or 220)
            height = max(28, legendCanvas.winfo_height() or 28)
            legendCanvas.configure(scrollregion=(0, 0, width, height))

            items = [(name, hours) for name, hours in sorted(taskAgg.items(), key=lambda kv: kv[1], reverse=True) if float(hours) > 0.0]
            if not items:
                return

            legendFont = tkfont.Font(family="Segoe UI", size=9)
            x = 10
            y = 10
            rowH = 22
            swatch = 10
            gap = 6
            itemGap = 16
            maxX = width - 10

            for name, _hours in items:
                textW = legendFont.measure(name)
                itemW = swatch + gap + textW + itemGap

                if x > 10 and (x + itemW) > maxX:
                    x = 10
                    y += rowH

                color = colorMap.get(name, self.accentColor)
                legendCanvas.create_rectangle(
                    x,
                    y + 3,
                    x + swatch,
                    y + 3 + swatch,
                    fill=color,
                    outline=""
                )
                legendCanvas.create_text(
                    x + swatch + gap,
                    y + 8,
                    text=name,
                    anchor="w",
                    fill=self.textColor,
                    font=legendFont
                )
                x += itemW

            totalH = y + rowH
            legendCanvas.configure(height=max(28, totalH + 2), scrollregion=(0, 0, width, totalH + 2))

        def refreshTotalAreaWindow(resetScroll=False):
            win = totalAreaState.get("win")
            canvas = totalAreaState.get("canvas")
            legendCanvas = totalAreaState.get("legendCanvas")
            summaryBox = totalAreaState.get("summaryBox")
            subtitleLabel = totalAreaState.get("subtitleLabel")

            if win is None or not win.winfo_exists() or canvas is None or not canvas.winfo_exists():
                return

            agg = totalOverview.get("agg", {})
            total = totalOverview.get("total", 0.0)
            colorMap = self.buildTaskColorMap(agg)
            canvas.update_idletasks()
            bucketSize = computeAutoBucketSize(totalOverview, canvas.winfo_width() or 240, targetPointSpacing=22.0)
            roundnessSteps = 9

            labels = {}
            meta = drawStackedArea(
                canvas,
                totalOverview,
                agg,
                labels,
                colorMap,
                minDayWidth=0.0,
                bucketSize=bucketSize,
                averageBuckets=True,
                softenCurves=(roundnessSteps > 1),
                curveSubdivisions=roundnessSteps
            )
            totalAreaState["labels"] = labels

            drawTotalAreaLegend(legendCanvas, agg, colorMap)

            if subtitleLabel is not None and subtitleLabel.winfo_exists():
                usedBucket = int(meta.get("bucketSize", bucketSize))
                pointCount = int(meta.get("pointCount", 0))
                dayCount = int(meta.get("dayCount", len(totalOverview.get("days", []))))
                if usedBucket <= 1:
                    subtitleText = f"Smoothed stacked area ({pointCount} points)"
                else:
                    subtitleText = (
                        f"Auto-grouped in {usedBucket}-day averages, "
                        f"({dayCount} days -> {pointCount} points)"
                    )
                subtitleLabel.config(text=subtitleText)

            if summaryBox is not None and summaryBox.winfo_exists():
                summaryBox.delete("1.0", tk.END)
                summaryBox.insert(tk.END, "\n".join(formatLines(total, agg)))

                for name, color in colorMap.items():
                    tagName = f"total_{name}"
                    try:
                        summaryBox.tag_configure(tagName, foreground=color)
                    except tk.TclError:
                        continue

                    start = "1.0"
                    pattern = f"{name}:"
                    while True:
                        pos = summaryBox.search(pattern, start, tk.END)
                        if not pos:
                            break
                        end = f"{pos}+{len(name)}c"
                        summaryBox.tag_add(tagName, pos, end)
                        start = f"{end}+1c"

        def runTotalAreaRedraw():
            totalAreaState["redrawJob"] = None
            refreshTotalAreaWindow()

        def scheduleTotalAreaRedraw(event=None):
            canvas = totalAreaState.get("canvas")
            if canvas is None or not canvas.winfo_exists():
                return

            job = totalAreaState.get("redrawJob")
            if job is not None:
                try:
                    canvas.after_cancel(job)
                except Exception:
                    pass

            totalAreaState["redrawJob"] = canvas.after(60, runTotalAreaRedraw)

        def closeTotalAreaWindow():
            canvas = totalAreaState.get("canvas")
            job = totalAreaState.get("redrawJob")
            if canvas is not None and job is not None and canvas.winfo_exists():
                try:
                    canvas.after_cancel(job)
                except Exception:
                    pass

            hideTotalAreaTooltip()
            win = totalAreaState.get("win")
            if win is not None and win.winfo_exists():
                win.destroy()

            totalAreaState["win"] = None
            totalAreaState["canvas"] = None
            totalAreaState["legendCanvas"] = None
            totalAreaState["summaryBox"] = None
            totalAreaState["subtitleLabel"] = None
            totalAreaState["labels"] = {}
            totalAreaState["redrawJob"] = None

        def openTotalAreaWindow():
            win = totalAreaState.get("win")
            if win is not None and win.winfo_exists():
                win.deiconify()
                win.lift()
                win.focus_force()
                refreshTotalAreaWindow()
                return

            win = tk.Toplevel(histWin)
            win.configure(bg=self.bgColor)
            win.title("Total Area Chart")
            win.minsize(980, 560)
            win.geometry("1180x680")
            win.transient(histWin)

            iconPath = resourcePath("hourglass.ico")
            if os.path.exists(iconPath):
                try:
                    win.iconbitmap(iconPath)
                except Exception:
                    pass

            win.columnconfigure(0, weight=1)
            win.rowconfigure(1, weight=1)
            win.rowconfigure(2, weight=0)
            win.rowconfigure(3, weight=0)
            win.rowconfigure(4, weight=0)

            headerFrame = tk.Frame(win, bg=self.bgColor)
            headerFrame.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 6))
            headerFrame.columnconfigure(0, weight=1)

            titleLabel = tk.Label(
                headerFrame,
                text="Total History Area",
                font=("Segoe UI", 11, "bold"),
                fg=self.textColor,
                bg=self.bgColor
            )
            titleLabel.grid(row=0, column=0, sticky="w")

            subtitleLabel = tk.Label(
                headerFrame,
                text="Smoothed stacked area",
                font=("Segoe UI", 9),
                fg="#9ca3af",
                bg=self.bgColor
            )
            subtitleLabel.grid(row=1, column=0, sticky="w", pady=(2, 0))

            chartFrame = tk.Frame(win, bg=self.bgColor)
            chartFrame.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 8))
            chartFrame.columnconfigure(0, weight=1)
            chartFrame.rowconfigure(0, weight=1)

            chartCanvas = tk.Canvas(
                chartFrame,
                bg="#1b1f24",
                highlightthickness=0
            )
            chartCanvas.grid(row=0, column=0, sticky="nsew")

            legendCanvas = tk.Canvas(
                win,
                height=32,
                bg="#1b1f24",
                highlightthickness=0
            )
            legendCanvas.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 8))

            summaryBox = tk.Text(
                win,
                height=8,
                bg="#1b1f24",
                fg=self.textColor,
                wrap="word",
                borderwidth=0,
                highlightthickness=0,
                font=("Segoe UI", 10)
            )
            summaryBox.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 8))

            closeFrame = tk.Frame(win, bg=self.bgColor)
            closeFrame.grid(row=4, column=0, sticky="e", padx=10, pady=(0, 10))

            closeTotalBtn = tk.Button(
                closeFrame,
                text="Close",
                font=("Segoe UI", 10, "bold"),
                bg="#1b1f24",
                fg=self.textColor,
                activebackground="#2c3440",
                activeforeground=self.textColor,
                relief="flat",
                command=closeTotalAreaWindow
            )
            style_btn(closeTotalBtn)
            closeTotalBtn.pack(anchor="e")

            totalAreaState["win"] = win
            totalAreaState["canvas"] = chartCanvas
            totalAreaState["legendCanvas"] = legendCanvas
            totalAreaState["summaryBox"] = summaryBox
            totalAreaState["subtitleLabel"] = subtitleLabel
            totalAreaState["labels"] = {}
            totalAreaState["tooltip"] = {"win": None, "item": None}
            totalAreaState["redrawJob"] = None

            chartCanvas.bind("<Motion>", showTotalAreaTooltip)
            chartCanvas.bind("<Leave>", hideTotalAreaTooltip)
            chartCanvas.bind("<Configure>", scheduleTotalAreaRedraw)
            legendCanvas.bind("<Configure>", scheduleTotalAreaRedraw)
            win.protocol("WM_DELETE_WINDOW", closeTotalAreaWindow)
            win.bind("<Escape>", lambda e: closeTotalAreaWindow())

            win.update_idletasks()
            refreshTotalAreaWindow(resetScroll=True)

        def showPayPeriodSummary():
            ppIdx = current["ppIndex"]
            if ppIdx < 0 or ppIdx >= len(periods):
                ppSummaryBox.delete("1.0", tk.END)
                ppPieCanvas.delete("all")
                return

            p = periods[ppIdx]
            agg = p.get("agg", {})
            total = p.get("total", 0.0)

            computePayPeriodColorMap(agg)
            isArea = (current.get("ppChartMode") == "area")
            ppChartModeBtn.config(text=("Pie" if isArea else "Area"))

            if isArea:
                drawPayPeriodStackedArea(p, agg)
            else:
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
            segments = entry.get("timeline") if isinstance(entry, dict) else []

            if not segments:
                return

            min_sec, max_sec = 24 * 3600, 0
            valid_segments = []

            for seg in segments:
                startStr = seg.get("start")
                endStr = seg.get("end")
                if not startStr or not endStr:
                    continue

                hStart, mStart, sStart, startSec = _parseTimeToSeconds(startStr)
                hEnd, mEnd, sEnd, endSec = _parseTimeToSeconds(endStr)
                if startSec is None or endSec is None:
                    continue

                if endSec > startSec:
                    min_sec = min(min_sec, startSec)
                    max_sec = max(max_sec, endSec)
                    valid_segments.append({
                        **seg,
                        "task": seg.get("task") or "Untasked",
                        "startSec": startSec,
                        "endSec": endSec,
                        "hStart": hStart,
                        "mStart": mStart,
                        "hEnd": hEnd,
                        "mEnd": mEnd,
                    })

            if not valid_segments:
                return

            spanStartSec = max(0, (min_sec // 3600) * 3600)
            spanEndSec = min(24 * 3600, ((max_sec + 3599) // 3600) * 3600)
            spanSec = max(60.0, spanEndSec - spanStartSec)

            timelineCanvas.update_idletasks()
            width = timelineCanvas.winfo_width() or 260
            height = timelineCanvas.winfo_height() or 140

            marginLeft = 10
            marginRight = 10
            marginTop = 10
            marginBottom = 30

            areaTop = marginTop
            areaBottom = height - marginBottom
            areaBottom = areaTop + 10 if areaBottom <= areaTop else areaBottom

            tasks = sorted({seg["task"] for seg in valid_segments})

            keyWidthRatio = 0.25
            keyWidth = width * keyWidthRatio
            innerWidth = max(1, width - marginLeft - marginRight - keyWidth)
            plotAreaRight = marginLeft + innerWidth

            nTasks = max(1, len(tasks))
            rowGap = 4
            totalHeight = areaBottom - areaTop
            rowHeight = max(6, (totalHeight - rowGap * (nTasks - 1)) / nTasks)

            taskToRow = {t: i for i, t in enumerate(tasks)}

            # Color map: match the pay period pie colors (including group shading)
            colorMap = {}
            for task in tasks:
                if task == "Untasked":
                    colorMap[task] = "#444c56"
                else:
                    colorMap[task] = ppColorMap.get(task, self.accentColor)

            mode = current.get("timelineMode", "gantt")
            if mode == "stacked":
                totals = {}
                totalSpan = 0.0

                for seg in valid_segments:
                    dur = max(0.0, float(seg["endSec"] - seg["startSec"]))
                    t = seg["task"]
                    totals[t] = totals.get(t, 0.0) + dur
                    totalSpan += dur

                if totalSpan <= 0:
                    return

                barWidth = min(max(24.0, innerWidth * 0.30), 70.0)

                x1i = int(round(marginLeft + (innerWidth - barWidth) / 2.0))
                x2i = int(round(x1i + barWidth))

                yTop = int(round(areaTop))
                yBottom = int(round(areaBottom))
                totalPx = max(1, yBottom - yTop)

                drawTasks = [t for t in tasks if totals.get(t, 0.0) > 0.0]

                y = yTop
                for i, task in enumerate(drawTasks):
                    dur = totals[task]

                    if i == len(drawTasks) - 1:
                        y2 = yBottom
                    else:
                        hPx = int(round((dur / totalSpan) * totalPx))
                        hPx = max(1, min(hPx, yBottom - y))
                        y2 = y + hPx

                    item = timelineCanvas.create_rectangle(
                        x1i, y, x2i, y2,
                        fill=colorMap[task],
                        outline=""
                    )
                    rectTaskMap[item] = f"{task} {dur/3600.0:.2f}h"
                    y = y2


                legendX = plotAreaRight + 10
                rect_size = 10
                rect_gap = 4
                legendY = marginTop + (rowHeight - rect_size) / 2.0

                for task in tasks:
                    color = colorMap[task]
                    timelineCanvas.create_rectangle(
                        legendX, legendY, legendX + rect_size, legendY + rect_size,
                        fill=color,
                        outline=""
                    )
                    timelineCanvas.create_text(
                        legendX + rect_size + rect_gap,
                        legendY + rect_size / 2.0,
                        text=task,
                        anchor="w",
                        fill="#9ca3af",
                        font=("Segoe UI", 7)
                    )
                    legendY += rowHeight

                return

            for seg in valid_segments:
                task = seg["task"]
                startSec = seg["startSec"]
                endSec = seg["endSec"]

                rowIndex = taskToRow.get(task, 0)
                y1 = areaTop + rowIndex * (rowHeight + rowGap)
                y2 = y1 + rowHeight

                x1 = marginLeft + ((startSec - spanStartSec) / spanSec) * innerWidth
                x2 = marginLeft + ((endSec - spanStartSec) / spanSec) * innerWidth

                color = colorMap.get(task, self.accentColor)

                item = timelineCanvas.create_rectangle(
                    x1, y1, x2, y2,
                    fill=color,
                    outline=""
                )
                labelText = f"{task} {seg['hStart']:02d}:{seg['mStart']:02d}–{seg['hEnd']:02d}:{seg['mEnd']:02d}"
                rectTaskMap[item] = labelText

            axisY = areaBottom + 4
            tickY1 = axisY
            tickY2 = axisY + 4
            labelY = axisY + 10

            span_hours = spanSec / 3600.0
            if span_hours < 3:
                step_sec = 1800
            elif span_hours < 8:
                step_sec = 3600
            else:
                step_sec = 10800

            first_tick_sec = (spanStartSec // step_sec + 1) * step_sec
            ticks_sec = sorted(list(set([spanStartSec, spanEndSec] + list(range(first_tick_sec, spanEndSec, step_sec)))))

            timelineCanvas.create_line(marginLeft, axisY, plotAreaRight, axisY, fill="#6b7280")

            for sec in ticks_sec:
                if sec < spanStartSec or sec > spanEndSec:
                    continue

                x = marginLeft + ((sec - spanStartSec) / spanSec) * innerWidth
                if x > plotAreaRight:
                    continue

                hour = int(sec // 3600) % 24
                time_label = f"{hour:02d}"

                timelineCanvas.create_line(x, tickY1, x, tickY2, fill="#6b7280")
                timelineCanvas.create_text(
                    x, labelY, text=time_label,
                    fill="#9ca3af", anchor="n",
                    font=("Segoe UI", 7)
                )

            legendX = plotAreaRight + 10
            rect_size = 10
            rect_gap = 4
            legendY = marginTop + (rowHeight - rect_size) / 2.0

            for task in tasks:
                color = colorMap[task]
                timelineCanvas.create_rectangle(
                    legendX, legendY, legendX + rect_size, legendY + rect_size,
                    fill=color,
                    outline=""
                )
                timelineCanvas.create_text(
                    legendX + rect_size + rect_gap,
                    legendY + rect_size / 2.0,
                    text=task,
                    anchor="w",
                    fill="#9ca3af",
                    font=("Segoe UI", 7)
                )
                legendY += rowHeight

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

        def toggleTimelineMode():
            current["timelineMode"] = "stacked" if current.get("timelineMode") == "gantt" else "gantt"

            isStacked = (current["timelineMode"] == "stacked")
            timelineModeBtn.config(text=("Timeline" if isStacked else "Stacked"))
            timelineLabel.config(text=("Stacked" if isStacked else "Timeline"))

            if current.get("dayKey"):
                drawTimelineForDayKey(current["dayKey"])

        def togglePayPeriodChartMode():
            current["ppChartMode"] = "area" if current.get("ppChartMode") == "pie" else "pie"
            showPayPeriodSummary()


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
            current["dayKey"] = dStr
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
            for name, color in ppColorMap.items():
                tagName = f"pp_{name}"
                try:
                    daySummaryBox.tag_configure(tagName, foreground=color)
                except tk.TclError:
                    continue

                start = "1.0"
                pattern = f"{name}:"
                while True:
                    pos = daySummaryBox.search(pattern, start, tk.END)
                    if not pos:
                        break
                    end = f"{pos}+{len(name)}c"
                    daySummaryBox.tag_add(tagName, pos, end)
                    start = f"{end}+1c"
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
            refreshTotalAreaWindow()
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
                refreshTotalAreaWindow()
                dayIdx = getSelectedDayIdx()
                if dayIdx is not None:
                    showDaySummary(dayIdx)

        def closeHistoryWindow():
            closeTotalAreaWindow()
            if histWin.winfo_exists():
                histWin.destroy()
            self.histWin = None

        ppListbox.bind("<<ListboxSelect>>", onPayPeriodSelect)
        ppPieCanvas.bind("<Motion>", showPieTooltip)
        ppPieCanvas.bind("<Leave>", hidePieTooltip)
        timelineCanvas.bind("<Motion>", showTooltip)
        timelineCanvas.bind("<Leave>", hideTooltip)
        dayListbox.bind("<<ListboxSelect>>", onDaySelect)
        taskListbox.bind("<<ListboxSelect>>", onTaskSelect)
        setGroupBtn.config(command=setGroup)
        clearGroupBtn.config(command=clearGroup)
        ppChartModeBtn.config(command=togglePayPeriodChartMode)
        totalAreaBtn.config(command=openTotalAreaWindow)

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
            command=closeHistoryWindow
        )
        style_btn(closeBtn)
        closeBtn.pack(anchor="e")

        histWin.protocol("WM_DELETE_WINDOW", closeHistoryWindow)
        histWin.bind("<Escape>", lambda e: closeHistoryWindow())

        if periods:
            ppListbox.selection_set(0)
            current["ppIndex"] = 0
            refreshDays()
            refreshTaskList()
