"""Exact Arabic orthographic search; no stemming, guesswork or fuzzy matches."""
from pathlib import Path
from api.warehouse.live_stock import _normalize_live_stock_search

def test_fold_equivalent_forms_without_unrelated_expansion():
    normalize = _normalize_live_stock_search
    assert normalize("ارز") == normalize("أرز") == normalize("إرز") == normalize("آرز")
    assert normalize("أَرُز") == normalize("ارز")
    assert normalize("أرز بسمتي اقتصادي 2 لتر") == "ارز بسمتي اقتصادي 2 لتر"
    assert normalize("أرز بسمتي") != normalize("أرز قصير")
    assert normalize("ارز") != normalize("عدس")
    assert normalize("موز") != normalize("رز")
    assert normalize("SKU-100") == "sku-100"

def test_sql_sparse_and_broad_paths_use_identical_normalized_name():
    root = Path(__file__).resolve().parents[1]
    source = (root / "api" / "warehouse" / "live_stock.py").read_text(encoding="utf-8")
    migration = (root / "alembic" / "versions" / "c9a1e4d7b630_live_stock_arabic_exact_name_search.py").read_text(encoding="utf-8")
    assert "live_stock_normalize_arabic(ProductVariant.name)" in source
    assert "strpos(searchable_text, token) > 0" in source
    assert "live_stock_search_variant_ids(" in source
    assert "live_stock_normalize_arabic((pv.name)::text) LIKE" in migration
    assert "pv.company_id = $1" in migration
    assert "expected_company_id IS DISTINCT FROM tenant_id" in migration
    assert "SET row_security = off" in migration
    assert "CREATE INDEX CONCURRENTLY" in migration
    assert "pg_catalog.btrim(search_pattern, '%')" in migration
    assert "searchable_text.op(\"~\")" in source
    assert "REVOKE ALL ON FUNCTION public.live_stock_normalize_arabic" in migration
