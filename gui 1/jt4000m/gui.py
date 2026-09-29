"""JT-4000M Editor — offline Tkinter GUI.

This module never touches MIDI/hardware. It only reads and writes local .syx
files through jt4000m.syx / jt4000m.patch.

Layout:
    left   — bank preset list (32 slots) + search filter
    center — grouped parameter controls for the selected program
    right  — developer panel (raw byte table / compare / bank analysis)

Model flow: every control edit produces a new immutable ``Bank``; the GUI is
synced back from the model, so model changes update the GUI and vice versa.
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .analyzer import cross_bank
from .diff import format_change, semantic_diff
from .editor_model import EditorHistory, EditorModel
from .model import BY_KEY, PARAMETERS, display_value, enum_options
from .patch import Bank, JTProgram, program_to_single
from .syx import SysExFile, field_name, parse_file, semantic_value

# Parameter groups rendered in this order in the editor grid.
SECTION_ORDER = ["OSCILLATORS", "FILTER", "VCF ENVELOPE", "VCA ENVELOPE", "LFO", "MODULATION"]

# Offset 0x2C changes together with Ring Mod on/off in existing banks.
# Correlation only — NOT a confirmed parameter. Needs hardware verification.
RING_MOD_CANDIDATE_OFFSET = 0x2C


def _row_label(spec, developer: bool) -> str:
    label = spec.label
    if spec.orientation == "centered":
        label += f" [{display_value(spec.key, 64)}]"
    if developer and spec.offset is not None:
        label = f"0x{spec.offset:02X} {label}"
    return label


class Editor(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("JT-4000M Editor v0.1")
        self.geometry("1420x860")
        self.minsize(1100, 700)
        self.configure(bg="#202124")

        # ----- state -------------------------------------------------------
        # P1.10: the GUI is a thin presentation layer.  EditorModel is the
        # single source of truth for patch data, dirty state and history;
        # `self.bank` is only a *read-only view* refreshed after every model
        # mutation (used by the diagnostic Raw/Compare/Analyze tabs).
        self.editor = EditorModel()
        self._history = EditorHistory(self.editor)
        self.bank: Bank | None = None            # read-only mirror of editor.bank
        self.path: Path | None = None            # last loaded/saved file
        self.selected_index: int | None = None   # program slot 1..32 (UI state)
        self._clipboard: JTProgram | None = None
        self._loading_bank = False
        self._syncing = False                    # guard: model->widget->event loop

        self.vars: dict[str, tk.IntVar] = {}
        self.value_vars: dict[str, tk.StringVar] = {}
        self.name_var = tk.StringVar()
        self.slot_var = tk.StringVar(value="P--")
        self.modified_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="Open a JT-4000M bulk .syx file (File ▸ Open Bank)")
        self.developer_var = tk.BooleanVar(value=False)

        self._style()
        self._build()

    # ------------------------------------------------------------------ style
    def _style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background="#202124")
        style.configure("Panel.TFrame", background="#292a2d")
        style.configure("TLabel", background="#202124", foreground="#e7e7e7")
        style.configure("Panel.TLabel", background="#292a2d", foreground="#e7e7e7")
        style.configure("Muted.TLabel", background="#292a2d", foreground="#9aa0a6")
        style.configure("TButton", padding=(9, 5))
        style.configure("TLabelframe", background="#292a2d", foreground="#e7e7e7")
        style.configure("TLabelframe.Label", background="#292a2d", foreground="#f0f0f0")
        style.configure("TEntry", fieldbackground="#17181a", foreground="#eeeeee")
        style.configure("Treeview", background="#17181a", fieldbackground="#17181a",
                        foreground="#e8e8e8", rowheight=20)
        style.configure("Treeview.Heading", background="#3b3d40", foreground="#f0f0f0")

    # ------------------------------------------------------------------- build
    def _build(self) -> None:
        menubar = tk.Menu(self)
        filemenu = tk.Menu(menubar, tearoff=0)
        filemenu.add_command(label="Open Bank…", command=self.open_bank, accelerator="Ctrl+O")
        filemenu.add_command(label="Save Bank", command=self.save_bank, accelerator="Ctrl+S")
        filemenu.add_command(label="Save Bank As…", command=self.save_bank_as)
        filemenu.add_separator()
        filemenu.add_command(label="Export Program as Single .syx…", command=self.export_single)
        filemenu.add_separator()
        filemenu.add_command(label="Reload from Disk", command=self.reload_from_disk)
        filemenu.add_command(label="Exit", command=self.quit_or_ask)
        menubar.add_cascade(label="File", menu=filemenu)
        editmenu = tk.Menu(menubar, tearoff=0)
        editmenu.add_command(label="Undo", command=self.undo, accelerator="Ctrl+Z")
        editmenu.add_command(label="Redo", command=self.redo, accelerator="Ctrl+Y")
        editmenu.add_separator()
        editmenu.add_command(label="Copy Program", command=self.copy_program, accelerator="Ctrl+C")
        editmenu.add_command(label="Paste Program Into Selected Slot", command=self.paste_program, accelerator="Ctrl+V")
        editmenu.add_command(label="Duplicate Program Into Next Slot", command=self.duplicate_program)
        editmenu.add_separator()
        editmenu.add_command(label="Reset Program (Undo All Edits)", command=self.reset_program)
        menubar.add_cascade(label="Edit", menu=editmenu)
        self._edit_menu = editmenu              # direct ref for undo/redo state
        self.config(menu=menubar)
        self.bind("<Control-o>", lambda _e: self.open_bank())
        self.bind("<Control-s>", lambda _e: self.save_bank())
        self.bind("<Control-z>", lambda _e: self.undo())
        self.bind("<Control-y>", lambda _e: self.redo())

        header = tk.Frame(self, bg="#151619", height=56)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(header, text="JT-4000M", bg="#151619", fg="#f2f2f2",
                 font=("TkDefaultFont", 16, "bold")).pack(side="left", padx=16)
        tk.Label(header, text="OFFLINE PRESET EDITOR — no MIDI required", bg="#151619", fg="#8f949b",
                 font=("TkDefaultFont", 9, "bold")).pack(side="left")
        ttk.Checkbutton(header, text="Developer view", variable=self.developer_var,
                        command=self._update_developer).pack(side="right", padx=10)
        tk.Label(header, textvariable=self.modified_var, bg="#151619",
                 fg="#ffb74d", font=("TkDefaultFont", 10, "bold")).pack(side="right", padx=8)

        body = ttk.Panedwindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=8, pady=(4, 8))

        left = ttk.Frame(body, style="Panel.TFrame", padding=8)
        center = ttk.Frame(body, style="Panel.TFrame", padding=8)
        right = ttk.Frame(body, style="Panel.TFrame", padding=8)
        body.add(left, weight=2)
        body.add(center, weight=6)
        body.add(right, weight=4)

        # ---- left: bank list -------------------------------------------
        head = ttk.Frame(left, style="Panel.TFrame")
        head.pack(fill="x")
        ttk.Label(head, text="BANK / PRESETS", style="Panel.TLabel",
                  font=("TkDefaultFont", 10, "bold")).pack(side="left")
        self.count_label = ttk.Label(head, text="", style="Muted.TLabel")
        self.count_label.pack(side="right")
        self.search_var = tk.StringVar()
        search = ttk.Entry(left, textvariable=self.search_var)
        search.pack(fill="x", pady=(7, 4))
        search.bind("<KeyRelease>", lambda _e: self.refresh_list())
        self.listbox = tk.Listbox(left, exportselection=False, bg="#17181a", fg="#e8e8e8",
                                  selectbackground="#4c6ef5", selectforeground="#ffffff",
                                  relief="flat", highlightthickness=0, activestyle="none")
        self.listbox.pack(fill="both", expand=True)
        self.listbox.bind("<<ListboxSelect>>", self._on_select)
        self.listbox.bind("<Double-Button-1>", lambda _e: self.duplicate_program())
        ttk.Label(left, text="Click to open · double-click to duplicate into next slot.",
                  style="Muted.TLabel").pack(anchor="w", pady=(4, 0))

        # ---- center: preset editor ------------------------------------
        bar = tk.Frame(center, bg="#292a2d")
        bar.pack(fill="x", pady=(0, 6))
        ttk.Label(bar, text="PRESET", style="Panel.TLabel").pack(side="left")
        self.name_entry = ttk.Entry(bar, textvariable=self.name_var, width=14, state="disabled")
        self.name_entry.pack(side="left", padx=7)
        self.apply_name_btn = ttk.Button(bar, text="Apply Name", command=self.apply_name, state="disabled")
        self.apply_name_btn.pack(side="left")
        ttk.Button(bar, text="Revert Name", command=self._revert_name).pack(side="left", padx=4)
        self.slot_label = tk.Label(bar, textvariable=self.slot_var, bg="#292a2d", fg="#9aa0a6",
                                   font=("TkDefaultFont", 11, "bold"))
        self.slot_label.pack(side="right", padx=8)

        canvas = tk.Canvas(center, bg="#202124", highlightthickness=0)
        scrollbar = ttk.Scrollbar(center, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.canvas = canvas
        self.controls = ttk.Frame(canvas, style="TFrame")
        self.canvas_window = canvas.create_window((0, 0), window=self.controls, anchor="nw")
        self.controls.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(self.canvas_window, width=e.width))
        for col in range(2):
            self.controls.grid_columnconfigure(col, weight=1)

        self.section_labels: dict[str, tk.Label] = {}
        self.reset_buttons: dict[str, tuple[tk.Button, tk.Label]] = {}
        self._build_sections()

        # ---- right: developer panel ------------------------------------
        nb = ttk.Notebook(right)
        nb.pack(fill="both", expand=True)
        self.dev_tab = ttk.Frame(nb, style="Panel.TFrame")
        self.cmp_tab = ttk.Frame(nb, style="Panel.TFrame")
        self.an_tab = ttk.Frame(nb, style="Panel.TFrame")
        nb.add(self.dev_tab, text="Raw Program")
        nb.add(self.cmp_tab, text="Compare")
        nb.add(self.an_tab, text="Analyze Banks")
        self._build_raw_tab()
        self._build_compare_tab()
        self._build_analysis_tab()

        status = tk.Frame(self, bg="#151619")
        status.pack(fill="x", side="bottom")
        tk.Label(status, textvariable=self.status_var, bg="#151619", fg="#c8ccd0",
                 anchor="w").pack(fill="x", padx=8, pady=3)

    # ------------------------------------------------------------ sections UI
    def _build_sections(self) -> None:
        layout = {"OSCILLATORS": (0, 0), "FILTER": (0, 1), "VCF ENVELOPE": (1, 0),
                  "VCA ENVELOPE": (1, 1), "LFO": (2, 0), "MODULATION": (2, 1)}
        for section in SECTION_ORDER:
            r, c = layout[section]
            box = tk.Frame(self.controls, bg="#292a2d", highlightthickness=1,
                           highlightbackground="#3b3d40")
            box.grid(row=r, column=c, sticky="nsew", padx=5, pady=5)
            self.controls.grid_rowconfigure(r, weight=1)
            title = tk.Label(box, text=section, bg="#292a2d", fg="#f1f1f1",
                              font=("TkDefaultFont", 10, "bold"))
            title.pack(anchor="w", padx=10, pady=(8, 4))
            inner = tk.Frame(box, bg="#292a2d")
            inner.pack(fill="both", expand=True, padx=8, pady=(0, 8))
            for spec in PARAMETERS:
                if spec.section == section and spec.offset is not None:
                    self._parameter_row(inner, spec)
        # CC-only parameters are documented but have no SysEx offset yet.
        unmapped = [s for s in PARAMETERS if s.offset is None]
        if unmapped:
            box = tk.Frame(self.controls, bg="#292a2d", highlightthickness=1,
                           highlightbackground="#3b3d40")
            box.grid(row=3, column=0, columnspan=2, sticky="nsew", padx=5, pady=5)
            tk.Label(box, text="CC ONLY — SysEx offset not established (read-only)",
                     bg="#292a2d", fg="#f1f1f1", font=("TkDefaultFont", 10, "bold")).pack(anchor="w", padx=10, pady=(8, 4))
            inner = tk.Frame(box, bg="#292a2d")
            inner.pack(fill="x", padx=8, pady=(0, 8))
            for spec in unmapped:
                row = tk.Frame(inner, bg="#292a2d")
                row.pack(fill="x")
                tk.Label(row, text=f"{spec.label}: CC {spec.cc}", bg="#292a2d",
                         fg="#9aa0a6", anchor="w").pack(side="left")

    def _parameter_row(self, parent, spec) -> None:
        row = tk.Frame(parent, bg="#292a2d")
        row.pack(fill="x", pady=3)
        label = tk.Label(row, text=_row_label(spec, self.developer_var.get()), bg="#292a2d",
                         fg="#bfc3c8", width=26, anchor="w")
        label.pack(side="left")
        self.section_labels[spec.key] = label
        # Initial value = documented default; it is overwritten from the model
        # as soon as a bank is loaded (_sync_widgets_from_model).
        var = tk.IntVar(value=spec.default)
        self.vars[spec.key] = var
        value = tk.StringVar(value=self._formatted(spec.key, spec.default))
        self.value_vars[spec.key] = value

        if spec.kind == "enum":
            options = enum_options(spec.key)
            if options:
                combo = ttk.Combobox(row, state="readonly", width=16,
                                     values=[name for _v, name in options])
                combo.pack(side="right")
                setattr(self, f"combo_{spec.key}", combo)
                combo.bind("<<ComboboxSelected>>",
                           lambda _e, key=spec.key, w=combo: self._combo_apply(key, w))
            else:
                # No confirmed enum table exists yet (hardware TODO): show the
                # raw value read-only instead of inventing editable options.
                tk.Label(row, text="values not established", bg="#292a2d",
                         fg="#9aa0a6").pack(side="right")
        elif spec.kind == "boolean":
            check = ttk.Checkbutton(row, text="ON", variable=var,
                                    command=lambda key=spec.key: self.apply_parameter(key))
            check.pack(side="right")
        else:
            scale = tk.Scale(row, from_=spec.minimum, to=spec.maximum, orient="horizontal",
                             variable=var, showvalue=False, resolution=1, bg="#292a2d",
                             fg="#d8d8d8", troughcolor="#111214", highlightthickness=0, bd=0,
                             length=150,
                             command=lambda _v, key=spec.key: self._value_preview(key))
            scale.pack(side="left", fill="x", expand=True, padx=5)
            scale.bind("<ButtonRelease-1>", lambda _e, key=spec.key: self.apply_parameter(key))
        val_lbl = tk.Label(row, textvariable=value, bg="#292a2d", fg="#f1f1f1", width=11,
                           anchor="e")
        val_lbl.pack(side="right", padx=(4, 0))
        reset = tk.Button(row, text="D", width=2, relief="flat", bg="#292a2d", fg="#9aa0a6",
                          highlightthickness=0, bd=0,
                          command=lambda key=spec.key: self.reset_one(key))
        reset.pack(side="right", padx=(2, 0))
        self.reset_buttons[spec.key] = (reset, val_lbl)

    def reset_one(self, key: str) -> None:
        """Reset a single parameter to its documented default value."""
        if self.bank is None or self.selected_index is None:
            return
        spec = BY_KEY[key]
        try:
            self._history.push()
            # P1.10: mutation goes through EditorModel (bank ops are
            # byte-preserving and immediate); the GUI never writes raw bytes.
            self.editor.commit()                # fold pending working copy
            self.editor.reset_patch_parameter(self.selected_index, key)
        except Exception as exc:
            self._history.undo()
            messagebox.showerror("Parameter", str(exc))
            self._after_mutation()
            return
        self._after_mutation()
        self.status_var.set(f"P{self.selected_index:02d}  {spec.label} reset to "
                            f"default {display_value(key, spec.default)}")

    # ------------------------------------------------------------- raw table
    def _build_raw_tab(self) -> None:
        cols = ("offset", "hex", "dec", "field")
        self.raw_tree = ttk.Treeview(self.dev_tab, columns=cols, show="headings", height=24)
        widths = {"offset": 70, "hex": 60, "dec": 70, "field": 260}
        for c in cols:
            self.raw_tree.heading(c, text={"offset": "Offset", "hex": "Hex",
                                           "dec": "Decimal", "field": "Field"}[c])
            self.raw_tree.column(c, width=widths[c], anchor="w")
        scroll = ttk.Scrollbar(self.dev_tab, orient="vertical", command=self.raw_tree.yview)
        self.raw_tree.configure(yscrollcommand=scroll.set)
        self.raw_tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

    # ----------------------------------------------------------- compare tab
    def _build_compare_tab(self) -> None:
        top = ttk.Frame(self.cmp_tab, style="Panel.TFrame")
        top.pack(fill="x", pady=4)
        ttk.Label(top, text="A:", style="Panel.TLabel").pack(side="left")
        self.cmp_a = ttk.Combobox(top, state="readonly", width=26, values=[])
        self.cmp_a.pack(side="left", padx=4)
        ttk.Label(top, text="B:", style="Panel.TLabel").pack(side="left", padx=(10, 0))
        self.cmp_b = ttk.Combobox(top, state="readonly", width=26, values=[])
        self.cmp_b.pack(side="left", padx=4)
        ttk.Button(top, text="Compare", command=self.run_compare).pack(side="left", padx=8)
        body = ttk.Frame(self.cmp_tab, style="Panel.TFrame")
        body.pack(fill="both", expand=True)
        cols = ("field", "a", "b", "change")
        self.cmp_tree = ttk.Treeview(body, columns=cols, show="headings", height=20)
        for c, txt, w in (("field", "Parameter", 190), ("a", "Preset A", 90),
                          ("b", "Preset B", 90), ("change", "Change", 170)):
            self.cmp_tree.heading(c, text=txt)
            self.cmp_tree.column(c, width=w, anchor="w")
        scroll = ttk.Scrollbar(body, orient="vertical", command=self.cmp_tree.yview)
        self.cmp_tree.configure(yscrollcommand=scroll.set)
        self.cmp_tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

    def _slot_items(self) -> list[str]:
        if self.bank is None:
            return []
        return [f"{p.index:02d}  {p.name or '<unnamed>'}" for p in self.bank.programs]

    def run_compare(self) -> None:
        """Semantic diff of two programs in the current bank (offline)."""
        if self.bank is None:
            return
        ia, ib = self.cmp_a.current(), self.cmp_b.current()
        if ia < 0 or ib < 0:
            messagebox.showinfo("Compare", "Choose presets A and B first.")
            return
        pa = self.bank.get(ia + 1).to_program()
        pb = self.bank.get(ib + 1).to_program()
        sa = SysExFile(b"", "bulk", b"", (pa,), 0, 0, True)
        sb = SysExFile(b"", "bulk", b"", (pb,), 0, 0, True)
        self.cmp_tree.delete(*self.cmp_tree.get_children())
        diffs = semantic_diff(sa, sb)
        if not diffs:
            self.cmp_tree.insert("", "end", values=("No differences", "", "", ""))
            return
        for d in diffs:
            a_disp = semantic_value(d.relative_offset, d.old)
            b_disp = semantic_value(d.relative_offset, d.new)
            self.cmp_tree.insert("", "end", values=(d.field, a_disp, b_disp, format_change(d)))
        self.status_var.set(f"Compare: {len(diffs)} differing fields (semantic diff).")

    # ---------------------------------------------------------- analysis tab
    def _build_analysis_tab(self) -> None:
        top = ttk.Frame(self.an_tab, style="Panel.TFrame")
        top.pack(fill="x", pady=4)
        btns = ttk.Frame(top, style="Panel.TFrame")
        btns.pack(fill="x")
        ttk.Button(btns, text="Add Bank Files…", command=self.analysis_add).pack(side="left")
        ttk.Button(btns, text="Run Cross-Bank Analysis", command=self.analysis_run).pack(side="left", padx=6)
        ttk.Button(btns, text="Clear", command=self.analysis_clear).pack(side="left")
        self.an_files: list[str] = []
        self.an_list = tk.Listbox(top, height=3, bg="#17181a", fg="#e8e8e8",
                                  selectbackground="#4c525a", relief="flat", highlightthickness=0)
        self.an_list.pack(fill="x", pady=4)
        body = ttk.Frame(self.an_tab, style="Panel.TFrame")
        body.pack(fill="both", expand=True)
        cols = ("offset", "field", "kind", "unique", "min", "max")
        self.an_tree = ttk.Treeview(body, columns=cols, show="headings", height=16)
        for c, txt, w in (("offset", "Offset", 60), ("field", "Field", 170),
                          ("kind", "Kind", 130), ("unique", "Unique values", 210),
                          ("min", "Min", 50), ("max", "Max", 50)):
            self.an_tree.heading(c, text=txt)
            self.an_tree.column(c, width=w, anchor="w")
        scroll = ttk.Scrollbar(body, orient="vertical", command=self.an_tree.yview)
        self.an_tree.configure(yscrollcommand=scroll.set)
        self.an_tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

    def analysis_clear(self) -> None:
        self.an_files.clear()
        self.an_list.delete(0, "end")
        self.an_tree.delete(*self.an_tree.get_children())

    def analysis_add(self) -> None:
        paths = filedialog.askopenfilenames(filetypes=[("JT-4000M SysEx", "*.syx"),
                                                       ("All files", "*.*")])
        for p in paths:
            try:
                s = parse_file(p)
            except Exception as exc:
                messagebox.showerror("Analysis", f"{Path(p).name}: {exc}")
                continue
            if s.mode != "bulk":
                messagebox.showwarning("Analysis", f"{Path(p).name} is not a bulk bank; skipped.")
                continue
            self.an_files.append(p)
            self.an_list.insert("end", Path(p).name)

    def analysis_run(self) -> None:
        if not self.an_files:
            messagebox.showinfo("Analyze banks", "Add at least one bulk bank first.")
            return
        try:
            banks = [(Path(p).name, parse_file(p)) for p in self.an_files]
            rows = cross_bank(banks)
        except Exception as exc:
            messagebox.showerror("Analysis failed", str(exc))
            return
        self.an_tree.delete(*self.an_tree.get_children())
        for r in rows:
            uniq = " ".join(f"{v:02X}" for v in r["unique_values"])
            if len(uniq) > 60:
                uniq = uniq[:57] + "…"
            self.an_tree.insert("", "end", values=(f"0x{r['offset']:02X}", r["field"],
                                                   r["kind"], uniq,
                                                   f"0x{r['min']:02X}", f"0x{r['max']:02X}"))
        self.status_var.set(f"Cross-bank analysis: {len(rows)} offsets across {len(banks)} bank(s).")

    # --------------------------------------------------------------- loading
    def open_bank(self) -> None:
        path = filedialog.askopenfilename(title="Open bulk .syx bank",
                                          filetypes=[("JT-4000M SysEx", "*.syx"), ("All files", "*.*")])
        if path:
            self.load_path(path)

    def load_path(self, path: str | Path) -> None:
        """Load a bank (bulk, or single placed into its slot) from disk.

        P1.10: parsing lives in the SYX layer; EditorModel.load_bank is the
        only entry point the GUI uses.  The GUI never touches raw bytes.
        """
        try:
            syx = parse_file(path)          # status info only (checksum display)
            self.editor.load_bank(path)     # model entry point
        except Exception as exc:
            messagebox.showerror("Open failed", str(exc))
            return
        self.bank = self.editor.bank        # read-only mirror for diagnostics
        self.path = Path(path)
        self._history.clear()               # fresh history per loaded bank
        self._loading_bank = True
        items = self._slot_items()
        self.cmp_a["values"] = items
        self.cmp_b["values"] = items
        self.cmp_a.current(0)
        self.cmp_b.current(min(1, max(0, len(items) - 1)))
        self.search_var.set("")
        self.refresh_list()
        self._loading_bank = False
        self.select_program(1)
        self._update_modified()               # CLEAN: baseline == loaded bank
        where = "" if syx.mode == "bulk" else f" (placed in slot {syx.programs[0].index:02d})"
        chk = "OK" if syx.checksum_ok else f"BAD (expected 0x{syx.checksum_expected:02X})"
        self.status_var.set(f"Loaded {self.path.name} — {len(self.bank.programs)} programs{where}, checksum {chk}")

    def _visible_programs(self) -> list[JTProgram]:
        needle = self.search_var.get().strip().lower()
        out = []
        for p in self.bank.programs:
            text = f"{p.index:02d}  {p.name or '<unnamed>'}"
            if not needle or needle in text.lower():
                out.append(p)
        return out

    def refresh_list(self) -> None:
        if self.bank is None:
            return
        visible = self._visible_programs()
        self.listbox.delete(0, "end")
        for p in visible:
            self.listbox.insert("end", f"{p.index:02d}  {p.name or '<unnamed>'}")
        self.count_label.configure(text=f"{len(visible)}/{len(self.bank.programs)}")
        self._highlight_selection()

    def _highlight_selection(self) -> None:
        """Keep the listbox selection in sync with self.selected_index."""
        if self.bank is None:
            return
        for pos, p in enumerate(self._visible_programs()):
            if p.index == self.selected_index:
                self.listbox.selection_set(pos)
                self.listbox.see(pos)
                return
        if self.listbox.size():
            self.listbox.selection_set(0)

    def _on_select(self, _event=None) -> None:
        if self._loading_bank:
            return
        sel = self.listbox.curselection()
        if not sel:
            return
        visible = self._visible_programs()
        if sel[0] < len(visible):
            self.select_program(visible[sel[0]].index)

    def select_program(self, index: int) -> None:
        if self.bank is None or not 1 <= index <= 32:
            return
        # Fold any pending uncommitted edit into the bank BEFORE switching
        # slots, so a working copy can never be silently lost or applied to
        # another patch (P1.10 §8: selection changes go through the model).
        self.editor.commit()
        self.editor.select_patch(index)
        self.selected_index = index
        self._sync_widgets_from_model()
        self._highlight_selection()
        self._update_developer()

    # ----------------------------------------------------- model -> widgets
    def _sync_widgets_from_model(self) -> None:
        if self.bank is None or self.selected_index is None:
            return
        self._syncing = True
        patch = self.editor.get_patch(self.selected_index)   # model read API
        p = patch.program
        self.slot_var.set(f"P{p.index:02d}")
        self.name_var.set(patch.name)
        for spec in PARAMETERS:
            if spec.offset is None or spec.key not in self.vars:
                continue
            raw = patch.get_raw(spec.key)     # value via ParameterValue layer
            self.vars[spec.key].set(raw)
            self.value_vars[spec.key].set(self._formatted(spec.key, raw))
            if spec.kind == "enum" and hasattr(self, f"combo_{spec.key}"):
                combo = getattr(self, f"combo_{spec.key}")
                labels = [name for _v, name in enum_options(spec.key)]
                text = self._combo_text(spec.key, raw)
                # A raw value with no confirmed label (e.g. loaded from a
                # third-party bank) must not snap to a wrong option and must
                # not raise: ttk.Combobox.current(-1) is invalid, so we set
                # the text directly. The numeric label next to the control
                # still shows "Unknown (0xNN)".
                if text in labels:
                    combo.set(text)
                else:
                    combo.set(f"Unknown ({raw:#04x})")
        enabled = self.bank is not None
        self.name_entry.configure(state="normal" if enabled else "disabled")
        self.apply_name_btn.configure(state="normal" if enabled else "disabled")
        self._syncing = False

    def _combo_text(self, key: str, raw: int) -> str:
        return dict(enum_options(key)).get(raw, "")

    def _formatted(self, key: str, raw: int) -> str:
        """Value string; developer mode appends the raw byte."""
        disp = display_value(key, raw)
        if self.developer_var.get():
            disp = f"{disp} ({raw})"
        # During initial widget construction value_vars may not contain the
        # key yet; callers set the StringVar right afterwards.
        lbl = self.value_vars.get(key)
        if lbl is not None:
            lbl.set(disp)
            # Widen the shared label so long values like "OFF (Unknown (0x3F))"
            # are never visually truncated.
            widget = self.reset_buttons.get(key, (None, None))[1]
            if widget is not None:
                try:
                    widget.configure(width=max(11, len(disp)))
                except tk.TclError:
                    pass
        return disp

    # ----------------------------------------------------- widgets -> model
    # ------------------------------------------------------------- refresh
    def _after_mutation(self) -> None:
        """P1.10 single synchronization point: model -> GUI projection.

        EditorModel/EditorHistory are the ONLY source of truth. This method
        never mutates anything: it re-reads the (immutable) bank mirror from
        the model and refreshes every dependent widget — patch list, name,
        parameter widgets, dirty indicator, undo/redo availability and the
        read-only developer/diagnostic views.

        Exception: if the GUI mirror `self.bank` was replaced directly with a
        *different* Bank instance (a diagnostic/test injection at the domain
        layer), we adopt that instance into the model instead of discarding
        it — the model remains the single source of truth afterwards.
        """
        try:
            model_bank = self.editor.bank       # raises if nothing loaded
        except RuntimeError:
            model_bank = None
        if (self.bank is not None and model_bank is not None
                and self.bank is not model_bank):
            # The mirror differs from the model.  Normally that means the
            # GUI/test replaced `app.bank` with a diagnostic Bank instance
            # (injection) — adopt it into the model so the model stays the
            # single source of truth afterwards.  But when the mirror is a
            # STALE reference to an older model bank (immutable copy-on-write
            # banks are superseded by every commit), adopting it would roll
            # the model back and silently discard the just-applied edit.
            # Detect staleness via serialization identity instead.
            stale = self.bank.to_sysex() == model_bank.to_sysex()
            if not stale:
                self.editor._bank = self.bank   # adopt injected mirror
                self.editor._working = None
                self.editor._dirty = self.editor._session_modified()
                model_bank = self.bank
        if model_bank is not None:
            self.bank = model_bank              # refresh mirror from model
        self.refresh_list()
        self._sync_widgets_from_model()
        self._update_modified()
        self._update_developer()

    def _update_history_buttons(self) -> None:
        """Reflect EditorHistory state in the Edit menu (single source:
        history.can_undo / can_redo — no GUI-side stack)."""
        # entrycget(...,"menu") returns a Tcl path string that includes the
        # "(...)" type tuple — nametowidget cannot parse it.  Keep a direct
        # reference to the Edit menu instead (single source of truth for
        # enabled state remains history.can_undo / can_redo).
        m = getattr(self, "_edit_menu", None)
        if m is None:
            return                              # menu not built yet (tests)
        try:
            m.entryconfigure(0, state="normal" if self._history.can_undo else "disabled")
            m.entryconfigure(1, state="normal" if self._history.can_redo else "disabled")
        except tk.TclError:
            pass

    def apply_parameter(self, key: str) -> None:
        if self._syncing or self.bank is None or self.selected_index is None:
            return
        spec = BY_KEY[key]
        raw = int(self.vars[key].get())
        if spec.kind == "boolean":
            raw = 127 if raw else 0
        try:
            self._history.push()                # record pre-mutation snapshot
            if self.editor._bank is None:
                raise RuntimeError("No bank loaded.")
            self.editor.commit()                # fold any pending working copy
            self.editor.select_patch(self.selected_index)
            self.editor.set_parameter(key, raw)
            self.editor.commit()                # write into the bank via model
        except Exception as exc:
            messagebox.showerror("Parameter", str(exc))
            self._history.undo()                # revert to pre-mutation state
            self._after_mutation()
            return
        self._after_mutation()
        self.value_vars[key].set(self._formatted(key, raw))
        self.status_var.set(f"P{self.selected_index:02d}  {spec.label} = {display_value(key, raw)}"
                            f"  [raw {raw}, offset 0x{spec.offset:02X}]")

    def _value_preview(self, key: str) -> None:
        if self._syncing:
            return
        self.value_vars[key].set(self._formatted(key, int(self.vars[key].get())))

    def _combo_apply(self, key: str, combo) -> None:
        if self._syncing:
            return
        value = enum_options(key)[combo.current()][0]
        self.vars[key].set(value)
        self.apply_parameter(key)

    def apply_name(self) -> None:
        if self.bank is None or self.selected_index is None:
            return
        try:
            self._history.push()
            self.editor.commit()                # fold pending working copy
            self.editor.select_patch(self.selected_index)
            self.editor.rename(self.name_var.get())
            self.editor.commit()
        except Exception as exc:
            messagebox.showerror("Patch name", str(exc))
            self._history.undo()
            self._after_mutation()
            return
        self._after_mutation()
        self.status_var.set(f"Renamed P{self.selected_index:02d} → "
                            f"{self.editor.get_patch(self.selected_index).name!r}")

    def _revert_name(self) -> None:
        if self.bank is not None and self.selected_index is not None:
            self.name_var.set(self.editor.get_patch(self.selected_index).name)

    # -------------------------------------------------------- modified state
    def _update_modified(self) -> None:
        """P1.10 §10/§12: dirty indicator is a PROJECTION of the model —
        the GUI never keeps its own dirty flag."""
        dirty = bool(self.editor.is_dirty()) if self.bank is not None else False
        self.modified_var.set("Modified *" if dirty else "")
        self._update_history_buttons()

    def reload_from_disk(self) -> None:
        if self.path is None:
            messagebox.showinfo("Reload", "No file loaded yet.")
            return
        self.load_path(self.path)

    # --------------------------------------------------------- save/export
    def save_bank(self) -> None:
        if self.bank is None:
            messagebox.showinfo("Save", "Open a bank first.")
            return
        if self.path is None:
            self.save_bank_as()
            return
        self._write(self.path)

    def save_bank_as(self) -> None:
        if self.bank is None:
            messagebox.showinfo("Save", "Open a bank first.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".syx",
                                            filetypes=[("JT-4000M SysEx", "*.syx")])
        if path:
            self._write(Path(path))

    def _write(self, path: Path) -> None:
        try:
            # P1.10 §7/§14: the GUI never serializes and never computes a
            # checksum — EditorModel.save() delegates to the existing
            # byte-preserving Bank.save(), which re-parses the payload and
            # rebuilds the checksum in the serializer layer.  On failure the
            # model keeps its baseline and stays MODIFIED.
            self.editor.commit()                # fold pending working copy
            self.editor.save(path)
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc))
            self._update_modified()             # dirty semantics unchanged
            return
        self.path = Path(path)
        self._after_mutation()                  # is_dirty() == False now
        saved = self.path.read_bytes() if self.path.exists() else b""
        chk = f"0x{saved[-2]:02X}" if saved else "n/a"
        self.status_var.set(f"Saved {self.path.name} — checksum rebuilt ({chk})")

    def export_single(self) -> None:
        if self.bank is None or self.selected_index is None:
            messagebox.showinfo("Export", "Select a program first.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".syx",
                                            filetypes=[("JT-4000M SysEx", "*.syx")])
        if not path:
            return
        try:
            prog = self.bank.get(self.selected_index)
            Path(path).write_bytes(program_to_single(prog))
        except Exception as exc:
            messagebox.showerror("Export failed", str(exc))
            return
        self.status_var.set(f"Exported P{self.selected_index:02d} as single-dump {Path(path).name}")

    # ------------------------------------------------------ copy/paste/undo
    def copy_program(self) -> None:
        if self.bank is None or self.selected_index is None:
            return
        # Copy is a pure READ through the model API (P1.10 §6).
        self._clipboard = self.editor.get_patch(self.selected_index).program
        self.status_var.set(f"Copied P{self.selected_index:02d} ({self._clipboard.name!r}) to clipboard.")

    def paste_program(self) -> None:
        if self._clipboard is None:
            messagebox.showinfo("Paste", "Copy a program first (Edit ▸ Copy Program).")
            return
        if self.bank is None or self.selected_index is None:
            return
        self._history.push()
        try:
            self.editor.commit()                # fold pending working copy
            self.editor.replace_patch(self.selected_index, self._clipboard)
        except Exception as exc:
            self._history.undo()
            messagebox.showerror("Paste failed", str(exc))
            self._after_mutation()
            return
        self._after_mutation()
        self.status_var.set(f"Pasted into P{self.selected_index:02d}.")

    def duplicate_program(self) -> None:
        if self.bank is None or self.selected_index is None:
            return
        target = self.selected_index % 32 + 1
        self._history.push()
        try:
            if self.editor._bank is None:
                raise RuntimeError("No bank loaded.")
            self.editor.commit()
            self.editor.duplicate_patch(self.selected_index, target)
        except Exception as exc:
            self._history.undo()
            messagebox.showerror("Duplicate failed", str(exc))
            self._after_mutation()
            return
        self._after_mutation()
        self.status_var.set(f"Duplicated P{self.selected_index:02d} → P{target:02d}.")

    def reset_program(self) -> None:
        if self.path is None or self.bank is None or self.selected_index is None:
            return
        try:
            original = Bank.load(str(self.path)).get(self.selected_index)
        except Exception as exc:
            messagebox.showerror("Reset", str(exc))
            return
        self._history.push()
        if self.editor._bank is not None:
            self.editor.commit()                # drop uncommitted edits
            self.editor.revert()
            self.editor.replace_patch(self.selected_index, original)
        else:
            self.bank = self.bank.replace(self.selected_index, original)
        self._after_mutation()
        self.status_var.set(f"Reset P{self.selected_index:02d} from {self.path.name}.")

    def undo(self) -> None:
        """P1.10 §9/§13: delegate to the existing EditorHistory — no GUI-side
        undo stack exists anymore."""
        if self._history.undo():
            self.selected_index = self.editor.selected
            self._after_mutation()

    def redo(self) -> None:
        if self._history.redo():
            self.selected_index = self.editor.selected
            self._after_mutation()

    # ------------------------------------------------------- developer views
    def _update_developer(self) -> None:
        for key, label in self.section_labels.items():
            label.configure(text=_row_label(BY_KEY[key], self.developer_var.get()))
        self._refresh_value_labels()
        self._refresh_raw_table()

    def _refresh_value_labels(self) -> None:
        if self.bank is None or self.selected_index is None:
            return
        patch = self.editor.get_patch(self.selected_index)
        for spec in PARAMETERS:
            if spec.offset is None or spec.key not in self.value_vars:
                continue
            self.value_vars[spec.key].set(self._formatted(spec.key, patch.get_raw(spec.key)))

    def _refresh_raw_table(self) -> None:
        """Raw Program table — uses syx.field_name(); mapping lives in one place."""
        self.raw_tree.delete(*self.raw_tree.get_children())
        if self.bank is None or self.selected_index is None:
            return
        data = self.bank.get(self.selected_index).data
        for off, val in enumerate(data):
            name = field_name(off)
            if name.startswith("Byte 0x"):
                name = "Unknown / Reserved"
            if off == RING_MOD_CANDIDATE_OFFSET:
                # candidate only — correlation with Ring Mod; needs hardware check
                name = "Candidate: Ring Mod level? (needs hardware verification)"
            self.raw_tree.insert("", "end", values=(f"0x{off:02X}", f"{val:02X}", val, name))

    # ---------------------------------------------------------------- misc
    def quit_or_ask(self) -> None:
        if self.bank is not None and self.modified_var.get():
            if not messagebox.askyesno("Unsaved changes", "Discard unsaved changes and quit?"):
                return
        self.destroy()


def main(argv: list[str] | None = None) -> None:
    app = Editor()
    args = list(argv or [])
    if args:  # optional: open a bank straight from the command line
        app.load_path(args[0])
    app.mainloop()
