#!/usr/bin/env python3
"""
Turnitin .rbc to Blackboard Ultra AI Rubric Prompt Generator

Converts .rbc rubric files into text prompts you can paste into
Blackboard Ultra's "Generate Rubric" AI description box (~2000 char limit).

The script automatically compresses output to stay under the limit by:
  1. Including Distinction + Fail descriptors, allocated proportionally by criterion weighting
  2. Trimming descriptors to key sentences to fit within each criterion's character budget
  3. Removing descriptors entirely as a last resort (criteria names/weights kept)

Usage:
    python3 rbc_to_bb_prompt.py file1.rbc [file2.rbc ...]
    python3 rbc_to_bb_prompt.py *.rbc
    python3 rbc_to_bb_prompt.py --gui

Output .txt files are saved alongside each .rbc file.
Requires Python 3.6+. GUI mode requires tkinter (standard on Mac/Windows).
"""

import json
import os
import re
import sys
import threading


CHAR_LIMIT = 1900   # Conservative limit below BB's ~2000 cap


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def sanitize(text):
    if not text:
        return ""
    return re.sub(r"\s+", " ", str(text)).strip()



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
        # Sort by position for display order in the prompt
        sorted_sv = sorted(scale_values, key=lambda s: s.get("position", s.get("num", 0)))
        levels    = [s["name"] for s in sorted_sv]
        level_ids = [s["id"]   for s in sorted_sv]
        # Identify top/fail by actual numeric value - rubrics may sort ascending or descending
        by_value = sorted(scale_values, key=lambda s: float(s.get("value", 0)))
        top_id   = by_value[-1]["id"]   # highest value = Distinction
        fail_id  = by_value[0]["id"]    # lowest value  = Fail
    else:
        levels, level_ids = [], []
        top_id = fail_id = None

    # Build per-criterion data: short desc + full Distinction & Fail descriptors
    crit_blocks = []
    for c in criteria_list:
        cname = sanitize(c.get("name", ""))
        cdesc = sanitize(c.get("description", ""))
        cval  = c.get("value", 0)
        dist_desc = ""
        fail_desc = ""
        if has_scales:
            cs_ids   = c.get("criterion_scales", [])
            cs_objs  = [cs_map[i] for i in cs_ids if i in cs_map]
            sv_to_cs = {cs["scale_value"]: cs for cs in cs_objs}
            if top_id:
                dist_desc = sanitize(sv_to_cs.get(top_id, {}).get("description", ""))
            if fail_id:
                fail_desc = sanitize(sv_to_cs.get(fail_id, {}).get("description", ""))
        crit_blocks.append({
            "name": cname, "desc": cdesc, "value": cval,
            "dist": dist_desc, "fail": fail_desc
        })

    return rubric_name, rubric_desc, is_form, levels, crit_blocks


# ---------------------------------------------------------------------------
# Sentence scoring — rewards specific/concrete content over generic quality prose
# ---------------------------------------------------------------------------

# Signals that indicate a sentence contains a concrete, checkable requirement.
# Grouped by category for maintainability.
# Scores: +10 for specific named requirements, +8 for important-but-slightly-broader terms.
_HIGH_VALUE_SIGNALS = [
    # Referencing styles — named styles are always high-value
    "harvard", "apa", "mla", "chicago", "vancouver",
    # Referencing mechanics
    "in-text citation", "bibliography", "reference format", "references are",
    "footnote", "endnote",
    # Source quality
    "peer-reviewed", "peer reviewed", "primary source",
    # Integrity / originality (Turnitin signals)
    "plagiar", "similarity score", "similarity", "originality",
    "ai-generated", "generative tool", "ai tool",
    # Document structure requirements
    "template", "executive summary", "appendix", "word count", "word limit",
    # Institutional / regulatory specifics
    "supervisor", "westminster", "un sdg", "sdgs", " sdg",
    "gdpr", "data protection", "consent",
    # Subject-specific terms
    "knowledge gap", "background/introduction", "future work",
    "comparing means", "statistical",
    "past and current perspectives", "problem or knowledge gap",
    # Audience
    "non-expert", "lay audience", "non-specialist", "expert audience",
]

# Medium-value signals — important but broader; each adds +8 instead of +10.
_MEDIUM_VALUE_SIGNALS = [
    "image", "visual", "diagram", "figure", "chart", "graph",
    "table", "screenshot", "illustration",
]

# Generic sentence openers that add little information value.
# Each match subtracts 3 from the sentence score.
_GENERIC_OPENERS = [
    "the case for support section is",
    "the technical summary is",
    "the lay summary is",
    "the beneficiaries section is",
    "it demonstrates a high level of",
    "it shows a strong level of",
    "it shows effort in",
    "it lacks the necessary",
    "the summary provides a",
    "the section demonstrates",
    "it does not make sufficient effort",
    "it demonstrates a moderate level of",
    # Additional generic quality openers
    "the response is outstanding",
    "the response lacks",
    "the argument is highly coherent",
    "the argument is unclear",
    "there is little to no evidence of",
    "supporting evidence is used",
    "the answer demonstrates",
    "the submission demonstrates",
    "the work demonstrates",
]


def _score_sentence(sentence):
    """
    Score a sentence by information density.
    Higher = more specific/concrete/checkable content.
    +10 per high-value signal (named requirements, specific terms)
    +8  per medium-value signal (visual elements, broad but concrete)
    -3  for generic openers
    +2  bonus for short sentences (tend to be more specific)
    """
    s = sentence.lower()
    score = 0
    for sig in _HIGH_VALUE_SIGNALS:
        if sig in s:
            score += 10
    for sig in _MEDIUM_VALUE_SIGNALS:
        if sig in s:
            score += 8
    for opener in _GENERIC_OPENERS:
        if s.startswith(opener):
            score -= 3
            break  # only penalise once
    # Short sentences tend to be more specific (e.g. "Harvard format required.")
    if len(sentence) < 60:
        score += 2
    return score


def _smart_extract(text, max_chars):
    """
    Select the highest-scoring sentences from a descriptor that fit within
    max_chars. Strategy:
      1. Score all sentences by information density.
      2. Attempt to include the first sentence as a context anchor ONLY if at
         least one high-scoring sentence (score > 0) still fits after it.
         If the anchor would crowd out all high-value content, skip it.
      3. Fill remaining space with the highest-scoring sentences in order.
      4. Return sentences in their original order for readability.
    This ensures high-value specific requirements (Harvard, template, knowledge
    gap, Westminster/SDGs, references format, supervisor) are never sacrificed
    for generic quality prose.
    """
    if not text or max_chars <= 0:
        return ""

    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    if not sentences:
        return ""

    order = {s: i for i, s in enumerate(sentences)}
    first = sentences[0]
    remaining = sentences[1:]

    # Score all non-first sentences
    scored_remaining = sorted(
        [(s, _score_sentence(s)) for s in remaining],
        key=lambda x: (-x[1], order.get(x[0], 999))
    )
    high_value = [(s, sc) for s, sc in scored_remaining if sc > 0]

    # Decide whether to include the first sentence as context anchor:
    # include it only if at least one high-value sentence still fits after it
    use_anchor = False
    if len(first) < max_chars:
        remaining_after_anchor = max_chars - len(first) - 1  # -1 for space
        if high_value and len(high_value[0][0]) <= remaining_after_anchor:
            use_anchor = True

    # Build selection
    selected = []
    if use_anchor:
        selected.append(first)
        used_chars = len(first)
        pool = scored_remaining  # include all, not just high_value
    else:
        used_chars = 0
        pool = scored_remaining  # start from highest-scoring

    for s, score in pool:
        if score <= 0 and not use_anchor:
            continue  # skip generic sentences when no anchor context
        needed = len(s) + (1 if selected else 0)
        if used_chars + needed <= max_chars:
            selected.append(s)
            used_chars += needed

    # If nothing selected at all, truncate the best sentence available
    if not selected:
        best = high_value[0][0] if high_value else first
        words = best.split()
        partial = ""
        for w in words:
            trial = (partial + " " + w).strip()
            if len(trial) <= max_chars - 1:
                partial = trial
            else:
                break
        return (partial + "…") if partial else ""

    # Return in original order
    selected.sort(key=lambda s: order.get(s, 999))
    return " ".join(selected)


def _build_prompt(rubric_name, rubric_desc, is_form, levels, crit_blocks,
                  char_limit, include_descs, chars_per_criterion):
    """
    Build the prompt. When include_descs=True, append Distinction and Fail
    descriptors for each criterion. Budget is allocated proportionally by
    weighting (higher-weighted criteria get more detail). Each criterion's
    budget is split 60/40 between Distinction and Fail descriptors, giving
    BB anchors at both ends of the scale.
    """
    lines = []
    # Strong naming instruction at the top so it's the first thing BB's AI reads
    lines.append("CRITICAL: Use the criterion names below EXACTLY as written. "
                 "Do NOT rephrase, rename, expand, or reword any criterion name.")
    lines.append("")
    lines.append(f"Please create a rubric titled: {rubric_name}")
    lines.append("")

    if rubric_desc:
        lines.append(f"Context: {rubric_desc}")
        lines.append("")

    many_levels = len(levels) > 6
    if is_form:
        lines.append("Rubric type: Percentage-based grading form.")
    elif levels:
        unique_levels = list(dict.fromkeys(levels))  # deduplicate preserving order
        if many_levels:
            # Always show range as top-grade to bottom-grade (e.g. Distinction to Fail)
            # by_value sort puts highest grade last; use that for display order
            display_first = unique_levels[-1]  # highest grade name
            display_last  = unique_levels[0]   # lowest grade name
            lines.append(f"Rubric type: Percentage-based with {len(levels)} levels "
                         f"from {display_first} to {display_last}.")
        else:
            # For small sets, list all levels highest-first
            lines.append(f"Rubric type: Percentage-based with {len(levels)} levels: "
                         f"{', '.join(reversed(unique_levels))}.")
    lines.append("")
    lines.append(f"The rubric must have exactly {len(crit_blocks)} criteria:")
    lines.append("")

    # Compute per-criterion descriptor budgets.
    # Base: proportional to weighting (60% dist / 40% fail split).
    # Targeted boost: Research Q (supervisor) and Presentation (Harvard/template)
    # have short but critical sentences that get cut under pure proportional
    # allocation because of their low weighting. We boost their dist budget to
    # fit their best sentence, funding the boost by trimming the highest-weight
    # criterion (CFS), but only if the total still fits within chars_per_criterion.
    BOOST_CRITERIA = {"research q", "presentation"}  # lowercased names to match

    if include_descs and chars_per_criterion:
        total_weight = sum(
            max(float(cb["value"]), 1) for cb in crit_blocks
            if cb.get("dist") or cb.get("fail")
        )
        total_budget = chars_per_criterion * len(crit_blocks)

        # First pass: proportional allocation
        crit_budgets = {}
        for i, cb in enumerate(crit_blocks, 1):
            if cb.get("dist") or cb.get("fail"):
                share = (max(float(cb["value"]), 1) / total_weight) * total_budget
                crit_budgets[i] = {
                    "dist": int(share * 0.60),
                    "fail": int(share * 0.40),
                }

        # Second pass: targeted boost for Research Q and Presentation
        import re as _re
        heaviest_i = max(
            (i for i in crit_budgets),
            key=lambda i: float(crit_blocks[i - 1]["value"])
        )
        boost_total = 0
        for i, cb in enumerate(crit_blocks, 1):
            if i not in crit_budgets or not cb.get("dist"):
                continue
            if cb["name"].lower() not in BOOST_CRITERIA:
                continue
            sentences = _re.split(r"(?<=[.!?])\s+", cb["dist"].strip())
            scored = [(s, _score_sentence(s)) for s in sentences]
            high = [(s, sc) for s, sc in scored if sc > 0]
            if not high:
                continue
            best_s = max(high, key=lambda x: x[1])[0]
            needed = len(best_s) + 2
            if needed > crit_budgets[i]["dist"]:
                boost = needed - crit_budgets[i]["dist"]
                # Only boost if heaviest can afford it (keep at least 50 chars dist)
                heaviest_spare = max(0, crit_budgets[heaviest_i]["dist"] - 50)
                actual_boost = min(boost, heaviest_spare)
                if actual_boost > 0:
                    crit_budgets[i]["dist"] += actual_boost
                    crit_budgets[heaviest_i]["dist"] -= actual_boost
                    boost_total += actual_boost
    else:
        crit_budgets = {}

    # Assemble criteria blocks
    for i, cb in enumerate(crit_blocks, 1):
        w = (f" ({int(float(cb['value']))}% weighting)"
             if cb["value"] and float(cb["value"]) > 0 else "")
        lines.append(f"{i}. {cb['name']}{w}")
        if cb["desc"]:
            # Truncate very long descriptions (e.g. full task instructions) to
            # keep the prompt within the character limit
            desc = cb["desc"]
            if len(desc) > 150:
                # Try to cut at a sentence boundary within the first 150 chars
                cut = desc[:150]
                last_stop = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
                desc = (cut[:last_stop + 1] if last_stop > 60 else cut.rstrip()) + "…"
            lines.append(f"   {desc}")
        if crit_budgets.get(i):
            budget = crit_budgets[i]
            if cb.get("dist") and budget["dist"] > 20:
                d = _smart_extract(cb["dist"], budget["dist"])
                if d:
                    lines.append(f"   Distinction: {d}")
            if cb.get("fail") and budget["fail"] > 20:
                f = _smart_extract(cb["fail"], budget["fail"])
                if f:
                    lines.append(f"   Fail: {f}")
        lines.append("")

    # Strong closing reminder — repeated for emphasis
    lines.append("IMPORTANT: Criterion names must be copied EXACTLY as listed above. "
                 "Do not rephrase, rename, or expand them.")
    return "\n".join(lines)


def rbc_to_prompt(filepath, char_limit=CHAR_LIMIT):
    """
    Convert .rbc to BB AI prompt, maximising use of the char_limit.
    Strategy:
      1. Build base prompt (names, weights, short descriptions, strong naming instructions).
      2. Use remaining characters for Distinction + Fail descriptors, allocated
         proportionally by criterion weighting (higher weight = more detail).
         Each criterion's budget is split 60% Distinction / 40% Fail.
      3. If base alone exceeds limit, fall back to names/weights only.
    Returns (prompt_text, char_count, was_compressed, rubric_name, is_form, n_criteria, n_levels)
    """
    rubric_name, rubric_desc, is_form, levels, crit_blocks = _load_rbc(filepath)

    # Step 1: build base prompt with no descriptors
    base_prompt = _build_prompt(
        rubric_name, rubric_desc, is_form, levels, crit_blocks,
        char_limit, include_descs=False, chars_per_criterion=0
    )

    if len(base_prompt) > char_limit:
        # Base prompt (names + descriptions, no level descriptors) already exceeds limit.
        # This happens when a rubric has many criteria with very long descriptions
        # (e.g. full coursework task instructions used as criterion descriptions).
        # Return a warning prompt explaining the situation rather than an unusable
        # truncated fragment.
        n = len(crit_blocks)
        total_desc_chars = sum(len(cb.get("desc", "")) for cb in crit_blocks)
        lines = [
            f"WARNING: This rubric ({rubric_name!r}) cannot be automatically converted "
            f"to a Blackboard AI prompt.",
            "",
            f"Reason: The rubric has {n} criteria whose descriptions total "
            f"{total_desc_chars:,} characters. Even with no level descriptors, "
            f"the prompt exceeds Blackboard's ~{char_limit:,} character limit.",
            "",
            "Suggested actions:",
            "  1. Use Blackboard's rubric editor directly to create this rubric manually.",
            "  2. If the criterion descriptions contain full task instructions, consider",
            "     whether a simpler rubric structure is appropriate for Blackboard.",
            f"  3. The rubric has {n} criteria — Blackboard AI works best with 10 or fewer.",
            "",
            "Criterion names for reference:",
        ]
        for i, cb in enumerate(crit_blocks, 1):
            w = f" ({int(float(cb['value']))}%)" if cb.get("value") and float(cb["value"]) > 0 else ""
            lines.append(f"  {i}. {cb['name']}{w}")
        prompt = "\n".join(lines)
        return prompt, len(prompt), True, rubric_name, is_form, len(crit_blocks), len(levels)

    # Step 2: binary search for the largest descriptor budget that fits
    remaining = char_limit - len(base_prompt)
    n_with_descs = sum(1 for cb in crit_blocks if cb.get("dist") or cb.get("fail"))

    if remaining > 60 and n_with_descs > 0:
        lo, hi = 0, remaining
        best_prompt = base_prompt
        while lo <= hi:
            mid = (lo + hi) // 2
            candidate = _build_prompt(
                rubric_name, rubric_desc, is_form, levels, crit_blocks,
                char_limit, include_descs=True, chars_per_criterion=mid
            )
            if len(candidate) <= char_limit:
                best_prompt = candidate
                lo = mid + 1
            else:
                hi = mid - 1
        prompt = best_prompt
    else:
        prompt = base_prompt

    compressed = len(prompt) < char_limit * 0.85
    return prompt, len(prompt), compressed, rubric_name, is_form, len(crit_blocks), len(levels)


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
COLOUR_SUBTEXT = "#a0a8c0"
COLOUR_BTN     = "#7c6af7"
COLOUR_BTN_HOV = "#9d8ff9"
COLOUR_INPUT   = "#0d0d1a"


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
            bg     = "#3a3a55" if secondary else COLOUR_BTN
            bg_hov = "#4a4a6a" if secondary else COLOUR_BTN_HOV
            fg     = COLOUR_TEXT if secondary else "white"
            # Use Label instead of Button — macOS Aqua cannot override Label colours
            b = tk.Label(parent, text=text, bg=bg, fg=fg,
                         font=font, padx=12, pady=pady,
                         cursor="hand2", relief="flat")
            b.bind("<Button-1>", lambda e: cmd())
            b.bind("<Enter>",    lambda e: b.config(bg=bg_hov))
            b.bind("<Leave>",    lambda e: b.config(bg=bg))
            # Support .config(state="disabled"/"normal") for Generate button
            _orig_config = b.config
            def _patched_config(_b=b, _fg=fg, _cmd=cmd, **kw):
                if "state" in kw:
                    state = kw.pop("state")
                    if state == "disabled":
                        _b.configure(fg="#555577")
                        _b.unbind("<Button-1>")
                    else:
                        _b.configure(fg=_fg)
                        _b.bind("<Button-1>", lambda e: _cmd())
                if kw:
                    _orig_config(**kw)
            b.config = _patched_config
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
                lc, bg=COLOUR_INPUT, fg=COLOUR_TEXT,
                selectbackground=COLOUR_ACCENT, selectforeground="white",
                font=("Courier", 10), bd=0, highlightthickness=1,
                highlightbackground=COLOUR_ACCENT, highlightcolor=COLOUR_ACCENT,
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
                bg=COLOUR_INPUT, fg=COLOUR_TEXT, insertbackground=COLOUR_TEXT,
                font=("Courier", 10), bd=0, highlightthickness=1,
                highlightcolor=COLOUR_ACCENT, highlightbackground=COLOUR_ACCENT,
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
                lf, height=7, bg=COLOUR_INPUT, fg=COLOUR_TEXT,
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
            self.after(0, lambda: self.conv_btn.config(state="normal"))
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
