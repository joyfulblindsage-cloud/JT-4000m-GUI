from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path

from .model import PARAMETERS, WAVE_NAMES
from .patch import Bank


SECTIONS = {
    "OSC 1": ["osc1_wave", "osc1_pwm_fm", "osc1_coarse", "osc1_fine"],
    "OSC 2": ["osc2_wave", "osc2_pwm", "osc2_coarse", "osc2_fine"],
    "MIX / PORTAMENTO": ["osc_balance", "portamento_mode"],
    "FILTER": ["filter_cutoff", "filter_resonance", "filter_env_amount"],
    "FILTER ENV": ["vcf_attack", "vcf_decay", "vcf_sustain", "vcf_release"],
    "AMP ENV": ["vca_attack", "vca_decay", "vca_sustain", "vca_release"],
    "LFO 1": ["lfo1_wave", "lfo1_rate", "lfo1_amount", "lfo1_destination"],
    "LFO 2": ["lfo2_wave", "lfo2_rate", "lfo2_amount"],
    "RING MOD": ["ring_mod_toggle", "ring_mod_amount"],
}


def spec_by_key(key: str):
    return next(s for s in PARAMETERS if s.key == key)


class Editor(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("JT-4000M Editor")
        self.geometry("1280x820")
        self.minsize(1050, 700)
        self.configure(bg="#202124")
        self.bank: Bank | None = None
        self.path: Path | None = None
        self.vars: dict[str, tk.IntVar] = {}
        self.name_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Open a JT-4000M bulk .syx file")
        self.value_vars: dict[str, tk.StringVar] = {}
        self._building = False
        self._build()

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
        style.configure("Section.TLabel", background="#292a2d", foreground="#f0f0f0", font=("TkDefaultFont", 10, "bold"))
        style.configure("TButton", padding=(9, 5))
        style.configure("TLabelframe", background="#292a2d", foreground="#e7e7e7")
        style.configure("TLabelframe.Label", background="#292a2d", foreground="#e7e7e7")
        style.configure("TEntry", fieldbackground="#17181a", foreground="#eeeeee")
        style.configure("TSpinbox", fieldbackground="#17181a", foreground="#eeeeee")

    def _build(self) -> None:
        self._style()
        header = tk.Frame(self, bg="#151619", height=62)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(header, text="JT-4000M", bg="#151619", fg="#f2f2f2",
                 font=("TkDefaultFont", 17, "bold")).pack(side="left", padx=16)
        tk.Label(header, text="SERUM-STYLE EDITOR", bg="#151619", fg="#8f949b",
                 font=("TkDefaultFont", 9, "bold")).pack(side="left", padx=2)
        ttk.Button(header, text="Open Bank…", command=self.open_bank).pack(side="right", padx=6)
        ttk.Button(header, text="Save Bank As…", command=self.save_bank).pack(side="right", padx=6)

        body = ttk.Panedwindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=8, pady=8)
        left = ttk.Frame(body, style="Panel.TFrame", padding=8)
        center = ttk.Frame(body, style="Panel.TFrame", padding=8)
        body.add(left, weight=1)
        body.add(center, weight=5)

        ttk.Label(left, text="PATCH LIBRARY", style="Panel.TLabel", font=("TkDefaultFont", 10, "bold")).pack(anchor="w")
        self.search_var = tk.StringVar()
        search = ttk.Entry(left, textvariable=self.search_var)
        search.pack(fill="x", pady=(7, 6))
        search.bind("<KeyRelease>", lambda _e: self.refresh_list())
        self.listbox = tk.Listbox(left, exportselection=False, bg="#17181a", fg="#e8e8e8",
                                  selectbackground="#4c525a", selectforeground="#ffffff",
                                  relief="flat", highlightthickness=0)
        self.listbox.pack(fill="both", expand=True)
        self.listbox.bind("<<ListboxSelect>>", self.select_patch)

        self._build_header(center)
        self._build_editor(center)
        ttk.Label(self, textvariable=self.status_var, relief="sunken", anchor="w").pack(fill="x", side="bottom")

    def _build_header(self, parent) -> None:
        bar = tk.Frame(parent, bg="#292a2d")
        bar.pack(fill="x", pady=(0, 8))
        ttk.Label(bar, text="PATCH", style="Panel.TLabel").pack(side="left")
        self.name_entry = ttk.Entry(bar, textvariable=self.name_var, width=14)
        self.name_entry.pack(side="left", padx=7)
        ttk.Button(bar, text="Apply", command=self.apply_name).pack(side="left")
        self.slot_label = tk.Label(bar, text="P--", bg="#292a2d", fg="#9aa0a6", font=("TkDefaultFont", 10, "bold"))
        self.slot_label.pack(side="right", padx=8)

    def _build_editor(self, parent) -> None:
        canvas = tk.Canvas(parent, bg="#202124", highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.canvas = canvas
        self.controls = ttk.Frame(canvas, style="TFrame")
        self.canvas_window = canvas.create_window((0, 0), window=self.controls, anchor="nw")
        self.controls.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(self.canvas_window, width=e.width))

        for row in range(3):
            self.controls.grid_rowconfigure(row, weight=1)
        for col in range(3):
            self.controls.grid_columnconfigure(col, weight=1)

        order = [
            ("OSC 1", 0, 0), ("OSC 2", 0, 1), ("FILTER", 0, 2),
            ("FILTER ENV", 1, 0), ("AMP ENV", 1, 1), ("LFO 1", 1, 2),
            ("LFO 2", 2, 0), ("RING MOD", 2, 1), ("MIX / PORTAMENTO", 2, 2),
        ]
        for section, r, c in order:
            self._section(self.controls, section, r, c)

    def _section(self, parent, title: str, row: int, col: int) -> None:
        box = tk.Frame(parent, bg="#292a2d", highlightthickness=1, highlightbackground="#3b3d40")
        box.grid(row=row, column=col, sticky="nsew", padx=5, pady=5)
        tk.Label(box, text=title, bg="#292a2d", fg="#f1f1f1", font=("TkDefaultFont", 10, "bold")).pack(anchor="w", padx=10, pady=(8, 5))
        inner = tk.Frame(box, bg="#292a2d")
        inner.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        for key in SECTIONS[title]:
            spec = spec_by_key(key)
            self._parameter_row(inner, spec)

    def _parameter_row(self, parent, spec) -> None:
        row = tk.Frame(parent, bg="#292a2d")
        row.pack(fill="x", pady=3)
        label = tk.Label(row, text=spec.label, bg="#292a2d", fg="#bfc3c8", width=19, anchor="w")
        label.pack(side="left")
        var = tk.IntVar(value=0)
        self.vars[spec.key] = var
        value = tk.StringVar(value="0")
        self.value_vars[spec.key] = value
        if spec.kind == "enum":
            names = WAVE_NAMES if "wave" in spec.key else None
            values = list(range(spec.minimum, spec.maximum + 1))
            combo = ttk.Combobox(row, state="readonly", width=11,
                                 values=[names.get(v, str(v)) if names else str(v) for v in values])
            combo.pack(side="right")
            combo.bind("<<ComboboxSelected>>", lambda _e, key=spec.key, w=combo: self._combo_apply(key, w))
            setattr(self, f"combo_{spec.key}", combo)
        elif spec.kind == "bool":
            check = ttk.Checkbutton(row, variable=var, command=lambda key=spec.key: self.apply_parameter(key))
            check.pack(side="right")
        else:
            scale = tk.Scale(row, from_=spec.minimum, to=spec.maximum, orient="horizontal",
                             variable=var, showvalue=False, resolution=1, bg="#292a2d", fg="#d8d8d8",
                             troughcolor="#111214", highlightthickness=0, bd=0,
                             command=lambda _v, key=spec.key: self._value_preview(key))
            scale.pack(side="left", fill="x", expand=True, padx=5)
            scale.bind("<ButtonRelease-1>", lambda _e, key=spec.key: self.apply_parameter(key))
        tk.Label(row, textvariable=value, bg="#292a2d", fg="#f1f1f1", width=7, anchor="e").pack(side="right", padx=(4, 0))

    def _selected(self):
        if self.bank is None:
            return None
        sel = self.listbox.curselection()
        return None if not sel else self.bank.get(sel[0] + 1)

    def refresh_list(self) -> None:
        if self.bank is None:
            return
        needle = self.search_var.get().strip().lower()
        current = self.listbox.curselection()
        selected_index = current[0] if current else 0
        self.listbox.delete(0, "end")
        for p in self.bank.programs:
            text = f"{p.index:02d}  {p.name or '<unnamed>'}"
            if not needle or needle in text.lower():
                self.listbox.insert("end", text)
        if self.listbox.size():
            self.listbox.selection_set(min(selected_index, self.listbox.size() - 1))

    def open_bank(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("JT-4000M SysEx", "*.syx"), ("All files", "*.*")])
        if not path:
            return
        try:
            self.bank = Bank.load(path)
        except Exception as exc:
            messagebox.showerror("Open failed", str(exc))
            return
        self.path = Path(path)
        self.search_var.set("")
        self.refresh_list()
        self.listbox.selection_set(0)
        self.listbox.event_generate("<<ListboxSelect>>")
        self.status_var.set(f"Loaded {self.path.name} — 32 programs")

    def select_patch(self, _event=None) -> None:
        p = self._selected()
        if p is None:
            return
        self._building = True
        self.slot_label.configure(text=f"P{p.index:02d}")
        self.name_var.set(p.name)
        for spec in PARAMETERS:
            if spec.offset is None or spec.key not in self.vars:
                continue
            raw = p.data[spec.offset]
            self.vars[spec.key].set(raw)
            self.value_vars[spec.key].set(self._display_value(spec, raw))
            if spec.kind == "enum" and hasattr(self, f"combo_{spec.key}"):
                combo = getattr(self, f"combo_{spec.key}")
                combo.current(max(0, min(raw - spec.minimum, len(combo["values"]) - 1)))
        self._building = False

    def _display_value(self, spec, raw: int) -> str:
        if spec.kind == "bool":
            return "ON" if raw else "OFF"
        if spec.kind == "enum" and "wave" in spec.key:
            return WAVE_NAMES.get(raw, str(raw))
        return str(raw)

    def _value_preview(self, key: str) -> None:
        if self._building:
            return
        spec = spec_by_key(key)
        self.value_vars[key].set(self._display_value(spec, int(self.vars[key].get())))

    def _combo_apply(self, key: str, combo) -> None:
        if self._building:
            return
        self.vars[key].set(spec_by_key(key).minimum + combo.current())
        self.apply_parameter(key)

    def apply_parameter(self, key: str) -> None:
        if self.bank is None:
            return
        sel = self.listbox.curselection()
        if not sel:
            return
        index = sel[0] + 1
        try:
            value = int(self.vars[key].get())
            self.bank = self.bank.set_parameter(index, key, value)
            spec = spec_by_key(key)
            self.value_vars[key].set(self._display_value(spec, value))
            self.status_var.set(f"P{index:02d}  {spec.label} = {self.value_vars[key].get()}")
        except Exception as exc:
            messagebox.showerror("Parameter", str(exc))
            self.select_patch()

    def apply_name(self) -> None:
        if self.bank is None:
            return
        sel = self.listbox.curselection()
        if not sel:
            return
        index = sel[0] + 1
        try:
            self.bank = self.bank.set_name(index, self.name_var.get())
            self.refresh_list()
            self.listbox.selection_set(sel[0])
            self.status_var.set(f"Renamed P{index:02d}")
        except Exception as exc:
            messagebox.showerror("Patch name", str(exc))

    def save_bank(self) -> None:
        if self.bank is None:
            messagebox.showinfo("Save", "Open a bank first.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".syx", filetypes=[("JT-4000M SysEx", "*.syx")])
        if not path:
            return
        try:
            Path(path).write_bytes(self.bank.to_sysex())
            self.status_var.set(f"Saved {Path(path).name} — checksum rebuilt")
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc))


def main() -> None:
    Editor().mainloop()
