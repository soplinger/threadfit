import os

import pytest

import threadfit as tf

EXAMPLE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "examples", "bench.thr")


def test_metric_default_coarse_pitch():
    t = tf.parse_designation("M8")
    assert t.name == "M8x1.25"
    assert t.pitch == pytest.approx(1.25)


def test_metric_explicit_fine_pitch():
    t = tf.parse_designation("M8x1")
    assert t.pitch == 1.0


def test_metric_without_standard_pitch_is_rejected():
    with pytest.raises(tf.ThreadError, match="no standard coarse pitch"):
        tf.parse_designation("M7")


def test_unified_inch_thread_converts_to_mm():
    t = tf.parse_designation("1/4-20 UNC")
    assert t.major == pytest.approx(6.35)
    assert t.pitch == pytest.approx(25.4 / 20)


def test_unified_number_size_uses_gauge_formula():
    t = tf.parse_designation("#10-32 UNF")
    assert t.major == pytest.approx(0.190 * 25.4)


def test_bad_designation_is_rejected():
    with pytest.raises(tf.ThreadError, match="unrecognised"):
        tf.parse_designation("widget")


def test_m8_geometry_matches_handbook_values():
    g = tf.parse_designation("M8x1.25").geometry()
    assert g["pitch_dia"] == pytest.approx(7.188, abs=0.001)
    assert g["external_minor"] == pytest.approx(6.466, abs=0.001)
    assert g["stress_area"] == pytest.approx(36.6, abs=0.1)


def test_unified_stress_area_matches_handbook_in2():
    g = tf.parse_designation("1/4-20 UNC").geometry()
    assert g["stress_area"] / tf.INCH ** 2 == pytest.approx(0.0318, abs=0.0002)


def test_tap_drill_uses_75_percent_rule():
    assert tf.parse_designation("M8").geometry()["tap_drill"] == pytest.approx(6.75)


def test_iso_273_clearance_holes():
    m8 = tf.parse_designation("M8")
    assert tf.clearance(m8, "fine") == pytest.approx(8.4)
    assert tf.clearance(m8, "medium") == pytest.approx(9.0)
    assert tf.clearance(m8, "coarse") == pytest.approx(10.0)
    assert tf.clearance(tf.parse_designation("1/4-20 UNC"), "medium") is None


def test_length_and_force_units():
    assert tf.parse_length("20") == 20
    assert tf.parse_length("1in") == pytest.approx(25.4)
    assert tf.parse_force("9kN") == 9000
    assert tf.parse_force("1000lbf") == pytest.approx(4448.2216)
    with pytest.raises(tf.ThreadError):
        tf.parse_length("twenty")


def test_plan_errors_carry_line_numbers():
    text = "M8 grade=8.8\nM8 colour=red\nM10 grade=8.8 grade=8.8\n\nM8 material=wood\n"
    entries, errors = tf.parse_plan(text)
    assert len(entries) == 1
    assert [(e.line, e.message) for e in errors] == [
        (2, "unknown option 'colour' (expected grade, material, depth, fit, load)"),
        (3, "duplicate option 'grade'"),
        (5, "unknown material 'wood'"),
    ]


def test_plan_ignores_comments_and_blank_lines():
    entries, errors = tf.parse_plan("; header\n\nM6 ; trailing note\n")
    assert errors == []
    assert [e.line for e in entries] == [3]


def test_grade_must_match_thread_family():
    _, errors = tf.parse_plan("1/4-20 UNC grade=8.8\n")
    assert errors and "does not suit" in errors[0].message


def test_engagement_failure_is_flagged():
    entries, _ = tf.parse_plan("M10 material=cast-iron depth=12\n")
    row = tf.analyse(entries[0])
    assert row["engage_needed"] == pytest.approx(15.0)
    assert row["engage_ok"] is False
    assert any("engagement" in p for p in tf.gate_problems(row, 1.5))


def test_safety_factor_is_proof_over_load():
    entries, _ = tf.parse_plan("M8 grade=8.8 load=9kN\n")
    row = tf.analyse(entries[0])
    assert row["proof_load"] == pytest.approx(36.6 * 600, abs=60)
    assert row["safety_factor"] == pytest.approx(row["proof_load"] / 9000)
    assert any("safety factor" in p for p in tf.gate_problems(row, 3.0))
    assert tf.gate_problems(row, 1.5) == []


def test_cli_lint_exit_codes(tmp_path, capsys):
    assert tf.main(["lint", EXAMPLE]) == 0
    bad = tmp_path / "bad.thr"
    bad.write_text("M8 grade=99\n", encoding="utf-8")
    assert tf.main(["lint", str(bad)]) == 1
    assert f"{bad}:1: error: unknown grade" in capsys.readouterr().out


def test_cli_check_gate_fails_on_low_safety_factor(tmp_path, capsys):
    plan = tmp_path / "weak.thr"
    plan.write_text("M8 grade=4.6 load=9kN\n", encoding="utf-8")
    assert tf.main(["check", str(plan)]) == 2
    assert "safety factor" in capsys.readouterr().out


def test_cli_check_passes_example_file(capsys):
    assert tf.main(["check", EXAMPLE]) == 0
    assert "all 6 entries pass" in capsys.readouterr().out


def test_cli_report_writes_csv(tmp_path, capsys):
    out = tmp_path / "rows.csv"
    assert tf.main(["report", EXAMPLE, "--units", "in", "--csv", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    assert text.splitlines()[0].startswith("line,thread,system,pitch")
    assert "M8x1.25" in capsys.readouterr().out


def test_cli_show_json(capsys):
    assert tf.main(["show", "M10", "--json"]) == 0
    assert '"stress_area"' in capsys.readouterr().out
