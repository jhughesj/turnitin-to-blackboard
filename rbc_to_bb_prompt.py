#!/usr/bin/env python3
"""
Turnitin .rbc to Blackboard Ultra AI Rubric Prompt Generator

Converts .rbc rubric files into text prompts you can paste into
Blackboard Ultra's "Generate Rubric" AI description box (~2000 char limit).

The script automatically compresses output to stay under the limit by:
  1. Trimming long descriptors to key sentences
  2. Grouping criteria that share identical descriptors
  3. Removing descriptors entirely as a last resort (criteria names/weights kept)

Usage:
    python3 rbc_to_bb_prompt.py file1.rbc [file2.rbc ...]
    python3 rbc_to_bb_prompt.py *.rbc
    python3 rbc_to_bb_prompt.py --gui

Output .txt files are saved alongside each .rbc file.
Requires Python 3.6+. GUI mode requires tkinter (standard on Mac/Windows installer).
"""

import json
import os
import re
import sys
import threading
from collections import defaultdict

CHAR_LIMIT = 1900   # Conservative limit below BB's ~2000 cap


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def sanitize(text):
    if not text:
        return ""
    return re.sub(r"\s+", " ", str(text)).strip()


def compress_descriptor(text, max_words):
    """Trim descriptor to first sentence if it fits, else hard truncate."""
    if not text:
        return ""
    text = sanitize(text)
    if max_words is None:
        return text
    words = text.split()
    if len(words) <= max_words:
        return text
    sentences = re.split(r"(?<=[.!?])\s+", text)
    if sentences and len(sentences[0].split()) <= max_words:
        return sentences[0]
    return " ".join(words[:max_words]) + "…"


# ---------------------------------------------------------------------------
# Core conversion
# ---------------------------------------------------------------------------

def _load_rbc(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    rubric_data   = data.get("Rubric", [{}])[0]
    criteria_list = data.get("RubricCriterion", [])
    crit_scales   = data.get("RubricCriterionScale", [])
    scale_values  = data.get("RubricScale", [])

    rubric_name    = rubric_data.get("name", os.path.splitext(os.path.basename(filepath))[0])
    rubric_desc    = sanitize(rubric_data.get("description", ""))
    scoring_method = rubric_data.get("scoring_method", 2)

    criteria_list = sorted(criteria_list, key=lambda c: c.get("position", c.get("num", 0)))
    cs_map        = {cs["id"]: cs for cs in crit_scales}
    has_scales    = bool(scale_values) or any(c.get("criterion_scales") for c in criteria_list)
    is_form       = scoring_method == 6 or not has_scales

    if scale_values:
        sorted_sv = sorted(scale_values, key=lambda s: s.get("position", s.get("num", 0)))
        levels    = [s["name"] for s in sorted_sv]
        level_ids = [s["id"]   for s in sorted_sv]
    else:
        levels, level_ids = [], []

    # Sample 3 representative levels: low / mid / high
    if level_ids:
        idxs         = [0, len(levels) // 2, len(levels) - 1]
        sample_pairs = [(level_ids[i], levels[i]) for i in idxs]
    else:
        sample_pairs = []

    # Build per-criterion data including descriptor samples
    crit_blocks = []
    for c in criteria_list:
        cname = sanitize(c.get("name", ""))
        cdesc = sanitize(c.get("description", ""))
        cval  = c.get("value", 0)
        descs = {}
        if has_scales and sample_pairs:
            cs_ids   = c.get("criterion_scales", [])
            cs_objs  = [cs_map[i] for i in cs_ids if i in cs_map]
            sv_to_cs = {cs["scale_value"]: cs for cs in cs_objs}
            for lvl_id, lvl_name in sample_pairs:
                descs[lvl_name] = sanitize(sv_to_cs.get(lvl_id, {}).get("description", ""))
        crit_blocks.append({"name": cname, "desc": cdesc, "value": cval, "descs": descs})

    return rubric_name, rubric_desc, is_form, levels, sample_pairs, crit_blocks


def _build_prompt(rubric_name, rubric_desc, is_form, levels, sample_pairs,
                  crit_blocks, word_limit, group_identical, include_descs):
    lines = []
    lines.append(f"Please create a rubric titled: {rubric_name}")
    lines.append("")

    if rubric_desc:
        lines.append(f"Context: {rubric_desc}")
        lines.append("")

    # Rubric type line
    many_levels = len(levels) > 6
    if is_form:
        lines.append("Rubric type: Percentage-based grading form.")
    elif levels:
        if many_levels:
            lines.append(f"Rubric type: Percentage-based with {len(levels)} levels "
                         f"from {levels[0]} to {levels[-1]}.")
        else:
            lines.append(f"Rubric type: Percentage-based with {len(levels)} levels: "
                         f"{', '.join(levels)}.")
    lines.append("")
    lines.append(f"The rubric must have exactly {len(crit_blocks)} criteria:")
    lines.append("")

    if group_identical and sample_pairs and include_descs:
        # Group criteria that share identical descriptor text
        groups = defaultdict(list)
        for cb in crit_blocks:
            key = tuple(cb["descs"].get(lvl, "") for _, lvl in sample_pairs)
            groups[key].append(cb)

        for key, members in groups.items():
            for cb in members:
                w = (f" ({int(float(cb['value']))}% weighting)"
                     if cb["value"] and float(cb["value"]) > 0 else "")
                lines.append(f"  • {cb['name']}{w}: {cb['desc']}")
            if any(key):
                lines.append("  Performance descriptors:")
                for (_, lvl_name), desc in zip(sample_pairs, key):
                    if desc:
                        d = compress_descriptor(desc, word_limit)
                        lines.append(f"    • {lvl_name}: {d}")
            lines.append("")

    else:
        for i, cb in enumerate(crit_blocks, 1):
            w = (f" ({int(float(cb['value']))}% weighting)"
                 if cb["value"] and float(cb["value"]) > 0 else "")
            lines.append(f"{i}. {cb['name']}{w}")
            if cb["desc"]:
                lines.append(f"   {cb['desc']}")
            if include_descs and cb["descs"] and sample_pairs:
                lines.append("   Performance descriptors:")
                for _, lvl_name in sample_pairs:
                    d = cb["descs"].get(lvl_name, "")
                    if d:
                        d = compress_descriptor(d, word_limit)
                        lines.append(f"     • {lvl_name}: {d}")
            lines.append("")

    lines.append("Important: Use exactly the criteria names and weightings listed above.")
    return "\n".join(lines)


def rbc_to_prompt(filepath, char_limit=CHAR_LIMIT):
    """
    Convert .rbc to BB AI prompt, auto-compressing to stay under char_limit.
    Returns (prompt_text, char_count, was_compressed, rubric_name, is_form, n_criteria, n_levels)
    """
    rubric_name, rubric_desc, is_form, levels, sample_pairs, crit_blocks = _load_rbc(filepath)

    # Compression strategies in order: try each until under limit
    strategies = [
        dict(word_limit=None, group_identical=False, include_descs=True),   # Full
        dict(word_limit=50,   group_identical=False, include_descs=True),   # Light trim
        dict(word_limit=30,   group_identical=False, include_descs=True),   # Medium trim
        dict(word_limit=50,   group_identical=True,  include_descs=True),   # Group + light trim
        dict(word_limit=25,   group_identical=True,  include_descs=True),   # Group + medium trim
        dict(word_limit=15,   group_identical=True,  include_descs=True),   # Group + hard trim
        dict(word_limit=None, group_identical=False, include_descs=False),  # No descriptors
    ]

    for s in strategies:
        prompt = _build_prompt(
            rubric_name, rubric_desc, is_form, levels, sample_pairs, crit_blocks,
            s["word_limit"], s["group_identical"], s["include_descs"]
        )
        compressed = s["word_limit"] is not None or s["group_identical"] or not s["include_descs"]
        if len(prompt) <= char_limit:
            return prompt, len(prompt), compressed, rubric_name, is_form, len(crit_blocks), len(levels)

    # Absolute fallback: names and weights only
    lines = [f"Please create a rubric titled: {rubric_name}", ""]
    if levels:
        lines.append(f"Rubric type: Percentage-based, {len(levels)} levels "
                     f"from {levels[0]} to {levels[-1]}.")
        lines.append("")
    lines.append(f"The rubric must have exactly {len(crit_blocks)} criteria:")
    lines.append("")
    for i, cb in enumerate(crit_blocks, 1):
        w = f" ({int(float(cb['value']))}%)" if cb["value"] and float(cb["value"]) > 0 else ""
        lines.append(f"{i}. {cb['name']}{w} — {cb['desc']}")
    lines.append("")
    lines.append("Important: Use exactly the criteria names and weightings listed above.")
    prompt = "\n".join(lines)
    return prompt, len(prompt), True, rubric_name, is_form, len(crit_blocks), len(levels)


def save_prompt(filepath, output_dir=None, char_limit=CHAR_LIMIT):
    prompt, chars, compressed, rubric_name, is_form, n_crit, n_levels = rbc_to_prompt(
        filepath, char_limit=char_limit
    )
    base_name   = re.sub(r"[^\w\s-]", "", rubric_name).strip().replace(" ", "_")
    out_dir     = output_dir or os.path.dirname(os.path.abspath(filepath))
    os.makedirs(out_dir, exist_ok=True)
    output_path = os.path.join(out_dir, base_name + "_BB_prompt.txt")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(prompt)
    return output_path, rubric_name, is_form, n_crit, n_levels, chars, compressed


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def run_cli(files):
    ok = 0
    for fp in files:
        if not os.path.exists(fp):
            print("ERR  File not found: " + fp)
            continue
        try:
            out, name, is_form, n, lvls, chars, compressed = save_prompt(fp)
            rtype      = "Grading Form" if is_form else "Rubric"
            comp_note  = " [compressed to fit limit]" if compressed else ""
            print("OK   " + os.path.basename(fp))
            print(f"       Name    : {name}")
            print(f"       Type    : {rtype}  |  {n} criteria  |  {lvls} levels")
            print(f"       Size    : {chars} chars{comp_note}")
            print(f"       Output  : {out}")
            print("")
            ok += 1
        except Exception as e:
            print("ERR  " + fp + ": " + str(e))
    print(f"Converted {ok}/{len(files)} rubric(s).")


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

COLOUR_BG      = "#1e1e2e"
COLOUR_PANEL   = "#2a2a3e"
COLOUR_ACCENT  = "#7c6af7"
COLOUR_SUCCESS = "#50fa7b"
COLOUR_ERROR   = "#ff5555"
COLOUR_WARN    = "#f1fa8c"
COLOUR_TEXT    = "#cdd6f4"
COLOUR_SUBTEXT = "#6c7086"
COLOUR_BTN     = "#7c6af7"
COLOUR_BTN_HOV = "#9d8ff9"


def run_gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    class App(tk.Tk):
        def __init__(self):
            super().__init__()
            self.title("Turnitin → Blackboard AI Rubric Prompt Generator")
            self.resizable(True, True)
            self.minsize(700, 560)
            self.configure(bg=COLOUR_BG)
            self.files        = []
            self.output_dir   = tk.StringVar()
            self.same_dir_var = tk.BooleanVar(value=True)
            self._build_ui()
            self._center(760, 600)

        def _center(self, w, h):
            self.update_idletasks()
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
            self.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

        def _btn(self, parent, text, cmd, secondary=False,
                 font=("Helvetica", 10), pady=6):
            bg = COLOUR_PANEL if secondary else COLOUR_BTN
            fg = COLOUR_SUBTEXT if secondary else "white"
            b  = tk.Button(parent, text=text, command=cmd, bg=bg, fg=fg,
                           activebackground=COLOUR_BTN_HOV, activeforeground="white",
                           font=font, bd=0, padx=12, pady=pady,
                           cursor="hand2", relief="flat")
            b.bind("<Enter>", lambda e: b.config(bg=COLOUR_BTN_HOV if not secondary else "#555"))
            b.bind("<Leave>", lambda e: b.config(bg=bg))
            return b

        def _build_ui(self):
            # Title bar
            tf = tk.Frame(self, bg=COLOUR_ACCENT)
            tf.pack(fill="x")
            tk.Label(tf, text="  Turnitin → Blackboard AI Rubric Prompt Generator",
                     bg=COLOUR_ACCENT, fg="white",
                     font=("Helvetica", 13, "bold"), pady=10).pack(side="left")

            # Info banner
            info = tk.Frame(self, bg="#2d3250")
            info.pack(fill="x", padx=16, pady=(10, 2))
            tk.Label(info,
                     text="ℹ  Generates text prompts to paste into Blackboard Ultra → "
                          "Generate Rubric. Auto-compresses to stay under the ~2000 char limit.",
                     bg="#2d3250", fg="#a0b0ff", font=("Helvetica", 9),
                     wraplength=680, justify="left", pady=6, padx=8).pack(anchor="w")

            # File list
            ff = tk.LabelFrame(self, text=" Input Files (.rbc) ",
                               bg=COLOUR_PANEL, fg=COLOUR_TEXT,
                               font=("Helvetica", 10, "bold"), bd=1, relief="flat")
            ff.pack(fill="both", expand=True, padx=16, pady=(8, 4))

            lc = tk.Frame(ff, bg=COLOUR_PANEL)
            lc.pack(fill="both", expand=True, padx=8, pady=6)
            sb = tk.Scrollbar(lc, bg=COLOUR_PANEL)
            sb.pack(side="right", fill="y")
            self.listbox = tk.Listbox(
                lc, bg="#12121e", fg=COLOUR_TEXT,
                selectbackground=COLOUR_ACCENT, selectforeground="white",
                font=("Courier", 10), bd=0, highlightthickness=0,
                yscrollcommand=sb.set, activestyle="none")
            self.listbox.pack(fill="both", expand=True)
            sb.config(command=self.listbox.yview)

            br = tk.Frame(ff, bg=COLOUR_PANEL)
            br.pack(fill="x", padx=8, pady=(0, 8))
            self._btn(br, "＋ Add Files", self._add).pack(side="left", padx=(0, 6))
            self._btn(br, "✕ Remove", self._remove,
                      secondary=True).pack(side="left", padx=(0, 6))
            self._btn(br, "Clear All", self._clear,
                      secondary=True).pack(side="left")
            self.count_lbl = tk.Label(br, text="0 file(s)",
                                      bg=COLOUR_PANEL, fg=COLOUR_SUBTEXT,
                                      font=("Helvetica", 9))
            self.count_lbl.pack(side="right")

            # Output folder
            outf = tk.LabelFrame(self, text=" Output Folder ",
                                 bg=COLOUR_PANEL, fg=COLOUR_TEXT,
                                 font=("Helvetica", 10, "bold"), bd=1, relief="flat")
            outf.pack(fill="x", padx=16, pady=4)
            oi = tk.Frame(outf, bg=COLOUR_PANEL)
            oi.pack(fill="x", padx=8, pady=6)
            self.out_entry = tk.Entry(
                oi, textvariable=self.output_dir,
                bg="#12121e", fg=COLOUR_TEXT, insertbackground=COLOUR_TEXT,
                font=("Courier", 10), bd=0, highlightthickness=1,
                highlightcolor=COLOUR_ACCENT, highlightbackground=COLOUR_SUBTEXT,
                relief="flat")
            self.out_entry.pack(side="left", fill="x", expand=True,
                                ipady=4, padx=(0, 8))
            self._btn(oi, "Browse", self._browse_out).pack(side="left")
            tk.Checkbutton(
                oi, text="Same folder as input",
                variable=self.same_dir_var, command=self._toggle_same,
                bg=COLOUR_PANEL, fg=COLOUR_TEXT, selectcolor=COLOUR_PANEL,
                activebackground=COLOUR_PANEL, activeforeground=COLOUR_TEXT,
                font=("Helvetica", 9)).pack(side="left", padx=8)
            self._toggle_same()

            # Generate button
            cr = tk.Frame(self, bg=COLOUR_BG)
            cr.pack(fill="x", padx=16, pady=8)
            self.conv_btn = self._btn(
                cr, "▶  Generate Prompts", self._start,
                font=("Helvetica", 12, "bold"), pady=10)
            self.conv_btn.pack(fill="x")

            # Progress bar
            self.progress = ttk.Progressbar(self, mode="determinate", maximum=100)
            style = ttk.Style(self)
            style.theme_use("default")
            style.configure("TProgressbar", troughcolor=COLOUR_PANEL,
                            background=COLOUR_ACCENT, thickness=6)
            self.progress.pack(fill="x", padx=16, pady=(0, 4))

            # Log panel
            lf = tk.LabelFrame(self, text=" Log ",
                               bg=COLOUR_PANEL, fg=COLOUR_TEXT,
                               font=("Helvetica", 10, "bold"), bd=1, relief="flat")
            lf.pack(fill="both", expand=False, padx=16, pady=(4, 12))
            ls = tk.Scrollbar(lf, bg=COLOUR_PANEL)
            ls.pack(side="right", fill="y")
            self.log = tk.Text(
                lf, height=7, bg="#12121e", fg=COLOUR_TEXT,
                font=("Courier", 9), bd=0, state="disabled",
                yscrollcommand=ls.set, wrap="word")
            self.log.pack(fill="both", expand=True, padx=8, pady=6)
            ls.config(command=self.log.yview)
            self.log.tag_config("ok",   foreground=COLOUR_SUCCESS)
            self.log.tag_config("err",  foreground=COLOUR_ERROR)
            self.log.tag_config("info", foreground=COLOUR_WARN)
            self.log.tag_config("dim",  foreground=COLOUR_SUBTEXT)

        def _log(self, msg, tag="dim"):
            self.log.config(state="normal")
            self.log.insert(tk.END, msg + "\n", tag)
            self.log.see(tk.END)
            self.log.config(state="disabled")

        def _add(self):
            paths = filedialog.askopenfilenames(
                title="Select Turnitin Rubric Files",
                filetypes=[("Turnitin Rubric", "*.rbc"), ("All Files", "*.*")])
            added = 0
            for p in paths:
                if p not in self.files:
                    self.files.append(p)
                    self.listbox.insert("end", os.path.basename(p))
                    added += 1
            self._update_count()
            if added:
                self._log(f"Added {added} file(s).", "info")
                if self.same_dir_var.get() and self.files:
                    self.output_dir.set(os.path.dirname(self.files[0]))

        def _remove(self):
            for i in reversed(self.listbox.curselection()):
                self.listbox.delete(i)
                del self.files[i]
            self._update_count()

        def _clear(self):
            self.files.clear()
            self.listbox.delete(0, "end")
            self._update_count()

        def _update_count(self):
            self.count_lbl.config(text=f"{len(self.files)} file(s)")

        def _browse_out(self):
            folder = filedialog.askdirectory(title="Select Output Folder")
            if folder:
                self.output_dir.set(folder)
                self.same_dir_var.set(False)
                self.out_entry.config(state="normal")

        def _toggle_same(self):
            if self.same_dir_var.get():
                self.out_entry.config(state="disabled")
                self.output_dir.set(
                    os.path.dirname(self.files[0]) if self.files
                    else "(same folder as each input file)")
            else:
                self.out_entry.config(state="normal")

        def _set_progress(self, v):
            self.progress["value"] = v

        def _start(self):
            if not self.files:
                messagebox.showwarning("No Files", "Please add at least one .rbc file.")
                return
            out_dir = (None if self.same_dir_var.get()
                       else self.output_dir.get().strip() or None)
            self.conv_btn.config(state="disabled")
            self.progress["value"] = 0
            self._log("─" * 48, "dim")
            self._log(f"Generating prompts for {len(self.files)} file(s)…", "info")
            threading.Thread(
                target=self._run, args=(list(self.files), out_dir),
                daemon=True).start()

        def _run(self, files, out_dir):
            ok = err = 0
            total = len(files)
            for i, fp in enumerate(files):
                try:
                    effective = out_dir or os.path.dirname(os.path.abspath(fp))
                    out, name, is_form, n, lvls, chars, compressed = save_prompt(fp, effective)
                    rtype     = "Grading Form" if is_form else "Rubric"
                    comp_note = " ⚡compressed" if compressed else ""
                    self.after(0, self._log,
                               f"✓  {os.path.basename(fp)}  "
                               f"[{rtype} · {n} criteria · {chars} chars{comp_note}]", "ok")
                    self.after(0, self._log, f"   → {out}", "dim")
                    ok += 1
                except Exception as e:
                    self.after(0, self._log,
                               f"✗  {os.path.basename(fp)}: {e}", "err")
                    err += 1
                self.after(0, self._set_progress, int((i + 1) / total * 100))

            summary = f"Done: {ok} generated" + (f", {err} failed" if err else "")
            self.after(0, self._log, summary, "info" if not err else "err")
            self.after(0, self.conv_btn.config, {"state": "normal"})
            if not err:
                self.after(0, messagebox.showinfo, "Complete",
                           f"All {ok} prompt file(s) saved.\n\n"
                           f"Paste each .txt into Blackboard Ultra →\n"
                           f"Assignment → Add Marking Rubric → Generate → Description box.")
            else:
                self.after(0, messagebox.showwarning, "Completed with errors",
                           f"{ok} succeeded, {err} failed.")

    App().mainloop()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] == "--gui":
        run_gui()
    else:
        run_cli(args)
