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
    args = ap.parse_args(argv)
    try:
        if args.cmd == 'inspect': cmd_inspect(args.file)
        elif args.cmd == 'program': cmd_program(args.file, args.program)
        elif args.cmd == 'diff': print_diff(semantic_diff(parse_file(args.a), parse_file(args.b)))
        elif args.cmd == 'semantic-diff': print_diff(semantic_diff(parse_file(args.a), parse_file(args.b)))
        elif args.cmd == 'raw-diff': print_diff(raw_diff(parse_file(args.a), parse_file(args.b)), False)
        elif args.cmd == 'cross-bank': cmd_cross(args.files, args.csv, args.json)
        elif args.cmd == 'parameter-map': cmd_parameter_map(args.csv, args.json)
    except (OSError, ValueError) as e:
        ap.error(str(e))


if __name__ == '__main__':
    main()
