# 🔩 Threadfit

**Offline screw-thread calculator: geometry, tap drills, clearance holes, engagement and bolt safety, from one plain-text plan.**

Threadfit reads a short plan of bolts and tapped holes, works out the thread geometry for each one, and tells you whether the engagement and safety factor pass your limits. It runs entirely on your machine with the Python standard library: no network, no accounts, no API keys.

## Features

- **Metric designations** — `M8`, `M8x1`, `M10x1.25`, with ISO 262 coarse pitches filled in automatically.
- **Unified inch designations** — `1/4-20 UNC`, `5/16-18 UNF`, `1 1/4-7 UNC`, `#10-32 UNF`.
- **Pitch and diameter geometry** — pitch diameter, external and internal minor diameters, computed from the standard thread formulas.
- **Tensile stress area** — ISO 898 metric and unified forms, in mm² or in².
- **Tap drill sizes** — the 75% thread engagement rule, for both metric and unified threads.
- **ISO 273 clearance holes** — fine, medium and coarse for common metric sizes.
- **Thread engagement check** — minimum engagement per material (steel, stainless, brass, cast iron, aluminium, plastic) against the depth you actually have.
- **Proof load and safety factor** — proof strength for grades 4.6 to 12.9 and SAE 2, 5 and 8, against your applied load in N, kN or lbf.
- **Plan files with line-numbered errors** — `file:line: error: …` messages for typos, unknown options, bad grades, and mismatched grade families.
- **Unit switching** — report and show in millimetres or inches.
- **CSV export** — every computed field in SI units, ready for a spreadsheet.
- **CI gate** — `threadfit check` exits `2` when engagement or safety factor fails, and `1` for plan errors.
- **Reference listing** — `threadfit list` prints every supported size, grade, material and fit.

## Quick start

Threadfit needs Python 3.8 or newer. Nothing needs installing.

```bash
python3 threadfit.py lint examples/bench.thr
python3 threadfit.py check examples/bench.thr
```

Output:

```
examples/bench.thr: 6 entries, 0 errors
examples/bench.thr: all 6 entries pass (min SF 1.5)
```

The plan file uses one thread per line. Anything after `;` is a comment.

```
; Bench frame and mounting bolts
; Format: <designation> [grade=] [material=] [depth=] [fit=] [load=]
M8x1.25      grade=8.8   material=steel      depth=20      fit=medium  load=9kN
M6           grade=8.8   material=aluminium  depth=10      fit=fine    load=3kN
M10          grade=10.9  material=cast-iron  depth=16      load=15kN
1/4-20 UNC   grade=SAE5  material=steel      depth=0.75in  load=1500lbf
#10-32 UNF   grade=SAE2  material=brass      depth=0.25in  load=200lbf
M5x0.8       material=plastic depth=12
```

## Usage

```bash
# Geometry for one size (add --units in, --fit coarse, or --json)
python3 threadfit.py show M8

# Table for a whole plan, in inches, also saved as CSV
python3 threadfit.py report examples/bench.thr --units in --csv bench.csv

# Supported sizes, grades, materials and fits
python3 threadfit.py list
```

Plan options:

| Option     | Meaning                                          | Default  |
|------------|--------------------------------------------------|----------|
| `grade`    | Bolt grade: `4.6`, `5.8`, `8.8`, `10.9`, `12.9`, `SAE2`, `SAE5`, `SAE8` | none (no load check) |
| `material` | Material the thread is tapped into               | `steel`  |
| `depth`    | Tapped depth, mm or `in` (e.g. `20` or `0.75in`) | none (no engagement check) |
| `fit`      | Clearance fit for metric holes: `fine`, `medium`, `coarse` | `medium` |
| `load`     | Applied tensile load per bolt: `N`, `kN` or `lbf` | none (no safety factor) |

### Exit codes

| Command | 0               | 1                     | 2                              |
|---------|-----------------|-----------------------|--------------------------------|
| `lint`  | no syntax errors | syntax errors or unreadable file | —                    |
| `report`| table printed   | syntax errors or unreadable file | —                    |
| `check` | all entries pass | syntax errors or unreadable file | engagement or safety factor fails |

`check --min-sf 2` raises the safety factor bar; the default is 1.5.

## Notes on the numbers

- Metric and unified geometry use the standard thread formulas (for example, pitch diameter = d − 0.649519·P).
- Tap drills use the simple 75% rule: nominal diameter minus one pitch. Check the drill chart for your specific tap.
- Engagement minimums are rules of thumb expressed as multiples of the nominal diameter. Use your own design code where it applies, and override by editing `ENGAGEMENT` in `threadfit.py`.
- Clearance holes come from ISO 273 and are only given for metric sizes M3 to M12.

## Run

Threadfit is one file, so run it in place:

```bash
python3 threadfit.py <command> [options]
```

Or import it from Python:

```python
import threadfit

entries, errors = threadfit.parse_plan(open("examples/bench.thr").read())
rows = [threadfit.analyse(e) for e in entries]
```

## Test

The tests use pytest and cover parsing, geometry against handbook values, plan line-numbered errors, engagement and safety-factor gates, and the CLI exit codes.

```bash
python3 -m pytest -q
```

## Project layout

```
threadfit.py              the whole tool: parser, geometry, checks and CLI
examples/bench.thr        a sample plan that passes every check
tests/conftest.py         puts the project root on the import path
tests/test_threadfit.py   unit and CLI tests
README.md
```
