from pathlib import Path


SOURCE = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "seed_live_stock_scale.py"
).read_text(encoding="utf-8")


def test_synthetic_reservations_are_explicit_opt_in():
    assert '"--synthetic-reservations"' in SOURCE
    assert 'action="store_true"' in SOURCE
    assert "include_synthetic_reservations=args.synthetic_reservations" in SOURCE
    assert "WHEN :include_synthetic_reservations AND r.rn % 5 = 0 THEN 100" in SOURCE
