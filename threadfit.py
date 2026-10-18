#!/usr/bin/env python3
"""threadfit: screw-thread geometry, tap drills, clearance holes, engagement and bolt-load checks.

Standard library only. Lengths are millimetres internally; inch threads are converted
at 25.4 mm per inch. Commands: show, list, lint, report, check.
"""

import argparse
import csv
import json
import math
import re
import sys
from dataclasses import dataclass

INCH = 25.4
LBF = 4.4482216  # newtons per pound-force
MIN_SF_DEFAULT = 1.5

# ISO 262 coarse pitches (mm) for the common metric sizes.
COARSE_PITCH = {1.6: 0.35, 2: 0.4, 2.5: 0.45, 3: 0.5, 4: 0.7, 5: 0.8, 6: 1.0, 8: 1.25,
                10: 1.5, 12: 1.75, 14: 2.0, 16: 2.0, 18: 2.5, 20: 2.5, 22: 2.5, 24: 3.0,
                30: 3.5, 36: 4.0}

# ISO 273 clearance hole diameters (mm) as (fine, medium, coarse).
CLEARANCE = {3: (3.2, 3.4, 3.6), 4: (4.3, 4.5, 4.8), 5: (5.3, 5.5, 5.8), 6: (6.4, 6.6, 7.0),
             8: (8.4, 9.0, 10.0), 10: (10.5, 11.0, 12.0), 12: (13.0, 14.0, 15.0)}
FITS = ("fine", "medium", "coarse")

# Proof strengths in MPa: ISO 898-1 for metric (diameters up to M16),
# SAE J429 proof loads for unified grades (55, 85 and 120 ksi).
GRADES = {
    "4.6": ("M", 225.0), "5.8": ("M", 380.0), "8.8": ("M", 600.0),
    "10.9": ("M", 830.0), "12.9": ("M", 970.0),
    "SAE2": ("UN", 379.0), "SAE5": ("UN", 586.0), "SAE8": ("UN", 827.0),
}

# Minimum thread engagement as a multiple of nominal diameter (rule of thumb).
ENGAGEMENT = {"steel": 1.0, "stainless": 1.0, "brass": 1.0, "cast-iron": 1.5,
              "aluminium": 1.5, "plastic": 2.0}
ALIASES = {"aluminum": "aluminium", "cast iron": "cast-iron", "cast_iron": "cast-iron"}
OPTION_KEYS = ("grade", "material", "depth", "fit", "load")


class ThreadError(ValueError):
    def __init__(self, message, line=None):
        super().__init__(message)
        self.message = message
        self.line = line


@dataclass(frozen=True)
class Thread:
    system: str   # "M" metric or "UN" unified inch
    name: str
    major: float  # mm
    pitch: float  # mm

    def geometry(self):
        d, p = self.major, self.pitch
        # Stress-area coefficient differs between ISO and unified forms.
        stress_k = 0.938194 if self.system == "M" else 0.9743
        return {
            "pitch_dia": d - 0.649519 * p,
            "external_minor": d - 1.226869 * p,
            "internal_minor": d - 1.082532 * p,
            "stress_area": math.pi / 4 * (d - stress_k * p) ** 2,
            "tap_drill": d - p,  # 75% thread engagement rule
        }


def _fmt(value):
    return f"{value:g}"


def _fraction(text):
    num, den = text.split("/")
    if int(den) == 0:
        raise ThreadError(f"bad fraction '{text}'")
    return int(num) / int(den)


def _inch_diameter(size):
    if size.startswith("#"):
        return 0.060 + 0.013 * int(size[1:])
    if " " in size:
        whole, frac = size.split()
        return int(whole) + _fraction(frac)
    if "/" in size:
        return _fraction(size)
    return float(size)


def parse_designation(text):
    """Turn 'M8', 'M8x1', '1/4-20 UNC' or '#10-32 UNF' into a Thread."""
    s = " ".join(text.split())
    m = re.fullmatch(r"[Mm](\d+(?:\.\d+)?)(?:[xX](\d+(?:\.\d+)?))?", s)
    if m:
        major = float(m.group(1))
        if m.group(2):
            pitch = float(m.group(2))
        elif major in COARSE_PITCH:
            pitch = COARSE_PITCH[major]
        else:
            raise ThreadError(f"no standard coarse pitch for M{m.group(1)}; "
                              f"write it as M{m.group(1)}x<pitch>")
        if pitch <= 0 or pitch >= major:
            raise ThreadError(f"pitch {pitch} is out of range for M{m.group(1)}")
        return Thread("M", f"M{_fmt(major)}x{_fmt(pitch)}", major, pitch)

    m = re.fullmatch(r"(#\d+|\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)\s*-\s*(\d+)\s*(UNC|UNF)?",
                     s, re.IGNORECASE)
    if m:
        size, tpi = m.group(1), int(m.group(2))
        cls = (m.group(3) or "UNC").upper()
        if tpi <= 0:
            raise ThreadError(f"threads per inch must be positive in '{s}'")
        major = _inch_diameter(size) * INCH
        if major <= 0:
            raise ThreadError(f"diameter must be positive in '{s}'")
        return Thread("UN", f"{size}-{tpi} {cls}", major, INCH / tpi)

    raise ThreadError(f"unrecognised thread designation '{s}'")


def parse_length(text):
    """'20' or '20mm' gives millimetres; '0.75in' is converted."""
    m = re.fullmatch(r"(\d+(?:\.\d+)?)(mm|in)?", text, re.IGNORECASE)
    if not m:
        raise ThreadError(f"bad length '{text}'")
    value = float(m.group(1))
    return value * INCH if (m.group(2) or "").lower() == "in" else value


def parse_force(text):
    """'9kN', '300N' or '1500lbf' gives newtons."""
    m = re.fullmatch(r"(\d+(?:\.\d+)?)(N|kN|lbf)?", text, re.IGNORECASE)
    if not m:
        raise ThreadError(f"bad force '{text}'")
    value = float(m.group(1))
    unit = (m.group(2) or "N").lower()
    return {"n": value, "kn": value * 1000.0, "lbf": value * LBF}[unit]


def clearance(thread, fit):
    """ISO 273 clearance hole (mm) for metric threads, None for unified."""
    if thread.system != "M" or thread.major not in CLEARANCE:
        return None
    return CLEARANCE[thread.major][FITS.index(fit)]


@dataclass
class Entry:
    line: int
    thread: Thread
    grade: str
    material: str
    depth: float
    fit: str
    load: float


def _parse_line(body, lineno):
    words, opts = [], {}
    for tok in body.split():
        if "=" not in tok:
            words.append(tok)
            continue
        key, _, value = tok.partition("=")
        key = key.lower()
        if key not in OPTION_KEYS:
            raise ThreadError(f"unknown option '{key}' (expected {', '.join(OPTION_KEYS)})")
        if key in opts:
            raise ThreadError(f"duplicate option '{key}'")
        if not value:
            raise ThreadError(f"option '{key}' has no value")
        opts[key] = value
    if not words:
        raise ThreadError("missing thread designation")
    thread = parse_designation(" ".join(words))

    material = ALIASES.get(opts.get("material", "steel").lower(), opts.get("material", "steel").lower())
    if material not in ENGAGEMENT:
        raise ThreadError(f"unknown material '{opts['material']}'")
    fit = opts.get("fit", "medium").lower()
    if fit not in FITS:
        raise ThreadError(f"unknown fit '{opts['fit']}' (use fine, medium or coarse)")
    grade = None
    if "grade" in opts:
        grade = opts["grade"].upper()
        if grade not in GRADES:
            raise ThreadError(f"unknown grade '{opts['grade']}'")
        if GRADES[grade][0] != thread.system:
            raise ThreadError(f"grade {opts['grade']} does not suit thread {thread.name}")
    depth = parse_length(opts["depth"]) if "depth" in opts else None
    if depth is not None and depth <= 0:
        raise ThreadError("depth must be positive")
    load = parse_force(opts["load"]) if "load" in opts else None
    if load is not None and load <= 0:
        raise ThreadError("load must be positive")
    return Entry(lineno, thread, grade, material, depth, fit, load)


def parse_plan(text):
    """Return (entries, errors). Lines starting after ';' are comments."""
    entries, errors = [], []
    for lineno, raw in enumerate(text.splitlines(), 1):
        body = raw.split(";", 1)[0].strip()
        if not body:
            continue
        try:
            entries.append(_parse_line(body, lineno))
        except ThreadError as exc:
            errors.append(ThreadError(exc.message, lineno))
    return entries, errors


def analyse(entry):
    t = entry.thread
    row = {"line": entry.line, "thread": t.name, "system": t.system, "pitch": t.pitch,
           **t.geometry(), "clearance": clearance(t, entry.fit), "fit": entry.fit,
           "material": entry.material, "grade": entry.grade, "depth": entry.depth,
           "engage_needed": ENGAGEMENT[entry.material] * t.major,
           "engage_ok": None, "load": entry.load,
           "proof_load": None, "safety_factor": None}
    if entry.depth is not None:
        row["engage_ok"] = entry.depth >= row["engage_needed"]
    if entry.grade:
        row["proof_load"] = row["stress_area"] * GRADES[entry.grade][1]
        if entry.load:
            row["safety_factor"] = row["proof_load"] / entry.load
    return row


def gate_problems(row, min_sf):
    out = []
    if row["engage_ok"] is False:
        out.append(f"engagement {row['depth']:.2f} mm below {row['engage_needed']:.2f} mm needed")
    sf = row["safety_factor"]
    if sf is not None and sf < min_sf:
        out.append(f"safety factor {sf:.2f} below {min_sf:.2f}")
    return out


# Report columns: (label, key, kind). Kind decides units and formatting.
COLUMNS = [
    ("Thread", "thread", "text"), ("Pitch", "pitch", "len"),
    ("Pitch dia", "pitch_dia", "len"), ("Ext minor", "external_minor", "len"),
    ("Int minor", "internal_minor", "len"), ("Tap drill", "tap_drill", "len"),
    ("Clearance", "clearance", "len"), ("Stress area", "stress_area", "area"),
    ("Eng need", "engage_needed", "len"), ("Depth", "depth", "len"),
    ("Proof", "proof_load", "force"), ("SF", "safety_factor", "num"),
]


def _unit_label(kind, units):
    return {"len": units, "area": f"{units}2", "force": "lbf" if units == "in" else "N",
            "num": "", "text": ""}[kind]


def _cell(value, kind, units):
    if value is None:
        return "-"
    if kind == "text":
        return str(value)
    if kind == "len":
        return f"{value / INCH:.4f}" if units == "in" else f"{value:.3f}"
    if kind == "area":
        return f"{value / INCH ** 2:.5f}" if units == "in" else f"{value:.2f}"
    if kind == "force":
        return f"{value / LBF:.1f}" if units == "in" else f"{value:.0f}"
    return f"{value:.2f}"


def _table(rows, units):
    headers = [f"{label} ({_unit_label(kind, units)})".replace(" ()", "")
               for label, _, kind in COLUMNS]
    body = [[_cell(r[key], kind, units) for _, key, kind in COLUMNS] for r in rows]
    widths = [max(len(h), *(len(b[i]) for b in body)) if body else len(h)
              for i, h in enumerate(headers)]
    lines = ["  ".join(h.ljust(w) for h, w in zip(headers, widths)),
             "  ".join("-" * w for w in widths)]
    lines += ["  ".join(c.ljust(w) for c, w in zip(b, widths)) for b in body]
    return "\n".join(lines)


def _read(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError as exc:
        print(f"threadfit: cannot read {path}: {exc.strerror}", file=sys.stderr)
        return None


def _load_entries(path):
    text = _read(path)
    if text is None:
        return None, None
    return parse_plan(text)


def _report_errors(path, errors):
    for err in errors:
        print(f"{path}:{err.line}: error: {err.message}")


def cmd_show(args):
    try:
        thread = parse_designation(args.designation)
    except ThreadError as exc:
        print(f"threadfit: {exc.message}", file=sys.stderr)
        return 1
    row = analyse(Entry(0, thread, None, "steel", None, args.fit, None))
    if args.json:
        print(json.dumps(row, indent=2))
        return 0
    for label, key, kind in COLUMNS:
        unit = _unit_label(kind, args.units)
        suffix = f" ({unit})" if unit else ""
        print(f"{label + suffix:<22}{_cell(row[key], kind, args.units)}")
    print(f"{'Engagement (steel)':<22}{_cell(row['engage_needed'], 'len', args.units)}"
          f" ({args.units})")
    return 0


def cmd_list(_args):
    print("Metric coarse sizes (ISO 262):")
    print("  " + ", ".join(f"M{_fmt(d)}x{_fmt(p)}" for d, p in COARSE_PITCH.items()))
    print("Unified sizes: any N-TPI pair, e.g. 1/4-20 UNC, 5/16-18 UNF, #10-32 UNF")
    print("Clearance fits (ISO 273): " + ", ".join(FITS) + " (metric only)")
    print("Grades: " + ", ".join(f"{g} ({fam})" for g, (fam, _) in GRADES.items()))
    print("Materials: " + ", ".join(f"{m} ({f}x d)" for m, f in ENGAGEMENT.items()))
    return 0


def cmd_lint(args):
    entries, errors = _load_entries(args.file)
    if entries is None:
        return 1
    _report_errors(args.file, errors)
    print(f"{args.file}: {len(entries)} entries, {len(errors)} errors")
    return 1 if errors else 0


def cmd_report(args):
    entries, errors = _load_entries(args.file)
    if entries is None:
        return 1
    if errors:
        _report_errors(args.file, errors)
        return 1
    rows = [analyse(e) for e in entries]
    print(_table(rows, args.units))
    if args.csv:
        with open(args.csv, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else [])
            writer.writeheader()
            writer.writerows(rows)
        print(f"wrote {len(rows)} rows to {args.csv} (SI units)")
    return 0


def cmd_check(args):
    entries, errors = _load_entries(args.file)
    if entries is None:
        return 1
    if errors:
        _report_errors(args.file, errors)
        return 1
    failed = 0
    for entry in entries:
        row = analyse(entry)
        for problem in gate_problems(row, args.min_sf):
            failed += 1
            print(f"{args.file}:{row['line']}: fail: {row['thread']}: {problem}")
    if failed:
        print(f"{args.file}: {failed} check(s) failed")
        return 2
    print(f"{args.file}: all {len(entries)} entries pass (min SF {args.min_sf:g})")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog="threadfit", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("show", help="geometry for one designation")
    p.add_argument("designation")
    p.add_argument("--fit", choices=FITS, default="medium")
    p.add_argument("--units", choices=("mm", "in"), default="mm")
    p.add_argument("--json", action="store_true", help="print raw SI values as JSON")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("list", help="supported sizes, grades and materials")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("lint", help="check a plan file for syntax errors")
    p.add_argument("file")
    p.set_defaults(func=cmd_lint)

    p = sub.add_parser("report", help="table of geometry and loads for a plan file")
    p.add_argument("file")
    p.add_argument("--units", choices=("mm", "in"), default="mm")
    p.add_argument("--csv", metavar="PATH", help="also write the rows as CSV (SI units)")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("check", help="CI gate: engagement and safety factor, exit 2 on failure")
    p.add_argument("file")
    p.add_argument("--min-sf", type=float, default=MIN_SF_DEFAULT)
    p.set_defaults(func=cmd_check)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
