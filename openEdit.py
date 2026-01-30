import tkinter as tk
from datetime import datetime, date, time as dtime
import sys

def resourcePath(relPath):
	if hasattr(sys, "_MEIPASS"):
		return os.path.join(sys._MEIPASS, relPath)
	return relPath

def open_day_editor(self, parent, dayKey, periods, current, showPayPeriodSummary, refreshDays, showDaySummary, ppColorMap, updatePeriods, tasks):
    """
    Gantt-style day editor:
    - tasks: list of task names to allocate rows for (one row per task).
    - Supports dragging rectangles horizontally to resize and vertically to move tasks.
    - Click empty canvas to add a new segment for selected task.
    """
    entry = self.history.get(dayKey, {}) or {}
    segs = [dict(s) for s in (entry.get("timeline") or [])]

    # normalize segment fields
    for s in segs:
        s.setdefault("task", "Untasked")
        s.setdefault("start", "")
        s.setdefault("end", "")

    editor = tk.Toplevel(parent)
    editor.transient(parent)
    editor.title(f"Edit {dayKey}")
    editor.configure(bg=self.bgColor)

    dw, dh = 1050, 620
    editor.geometry(f"{dw}x{dh}")
    editor.minsize(800, 420)

    editor.update_idletasks()
    sw = editor.winfo_screenwidth()
    sh = editor.winfo_screenheight()
    x = (sw - dw) // 2
    y = (sh - dh) // 2
    editor.geometry(f"{dw}x{dh}+{x}+{y}")

    editor.grab_set()

    editor.iconbitmap(resourcePath("hourglass.ico"))

    editor.columnconfigure(0, weight=0)
    editor.columnconfigure(1, weight=1)
    editor.rowconfigure(0, weight=1)
    editor.rowconfigure(1, weight=0)

    # no left-side task list — the canvas uses full width; y-axis labels show task rows
    editor.columnconfigure(0, weight=1)
    canvasFrame = tk.Frame(editor, bg=self.bgColor)
    canvasFrame.grid(row=0, column=0, padx=8, pady=8, sticky="nsew")
    canvasFrame.columnconfigure(0, weight=1)
    canvasFrame.rowconfigure(0, weight=1)

    # right: canvas timeline
    canvas = tk.Canvas(canvasFrame, bg="#0f1720", highlightthickness=0)
    canvas.grid(row=0, column=0, sticky="nsew")
    # make the canvas start at a reasonably large width so first click coordinates match final layout
    editor.update_idletasks()
    init_w = max(800, editor.winfo_width() - 40)
    canvas.config(width=init_w)
    # redraw when the canvas is resized so layout stays correct
    canvas.bind("<Configure>", lambda e: redraw())
    # bottom: summary text and save/cancel
    bottomFrame = tk.Frame(editor, bg=self.bgColor)
    bottomFrame.grid(row=1, column=0, columnspan=2, sticky="we", padx=8, pady=(0,8))
    tk.Label(bottomFrame, text="Summary (editable)", fg=self.textColor, bg=self.bgColor, font=("Segoe UI",9)).pack(anchor="w")
    summaryBox = tk.Text(bottomFrame, bg="#1b1f24", fg=self.textColor, wrap="word", height=6, borderwidth=0, highlightthickness=0, font=("Segoe UI",10))
    summaryBox.pack(fill="both", expand=False)
    summaryBox.insert(tk.END, entry.get("summary","") or "")

    saveRow = tk.Frame(bottomFrame, bg=self.bgColor)
    saveRow.pack(fill="x", pady=(6,0))
    saveBtn = tk.Button(saveRow, text="Save", font=("Segoe UI",10,"bold"), bg=self.accentColor, fg="#fff", relief="flat")
    saveBtn.pack(side="right", padx=4)
    cancelBtn = tk.Button(saveRow, text="Cancel", font=("Segoe UI",10), bg="#1b1f24", fg=self.textColor, relief="flat")
    cancelBtn.pack(side="right")

    # helper: parse ISO time to seconds since midnight
    def iso_to_secs(ts):
        if not ts or "T" not in ts:
            return None
        try:
            parts = ts.split("T",1)[1]
            for sep in ("+", "-", "Z"):
                i = parts.find(sep)
                if i > 0:
                    parts = parts[:i]
                    break
            comps = parts.split(":")
            h = int(comps[0]); m = int(comps[1]); s = int(comps[2]) if len(comps)>2 else 0
            return h*3600 + m*60 + s
        except Exception:
            return None
    def hhmm_to_secs(hhmm, fallbackSecs=0):
        if not hhmm:
            return fallbackSecs

        if isinstance(hhmm, (int, float)):
            return int(hhmm)

        try:
            h, m = hhmm.strip().split(":", 1)
            h = int(h)
            m = int(m)
            if h < 0 or h > 23 or m < 0 or m > 59:
                return fallbackSecs
            return h * 3600 + m * 60
        except Exception:
            return fallbackSecs

    # format seconds to ISO for this dayKey
    def secs_to_iso(secs):
        secs = max(0, min(int(round(secs)), 24*3600-1))
        h = secs//3600; m = (secs%3600)//60; s = secs%60
        return f"{dayKey}T{h:02d}:{m:02d}:{s:02d}"

        
    # drawing / layout state
    margin_left = 60
    margin_right = 20
    row_h = 26
    row_gap = 6
    top_margin = 20
    min_seg_s = getattr(self, "minSegmentSeconds", 30)
    click_min_s = 15 * 60

    # build mapping from task -> row index
    rows = list(tasks)
    if "Untasked" not in rows:
        rows.append("Untasked")
    task_to_row = {t:i for i,t in enumerate(rows)}

    rect_map = {}   # canvas item id -> segment index
    item_info = {}  # item id -> dict with seg idx, mode

    def layout_dimensions():
        canvas.update_idletasks()
        cw = max(400, canvas.winfo_width() or 600)
        ch = top_margin + len(rows)*(row_h + row_gap) + 20
        canvas.config(scrollregion=(0,0,cw,ch))
        return cw, ch

    def seconds_to_x(sec, width):
        usable_w = max(10, width - margin_left - margin_right)
        return margin_left + (sec / 86400.0) * usable_w

    def x_to_seconds(x, width):
        usable_w = max(10, width - margin_left - margin_right)
        s = (x - margin_left) / float(usable_w) * 86400.0
        return max(0, min(86400-1, int(round(s))))

    def redraw():
        canvas.delete("all")
        cw, ch = layout_dimensions()
        workStartSecs = hhmm_to_secs(self.workDayStart, 9 * 3600)
        workEndSecs   = hhmm_to_secs(self.workDayEnd, 17 * 3600)
        taskAreaTop = top_margin
        taskAreaBottom = top_margin + (len(rows) - 1) * (row_h + row_gap) + row_h

        xStart = seconds_to_x(workStartSecs, cw)
        xEnd = seconds_to_x(workEndSecs, cw)

        # header ticks: every 2 hours with labels
        for hr in range(0, 25, 2):
            # align to usable width
            x = seconds_to_x(hr*3600, cw)
            canvas.create_line(x, 0, x, ch, fill="#0b1220")
            canvas.create_text(x+2, 6, text=f"{hr:02d}:00", anchor="n", fill="#9ca3af", font=("Segoe UI",7))

        # draw rows
        for i, t in enumerate(rows):
            y = top_margin + i*(row_h + row_gap)
            canvas.create_rectangle(margin_left, y, cw-margin_right, y+row_h, fill="#071018", outline="#0b1220")
            canvas.create_text(margin_left-6, y + row_h/2, text=t, anchor="e", fill="#9ca3af", font=("Segoe UI",8))

        # draw segments (no internal text; y-axis labels suffice)
        rect_map.clear(); item_info.clear()
        for idx, s in enumerate(segs):
            start_s = iso_to_secs(s.get("start") or "")
            end_s = iso_to_secs(s.get("end") or "")
            if start_s is None or end_s is None or end_s <= start_s:
                continue
            task = s.get("task") or "Untasked"
            rowidx = task_to_row.get(task, len(rows)-1)
            y = top_margin + rowidx*(row_h + row_gap)
            c1 = seconds_to_x(start_s, cw)
            c2 = seconds_to_x(end_s, cw)
            # clamp
            if c2 - c1 < 4:
                c2 = c1 + 4
            color = ppColorMap.get(task, self.accentColor) if ppColorMap else self.accentColor
            item = canvas.create_rectangle(c1, y, c2, y+row_h, fill=color, outline="#0f1720")
            rect_map[item] = idx
            item_info[item] = {"seg": idx}
        
        canvas.create_line(xStart, taskAreaTop, xStart, taskAreaBottom, fill="#94a3b8", width=1)
        canvas.create_line(xEnd, taskAreaTop, xEnd, taskAreaBottom, fill="#94a3b8", width=1)

    # interactivity: drag/resize/move
    drag = {"item": None, "mode": None, "x0":0, "y0":0, "orig":None}

    # create-on-drag state (kept only for compatibility); new creation uses provisional seg + drag["creating"]
    create_state = {"active": False, "x0": 0, "y0": 0, "rubber": None}

    # mark drag entries for newly created segment so we can distinguish them
    drag["creating"] = False
    drag["fixed_row"] = None

    EDGE_MARGIN = 8

    def find_item_at(x,y):
        ids = canvas.find_overlapping(x,y,x,y)
        for iid in ids[::-1]:
            if iid in rect_map:
                return iid
        return None
    
    def mergeSameTaskSegments():
        # merge segments with same task when they overlap or touch (end == start)
        # keeps ordering by time for stable UI
        valid = []
        for s in segs:
            start_s = iso_to_secs(s.get("start",""))
            end_s = iso_to_secs(s.get("end",""))
            if start_s is None or end_s is None or end_s <= start_s:
                continue
            valid.append((start_s, end_s, s.get("task") or "Untasked"))

        valid.sort(key=lambda t: t[0])

        merged = []
        for start_s, end_s, task in valid:
            if merged and merged[-1][2] == task and start_s <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end_s), task)
            else:
                merged.append((start_s, end_s, task))

        segs[:] = [{"task": task, "start": secs_to_iso(start_s), "end": secs_to_iso(end_s)} for start_s, end_s, task in merged]

    def on_button_press(ev):
        # left-button press: start drag on existing segment OR start creating a provisional seg immediately
        cw, ch = layout_dimensions()
        x,y = canvas.canvasx(ev.x), canvas.canvasy(ev.y)
        iid = find_item_at(x,y)
        # clear any existing rubber visuals
        if create_state["rubber"] is not None:
            try:
                canvas.delete(create_state["rubber"])
            except Exception:
                pass
            create_state["rubber"] = None
            create_state["active"] = False
        if iid:
            # determine edge proximity for drag/resize
            coords = canvas.coords(iid)  # x1,y1,x2,y2
            x1,x2 = coords[0], coords[2]
            if abs(x - x1) <= EDGE_MARGIN:
                mode = "resize_left"
            elif abs(x - x2) <= EDGE_MARGIN:
                mode = "resize_right"
            else:
                mode = "move"
            drag["item"] = iid
            drag["mode"] = mode
            drag["x0"] = x
            drag["y0"] = y
            drag["origCoords"] = canvas.coords(iid)
            drag["grabDx"] = x - drag["origCoords"][0]
            sidx = rect_map.get(iid)
            drag["orig"] = dict(seg=segs[sidx].copy(), idx=sidx)
            drag["creating"] = False
        else:
            # start creating a provisional segment immediately, locked to the clicked row
            rowidx = int((y - top_margin) // (row_h + row_gap))
            rowidx = max(0, min(len(rows)-1, rowidx))
            task = rows[rowidx]
            start_s = x_to_seconds(x, cw)
            # provisional: create a minimal width rect (will be expanded while dragging)
            cx = seconds_to_x(start_s, cw)
            y1 = top_margin + rowidx * (row_h + row_gap)
            y2 = y1 + row_h
            color = ppColorMap.get(task, self.accentColor) if ppColorMap else self.accentColor
            item = canvas.create_rectangle(cx, y1, cx + 4, y2, fill=color, outline="#0f1720")
            # append provisional segment to segs and map
            segs.append({"task": task, "start": secs_to_iso(start_s), "end": secs_to_iso(start_s)})
            idx = len(segs) - 1
            rect_map[item] = idx
            item_info[item] = {"seg": idx}
            # set drag so motion will resize; lock vertical to rowidx
            # record start_x so user can drag either direction and flip mid-drag
            drag["item"] = item
            drag["mode"] = "resize_right"
            drag["x0"] = x
            drag["y0"] = y
            drag["start_x"] = x
            drag["orig"] = {"seg": segs[idx].copy(), "idx": idx}
            drag["creating"] = True
            drag["fixed_row"] = rowidx

    def on_motion(ev):
        # Update create provisional rect while dragging, otherwise update drag/resize visuals
        cw, ch = layout_dimensions()
        x,y = canvas.canvasx(ev.x), canvas.canvasy(ev.y)
        # if creating a new seg and we have an assigned drag item, expand the right edge but lock vertical lane
        if drag.get("creating") and drag.get("item"):
            iid = drag["item"]
            if iid not in rect_map:
                return
            sidx = rect_map[iid]
            # allow drawing in either direction and flip mid-drag by using start_x
            start_pixel = drag.get("start_x", drag.get("x0", 0))
            left_x = min(start_pixel, x)
            right_x = max(start_pixel, x)

            # convert creation-minimum to pixels and enforce
            cw, _ = layout_dimensions()
            min_px = max(4, int(round((click_min_s / 86400.0) * max(10, cw - margin_left - margin_right))))
            if (right_x - left_x) < min_px:
                if x >= start_pixel:
                    right_x = start_pixel + min_px
                else:
                    left_x = start_pixel - min_px

            # clamp to canvas bounds
            canvas_w, _ = layout_dimensions()
            left_x = max(margin_left, min(left_x, canvas_w - margin_right))
            right_x = max(margin_left + 4, min(right_x, canvas_w - margin_right))

            # lock vertical to the row where creation started
            rowidx = drag.get("fixed_row", 0)
            y1 = top_margin + rowidx * (row_h + row_gap)
            y2 = y1 + row_h
            canvas.coords(iid, left_x, y1, right_x, y2)

            # update provisional segment times (use click_min_s as minimum)
            start_s = x_to_seconds(left_x, canvas_w)
            end_s = x_to_seconds(right_x, canvas_w)
            if (end_s - start_s) < click_min_s:
                end_s = min(86400-1, start_s + click_min_s)
            try:
                segs[sidx]["start"] = secs_to_iso(start_s)
                segs[sidx]["end"] = secs_to_iso(end_s)
            except Exception:
                pass
            return
        # normal existing-segment drag/resize behavior
        if not drag["item"]:
            return
        iid = drag["item"]
        if iid not in rect_map:
            return
        sidx = rect_map[iid]
        seg = segs[sidx]
        coords = canvas.coords(iid)
        x1,y1,x2,y2 = coords
        if drag["mode"] == "move":
            # keep the grab point fixed under the mouse
            coords0 = drag["origCoords"]
            width = coords0[2] - coords0[0]
            grabDx = drag["grabDx"]

            cx1 = x - grabDx
            cx2 = cx1 + width

            center_y = y
            new_row = int((center_y - top_margin) // (row_h + row_gap))
            new_row = max(0, min(len(rows)-1, new_row))

            ny1 = top_margin + new_row*(row_h+row_gap)
            ny2 = ny1 + row_h

            canvas.coords(iid, cx1, ny1, cx2, ny2)
            drag["temp"] = {"cx1": cx1, "cx2": cx2, "row": new_row}
        elif drag["mode"] == "resize_left":
            cx1 = min(x, x2-4)
            canvas.coords(iid, cx1, y1, x2, y2)
            drag["temp"] = {"cx1":cx1}
        elif drag["mode"] == "resize_right":
            cx2 = max(x, x1+4)
            canvas.coords(iid, x1, y1, cx2, y2)
            drag["temp"] = {"cx2":cx2}

    def on_button_release(ev):
        # finalize creation (if creating) or finalize drag/resize (existing)
        cw, ch = layout_dimensions()
        x_rel,y_rel = canvas.canvasx(ev.x), canvas.canvasy(ev.y)
        workStartSecs = hhmm_to_secs(self.workDayStart, 9 * 3600)
        workEndSecs   = hhmm_to_secs(self.workDayEnd, 17 * 3600)
        snap_threshold_s = 10 * 60  # 10 minutes in seconds
        
        # If user was creating (we started a provisional seg on press)
        if drag.get("creating") and drag.get("item"):
            iid = drag["item"]
            if iid not in rect_map:
                # mergeSameTaskSegments()
                drag["creating"] = False
                drag["item"] = None
                drag["mode"] = None
                drag["fixed_row"] = None
                return
            sidx = rect_map[iid]
            coords = canvas.coords(iid)
            x1,y1,x2,y2 = coords
            # compute start/end seconds from current rect
            start_s = x_to_seconds(x1, cw)
            end_s = x_to_seconds(x2, cw)
            if end_s <= start_s or (end_s - start_s) < click_min_s:
                end_s = min(86400-1, start_s + click_min_s)
            
            # snap to work hours if within threshold
            if abs(start_s - workStartSecs) <= snap_threshold_s:
                start_s = workStartSecs
            if abs(end_s - workEndSecs) <= snap_threshold_s:
                end_s = workEndSecs
            
            # commit provisional segment
            segs[sidx]["start"] = secs_to_iso(start_s)
            segs[sidx]["end"] = secs_to_iso(end_s)
            # resolve overlaps now (reuse same rules)
            mod_idx = sidx
            A_start = start_s
            A_end = end_s
            i = 0
            while i < len(segs):
                if i == mod_idx:
                    i += 1
                    continue
                B_start = iso_to_secs(segs[i].get("start",""))
                B_end = iso_to_secs(segs[i].get("end",""))
                if B_start is None or B_end is None or B_end <= B_start:
                    segs.pop(i)
                    if i < mod_idx:
                        mod_idx -= 1
                    continue
                if B_end <= A_start or B_start >= A_end:
                    i += 1
                    continue
                if B_start >= A_start and B_end <= A_end:
                    segs.pop(i)
                    if i < mod_idx:
                        mod_idx -= 1
                    continue
                if B_start < A_start and B_end > A_end:
                    left_dur = A_start - B_start
                    right_dur = B_end - A_end
                    left_seg = None
                    right_seg = None
                    if left_dur >= min_seg_s:
                        left_seg = {"task": segs[i].get("task","Untasked"), "start": secs_to_iso(B_start), "end": secs_to_iso(A_start)}
                    if right_dur >= min_seg_s:
                        right_seg = {"task": segs[i].get("task","Untasked"), "start": secs_to_iso(A_end), "end": secs_to_iso(B_end)}
                    if left_seg and right_seg:
                        segs[i] = left_seg
                        segs.insert(i+1, right_seg)
                        if i < mod_idx:
                            mod_idx += 1
                        i += 2
                        continue
                    elif left_seg:
                        segs[i] = left_seg
                        i += 1
                        continue
                    elif right_seg:
                        segs[i] = right_seg
                        i += 1
                        continue
                    else:
                        segs.pop(i)
                        if i < mod_idx:
                            mod_idx -= 1
                        continue
                if B_start < A_start < B_end <= A_end:
                    new_end = A_start
                    if (new_end - B_start) < min_seg_s:
                        segs.pop(i)
                        if i < mod_idx:
                            mod_idx -= 1
                        continue
                    segs[i]["end"] = secs_to_iso(new_end)
                    i += 1
                    continue
                if A_start <= B_start < A_end < B_end:
                    new_start = A_end
                    if (B_end - new_start) < min_seg_s:
                        segs.pop(i)
                        if i < mod_idx:
                            mod_idx -= 1
                        continue
                    segs[i]["start"] = secs_to_iso(new_start)
                    i += 1
                    continue
                i += 1
            # finished creating
            mergeSameTaskSegments()
            drag["creating"] = False
            drag["fixed_row"] = None
            drag["item"] = None
            drag["mode"] = None
            redraw()
            return
        # otherwise finalize drag/resize of existing item (original behavior)
        if not drag["item"]:
            return
        iid = drag["item"]
        if iid not in rect_map:
            drag.clear()
            return
        sidx = rect_map[iid]
        coords = canvas.coords(iid)
        x1,y1,x2,y2 = coords
        # convert coords back to times/rows and commit
        start_s = x_to_seconds(x1, cw)
        end_s = x_to_seconds(x2, cw)
        
        # snap to work hours if within threshold
        if abs(start_s - workStartSecs) <= snap_threshold_s:
            start_s = workStartSecs
            x1 = seconds_to_x(start_s, cw)
        if abs(end_s - workEndSecs) <= snap_threshold_s:
            end_s = workEndSecs
            x2 = seconds_to_x(end_s, cw)
        
        if end_s <= start_s or (end_s - start_s) < min_seg_s:
            # remove segment if too short
            try:
                segs.pop(sidx)
            except Exception:
                pass
            redraw()
            drag["item"] = None
            drag["mode"] = None
            return
        # determine row
        mid_y = (y1 + y2)/2
        new_row = int((mid_y - top_margin) // (row_h + row_gap))
        new_row = max(0, min(len(rows)-1, new_row))
        new_task = rows[new_row]
        # commit changes
        segs[sidx]["start"] = secs_to_iso(start_s)
        segs[sidx]["end"] = secs_to_iso(end_s)
        segs[sidx]["task"] = new_task
        # resolve overlaps after committing the edit (existing logic reused)
        def resolve_overlaps_for(mod_idx):
            if mod_idx < 0 or mod_idx >= len(segs):
                return
            A_start = iso_to_secs(segs[mod_idx].get("start",""))
            A_end = iso_to_secs(segs[mod_idx].get("end",""))
            if A_start is None or A_end is None:
                return
            i = 0
            while i < len(segs):
                if i == mod_idx:
                    i += 1
                    continue
                B_start = iso_to_secs(segs[i].get("start",""))
                B_end = iso_to_secs(segs[i].get("end",""))
                if B_start is None or B_end is None or B_end <= B_start:
                    segs.pop(i)
                    if i < mod_idx:
                        mod_idx -= 1
                    continue
                if B_end <= A_start or B_start >= A_end:
                    i += 1
                    continue
                if B_start >= A_start and B_end <= A_end:
                    segs.pop(i)
                    if i < mod_idx:
                        mod_idx -= 1
                    continue
                if B_start < A_start and B_end > A_end:
                    left_dur = A_start - B_start
                    right_dur = B_end - A_end
                    left_seg = None
                    right_seg = None
                    if left_dur >= min_seg_s:
                        left_seg = {"task": segs[i].get("task","Untasked"), "start": secs_to_iso(B_start), "end": secs_to_iso(A_start)}
                    if right_dur >= min_seg_s:
                        right_seg = {"task": segs[i].get("task","Untasked"), "start": secs_to_iso(A_end), "end": secs_to_iso(B_end)}
                    if left_seg and right_seg:
                        segs[i] = left_seg
                        segs.insert(i+1, right_seg)
                        if i < mod_idx:
                            mod_idx += 1
                        i += 2
                        continue
                    elif left_seg:
                        segs[i] = left_seg
                        i += 1
                        continue
                    elif right_seg:
                        segs[i] = right_seg
                        i += 1
                        continue
                    else:
                        segs.pop(i)
                        if i < mod_idx:
                            mod_idx -= 1
                        continue
                if B_start < A_start < B_end <= A_end:
                    new_end = A_start
                    if (new_end - B_start) < min_seg_s:
                        segs.pop(i)
                        if i < mod_idx:
                            mod_idx -= 1
                        continue
                    segs[i]["end"] = secs_to_iso(new_end)
                    i += 1
                    continue
                if A_start <= B_start < A_end < B_end:
                    new_start = A_end
                    if (B_end - new_start) < min_seg_s:
                        segs.pop(i)
                        if i < mod_idx:
                            mod_idx -= 1
                        continue
                    segs[i]["start"] = secs_to_iso(new_start)
                    i += 1
                    continue
                i += 1
        resolve_overlaps_for(sidx)
        mergeSameTaskSegments()
        redraw()
        drag["item"] = None
        drag["mode"] = None

    # right-click: remove segment under cursor (if any)
    def on_right_click(ev):
        cw, ch = layout_dimensions()
        x,y = canvas.canvasx(ev.x), canvas.canvasy(ev.y)
        iid = find_item_at(x,y)
        if not iid:
            return
        sidx = rect_map.get(iid)
        if sidx is None:
            return
        # remove the segment and redraw
        try:
            segs.pop(sidx)
        except Exception:
            pass
        redraw()

    def on_hover(ev):
        if drag.get("item"):
            return
        x,y = canvas.canvasx(ev.x), canvas.canvasy(ev.y)
        iid = find_item_at(x,y)
        if not iid:
            canvas.config(cursor="arrow")
            return
        coords = canvas.coords(iid)
        x1,x2 = coords[0], coords[2]
        if abs(x - x1) <= EDGE_MARGIN or abs(x - x2) <= EDGE_MARGIN:
            canvas.config(cursor="sb_h_double_arrow")
        else:
            canvas.config(cursor="arrow")

    def on_leave(ev):
        if not drag.get("item"):
            canvas.config(cursor="arrow")

    canvas.bind("<Motion>", on_hover)
    canvas.bind("<Leave>", on_leave)
    canvas.bind("<Button-1>", on_button_press)
    canvas.bind("<B1-Motion>", on_motion)
    canvas.bind("<ButtonRelease-1>", on_button_release)
    canvas.bind("<Button-3>", on_right_click)
    # Save/Cancel logic
    def save_and_close():
        # compute totals from timeline segments (override summary)
        per_task_seconds = {}
        for s in segs:
            start_s = iso_to_secs(s.get("start",""))
            end_s = iso_to_secs(s.get("end",""))
            if start_s is None or end_s is None or end_s <= start_s:
                continue
            sec = end_s - start_s
            per_task_seconds[s.get("task","Untasked")] = per_task_seconds.get(s.get("task","Untasked"), 0) + sec

        # build summary lines with same rounding semantics as TaskTimerApp.endDay
        lines = []
        totalHours = 0.0
        for name, secs in sorted(per_task_seconds.items(), key=lambda kv: kv[0].lower()):
            hours = secs / 3600.0
            rounded = round(hours, 1)
            totalHours += rounded
            lines.append(f"{name}: {rounded:.1f} h")
        lines.append(f"Total: {totalHours:.1f} h")
        computed_summary = "\n".join(lines)

        new_summary = computed_summary  # override user edits for correctness
        # normalize segs: remove invalid and very short ones, and ensure ISO formatting
        final = []
        for s in segs:
            start_s = iso_to_secs(s.get("start",""))
            end_s = iso_to_secs(s.get("end",""))
            if start_s is None or end_s is None:
                continue
            if end_s <= start_s:
                continue
            if (end_s - start_s) < min_seg_s:
                continue
            final.append({"task": s.get("task","Untasked"), "start": secs_to_iso(start_s), "end": secs_to_iso(end_s)})

        # merge same-task segments that overlap or touch (end == start)
        final.sort(key=lambda s: iso_to_secs(s.get("start","")) or 0)
        merged = []
        for s in final:
            if not merged:
                merged.append(s)
                continue

            prev = merged[-1]
            if s.get("task") == prev.get("task"):
                prevEnd = iso_to_secs(prev.get("end",""))
                sStart = iso_to_secs(s.get("start",""))
                sEnd = iso_to_secs(s.get("end",""))

                if prevEnd is not None and sStart is not None and sEnd is not None and sStart <= prevEnd:
                    if sEnd > prevEnd:
                        prev["end"] = s["end"]
                    continue

            merged.append(s)

        # persist
        self.history[dayKey] = {"summary": new_summary, "timeline": merged}

        try:
            self.append_history_entry(dayKey, self.history[dayKey])
        except Exception:
            pass
        # post charge codes for edits only when editing within the most recent (non-ended) pay period
        try:
            if getattr(self, "autoChargeCodes", False) and getattr(self, "useTimesheetFunctions", False):
                mostRecent = periods[0] if periods else None
                mostRecentDays = (mostRecent or {}).get("days") if isinstance(mostRecent, dict) else None

                if isinstance(mostRecentDays, list) and dayKey in mostRecentDays and mostRecentDays:
                    endKey = max(str(d) for d in mostRecentDays if d)
                    if endKey >= date.today().isoformat():
                        taskSecondsSnapshot = dict(per_task_seconds)
                        self.postChargeCodeHours(taskSecondsSnapshot, dateKey=dayKey)
        except Exception:
            pass

        # update pay-period aggregates before refreshing UI
        try:
            updatePeriods()
        except Exception:
            # best-effort: ignore if callback missing
            pass
        # refresh main UI
        try:
            showPayPeriodSummary()
        except Exception:
            pass
        try:
            refreshDays()
        except Exception:
            pass
        try:
            ppIdx = current.get("ppIndex", 0)
            dayIdx = periods[ppIdx]["days"].index(dayKey)
            showDaySummary(dayIdx)
        except Exception:
            pass
        editor.destroy()

    def cancel():
        editor.destroy()

    saveBtn.config(command=save_and_close)
    cancelBtn.config(command=cancel)

    # initial draw
    redraw()
