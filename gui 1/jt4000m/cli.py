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


def cmd_midi(action, args):
    tr = _transport()

    if action == 'list':
        _print_ports(tr)
        return

    if action == 'probe':
        # Discovery only: find JT-4000M endpoints BY NAME. Sends nothing.
        needle = args.name or DEVICE_NAME_HINT
        _print_ports(tr)
        matches = tr.find(needle)
        print(f"\nPROBE for {needle!r}:")
        if not matches:
            print("  no endpoints matched; NOT assuming any port index.")
            return
        for p in matches:
            print(f"  [{p.direction}] {p.index}: {p.name}")
        ins = [p for p in matches if p.direction == 'input']
        outs = [p for p in matches if p.direction == 'output']
        print("\nProbe result: discovery only — NO SysEx was sent, NO "
              "parameters were changed, and communication with the device "
              "is still UNVERIFIED until an RX/SysEx response is captured.")
        if ins and outs:
            print("Both input and output endpoints found by name; use "
                  "`midi listen` (RX) to verify the device actually talks.")
        return

    if action == 'cc':
        # Explicit diagnostic TX. Requires a resolvable output endpoint.
        out_port = _resolve_output(tr, args)
        rep = tr.send_cc(out_port, args.channel, args.controller, args.value)
        print(rep.format())
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
        out_port = _resolve_output(tr, args)
        print(f"Send to:\n  [{out_port.index}] {out_port.name}")
        if not args.yes:
            ans = input("Confirm: type YES to send: ").strip()
            if ans != 'YES':
                print("Aborted; nothing was sent.")
                return
        rep = tr.send_sysex(out_port, syx.raw)
        print(rep.format())
        if not rep.api_ok:
            raise SystemExit(2)
        return

    if action in ('listen', 'capture'):
        in_port = _resolve_input(tr, args)
        out_path = getattr(args, 'output', None)
        timeout = args.timeout
        print(f"Listening on input [{in_port.index}] {in_port.name} "
              f"for {timeout:.1f}s...")
        print("Waiting for MIDI...")
        from .transport import PortInfo  # noqa: F401  (typing clarity)
        got = 0
        captures = []
        try:
            tr.open_input(in_port)
            for ts, data in tr.receive(timeout=timeout):
                got += 1
                kind = classify_midi(data)
                shown = data if len(data) <= 32 else data[:24] + b'..'
                hexed = ' '.join(f'{b:02X}' for b in shown)
                print(f"[{ts:.3f}] {kind:20} len={len(data):5}  {hexed}")
                if data.startswith(b'\xF0'):
                    captures.append(data)
        except RuntimeError as e:
            print(f"Input unavailable: {e}")
            raise SystemExit(2)
        finally:
            tr.close()
        if got == 0:
            print("No MIDI received within the timeout. This is NOT a Python "
                  "error — absence of RX simply means no device response was "
                  "observed (DEVICE BEHAVIOR: NOT VERIFIED).")
        if out_path is not None:
            if not captures:
                print(f"--output given but no SysEx was received; {out_path} "
                      "was NOT written.")
            else:
                Path(out_path).write_bytes(captures[-1])
                print(f"Saved last SysEx capture ({len(captures[-1])} bytes) "
                      f"to {out_path}")
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

    def prov(v):
        return PROVENANCE_DEVICE if v == 'device' else PROVENANCE_FIXTURE

    if action == 'compare':
        res = compare_experiment(
            args.before, args.after, program=args.program,
            hypothesis=args.hypothesis,
            before_provenance=prov(args.before_prov),
            after_provenance=prov(args.after_prov))
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
              "Workflow (manual, hardware side):\n"
              f"  1. python -m jt4000m.cli midi capture --output BEFORE.syx\n"
              "     (dump the current state from the JT-4000M)\n"
              "  2. Change the parameter physically on the synth.\n"
              f"  3. python -m jt4000m.cli midi capture --output AFTER.syx\n"
              "  4. python -m jt4000m.cli experiment compare BEFORE.syx "
              f"AFTER.syx --program {args.program} --hypothesis "
              f"{args.parameter} --before-prov device --after-prov device "
              "--log\n\n"
              "The tool will then classify every changed byte and give a "
              "CONFIRMED / AMBIGUOUS verdict without ever renaming unknown "
              "bytes automatically.")
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
    md = sp.add_parser('midi', help='P1.5 MIDI transport commands '
                       '(list/probe are safe discovery; send requires '
                       'explicit user action)')
    mdsp = md.add_subparsers(dest='action', required=True)
    mdsp.add_parser('list')
    x = mdsp.add_parser('probe'); x.add_argument('--name', default=None,
        help='substring to match endpoints by name (default: JT-4000M)')
    x = mdsp.add_parser('cc', aliases=['cc-test']); x.add_argument('channel', type=int)
    x.add_argument('controller', type=int); x.add_argument('value', type=int)
    x.add_argument('--port', type=int, default=None)
    x.add_argument('--device', default=None)
    x = mdsp.add_parser('sysex-send'); x.add_argument('file')
    x.add_argument('--port', type=int, default=None); x.add_argument('--device', default=None)
    x.add_argument('--yes', action='store_true',
                   help='skip interactive YES confirmation (for scripts; '
                        'NEVER used in automated tests)')
    x = mdsp.add_parser('listen'); x.add_argument('--port', type=int, default=None)
    x.add_argument('--device', default=None); x.add_argument('--timeout', type=float, default=10.0)
    x = mdsp.add_parser('capture'); x.add_argument('--port', type=int, default=None)
    x.add_argument('--device', default=None); x.add_argument('--timeout', type=float, default=10.0)
    x.add_argument('--output', required=True, help='write received SysEx dump here')

    # P1.5 — experiment subcommands (pure offline analysis of .syx files).
    ex = sp.add_parser('experiment', help='P1.5 A/B SysEx experiment protocol '
                       '(offline file analysis only; sends no MIDI)')
    exsp = ex.add_subparsers(dest='action', required=True)
    x = exsp.add_parser('compare'); x.add_argument('before'); x.add_argument('after')
    x.add_argument('--program', type=int, default=1)
    x.add_argument('--hypothesis', default=None,
                   help='registry parameter key this experiment is about')
    x.add_argument('--before-prov', choices=('fixture', 'device'), default='fixture')
    x.add_argument('--after-prov', choices=('fixture', 'device'), default='fixture')
    x.add_argument('--json', default=None); x.add_argument('--md', default=None)
    x.add_argument('--log', action='store_true',
                   help='append evidence records to experiments/evidence_log.jsonl')
    x = exsp.add_parser('report'); x.add_argument('parameter')
    x.add_argument('--program', type=int, default=1)
    exsp.add_parser('registry-status')

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
    except RuntimeError as e:
        ap.error(str(e))
    except (OSError, ValueError) as e:
        ap.error(str(e))


if __name__ == '__main__':
    main()
