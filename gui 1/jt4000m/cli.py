from __future__ import annotations
import argparse, csv, json
from pathlib import Path
from .syx import parse_file, semantic_value, field_name
from .diff import raw_diff, semantic_diff, format_change
from .analyzer import cross_bank
from .parameter_map import rows as parameter_rows, write_csv as write_parameter_csv, write_json as write_parameter_json


def cmd_inspect(path):
    s = parse_file(path)
    print(f"mode: {s.mode}\nprograms: {len(s.programs)}")
    if s.mode == 'single':
        print(f"checksum: 0x{s.checksum_value:02X} ({'OK' if s.checksum_ok else 'BAD'})")
    else:
        print(f"checksum: 0x{s.checksum_value:02X} ({'OK' if s.checksum_ok else 'BAD'}, expected 0x{s.checksum_expected:02X})")
    for p in s.programs:
        print(f"{p.index:02}: {p.name!r}")


def cmd_program(path, n):
    s = parse_file(path)
    if not 1 <= n <= len(s.programs):
        raise ValueError('Program out of range')
    p = s.programs[n - 1]
    print(f"Program {p.index:02}\nName: {p.name!r}\n\nOffset  Hex  Field\n------  ---  ------------------------")
    for i, v in enumerate(p.data):
        print(f"0x{i:02X}    {v:02X}   {field_name(i)}")


def print_diff(ds, semantic=True):
    if not ds:
        print('No differences.')
        return
    current = None
    for d in ds:
        if semantic and d.program != current:
            current = d.program
            print(f"\nProgram {current:02}\n{'-' * 40}")
        if semantic:
            print(f"{d.field:24}: {format_change(d)}")
        else:
            print(f"0x{d.absolute_offset:04X}  P{d.program:02}  +0x{d.relative_offset:02X}  {d.old:02X} -> {d.new:02X}  {d.field}")


def _fmt_values(values):
    return ' '.join(f'{v:02X}' for v in values)


def _fmt_frequency(freq):
    return ' '.join(f'{v:02X}:{n}' for v, n in sorted(freq.items()))


def _fmt_semantic_values(offset, values):
    return ' | '.join(f'{v:02X}={semantic_value(offset, v)}' for v in values)


def cmd_cross(paths, out=None, json_out=None):
    banks = [(Path(p).name, parse_file(p)) for p in paths]
    rows = cross_bank(banks)

    if out:
        with open(out, 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            header = [
                'offset', 'field', 'kind', 'unique_count', 'unique_values',
                'min', 'max', 'frequency',
            ]
            for name, _ in banks:
                header += [f'{name} unique_values', f'{name} frequency', f'{name} min', f'{name} max']
            w.writerow(header)
            for r in rows:
                row = [
                    f"0x{r['offset']:02X}", r['field'], r['kind'], r['unique_count'],
                    _fmt_values(r['unique_values']), f"0x{r['min']:02X}", f"0x{r['max']:02X}",
                    _fmt_frequency(r['frequency']),
                ]
                for b in r['banks']:
                    row += [
                        _fmt_values(b['unique_values']),
                        _fmt_frequency(b['frequency']),
                        f"0x{b['min']:02X}", f"0x{b['max']:02X}",
                    ]
                w.writerow(row)
        print(f"Wrote {out}")

    if json_out:
        # JSON-friendly copy; tuples are converted recursively by json.dump's
        # default handling only if explicitly converted, so build it here.
        def clean(x):
            if isinstance(x, dict):
                return {k: clean(v) for k, v in x.items()}
            if isinstance(x, tuple):
                return [clean(v) for v in x]
            if isinstance(x, list):
                return [clean(v) for v in x]
            return x
        with open(json_out, 'w', encoding='utf-8') as f:
            json.dump(clean(rows), f, ensure_ascii=False, indent=2)
        print(f"Wrote {json_out}")

    if out or json_out:
        return

    print(f"{'Offset':<8} {'Field':<28} {'Type':<18} {'N':>3} {'Min':>5} {'Max':>5}  Values / frequencies")
    print('-' * 110)
    for r in rows:
        values = _fmt_semantic_values(r['offset'], r['unique_values'])
        freq = _fmt_frequency(r['frequency'])
        print(f"0x{r['offset']:02X}    {r['field']:<28} {r['kind']:<18} {r['unique_count']:>3}  {r['min']:02X}    {r['max']:02X}    {values}")
        print(f"{'':<8} {'':<28} {'frequency':<18} {'':>3}  {'':<5} {'':<5}  {freq}")


def cmd_parameter_map(out=None, json_out=None):
    rows = parameter_rows()
    if out:
        write_parameter_csv(out)
        print(f"Wrote {out}")
    if json_out:
        write_parameter_json(json_out)
        print(f"Wrote {json_out}")
    if out or json_out:
        return
    print(f"{'Key':<24} {'Offset':<8} {'CC':<5} {'Type':<12} {'Label'}")
    print('-' * 100)
    for r in rows:
        off = '—' if r['offset'] is None else f"0x{r['offset']:02X}"
        cc = '—' if r['cc'] is None else str(r['cc'])
        print(f"{r['key']:<24} {off:<8} {cc:<5} {r['kind']:<12} {r['label']}")


# ---------------------------------------------------------------------------
# P1 — patch library commands (offline .syx file operations only; no MIDI).
# These are additive subcommands; every pre-existing command is untouched.
# ---------------------------------------------------------------------------

def _slot(n: int, label: str) -> int:
    try:
        v = int(n)
    except ValueError:
        raise ValueError(f"{label} must be an integer 1..32; got {n!r}.")
    if not 1 <= v <= 32:
        raise ValueError(f"{label} must be 1..32; got {v}.")
    return v


def cmd_library(action: str, args) -> None:
    from .library import PatchLibrary

    if action == 'inspect':
        lib = PatchLibrary.from_file(args.file)
        syx = parse_file(args.file)
        chk = 'OK' if syx.checksum_ok else 'BAD'
        print(f"file: {args.file}\nmode: {syx.mode}\nprograms: {len(lib.bank.programs)}"
              f"\nchecksum: 0x{syx.checksum_value:02X} ({chk})")
        for p in lib.bank.programs:
            print(f"{p.index:02}: {p.name!r}")
        return

    if action == 'rename':
        lib = PatchLibrary.from_file(args.file)
        idx = _slot(args.program, 'program')
        before = lib.get(idx).name
        lib.rename(idx, args.name)
        after = lib.get(idx).name
        if args.output:
            payload = lib.save_bank(args.output)
            print(f"Renamed P{idx:02d} {before!r} -> {after!r}; wrote {args.output} "
                  f"({len(payload)} bytes)")
        else:
            print(f"P{idx:02d}: {before!r} -> {after!r} (dry run; use --output to save)")
        return

    if action == 'duplicate':
        lib = PatchLibrary.from_file(args.file)
        src = _slot(args.source, 'source')
        dst = _slot(args.target, 'target')
        lib.duplicate(src, dst)
        assert lib.get(dst).data == lib.get(src).data
        if args.output:
            payload = lib.save_bank(args.output)
            print(f"Duplicated P{src:02d} -> P{dst:02d}; wrote {args.output} "
                  f"({len(payload)} bytes)")
        else:
            print(f"P{src:02d} -> P{dst:02d}: {lib.get(dst).name!r} (dry run; use --output to save)")
        return

    if action == 'swap':
        lib = PatchLibrary.from_file(args.file)
        a = _slot(args.a, 'a')
        b = _slot(args.b, 'b')
        na, nb = lib.get(a).name, lib.get(b).name
        lib.swap(a, b)
        if args.output:
            payload = lib.save_bank(args.output)
            print(f"Swapped P{a:02d} <-> P{b:02d}; wrote {args.output} "
                  f"({len(payload)} bytes)")
        else:
            print(f"P{a:02d} {na!r} <-> P{b:02d} {nb!r} (dry run; use --output to save)")
        return

    if action == 'export':
        # Pure re-export: load, then save through the exporter (header frame
        # preserved, checksum recomputed at export time). Also validates that
        # our own parser accepts what we write.
        lib = PatchLibrary.from_file(args.file)
        payload = lib.save_bank(args.output)
        reparsed = parse_file(args.output)
        status = 'OK' if reparsed.checksum_ok and reparsed.raw == payload else 'MISMATCH'
        print(f"Exported {args.file} -> {args.output} ({len(payload)} bytes, "
              f"re-parse: {status})")
        return

    raise ValueError(f"Unknown library action: {action}")


# ---------------------------------------------------------------------------
# P1.5 — hardware experiment protocol.
#
# SAFETY RULES (enforced in code, not just docs):
#   * `experiment compare/report/registry-status` are PURE OFFLINE commands:
#     they only read local .syx files and never touch MIDI.
#   * `midi list/probe` only enumerate ports (no data is sent).
#   * `midi cc` / `midi sysex-send` transmit ONLY on explicit user request and
#     always report TX-level truth ("Transport OK") plus "Device response:
#     NOT VERIFIED". They are NEVER invoked by automated tests against a real
#     device (hardware tests live in tests/hardware/ and skip by default).
# ---------------------------------------------------------------------------

DEVICE_NAME_HINT = 'JT-4000M'


def _transport():
    from .transport import MidiTransport
    return MidiTransport()


def _print_ports(tr):
    print(f"MIDI backend: {tr.backend_name}"
          + ("" if tr.available else f" — {tr.note}"))
    inputs, outputs = tr.list_inputs(), tr.list_outputs()
    print("MIDI INPUTS")
    if not inputs:
        print("  (none)")
    for p in inputs:
        print(f"{p.index}: {p.name}")
    print("\nMIDI OUTPUTS")
    if not outputs:
        print("  (none)")
    for p in outputs:
        print(f"{p.index}: {p.name}")


def _session(tr, note: str = ""):
    """P1.6: every live midi command records a machine-readable session log."""
    from .session import SessionLog
    sl = SessionLog(tr.backend_name)
    if note:
        sl.note(note)
    return sl


def _save_session(sl, args) -> None:
    """Save the session JSON unless --no-session-log was passed. Prints path."""
    if getattr(args, 'no_session_log', False):
        return
    try:
        path = sl.save(getattr(args, 'sessions_dir', None))
        print(f"Session log:\n  {path}")
    except OSError as e:  # logging must never mask the real MIDI result
        print(f"WARNING: session log could not be saved: {e}")


def cmd_midi(action, args):
    tr = _transport()

    if action == 'list':
        _print_ports(tr)
        return

    if action == 'probe':
        # P1.6 probe: discovery + open/close test ONLY. Nothing is ever sent.
        needle = args.name or DEVICE_NAME_HINT
        sl = _session(tr)
        try:
            _print_ports(tr)
        except RuntimeError as e:
            # Enumeration can fail on systems without a working MIDI
            # subsystem (e.g. no ALSA sequencer). Honest report, no crash.
            print(f"MIDI PROBE for {needle!r} (backend: {tr.backend_name}):")
            print(f"  enumeration failed: {e}")
            print("RESULT: TRANSPORT NOT AVAILABLE")
            print("NOTE: this is an environment/backend limitation, not "
                  "proof about the device; on Windows/winmm re-run the probe.")
            sl.add_action('probe', rx_count=0, error=str(e),
                          detail={"result": "TRANSPORT NOT AVAILABLE",
                                  "sent": 0})
            _save_session(sl, args)
            raise SystemExit(2)
        matches = tr.find(needle)
        print(f"\nMIDI PROBE for {needle!r} (backend: {tr.backend_name}):")
        if not matches:
            print("  no endpoints matched; NOT assuming any port index.")
            self_note = ("probe: no endpoints matched; RESULT: TRANSPORT NOT "
                         "AVAILABLE")
            print(self_note)
            sl.add_action('probe', rx_count=0,
                          detail={"matched": 0, "sent": 0})
            _save_session(sl, args)
            return
        for p in matches:
            print(f"  [{p.direction}] {p.index}: {p.name}")
        ins = [p for p in matches if p.direction == 'input']
        outs = [p for p in matches if p.direction == 'output']
        sl.set_ports(input_port=ins[0] if ins else None,
                     output_port=outs[0] if outs else None)
        # Open/close test — no data crosses the wire.
        in_ok = out_ok = None
        if ins:
            try:
                tr.open_input(ins[0])
                in_ok = True
            except Exception as e:
                in_ok = False
                print(f"  INPUT OPEN failed: {e}")
            finally:
                try:
                    tr.close()
                except Exception:
                    pass
        if outs:
            try:
                h = tr.open_output(outs[0])
                out_ok = True
                if tr.backend_name != 'winmm' and h is not None:
                    try:
                        h.close_port()
                    except Exception:
                        pass
            except Exception as e:
                out_ok = False
                print(f"  OUTPUT OPEN failed: {e}")
        print(f"INPUT OPEN : {'OK' if in_ok else ('N/A' if in_ok is None else 'FAILED')}")
        print(f"OUTPUT OPEN: {'OK' if out_ok else ('N/A' if out_ok is None else 'FAILED')}")
        transport_available = bool(in_ok or out_ok)
        print("RESULT:", "TRANSPORT AVAILABLE" if transport_available
              else "TRANSPORT NOT AVAILABLE")
        print("\nProbe result: discovery + open/close only — NO SysEx was "
              "sent, NO parameters were changed.")
        print("This proves AT MOST 'TRANSPORT AVAILABLE'. It does NOT say "
              "'DEVICE VERIFIED': device behavior remains UNVERIFIED until an "
              "A/B SysEx capture (midi capture + experiment compare) exists.")
        sl.add_action('probe', rx_count=0, detail={
            "matched": len(matches),
            "input_open_ok": in_ok, "output_open_ok": out_ok,
            "result": ("TRANSPORT AVAILABLE" if transport_available
                       else "TRANSPORT NOT AVAILABLE"),
            "sent": 0,
        })
        _save_session(sl, args)
        return

    if action == 'cc':
        # Explicit diagnostic TX. Requires a resolvable output endpoint.
        out_port = _resolve_output(tr, args)
        sl = _session(tr)
        sl.set_ports(output_port=out_port)
        rep = tr.send_cc(out_port, args.channel, args.controller, args.value)
        print(rep.format())
        sl.add_action('cc', tx_bytes=rep.tx_bytes, api_ok=rep.api_ok,
                      error=rep.error, rx_count=0,
                      detail={"channel": args.channel,
                              "controller": args.controller,
                              "value": args.value,
                              "device_response": "NOT VERIFIED"})
        sl.note("TX-level result only; the synth's reaction was not and "
                "cannot be concluded from this command alone.")
        _save_session(sl, args)
        if not rep.api_ok:
            raise SystemExit(2)
        return

    if action == 'sysex-send':
        from .syx import parse_file as pf
        syx = pf(args.file)  # must parse — hard gate
        if not syx.checksum_ok:
            raise ValueError(
                f"Refusing to send: checksum is BAD in {args.file} "
                f"(stored 0x{syx.checksum_value:02X}, expected "
                f"0x{syx.checksum_expected:02X}).")
        chk = 'OK' if syx.checksum_ok else 'BAD'
        print(f"File:\n  {args.file}\nMode:\n  {syx.mode}\nPrograms:\n  "
              f"{len(syx.programs)}\nChecksum:\n  {chk} "
              f"(0x{syx.checksum_value:02X})\nBytes:\n  {len(syx.raw)}")
        print("Provenance of this file: REFERENCE_FIXTURE (bundled analysis "
              "bank) unless you know otherwise.")
        out_port = _resolve_output(tr, args)
        sl = _session(tr)
        sl.set_ports(output_port=out_port)
        sl.add_file(args.file, "fixture", checksum_status=chk)
        print(f"Send to:\n  [{out_port.index}] {out_port.name}")
        if not args.yes:
            ans = input("Confirm: type YES to send: ").strip()
            if ans != 'YES':
                print("Aborted; nothing was sent.")
                sl.add_action('sysex-send-aborted', rx_count=0)
                _save_session(sl, args)
                return
        rep = tr.send_sysex(out_port, syx.raw)
        print(rep.format())
        sl.add_action('sysex-send', tx_bytes=rep.tx_bytes, api_ok=rep.api_ok,
                      error=rep.error, rx_count=0,
                      detail={"file": str(args.file), "mode": syx.mode,
                              "device_response": "NOT VERIFIED"})
        sl.note("TX-level result only. Whether the JT-4000M applied the "
                "bank requires an A/B capture afterwards (DEVICE BEHAVIOR "
                "level), never assumed here.")
        _save_session(sl, args)
        if not rep.api_ok:
            raise SystemExit(2)
        return

    if action in ('listen', 'capture'):
        from .capture import CaptureBuffer
        in_port = _resolve_input(tr, args)
        out_path = getattr(args, 'output', None)
        raw_path = getattr(args, 'raw_log', None)
        timeout = args.timeout
        sl = _session(tr)
        sl.set_ports(input_port=in_port)
        print(f"Listening on input [{in_port.index}] {in_port.name} "
              f"for {timeout:.1f}s...")
        print("Waiting for MIDI...")
        buf = CaptureBuffer()
        try:
            tr.open_input(in_port)
            for ts, data in tr.receive(timeout=timeout):
                rec = buf.add(ts, data)
                shown = data if len(data) <= 32 else data[:24] + b'..'
                hexed = ' '.join(f'{b:02X}' for b in shown)
                print(f"[{ts:.3f}] {rec.kind:20} len={len(data):5}  {hexed}")
        except RuntimeError as e:
            print(f"Input unavailable: {e}")
            sl.add_action(action, rx_count=0, error=str(e))
            _save_session(sl, args)
            raise SystemExit(2)
        finally:
            tr.close()
        label = buf.result_label()
        counts = buf.counts_by_kind()
        print(f"\nRX messages: {buf.total}"
              + ("  (" + ", ".join(f"{k}: {v}" for k, v in
                                   sorted(counts.items())) + ")"
                 if counts else ""))
        print(f"RESULT: {label}")
        if buf.total == 0:
            print("No MIDI received within the timeout. This is NOT a Python "
                  "error — absence of RX simply means no device response was "
                  "observed (DEVICE BEHAVIOR: NOT VERIFIED).")
        saved = None
        if out_path is not None:
            saved = buf.save_last_sysex(out_path)
            if saved is None:
                print(f"--output given but no COMPLETE SysEx was received; "
                      f"{out_path} was NOT written.")
            else:
                print(f"Saved last complete SysEx capture "
                      f"({saved.stat().st_size} bytes) to {saved} "
                      "[CAPTURED_FROM_DEVICE]")
                # Honest post-check: does it even parse as a JT-4000M dump?
                chk_note = ""
                try:
                    from .syx import parse_file as pf2
                    s2 = pf2(saved)
                    chk_note = ('OK' if s2.checksum_ok else
                                f"BAD (0x{s2.checksum_value:02X}, expected "
                                f"0x{s2.checksum_expected:02X})")
                    print(f"Parse check: mode={s2.mode}, "
                          f"programs={len(s2.programs)}, checksum={chk_note}")
                except Exception as e:
                    chk_note = f"PARSE FAILED: {e}"
                    print(f"Parse check: {chk_note} — kept raw bytes as "
                          "captured; do NOT feed it to experiments without "
                          "inspection.")
                sl.add_file(saved, "capture",
                            provenance="CAPTURED_FROM_DEVICE",
                            checksum_status=chk_note,
                            messages=len(buf.sysex_complete))
        if raw_path is not None:
            rp = buf.save_all(raw_path)
            print(f"All {buf.total} RX packets logged to {rp}")
            sl.add_file(rp, "rx-log", provenance="CAPTURED_FROM_DEVICE",
                        messages=buf.total)
        sl.add_action(action, rx_count=buf.total,
                      detail={"counts": counts, "result": label,
                              "sent": 0})
        _save_session(sl, args)
        return

    raise ValueError(f"Unknown midi action: {action}")


def classify_midi(data: bytes) -> str:
    if data.startswith(b'\xF0'):
        return 'SYSEX'
    status = data[0] & 0xF0 if data else 0
    names = {0x80: 'NOTE_OFF', 0x90: 'NOTE_ON', 0xA0: 'PITCH_BEND',
             0xB0: 'CONTROL_CHANGE', 0xC0: 'PROGRAM_CHANGE',
             0xD0: 'CHANNEL_AFTERTOUCH', 0xE0: 'PITCH_WHEEL'}
    return names.get(status, f'STATUS_0x{data[0]:02X}' if data else 'EMPTY')


def _resolve_output(tr, args):
    from .transport import PortInfo
    if not tr.available:
        raise RuntimeError(tr.note or 'no MIDI backend available')
    outputs = tr.list_outputs()
    if getattr(args, 'port', None) is not None:
        for p in outputs:
            if p.index == args.port:
                return p
        raise ValueError(f"No MIDI output at index {args.port}.")
    needle = getattr(args, 'device', None) or DEVICE_NAME_HINT
    hits = [p for p in outputs if needle.lower() in p.name.lower()]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise ValueError(
            f"No MIDI output matching {needle!r}; choose one with --port:")
    raise ValueError(
        f"Multiple outputs match {needle!r}; choose one with --port: "
        + ", ".join(f"[{p.index}] {p.name}" for p in hits))


def _resolve_input(tr, args):
    if not tr.available:
        raise RuntimeError(tr.note or 'no MIDI backend available')
    inputs = tr.list_inputs()
    if getattr(args, 'port', None) is not None:
        for p in inputs:
            if p.index == args.port:
                return p
        raise ValueError(f"No MIDI input at index {args.port}.")
    needle = getattr(args, 'device', None) or DEVICE_NAME_HINT
    hits = [p for p in inputs if needle.lower() in p.name.lower()]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise ValueError(f"No MIDI input matching {needle!r}; "
                         "choose one with --port:")
    raise ValueError(
        f"Multiple inputs match {needle!r}; choose one with --port: "
        + ", ".join(f"[{p.index}] {p.name}" for p in hits))


# ---------------------------------------------------------------------------
# P1.5 — experiment commands (offline only; operate on BEFORE/AFTER .syx)
# ---------------------------------------------------------------------------

def cmd_experiment(action, args):
    from .experiment import (compare_experiment, append_evidence,
                             registry_status, PROVENANCE_FIXTURE,
                             PROVENANCE_DEVICE)

    def prov(v, path=None):
        # P1.6: 'auto' detects CAPTURED_FROM_DEVICE via recorded capture
        # files (sessions/*.json) and REFERENCE_FIXTURE for bundled banks.
        if v == 'device':
            return PROVENANCE_DEVICE
        if v == 'fixture':
            return PROVENANCE_FIXTURE
        from .experiment import detect_provenance
        return detect_provenance(path)

    if action == 'compare':
        res = compare_experiment(
            args.before, args.after, program=args.program,
            hypothesis=args.hypothesis,
            before_provenance=prov(args.before_prov, args.before),
            after_provenance=prov(args.after_prov, args.after))
        print(res.summary_text())

        def _write(path, text):
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding='utf-8')
            return p

        if args.json:
            _write(args.json, res.to_json())
            print(f"\nWrote {args.json}")
        if args.md:
            _write(args.md, res.to_markdown())
            print(f"Wrote {args.md}")
        if args.log:
            p = append_evidence(res)
            print(f"Appended evidence records to {p}")
        return

    if action == 'report':
        # Human workflow helper: shows what an experiment expects and how to
        # capture BEFORE/AFTER dumps. Performs NO MIDI I/O itself.
        from .model import BY_KEY
        spec = BY_KEY.get(args.parameter)
        if spec is None:
            raise ValueError(f"Unknown parameter key: {args.parameter}")
        cc = f"CC {spec.cc}" if spec.cc is not None else \
            "CC: not established (do NOT guess one)"
        off = 'not established' if spec.offset is None else \
            f"0x{spec.offset:02X}"
        print(f"Parameter : {args.parameter} ({spec.label})\n"
              f"SysEx offset: {off}\nExpected CC: {cc}\n"
              f"Program slot: {args.program:02d}\n\n"
              "REQUEST-DUMP STATUS:\n"
              "  No documented/established JT-4000M SysEx request-dump "
              "command exists in this project.\n"
              "  REQUEST_DUMP: NOT ESTABLISHED — the tool will NEVER send an\n"
              "  invented request packet (no guessing of manufacturer/"
              "realtime-dump bytes).\n"
              "  A capture therefore requires a device-initiated dump (e.g. a\n"
              "  front-panel bank-dump action, if the synth has one) observed\n"
              "  via `midi listen` / `midi capture`.\n\n"
              "Workflow (manual, hardware side):\n"
              "  1. python -m jt4000m.cli midi capture --output BEFORE.syx "
              "--timeout 60\n     (start listening, then trigger a dump from "
              "the JT-4000M)\n"
              "  2. Change ONLY this parameter physically on the synth.\n"
              "  3. python -m jt4000m.cli midi capture --output AFTER.syx "
              "--timeout 60\n"
              "  4. python -m jt4000m.cli experiment compare BEFORE.syx "
              f"AFTER.syx --program {args.program} --hypothesis "
              f"{args.parameter} --before-prov device --after-prov device "
              "--log\n\n"
              "Interpretation rules (fixed, no guessing):\n"
              "  * only bytes actually received over a MIDI input are "
              "CAPTURED_FROM_DEVICE;\n"
              "    bundled banks remain REFERENCE_FIXTURE;\n"
              "  * CONFIRMED requires exactly the hypothesised offset to "
              "change;\n"
              "  * any additional changed byte => AMBIGUOUS, listed, never "
              "auto-attributed;\n"
              "  * TX success alone NEVER means DEVICE BEHAVIOR VERIFIED.")
        return

    if action == 'registry-status':
        rows = registry_status()
        print(f"{'Offset':<8} {'Key':<22} {'Level':<26} Label")
        print('-' * 78)
        for r in rows:
            key = r['key'] or '—'
            print(f"0x{r['offset']:02X}    {key:<22} {r['level']:<26} "
                  f"{r['label']}")
        return

    raise ValueError(f"Unknown experiment action: {action}")


def cmd_knowledge(action, args):
    """P1.6 OFFLINE — reverse-engineering knowledge reports (no MIDI)."""
    from . import knowledge as K
    if action == 'report':
        rep = K.generate()
        c = rep.counts()
        print("JT-4000M OFFLINE KNOWLEDGE REPORT (all evidence REFERENCE_FIXTURE)")
        print(f"Known parameters: {c['known_parameters']}")
        print(f"Fixture-observed offsets: {c['fixture_observed']}")
        print(f"Static CC mappings: {c['static_cc_mappings']} "
              f"(FIXTURE_OBSERVED_SYSEX corroborated: {c['fixture_observed_cc']})")
        print(f"Hardware-confirmed parameters: {c['hardware_confirmed']}")
        print(f"Unknown offsets: {c['unknown_offsets']}")
        print(f"Fixture-constant offsets: {c['fixture_constant_offsets']}")
        print(f"Name bytes: 9 (0x37..0x3F)")
        print(f"Correlation hypotheses: {c['correlation_hypotheses']}")
        print(f"Conflicts: {c['conflicts']}")
        print("\nFixtures:")
        for f in rep.fixtures:
            chk = 'OK' if f['checksum_ok'] else 'BAD'
            print(f"  {f['file']:<42} {f['mode']:<7} "
                  f"programs={f['programs']:>2} checksum={chk}")
        print("\nPARAMETER KNOWLEDGE MATRIX (offset | param | CC | fixture | hardware | status)")
        print('-' * 100)
        for r in rep.offsets:
            if r.status == K.STATUS_NAME:
                continue
            if r.status == K.STATUS_UNKNOWN and r.unique_count == 1 and not args.all_unknown:
                continue
            fix = 'YES' if r.confidence in (K.CONF_FIXTURE, K.CONF_HW) else 'const/static'
            hw = 'YES' if r.confidence == K.CONF_HW else 'NO'
            key = r.parameter_key or '—'
            cc = str(r.cc) if r.cc is not None else '—'
            print(f"0x{r.offset:02X}   {key:<22} CC:{cc:<4} fixture:{fix:<12} hw:{hw:<4} "
                  f"{r.status:<15} uniq={r.unique_count:>3} [{r.min:02X}..{r.max:02X}]")
        print("\nCC <-> SYSEX MAPPING STATUS (never HARDWARE_CONFIRMED offline)")
        print('-' * 100)
        for m in rep.cc_table:
            off = m['sysex_offset'] or 'not established'
            print(f"CC {m['cc']:<3} -> {m['key']:<22} offset {off:<15} {m['status']}")
        if rep.corr:
            print("\nCORRELATIONS (HYPOTHESIS ONLY — never promoted automatically)")
            for x in rep.corr:
                print(f"  0x{int(x['unknown_offset'],16):02X}... "
                      f"{x['unknown_offset']} ~ {x['correlated_with']} "
                      f"(jaccard={x['jaccard']}) [{x['status']}]")
        if rep.conflicts:
            print("\nCONFLICTS (OPEN — no source auto-wins)")
            for cf in rep.conflicts:
                print(f"  [{cf['topic']}] A={cf['source_a']} B={cf['source_b']}")
                print(f"      observed: {cf['observed']}  status: {cf['status']}")
        print("\nCHECKSUMS (algorithm unchanged; coverage verified)")
        for srow in rep.checksums:
            print(f"  {srow['file']:<42} stored={srow['stored_checksum']} "
                  f"calc={srow['calculated_checksum']} {srow['status']}")
        print("\nNAME FIELD STUDY")
        n = rep.name
        print(f"  programs={n['programs_analyzed']} distinct={n['distinct_names']} "
              f"max_len={n['max_used_length']} pad00={n['padding_0x00_programs']} "
              f"pad20={n['padding_0x20_programs']} all_7bit={n['all_bytes_7bit']}")
        print("\nNOTE: fixture-derived CONFIRMED verdicts validate the PROTOCOL "
              "only;\nDEVICE BEHAVIOR VERIFIED requires CAPTURED_FROM_DEVICE "
              "evidence.")
        return
    if action == 'csv':
        import csv as _csv, json as _json
        rep = K.generate()
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, 'w', newline='', encoding='utf-8') as fh:
            w = _csv.writer(fh)
            w.writerow(['offset', 'field', 'status', 'key', 'kind', 'cc',
                        'unique_count', 'min', 'max', 'fixture_constant',
                        'confidence'])
            for r in rep.offsets:
                w.writerow([f"0x{r.offset:02X}", r.field, r.status,
                            r.parameter_key or '', r.kind or '',
                            '' if r.cc is None else r.cc, r.unique_count,
                            f"0x{r.min:02X}", f"0x{r.max:02X}",
                            r.fixture_constant, r.confidence])
        db = K.build_evidence_db()
        Path(args.json_out or Path(args.output).with_suffix('.json')).write_text(
            _json.dumps(db, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f"Wrote {args.output} and evidence JSON")
        return
    raise ValueError(f"Unknown knowledge action: {action}")


def cmd_analyze(action, args):
    """P1.7 OFFLINE — statistical parameter discovery from local .syx files.

    analyze-bank   : dataset inventory (mode/checksum/provenance/duplicates)
    analyze-offsets: per-offset entropy/frequency/transition table
    registry-audit : every registry parameter vs the fixture corpus
    cc-audit       : CC mapping sources (never hardware-confirmed offline)
    report         : full JSON + Markdown dataset under analysis/
    Nothing here touches MIDI; results are deterministic.
    """
    import json as _json
    from pathlib import Path as _Path
    from . import discovery as D

    paths = list(args.files) if args.files else [str(p) for p in D.discover_fixtures()]
    rep = D.generate(paths, mi_threshold=getattr(args, 'mi', 0.3))

    if action == 'analyze-bank':
        print("P1.7 DATASET INVENTORY (all provenance = REFERENCE_FIXTURE)")
        for f in rep.files:
            dupes = sum(len(s) for s in f.duplicate_programs.values())
            print(f"\n{f.path}")
            print(f"  mode: {f.mode}  programs: {f.programs}  bytes: {f.total_bytes}")
            print(f"  checksum: stored {f.checksum_stored} expected "
                  f"{f.checksum_expected} status {'OK' if f.checksum_ok else 'BAD'}")
            print(f"  provenance: {f.provenance}")
            print(f"  unique programs: {f.unique_programs}  "
                  f"duplicate slots: {dupes}")
            names = [n.strip() or '(empty)' for n in f.names]
            shown = ', '.join(names[:8]) + ('...' if len(names) > 8 else '')
            print(f"  names: {shown}")
        return
    if action == 'analyze-offsets':
        print(f"{'Offset':6} {'Field':28} {'Class':20} {'Level':12} "
              f"{'N':>3} {'Entropy':>8} {'Min':5} {'Max':5} {'Trans':>5}")
        for p in rep.profiles:
            mn = '-' if p.min is None else f"0x{p.min:02X}"
            mx = '-' if p.max is None else f"0x{p.max:02X}"
            print(f"0x{p.offset:02X}   {p.field:28} {p.classification:20} "
                  f"{p.evidence_level:12} {p.unique_count:>3} "
                  f"{p.entropy:>8.3f} {mn:>5} {mx:>5} {p.transition_count:>5}")
        print("\nClassification summary:",
              ', '.join(f'{k}={v}' for k, v in sorted(rep.classifications.items())))
        print("NOTE: classifications describe DATA BEHAVIOUR only; unknown "
              "offsets keep candidate_meaning=UNKNOWN (no hardware used).")
        return
    if action == 'registry-audit':
        for r in rep.registry_audit:
            print(f"{r['key']:22} off={r['offset']} cc={r['cc']} "
                  f"kind={r['kind']} level={r['evidence_level']} "
                  f"coverage={r['fixture_coverage']} "
                  f"contradictions={len(r['contradictions'])} "
                  f"hardware={'NO (REQUIRED)' if not r['hardware_evidence'] else 'YES'}")
            for c in r['contradictions']:
                print(f"    - {c}")
        return
    if action == 'cc-audit':
        for c in rep.cc_audit:
            print(f"CC {c['cc']:>3} -> {c['parameter']:22} off={c['offset']} "
                  f"| source: {c['source']} | fixtures: {c['offset_fixture_evidence']} "
                  f"| {c['hardware_evidence']}")
        return
    if action == 'report':
        out_dir = args.output or 'analysis'
        stem = args.name or 'parameter_discovery'
        jp, mp = D.write_reports(rep, out_dir, stem)
        print(f"Wrote {jp}")
        print(f"Wrote {mp}")
        print(f"Offsets analyzed: {len(rep.profiles)}; "
              f"correlations (INFERRED): {len(rep.pairs)}; "
              f"contradictions: {len(rep.contradictions)}; "
              f"unknown dossiers: {len(rep.dossiers)}")
        print("Hardware-confirmed parameters: 0 (no physical JT-4000M was used)")
        return
    raise ValueError(f"Unknown analyze action: {action}")


def cmd_model(action: str, args) -> None:
    """P1.8 -- offline editor data model inspection/export (no GUI, no MIDI)."""
    from .editor_model import EditorModel, definition_for
    if action == 'inspect':
        m = EditorModel()
        m.load_bank(args.file)
        ps = m.select(args.program)
        print(f"File: {args.file}")
        print(f"Provenance: {m.provenance}")
        print(f"Program {ps.index:02d}: {ps.name!r}")
        for key in sorted(ps.all_values()):
            v = ps.value(key)
            d = definition_for(key)
            hw = "NOT_CONFIRMED" if not v.hardware_confirmed else "CONFIRMED"
            print(f"{d.label:<32} raw=0x{v.raw:02X} ({v.raw:>3})  "
                  f"display={v.display:<16} evidence={v.evidence_level:<11} "
                  f"hardware={hw}"
                  + (f"  cc={d.cc}" if d.cc is not None else ""))
        u = ps.unknown_bytes()
        print(f"\nUnknown bytes ({len(u)}):")
        for off in sorted(u):
            print(f"  0x{off:02X} = 0x{u[off]:02X}")
        return
    if action == 'export':
        import json as _json
        m = EditorModel()
        m.load_bank(args.file)
        ps = m.select(args.program)
        payload = _json.dumps(ps.to_json_dict(), ensure_ascii=False, indent=2)
        if args.json:
            Path(args.json).write_text(payload, encoding='utf-8')
            print(f"Wrote {args.json}")
        else:
            print(payload)
        return
    # ---- P1.9 public-API surface (regression/testing aid, not a GUI) ----
    if action == 'search':
        m = EditorModel(); m.load_bank(args.file)
        hits = m.search_patches(args.query)
        print(f"Search {args.query!r}: {len(hits)} patch(es)")
        for p in hits:
            print(f"  {p.index:02d}  {p.name}")
        return
    if action == 'groups':
        m = EditorModel(); m.load_bank(args.file)
        for g in m.list_groups():
            print(f"{g:<16} {len(m.parameters(g))} parameter(s)")
        return
    if action == 'parameters':
        m = EditorModel(); m.load_bank(args.file)
        for d in m.parameters(args.group):
            off = f"0x{d.offset:02X}" if d.offset is not None else "-"
            rng = ("enum " + ",".join(str(v) for v in d.enum_options)
                   if d.enum_options else f"{d.minimum}..{d.maximum}")
            print(f"{d.key:<22} {d.label:<28} offset={off:<5} cc={d.cc if d.cc is not None else '-':<4} "
                  f"kind={d.kind:<11} {rng:<24} evidence={d.evidence_level} "
                  f"hardware={'CONFIRMED' if d.hardware_confirmed else 'NOT_CONFIRMED'}")
        return
    if action == 'session-save':
        m = EditorModel(); m.load_bank(args.file)
        m.save_session(args.session)
        print(f"Wrote session {args.session}")
        return
    if action == 'session-load':
        m = EditorModel.load_session(args.session)
        print(f"Session loaded from {args.session}")
        print(f"Source: {m.path}")
        print(f"Provenance: {m.provenance}")
        print(f"Selected patch: {m.selected:02d} ({m.current().name!r})")
        print(f"Dirty: {m.is_dirty()}")
        return
    if action == 'diff':
        from .editor_model import definition_for
        ma = EditorModel(); ma.load_bank(args.a)
        mb = EditorModel(); mb.load_bank(args.b)
        pa = ma.select(args.program_a); pb = mb.select(args.program_b)
        changes = pa.diff_to(pb)
        print(f"{args.a}[{args.program_a}] {pa.name!r} vs "
              f"{args.b}[{args.program_b}] {pb.name!r}: {len(changes)} byte change(s)")
        for c in changes:
            print(f"  0x{c['offset']:02X}  {c['old']:>3} -> {c['new']:>3}   "
                  f"[{c['category']}] {c['field']}")
        return
    raise ValueError(f"Unknown model action: {action}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog='jt4000m')
    sp = ap.add_subparsers(dest='cmd', required=True)
    x = sp.add_parser('inspect'); x.add_argument('file')
    x = sp.add_parser('program'); x.add_argument('file'); x.add_argument('program', type=int)
    x = sp.add_parser('diff'); x.add_argument('a'); x.add_argument('b')
    x = sp.add_parser('raw-diff'); x.add_argument('a'); x.add_argument('b')
    x = sp.add_parser('semantic-diff'); x.add_argument('a'); x.add_argument('b')
    x = sp.add_parser('cross-bank'); x.add_argument('files', nargs='+'); x.add_argument('--csv'); x.add_argument('--json')
    x = sp.add_parser('parameter-map'); x.add_argument('--csv'); x.add_argument('--json')

    lib = sp.add_parser('library', help='P1 patch-library operations on local .syx files (no MIDI)')
    libsp = lib.add_subparsers(dest='action', required=True)
    x = libsp.add_parser('inspect'); x.add_argument('file')
    x = libsp.add_parser('rename'); x.add_argument('file'); x.add_argument('program', type=int); x.add_argument('name'); x.add_argument('--output')
    x = libsp.add_parser('duplicate'); x.add_argument('file'); x.add_argument('source', type=int); x.add_argument('target', type=int); x.add_argument('--output')
    x = libsp.add_parser('swap'); x.add_argument('file'); x.add_argument('a', type=int); x.add_argument('b', type=int); x.add_argument('--output')
    x = libsp.add_parser('export'); x.add_argument('file'); x.add_argument('output')

    # P1.5 — midi subcommands. list/probe are discovery-only; cc/sysex-send/
    # listen/capture touch the device ONLY when a human invokes them and are
    # never exercised against real hardware by automated tests.
    md = sp.add_parser('midi', help='P1.5/P1.6 MIDI transport commands '
                       '(list/probe are safe discovery; send requires '
                       'explicit user action; every live command writes a '
                       'JSON session log under sessions/)')
    mdsp = md.add_subparsers(dest='action', required=True)

    def _common(p):
        p.add_argument('--sessions-dir', default=None,
                       help='directory for session logs (default ./sessions)')
        p.add_argument('--no-session-log', action='store_true',
                       help='do not write the machine-readable session JSON')
        return p

    _common(mdsp.add_parser('list'))
    x = _common(mdsp.add_parser('probe')); x.add_argument('--name', default=None,
        help='substring to match endpoints by name (default: JT-4000M)')
    x = _common(mdsp.add_parser('cc', aliases=['cc-test'])); x.add_argument('channel', type=int)
    x.add_argument('controller', type=int); x.add_argument('value', type=int)
    x.add_argument('--port', type=int, default=None)
    x.add_argument('--device', default=None)
    x = _common(mdsp.add_parser('sysex-send')); x.add_argument('file')
    x.add_argument('--port', type=int, default=None); x.add_argument('--device', default=None)
    x.add_argument('--yes', action='store_true',
                   help='skip interactive YES confirmation (for scripts; '
                        'NEVER used in automated tests)')
    x = _common(mdsp.add_parser('listen')); x.add_argument('--port', type=int, default=None)
    x.add_argument('--device', default=None); x.add_argument('--timeout', type=float, default=10.0)
    x.add_argument('--raw-log', default=None,
                   help='log EVERY received packet (typed hex) to this JSONL file')
    x = _common(mdsp.add_parser('capture')); x.add_argument('--port', type=int, default=None)
    x.add_argument('--device', default=None); x.add_argument('--timeout', type=float, default=10.0)
    x.add_argument('--output', required=True, help='write received SysEx dump here')
    x.add_argument('--raw-log', default=None,
                   help='log EVERY received packet (typed hex) to this JSONL file')

    # P1.5 — experiment subcommands (pure offline analysis of .syx files).
    ex = sp.add_parser('experiment', help='P1.5 A/B SysEx experiment protocol '
                       '(offline file analysis only; sends no MIDI)')
    exsp = ex.add_subparsers(dest='action', required=True)
    x = exsp.add_parser('compare'); x.add_argument('before'); x.add_argument('after')
    x.add_argument('--program', type=int, default=1)
    x.add_argument('--hypothesis', default=None,
                   help='registry parameter key this experiment is about')
    x.add_argument('--before-prov', choices=('fixture', 'device', 'auto'), default='fixture')
    x.add_argument('--after-prov', choices=('fixture', 'device', 'auto'), default='fixture')
    x.add_argument('--json', default=None); x.add_argument('--md', default=None)
    x.add_argument('--log', action='store_true',
                   help='append evidence records to experiments/evidence_log.jsonl')
    x = exsp.add_parser('report'); x.add_argument('parameter')
    x.add_argument('--program', type=int, default=1)
    exsp.add_parser('registry-status')

    # P1.6 OFFLINE — reverse-engineering knowledge reports (fixtures only).
    kn = sp.add_parser('knowledge', help='P1.6 offline RE knowledge base '
                       '(cross-bank statistics, CC/offset matrix, conflicts; '
                       'reads local .syx files only, no MIDI)')
    knsp = kn.add_subparsers(dest='action', required=True)
    x = knsp.add_parser('report'); x.add_argument('--all-unknown',
        action='store_true', help='also list fixture-constant unknown offsets')
    x = knsp.add_parser('csv'); x.add_argument('output')
    x.add_argument('--json-out', default=None)

    # P1.7 OFFLINE — statistical parameter discovery over the local .syx corpus.
    an = sp.add_parser('analyze', help='P1.7 offline statistical RE '
                       '(dataset inventory, entropy/transition tables, '
                       'registry & CC audits, JSON+Markdown reports; '
                       'reads local files only, no MIDI, deterministic)')
    ansp = an.add_subparsers(dest='action', required=True)
    for name_, helptxt in (('analyze-bank', 'dataset inventory of all .syx files'),
                           ('analyze-offsets', 'per-offset entropy/frequency/transition table'),
                           ('registry-audit', 'every registry parameter vs the fixture corpus'),
                           ('cc-audit', 'CC mapping sources; never hardware-confirmed offline'),
                           ('report', 'write full JSON + Markdown discovery dataset')):
        x = ansp.add_parser(name_, help=helptxt)
        x.add_argument('files', nargs='*',
                       help='.syx files (default: auto-discovered corpus, '
                            'deduplicated by content hash)')
        x.add_argument('--mi', type=float, default=0.3,
                       help='normalized-MI threshold for correlation pairs')
        if name_ == 'report':
            x.add_argument('--output', default=None,
                           help='output directory (default: analysis/)')
            x.add_argument('--name', default=None,
                           help='report stem (default: parameter_discovery)')

    # P1.8 OFFLINE -- editor data model inspection/export (no GUI, no MIDI).
    mo = sp.add_parser('model', help='P1.8 offline editor data model: '
                       'definition/value/evidence view of a patch; reads and '
                       'writes local files only')
    mosp = mo.add_subparsers(dest='action', required=True)
    x = mosp.add_parser('inspect'); x.add_argument('file'); x.add_argument('program', type=int)
    x = mosp.add_parser('export'); x.add_argument('file'); x.add_argument('program', type=int); x.add_argument('--json', default=None)
    x = mosp.add_parser('search', help='P1.9: search patches by name (read-only)')
    x.add_argument('file'); x.add_argument('query')
    x = mosp.add_parser('groups', help='P1.9: registry parameter groups')
    x.add_argument('file')
    x = mosp.add_parser('parameters', help='P1.9: definitions of one group')
    x.add_argument('file'); x.add_argument('group')
    x = mosp.add_parser('session-save', help='P1.9: write editor session JSON (state only; SYX stays authoritative)')
    x.add_argument('file'); x.add_argument('session')
    x = mosp.add_parser('session-load', help='P1.9: restore editor state from session JSON')
    x.add_argument('session')
    x = mosp.add_parser('diff', help='P1.9: byte diff between two patches via PatchState.diff_to')
    x.add_argument('a'); x.add_argument('b')
    x.add_argument('program_a', type=int); x.add_argument('program_b', type=int)

    args = ap.parse_args(argv)
    try:
        if args.cmd == 'inspect': cmd_inspect(args.file)
        elif args.cmd == 'program': cmd_program(args.file, args.program)
        elif args.cmd == 'diff': print_diff(semantic_diff(parse_file(args.a), parse_file(args.b)))
        elif args.cmd == 'semantic-diff': print_diff(semantic_diff(parse_file(args.a), parse_file(args.b)))
        elif args.cmd == 'raw-diff': print_diff(raw_diff(parse_file(args.a), parse_file(args.b)), False)
        elif args.cmd == 'cross-bank': cmd_cross(args.files, args.csv, args.json)
        elif args.cmd == 'parameter-map': cmd_parameter_map(args.csv, args.json)
        elif args.cmd == 'library': cmd_library(args.action, args)
        elif args.cmd == 'midi': cmd_midi(args.action, args)
        elif args.cmd == 'experiment': cmd_experiment(args.action, args)
        elif args.cmd == 'knowledge': cmd_knowledge(args.action, args)
        elif args.cmd == 'analyze': cmd_analyze(args.action, args)
        elif args.cmd == 'model': cmd_model(args.action, args)
    except RuntimeError as e:
        ap.error(str(e))
    except (OSError, ValueError) as e:
        ap.error(str(e))


if __name__ == '__main__':
    main()
