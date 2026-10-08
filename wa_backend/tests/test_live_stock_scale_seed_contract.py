from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
SOURCE = (SCRIPTS / "seed_live_stock_scale.py").read_text(encoding="utf-8")
PROVENANCE_SOURCE = (SCRIPTS / "live_stock_scale_provenance.py").read_text(encoding="utf-8")


def test_synthetic_reservations_are_explicit_opt_in():
    assert '"--synthetic-reservations"' in SOURCE
    assert 'action="store_true"' in SOURCE
    assert "include_synthetic_reservations=args.synthetic_reservations" in SOURCE
    assert "WHEN :include_synthetic_reservations AND r.rn % 5 = 0 THEN 100" in SOURCE


def test_business_provenance_is_seeded_and_repairable():
    assert '"--repair-hot-provenance"' in SOURCE
    assert "seed_hot_business_provenance(" in SOURCE
    assert "inventory_supplier_evidence" in PROVENANCE_SOURCE
    assert "inventory_cost_layers" in PROVENANCE_SOURCE
    assert "HOT_INBOUND_KEY_PREFIX" in PROVENANCE_SOURCE
