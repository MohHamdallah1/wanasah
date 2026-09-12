from __future__ import annotations

import argparse
import ast
import hashlib
import shutil
import subprocess
from pathlib import Path

MARKER = "STAGE4C_SYNCHRONOUS_BATCH_ELIGIBILITY"

EXPECTED_HASHES = {'services.py': '691a92f10807961d0f079066d10d1676e207c1e0bb8c3cb8afeb69cb75b3d85a',
 'api/warehouse.py': '63ce90da13bd78fe9ee3fe4fe2e12110630f725f2c3a561fb454a40e2a3829f3',
 'api/dispatch.py': 'dced03e6c2125afd801a093dbf08ab8680867fcb8f4f1d4161000f105b7d740a'}

EXPECTED_FINAL_HASHES = {'services.py': '66a876452987fa40d8b87e442e599a5991708633d8a41fcf20edcc13fadf79b2',
 'api/warehouse.py': 'e8778bd9ada4ae4c53ec0edcadde88f99c3cf2fbdc7f6c5191317ac78d78b9b6'}

OPS_SERVICES = [('def warehouse_setup_required_detail() -> Dict[str, Any]:\n'
  '    return inventory_business_error(\n'
  '        "WAREHOUSE_SETUP_REQUIRED",\n'
  '        "يجب إنشاء مستودع فعال قبل تنفيذ هذه العملية.",\n'
  '    )\n'
  '\n'
  '\n',
  'def warehouse_setup_required_detail() -> Dict[str, Any]:\n'
  '    return inventory_business_error(\n'
  '        "WAREHOUSE_SETUP_REQUIRED",\n'
  '        "يجب إنشاء مستودع فعال قبل تنفيذ هذه العملية.",\n'
  '    )\n'
  '\n'
  '\n'
  '# PATCH: STAGE4C_SYNCHRONOUS_BATCH_ELIGIBILITY\n'
  'def batch_sellability_predicate(\n'
  '    as_of_date: date,\n'
  '    *,\n'
  '    expiry_control_mode,\n'
  '    minimum_remaining_shelf_life_days=None,\n'
  '):\n'
  '    """SQL predicate موحد لصلاحية Batch للبيع/التحميل/الحوالة العادية."""\n'
  '    if type(as_of_date) is not date:\n'
  '        raise ValueError("as_of_date يجب أن يكون date صريحاً.")\n'
  '\n'
  '    min_days = (\n'
  '        func.coalesce(minimum_remaining_shelf_life_days, 0)\n'
  '        if minimum_remaining_shelf_life_days is not None\n'
  '        else 0\n'
  '    )\n'
  '    expiry_meets_policy = and_(\n'
  '        ProductBatch.expiry_date.is_not(None),\n'
  '        (ProductBatch.expiry_date - as_of_date) >= min_days,\n'
  '    )\n'
  '    no_expiry_allowed = and_(\n'
  '        ProductBatch.expiry_date.is_(None),\n'
  '        min_days == 0,\n'
  '    )\n'
  '\n'
  '    return and_(\n'
  '        ProductBatch.is_active.is_(True),\n'
  '        ProductBatch.disposition == "RELEASED",\n'
  '        or_(\n'
  '            ProductBatch.production_date.is_(None),\n'
  '            ProductBatch.production_date <= as_of_date,\n'
  '        ),\n'
  '        or_(\n'
  '            and_(\n'
  '                expiry_control_mode == "NONE",\n'
  '                no_expiry_allowed,\n'
  '            ),\n'
  '            and_(\n'
  '                expiry_control_mode == "OPTIONAL",\n'
  '                or_(no_expiry_allowed, expiry_meets_policy),\n'
  '            ),\n'
  '            and_(\n'
  '                expiry_control_mode == "REQUIRED",\n'
  '                expiry_meets_policy,\n'
  '            ),\n'
  '        ),\n'
  '    )\n'
  '\n'
  '\n'
  'def _batch_metadata_is_sellable(\n'
  '    *,\n'
  '    as_of_date: date,\n'
  '    expiry_control_mode: str,\n'
  '    production_date: Optional[date],\n'
  '    expiry_date: Optional[date],\n'
  '    minimum_remaining_shelf_life_days: int,\n'
  ') -> bool:\n'
  '    """نفس عقد SQL أعلاه لصفوف Metadata المقفلة داخل FEFO."""\n'
  '    if type(as_of_date) is not date:\n'
  '        raise InventoryMutationError("as_of_date يجب أن يكون date صريحاً.")\n'
  '\n'
  '    mode = str(expiry_control_mode or "").strip().upper()\n'
  '    if mode not in {"NONE", "OPTIONAL", "REQUIRED"}:\n'
  '        raise InventoryMutationError("expiry_control_mode غير صالح للصنف.")\n'
  '\n'
  '    try:\n'
  '        min_days = _strict_int(\n'
  '            minimum_remaining_shelf_life_days,\n'
  '            "minimum_remaining_shelf_life_days",\n'
  '            minimum=0,\n'
  '        )\n'
  '    except ValueError as exc:\n'
  '        raise InventoryMutationError(str(exc)) from exc\n'
  '\n'
  '    if production_date is not None and production_date > as_of_date:\n'
  '        return False\n'
  '\n'
  '    # لا يمكن إثبات Minimum Shelf Life موجب بدون expiry_date؛ نفشل مغلقاً.\n'
  '    if mode == "NONE":\n'
  '        return expiry_date is None and min_days == 0\n'
  '\n'
  '    if expiry_date is None:\n'
  '        return mode == "OPTIONAL" and min_days == 0\n'
  '\n'
  '    return expiry_date >= as_of_date + timedelta(days=min_days)\n'
  '\n'
  '\n',
  'services shared eligibility helpers'),
 ('            select(\n'
  '                ProductVariant.id,\n'
  '                ProductVariant.quantity_scale,\n'
  '                ProductVariant.quantity_step,\n'
  '            ).filter(\n',
  '            select(\n'
  '                ProductVariant.id,\n'
  '                ProductVariant.quantity_scale,\n'
  '                ProductVariant.quantity_step,\n'
  '                ProductVariant.expiry_control_mode,\n'
  '            ).filter(\n',
  'services FEFO expiry mode select'),
 ('    quantity_rules = {\n'
  '        int(row.id): (\n'
  '            int(row.quantity_scale),\n'
  '            row.quantity_step,\n'
  '        )\n'
  '        for row in quantity_rule_rows\n'
  '    }\n',
  '    quantity_rules = {\n'
  '        int(row.id): (\n'
  '            int(row.quantity_scale),\n'
  '            row.quantity_step,\n'
  '            str(row.expiry_control_mode),\n'
  '        )\n'
  '        for row in quantity_rule_rows\n'
  '    }\n',
  'services FEFO quantity rules'),
 ('            ).filter(\n'
  '                InventoryStockPolicy.company_id == company_id,\n'
  '                InventoryStockPolicy.location_id == location_id,\n'
  '                InventoryStockPolicy.product_variant_id.in_(\n'
  '                    requested_variant_ids\n'
  '                ),\n'
  '                InventoryStockPolicy.is_active.is_(True),\n'
  '            )\n'
  '        )\n'
  '    ).all()\n',
  '            ).filter(\n'
  '                InventoryStockPolicy.company_id == company_id,\n'
  '                InventoryStockPolicy.location_id == location_id,\n'
  '                InventoryStockPolicy.product_variant_id.in_(\n'
  '                    requested_variant_ids\n'
  '                ),\n'
  '                InventoryStockPolicy.is_active.is_(True),\n'
  '            ).order_by(\n'
  '                InventoryStockPolicy.product_variant_id.asc()\n'
  '            ).with_for_update(read=True)\n'
  '        )\n'
  '    ).all()\n',
  'services shelf life policy read lock'),
 ('                ProductBatch.is_active.is_(True),\n'
  '                ProductBatch.disposition == "RELEASED",\n'
  '                or_(\n'
  '                    ProductBatch.production_date.is_(None),\n'
  '                    ProductBatch.production_date <= as_of_date,\n'
  '                ),\n'
  '                ProductBatch.expiry_date >= as_of_date,\n'
  '            ).order_by(\n'
  '                InventoryBalance.product_variant_id.asc(),\n'
  '                ProductBatch.expiry_date.asc(),\n'
  '                ProductBatch.id.asc(),\n'
  '            )\n',
  '                ProductBatch.is_active.is_(True),\n'
  '                ProductBatch.disposition == "RELEASED",\n'
  '                or_(\n'
  '                    ProductBatch.production_date.is_(None),\n'
  '                    ProductBatch.production_date <= as_of_date,\n'
  '                ),\n'
  '                or_(\n'
  '                    ProductBatch.expiry_date.is_(None),\n'
  '                    ProductBatch.expiry_date >= as_of_date,\n'
  '                ),\n'
  '            ).order_by(\n'
  '                InventoryBalance.product_variant_id.asc(),\n'
  '                ProductBatch.expiry_date.asc().nulls_last(),\n'
  '                ProductBatch.id.asc(),\n'
  '            )\n',
  'services FEFO candidate eligibility'),
 ('    metadata_pairs = set()\n'
  '    metadata_expiry: Dict[Tuple[int, int], date] = {}\n'
  '\n'
  '    for offset in range(\n'
  '        0,\n'
  '        len(candidate_pairs),\n'
  '        _SQL_BULK_CHUNK_SIZE,\n'
  '    ):\n'
  '        chunk = candidate_pairs[\n'
  '            offset:offset + _SQL_BULK_CHUNK_SIZE\n'
  '        ]\n'
  '        rows = (\n'
  '            await db_session.execute(\n'
  '                select(\n'
  '                    ProductBatch.product_variant_id,\n'
  '                    ProductBatch.id,\n'
  '                    ProductBatch.expiry_date,\n'
  '                ).filter(\n'
  '                    ProductBatch.company_id == company_id,\n'
  '                    tuple_(\n'
  '                        ProductBatch.product_variant_id,\n'
  '                        ProductBatch.id,\n'
  '                    ).in_(chunk),\n'
  '                    ProductBatch.is_active.is_(True),\n'
  '                    ProductBatch.disposition == "RELEASED",\n'
  '                    or_(\n'
  '                        ProductBatch.production_date.is_(None),\n'
  '                        ProductBatch.production_date <= as_of_date,\n'
  '                    ),\n'
  '                    ProductBatch.expiry_date >= as_of_date,\n'
  '                ).order_by(\n'
  '                    ProductBatch.product_variant_id.asc(),\n'
  '                    ProductBatch.expiry_date.asc(),\n'
  '                    ProductBatch.id.asc(),\n'
  '                ).with_for_update(read=True)\n'
  '            )\n'
  '        ).all()\n'
  '\n'
  '        for variant_id, batch_id, expiry_date in rows:\n'
  '            key = (int(variant_id), int(batch_id))\n'
  '            metadata_pairs.add(key)\n'
  '            metadata_expiry[key] = expiry_date\n'
  '\n'
  '    valid_candidate_pairs = []\n'
  '    for pair in candidate_pairs:\n'
  '        if pair in metadata_pairs:\n'
  '            variant_id = pair[0]\n'
  '            expiry_date = metadata_expiry[pair]\n'
  '            min_days = minimum_shelf_life_by_variant.get(variant_id, 0)\n'
  '\n'
  '            if expiry_date >= as_of_date + timedelta(days=min_days):\n'
  '                valid_candidate_pairs.append(pair)\n'
  '    candidate_pairs = valid_candidate_pairs\n',
  '    metadata_pairs = set()\n'
  '    metadata_dates: Dict[\n'
  '        Tuple[int, int],\n'
  '        Tuple[Optional[date], Optional[date]],\n'
  '    ] = {}\n'
  '\n'
  '    for offset in range(\n'
  '        0,\n'
  '        len(candidate_pairs),\n'
  '        _SQL_BULK_CHUNK_SIZE,\n'
  '    ):\n'
  '        chunk = candidate_pairs[\n'
  '            offset:offset + _SQL_BULK_CHUNK_SIZE\n'
  '        ]\n'
  '        rows = (\n'
  '            await db_session.execute(\n'
  '                select(\n'
  '                    ProductBatch.product_variant_id,\n'
  '                    ProductBatch.id,\n'
  '                    ProductBatch.production_date,\n'
  '                    ProductBatch.expiry_date,\n'
  '                ).filter(\n'
  '                    ProductBatch.company_id == company_id,\n'
  '                    tuple_(\n'
  '                        ProductBatch.product_variant_id,\n'
  '                        ProductBatch.id,\n'
  '                    ).in_(chunk),\n'
  '                    ProductBatch.is_active.is_(True),\n'
  '                    ProductBatch.disposition == "RELEASED",\n'
  '                    or_(\n'
  '                        ProductBatch.production_date.is_(None),\n'
  '                        ProductBatch.production_date <= as_of_date,\n'
  '                    ),\n'
  '                    or_(\n'
  '                        ProductBatch.expiry_date.is_(None),\n'
  '                        ProductBatch.expiry_date >= as_of_date,\n'
  '                    ),\n'
  '                ).order_by(\n'
  '                    ProductBatch.product_variant_id.asc(),\n'
  '                    ProductBatch.expiry_date.asc().nulls_last(),\n'
  '                    ProductBatch.id.asc(),\n'
  '                ).with_for_update(read=True)\n'
  '            )\n'
  '        ).all()\n'
  '\n'
  '        for variant_id, batch_id, production_date, expiry_date in rows:\n'
  '            key = (int(variant_id), int(batch_id))\n'
  '            metadata_pairs.add(key)\n'
  '            metadata_dates[key] = (production_date, expiry_date)\n'
  '\n'
  '    valid_candidate_pairs = []\n'
  '    for pair in candidate_pairs:\n'
  '        if pair not in metadata_pairs:\n'
  '            continue\n'
  '\n'
  '        variant_id = pair[0]\n'
  '        production_date, expiry_date = metadata_dates[pair]\n'
  '        expiry_control_mode = quantity_rules[variant_id][2]\n'
  '        min_days = minimum_shelf_life_by_variant.get(variant_id, 0)\n'
  '\n'
  '        if _batch_metadata_is_sellable(\n'
  '            as_of_date=as_of_date,\n'
  '            expiry_control_mode=expiry_control_mode,\n'
  '            production_date=production_date,\n'
  '            expiry_date=expiry_date,\n'
  '            minimum_remaining_shelf_life_days=min_days,\n'
  '        ):\n'
  '            valid_candidate_pairs.append(pair)\n'
  '    candidate_pairs = valid_candidate_pairs\n',
  'services locked metadata revalidation'),
 ('    balance_rows.sort(\n'
  '        key=lambda balance: (\n'
  '            int(balance.product_variant_id),\n'
  '            metadata_expiry[\n'
  '                (\n'
  '                    int(balance.product_variant_id),\n'
  '                    int(balance.batch_id),\n'
  '                )\n'
  '            ],\n'
  '            int(balance.batch_id),\n'
  '        )\n'
  '    )\n',
  '    balance_rows.sort(\n'
  '        key=lambda balance: (\n'
  '            int(balance.product_variant_id),\n'
  '            metadata_dates[\n'
  '                (\n'
  '                    int(balance.product_variant_id),\n'
  '                    int(balance.batch_id),\n'
  '                )\n'
  '            ][1] is None,\n'
  '            metadata_dates[\n'
  '                (\n'
  '                    int(balance.product_variant_id),\n'
  '                    int(balance.batch_id),\n'
  '                )\n'
  '            ][1] or date.max,\n'
  '            int(balance.batch_id),\n'
  '        )\n'
  '    )\n',
  'services nullable expiry ordering'),
 ('            f"الرصيد FEFO غير المقفل وغير المنتهي لا يغطي الصنف ({first_variant}). "\n',
  '            f"الرصيد FEFO المؤهل وغير المقفل لا يغطي الصنف ({first_variant}). "\n',
  'services FEFO shortage message')]

OPS_WAREHOUSE = [('    post_approved_stocktake_adjustments,\n    allocate_fefo_inventory_batch,\n    get_company_local_date,\n',
  '    post_approved_stocktake_adjustments,\n'
  '    allocate_fefo_inventory_batch,\n'
  '    batch_sellability_predicate,\n'
  '    get_company_local_date,\n',
  'warehouse helper import'),
 ('router = APIRouter()\n\n\n',
  'router = APIRouter()\n\n# PATCH: STAGE4C_SYNCHRONOUS_BATCH_ELIGIBILITY\n\n',
  'warehouse marker'),
 ('        batch_is_sellable = and_(\n'
  '            ProductBatch.is_active.is_(True),\n'
  '            or_(\n'
  '                ProductBatch.production_date.is_(None),\n'
  '                ProductBatch.production_date <= as_of_date,\n'
  '            ),\n'
  '            ProductBatch.expiry_date >= as_of_date,\n'
  '        )\n',
  '        batch_is_sellable = batch_sellability_predicate(\n'
  '            as_of_date,\n'
  '            expiry_control_mode=ProductVariant.expiry_control_mode,\n'
  '            minimum_remaining_shelf_life_days=(\n'
  '                InventoryStockPolicy.minimum_remaining_shelf_life_days\n'
  '            ),\n'
  '        )\n',
  'warehouse live stock predicate'),
 ('                .join(\n'
  '                    ProductBatch,\n'
  '                    and_(\n'
  '                        ProductBatch.company_id\n'
  '                        == InventoryBalance.company_id,\n'
  '                        ProductBatch.product_variant_id\n'
  '                        == InventoryBalance.product_variant_id,\n'
  '                        ProductBatch.id == InventoryBalance.batch_id,\n'
  '                    ),\n'
  '                )\n'
  '                .filter(\n'
  '                    InventoryBalance.company_id == company_id,\n'
  '                    InventoryBalance.location_id == location_id,\n'
  "                    InventoryBalance.stock_status == 'AVAILABLE',\n"
  '                    batch_is_sellable,\n'
  '                )\n',
  '                .join(\n'
  '                    ProductBatch,\n'
  '                    and_(\n'
  '                        ProductBatch.company_id\n'
  '                        == InventoryBalance.company_id,\n'
  '                        ProductBatch.product_variant_id\n'
  '                        == InventoryBalance.product_variant_id,\n'
  '                        ProductBatch.id == InventoryBalance.batch_id,\n'
  '                    ),\n'
  '                )\n'
  '                .join(\n'
  '                    ProductVariant,\n'
  '                    and_(\n'
  '                        ProductVariant.company_id\n'
  '                        == InventoryBalance.company_id,\n'
  '                        ProductVariant.id\n'
  '                        == InventoryBalance.product_variant_id,\n'
  '                    ),\n'
  '                )\n'
  '                .outerjoin(\n'
  '                    InventoryStockPolicy,\n'
  '                    and_(\n'
  '                        InventoryStockPolicy.company_id\n'
  '                        == InventoryBalance.company_id,\n'
  '                        InventoryStockPolicy.location_id == location_id,\n'
  '                        InventoryStockPolicy.product_variant_id\n'
  '                        == InventoryBalance.product_variant_id,\n'
  '                        InventoryStockPolicy.is_active.is_(True),\n'
  '                    ),\n'
  '                )\n'
  '                .filter(\n'
  '                    InventoryBalance.company_id == company_id,\n'
  '                    InventoryBalance.location_id == location_id,\n'
  "                    InventoryBalance.stock_status == 'AVAILABLE',\n"
  '                    batch_is_sellable,\n'
  '                )\n',
  'warehouse alert eligibility joins'),
 ('            .join(\n'
  '                ProductBatch,\n'
  '                and_(\n'
  '                    ProductBatch.company_id\n'
  '                    == InventoryBalance.company_id,\n'
  '                    ProductBatch.product_variant_id\n'
  '                    == InventoryBalance.product_variant_id,\n'
  '                    ProductBatch.id == InventoryBalance.batch_id,\n'
  '                ),\n'
  '            )\n'
  '            .filter(\n'
  '                InventoryBalance.company_id == company_id,\n'
  '                InventoryBalance.location_id == location_id,\n'
  "                InventoryBalance.stock_status == 'AVAILABLE',\n"
  '                InventoryBalance.product_variant_id.in_(\n'
  '                    page_variant_ids\n'
  '                ),\n'
  '            )\n',
  '            .join(\n'
  '                ProductBatch,\n'
  '                and_(\n'
  '                    ProductBatch.company_id\n'
  '                    == InventoryBalance.company_id,\n'
  '                    ProductBatch.product_variant_id\n'
  '                    == InventoryBalance.product_variant_id,\n'
  '                    ProductBatch.id == InventoryBalance.batch_id,\n'
  '                ),\n'
  '            )\n'
  '            .join(\n'
  '                ProductVariant,\n'
  '                and_(\n'
  '                    ProductVariant.company_id\n'
  '                    == InventoryBalance.company_id,\n'
  '                    ProductVariant.id\n'
  '                    == InventoryBalance.product_variant_id,\n'
  '                ),\n'
  '            )\n'
  '            .outerjoin(\n'
  '                InventoryStockPolicy,\n'
  '                and_(\n'
  '                    InventoryStockPolicy.company_id\n'
  '                    == InventoryBalance.company_id,\n'
  '                    InventoryStockPolicy.location_id == location_id,\n'
  '                    InventoryStockPolicy.product_variant_id\n'
  '                    == InventoryBalance.product_variant_id,\n'
  '                    InventoryStockPolicy.is_active.is_(True),\n'
  '                ),\n'
  '            )\n'
  '            .filter(\n'
  '                InventoryBalance.company_id == company_id,\n'
  '                InventoryBalance.location_id == location_id,\n'
  "                InventoryBalance.stock_status == 'AVAILABLE',\n"
  '                InventoryBalance.product_variant_id.in_(\n'
  '                    page_variant_ids\n'
  '                ),\n'
  '            )\n',
  'warehouse live stock eligibility joins'),
 ('    sellable_batch = and_(\n'
  '        ProductBatch.company_id == InventoryBalance.company_id,\n'
  '        ProductBatch.product_variant_id\n'
  '        == InventoryBalance.product_variant_id,\n'
  '        ProductBatch.id == InventoryBalance.batch_id,\n'
  '        ProductBatch.is_active.is_(True),\n'
  '        or_(\n'
  '            ProductBatch.production_date.is_(None),\n'
  '            ProductBatch.production_date <= as_of_date,\n'
  '        ),\n'
  '        ProductBatch.expiry_date >= as_of_date,\n'
  '    )\n',
  '    sellable_batch_join = and_(\n'
  '        ProductBatch.company_id == InventoryBalance.company_id,\n'
  '        ProductBatch.product_variant_id\n'
  '        == InventoryBalance.product_variant_id,\n'
  '        ProductBatch.id == InventoryBalance.batch_id,\n'
  '    )\n'
  '    sellable_batch = batch_sellability_predicate(\n'
  '        as_of_date,\n'
  '        expiry_control_mode=ProductVariant.expiry_control_mode,\n'
  '        minimum_remaining_shelf_life_days=(\n'
  '            InventoryStockPolicy.minimum_remaining_shelf_life_days\n'
  '        ),\n'
  '    )\n',
  'transfer source predicate'),
 ('        .join(\n'
  '            ProductBatch,\n'
  '            sellable_batch,\n'
  '        )\n'
  '        .join(UOM, UOM.id == ProductVariant.base_uom_id)\n',
  '        .join(\n'
  '            ProductBatch,\n'
  '            sellable_batch_join,\n'
  '        )\n'
  '        .join(UOM, UOM.id == ProductVariant.base_uom_id)\n',
  'transfer source batch join'),
 ('        .join(\n'
  '            ProductLocation,\n'
  '            and_(\n'
  '                ProductLocation.company_id == ProductVariant.company_id,\n'
  '                ProductLocation.product_variant_id == ProductVariant.id,\n'
  '                ProductLocation.location_id == location_id,\n'
  '            ),\n'
  '        )\n'
  '        .filter(\n'
  '            ProductVariant.company_id == company_id,\n'
  '            product_capability_predicate(ProductVariant, WAREHOUSE_BALANCING),\n',
  '        .join(\n'
  '            ProductLocation,\n'
  '            and_(\n'
  '                ProductLocation.company_id == ProductVariant.company_id,\n'
  '                ProductLocation.product_variant_id == ProductVariant.id,\n'
  '                ProductLocation.location_id == location_id,\n'
  '            ),\n'
  '        )\n'
  '        .outerjoin(\n'
  '            InventoryStockPolicy,\n'
  '            and_(\n'
  '                InventoryStockPolicy.company_id\n'
  '                == ProductVariant.company_id,\n'
  '                InventoryStockPolicy.location_id == location_id,\n'
  '                InventoryStockPolicy.product_variant_id\n'
  '                == ProductVariant.id,\n'
  '                InventoryStockPolicy.is_active.is_(True),\n'
  '            ),\n'
  '        )\n'
  '        .filter(\n'
  '            ProductVariant.company_id == company_id,\n'
  '            product_capability_predicate(ProductVariant, WAREHOUSE_BALANCING),\n'
  '            sellable_batch,\n',
  'transfer source policy join'),
 ('            .filter(\n'
  '                ProductBatch.company_id == company_id,\n'
  '                ProductBatch.product_variant_id\n'
  '                == product_variant_id,\n'
  '                ProductBatch.is_active.is_(True),\n'
  '                or_(\n'
  '                    ProductBatch.production_date.is_(None),\n'
  '                    ProductBatch.production_date <= as_of_date,\n'
  '                ),\n'
  '                ProductBatch.expiry_date >= as_of_date,\n'
  '                InventoryBalance.company_id == company_id,\n'
  '                InventoryBalance.location_id == location_id,\n'
  '                InventoryBalance.product_variant_id\n'
  '                == product_variant_id,\n'
  "                InventoryBalance.stock_status == 'AVAILABLE',\n"
  '                ~active_lock_exists,\n'
  '            )\n',
  '            .join(\n'
  '                ProductVariant,\n'
  '                and_(\n'
  '                    ProductVariant.company_id == ProductBatch.company_id,\n'
  '                    ProductVariant.id == ProductBatch.product_variant_id,\n'
  '                ),\n'
  '            )\n'
  '            .outerjoin(\n'
  '                InventoryStockPolicy,\n'
  '                and_(\n'
  '                    InventoryStockPolicy.company_id == ProductBatch.company_id,\n'
  '                    InventoryStockPolicy.location_id == location_id,\n'
  '                    InventoryStockPolicy.product_variant_id\n'
  '                    == ProductBatch.product_variant_id,\n'
  '                    InventoryStockPolicy.is_active.is_(True),\n'
  '                ),\n'
  '            )\n'
  '            .filter(\n'
  '                ProductBatch.company_id == company_id,\n'
  '                ProductBatch.product_variant_id\n'
  '                == product_variant_id,\n'
  '                batch_sellability_predicate(\n'
  '                    as_of_date,\n'
  '                    expiry_control_mode=ProductVariant.expiry_control_mode,\n'
  '                    minimum_remaining_shelf_life_days=(\n'
  '                        InventoryStockPolicy.minimum_remaining_shelf_life_days\n'
  '                    ),\n'
  '                ),\n'
  '                InventoryBalance.company_id == company_id,\n'
  '                InventoryBalance.location_id == location_id,\n'
  '                InventoryBalance.product_variant_id\n'
  '                == product_variant_id,\n'
  "                InventoryBalance.stock_status == 'AVAILABLE',\n"
  '                ~active_lock_exists,\n'
  '            )\n',
  'override options eligibility'),
 ('            .order_by(\n'
  '                ProductBatch.expiry_date.asc(),\n'
  '                ProductBatch.id.asc(),\n'
  '            )\n',
  '            .order_by(\n'
  '                ProductBatch.expiry_date.asc().nulls_last(),\n'
  '                ProductBatch.id.asc(),\n'
  '            )\n',
  'override options nullable expiry ordering'),
 ('            valid_override_pairs = set(\n'
  '                (\n'
  '                    await db.execute(\n'
  '                        select(ProductBatch.product_variant_id, ProductBatch.id).filter(\n'
  '                            ProductBatch.company_id == company_id,\n'
  '                            tuple_(ProductBatch.product_variant_id, '
  'ProductBatch.id).in_(sorted(override_batch_pairs)),\n'
  '                            ProductBatch.is_active.is_(True),\n'
  '                            or_(\n'
  '                                ProductBatch.production_date.is_(None),\n'
  '                                ProductBatch.production_date <= as_of_date,\n'
  '                            ),\n'
  '                            ProductBatch.expiry_date >= as_of_date,\n'
  '                        )\n'
  '                    )\n'
  '                ).all()\n'
  '            )\n',
  '            valid_override_pairs = set(\n'
  '                (\n'
  '                    await db.execute(\n'
  '                        select(\n'
  '                            ProductBatch.product_variant_id,\n'
  '                            ProductBatch.id,\n'
  '                        )\n'
  '                        .join(\n'
  '                            ProductVariant,\n'
  '                            and_(\n'
  '                                ProductVariant.company_id\n'
  '                                == ProductBatch.company_id,\n'
  '                                ProductVariant.id\n'
  '                                == ProductBatch.product_variant_id,\n'
  '                            ),\n'
  '                        )\n'
  '                        .join(\n'
  '                            InventoryBalance,\n'
  '                            and_(\n'
  '                                InventoryBalance.company_id\n'
  '                                == ProductBatch.company_id,\n'
  '                                InventoryBalance.product_variant_id\n'
  '                                == ProductBatch.product_variant_id,\n'
  '                                InventoryBalance.batch_id == ProductBatch.id,\n'
  '                            ),\n'
  '                        )\n'
  '                        .outerjoin(\n'
  '                            InventoryStockPolicy,\n'
  '                            and_(\n'
  '                                InventoryStockPolicy.company_id\n'
  '                                == ProductBatch.company_id,\n'
  '                                InventoryStockPolicy.location_id\n'
  '                                == payload.source_location_id,\n'
  '                                InventoryStockPolicy.product_variant_id\n'
  '                                == ProductBatch.product_variant_id,\n'
  '                                InventoryStockPolicy.is_active.is_(True),\n'
  '                            ),\n'
  '                        )\n'
  '                        .filter(\n'
  '                            ProductBatch.company_id == company_id,\n'
  '                            tuple_(\n'
  '                                ProductBatch.product_variant_id,\n'
  '                                ProductBatch.id,\n'
  '                            ).in_(sorted(override_batch_pairs)),\n'
  '                            batch_sellability_predicate(\n'
  '                                as_of_date,\n'
  '                                expiry_control_mode=(\n'
  '                                    ProductVariant.expiry_control_mode\n'
  '                                ),\n'
  '                                minimum_remaining_shelf_life_days=(\n'
  '                                    InventoryStockPolicy.minimum_remaining_shelf_life_days\n'
  '                                ),\n'
  '                            ),\n'
  '                            InventoryBalance.company_id == company_id,\n'
  '                            InventoryBalance.location_id\n'
  '                            == payload.source_location_id,\n'
  '                            InventoryBalance.stock_status == "AVAILABLE",\n'
  '                            InventoryBalance.on_hand_quantity\n'
  '                            > InventoryBalance.reserved_quantity,\n'
  '                        )\n'
  '                        .order_by(\n'
  '                            ProductBatch.product_variant_id.asc(),\n'
  '                            ProductBatch.id.asc(),\n'
  '                        )\n'
  '                        .with_for_update(\n'
  '                            read=True,\n'
  '                            of=ProductBatch,\n'
  '                        )\n'
  '                    )\n'
  '                ).all()\n'
  '            )\n',
  'override dispatch eligibility/source existence'),
 ('                    detail="إحدى دفعات تجاوز FEFO غير صالحة أو منتهية أو لا تتبع الصنف/الشركة."\n',
  '                    detail=(\n'
  '                        "إحدى دفعات تجاوز FEFO غير مؤهلة للبيع/التحميل "\n'
  '                        "بسبب disposition/expiry/shelf-life أو لا تتبع الصنف/الشركة."\n'
  '                    )\n',
  'override dispatch error')]


def locate_root() -> Path:
    cwd = Path.cwd()
    for candidate in (cwd, cwd / "wa_backend"):
        if (
            (candidate / "services.py").exists()
            and (candidate / "api" / "warehouse.py").exists()
            and (candidate / "api" / "dispatch.py").exists()
            and (candidate / "api" / "driver.py").exists()
        ):
            return candidate
    raise SystemExit(
        "PATCH_ABORT: شغّل السكربت من جذر المشروع أو من داخل wa_backend."
    )


def read_normalized(path: Path) -> str:
    return (
        path.read_text(encoding="utf-8")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"PATCH_ABORT: {label}: expected exactly 1 match, found {count}."
        )
    return text.replace(old, new, 1)


def require(text: str, token: str, label: str) -> None:
    if token not in text:
        raise SystemExit(f"PATCH_ABORT: missing invariant: {label}")


def ensure_driver_matches_head(root: Path) -> None:
    try:
        result = subprocess.run(
            ["git", "diff", "--quiet", "HEAD", "--", "api/driver.py"],
            cwd=root,
            check=False,
        )
    except OSError as exc:
        raise SystemExit(
            f"PATCH_ABORT: تعذر تشغيل git للتحقق من api/driver.py: {exc}"
        ) from exc

    if result.returncode == 1:
        raise SystemExit(
            "PATCH_ABORT: api/driver.py يحمل تعديلات محلية غير مراجعة. "
            "ارفع النسخة الحالية قبل تطبيق Stage 4C."
        )
    if result.returncode != 0:
        raise SystemExit(
            "PATCH_ABORT: git diff فشل أثناء التحقق من api/driver.py."
        )


def validate_driver_dispatch(dispatch: str, driver: str) -> None:
    # البيع الفعلي يجب أن يبقى مستهلكاً لنفس FEFO المركزي.
    for token in (
        "fefo_allocations = await allocate_fefo_inventory_batch(",
        "as_of_date=company_local_date",
        '"reference_type": "VISIT_ITEM_OUT"',
        "allocation_state = {",
        "def consume_fefo(",
    ):
        require(driver, token, f"driver sale FEFO: {token}")

    # كل تحميل جديد للمسار يجب أن يمر من نفس allocator المركزي.
    for token in (
        "async def _dispatch_allocate_available_batches(",
        "if require_sellable:",
        "allocations = await allocate_fefo_inventory_batch(",
        "require_sellable=True",
        "src, dst, sellable = int(warehouse.id), vehicle_location_id, True",
        'src, dst, sellable, ref = int(warehouse.id), vehicle_location_id, True, "DISPATCH_LOAD"',
    ):
        require(dispatch, token, f"dispatch load FEFO: {token}")


def validate_prerequisites(root: Path, dispatch: str, driver: str) -> None:
    models = read_normalized(root / "models.py")
    schemas = read_normalized(root / "schemas.py")

    # Stage 4A/4B must already be present.
    for token, label in (
        ("minimum_remaining_shelf_life_days", "InventoryStockPolicy minimum shelf life"),
        ("disposition_reason", "ProductBatch disposition_reason"),
        ("disposition_revision", "ProductBatch disposition_revision"),
        ("'RECALL_RETURN'", "RECALL_RETURN transfer purpose"),
    ):
        require(models, token, label)

    require(
        schemas,
        "expiry_date: Optional[date] = None",
        "InboundBatchItem nullable expiry contract",
    )
    validate_driver_dispatch(dispatch, driver)


def patch_with_ops(text: str, ops, file_label: str) -> str:
    result = text
    for old, new, label in ops:
        result = replace_once(result, old, new, f"{file_label}: {label}")
    return result


def validate_postpatch(
    services: str,
    warehouse: str,
    dispatch: str,
    driver: str,
) -> None:
    for label, source in (
        ("services.py", services),
        ("api/warehouse.py", warehouse),
        ("api/dispatch.py", dispatch),
        ("api/driver.py", driver),
    ):
        try:
            ast.parse(source)
        except SyntaxError as exc:
            raise SystemExit(
                f"PATCH_ABORT: syntax validation failed for {label}: {exc}"
            ) from exc

    for token in (
        "# PATCH: STAGE4C_SYNCHRONOUS_BATCH_ELIGIBILITY",
        "def batch_sellability_predicate(",
        "def _batch_metadata_is_sellable(",
        'ProductBatch.disposition == "RELEASED"',
        "ProductBatch.expiry_date.is_(None)",
        "ProductVariant.expiry_control_mode",
        "InventoryStockPolicy.minimum_remaining_shelf_life_days",
        "metadata_dates",
        "date.max",
        ".with_for_update(read=True)",
    ):
        require(services, token, f"services postpatch: {token}")

    for token in (
        "# PATCH: STAGE4C_SYNCHRONOUS_BATCH_ELIGIBILITY",
        "batch_sellability_predicate,",
        "sellable_batch = batch_sellability_predicate(",
        "ProductBatch.expiry_date.asc().nulls_last()",
        "InventoryStockPolicy.minimum_remaining_shelf_life_days",
        "of=ProductBatch",
        "InventoryBalance.on_hand_quantity\n                            > InventoryBalance.reserved_quantity",
    ):
        require(warehouse, token, f"warehouse postpatch: {token}")

    # بعد جعل expiry nullable لا نسمح ببقاء predicate تشغيلي قديم يرفض NULL
    # قبل تطبيق expiry_control_mode والسياسة الموحدة.
    if "ProductBatch.expiry_date >= as_of_date" in warehouse:
        raise SystemExit(
            "PATCH_ABORT: warehouse.py still contains a legacy direct expiry predicate."
        )

    validate_driver_dispatch(dispatch, driver)


def write_lf(path: Path, text: str) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stage 4C synchronous batch eligibility surgical patch"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Preflight only; validate anchors and resulting code without writing.",
    )
    args = parser.parse_args()

    root = locate_root()
    ensure_driver_matches_head(root)
    paths = {
        "services.py": root / "services.py",
        "api/warehouse.py": root / "api" / "warehouse.py",
        "api/dispatch.py": root / "api" / "dispatch.py",
        "api/driver.py": root / "api" / "driver.py",
    }
    current = {name: read_normalized(path) for name, path in paths.items()}

    # Idempotent replay.
    if (
        f"# PATCH: {MARKER}" in current["services.py"]
        and f"# PATCH: {MARKER}" in current["api/warehouse.py"]
    ):
        validate_prerequisites(
            root,
            current["api/dispatch.py"],
            current["api/driver.py"],
        )
        validate_postpatch(
            current["services.py"],
            current["api/warehouse.py"],
            current["api/dispatch.py"],
            current["api/driver.py"],
        )
        print("STAGE4C_SYNCHRONOUS_BATCH_ELIGIBILITY_ALREADY_OK")
        return

    validate_prerequisites(
        root,
        current["api/dispatch.py"],
        current["api/driver.py"],
    )

    # Exact baseline guard for every file this patch was designed against.
    # dispatch.py is validated but intentionally not modified.
    for relative_path, expected_hash in EXPECTED_HASHES.items():
        actual_hash = sha256_text(current[relative_path])
        if actual_hash != expected_hash:
            raise SystemExit(
                "PATCH_ABORT: baseline changed for "
                f"{relative_path}. expected={expected_hash} actual={actual_hash}. "
                "ارفع النسخة الحالية للمراجعة بدل تطبيق باتش أعمى."
            )

    patched_services = patch_with_ops(
        current["services.py"],
        OPS_SERVICES,
        "services.py",
    )
    patched_warehouse = patch_with_ops(
        current["api/warehouse.py"],
        OPS_WAREHOUSE,
        "api/warehouse.py",
    )

    # Nothing is written before all anchors and syntax/invariants pass.
    validate_postpatch(
        patched_services,
        patched_warehouse,
        current["api/dispatch.py"],
        current["api/driver.py"],
    )
    if sha256_text(patched_services) != EXPECTED_FINAL_HASHES["services.py"]:
        raise SystemExit("PATCH_ABORT: generated services.py hash differs from reviewed target.")
    if sha256_text(patched_warehouse) != EXPECTED_FINAL_HASHES["api/warehouse.py"]:
        raise SystemExit("PATCH_ABORT: generated warehouse.py hash differs from reviewed target.")

    if args.check:
        print("STAGE4C_PREFLIGHT_OK")
        print("FILES_TO_CHANGE: services.py + api/warehouse.py")
        print(
            "FILES_VALIDATED_ONLY: "
            "api/dispatch.py + api/driver.py + models.py + schemas.py"
        )
        return

    backup_dir = root / ".patch_backups" / MARKER
    backup_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(paths["services.py"], backup_dir / "services.py.before")
    shutil.copy2(
        paths["api/warehouse.py"],
        backup_dir / "warehouse.py.before",
    )

    write_lf(paths["services.py"], patched_services)
    write_lf(paths["api/warehouse.py"], patched_warehouse)

    # Verify exact bytes re-read from disk after writing.
    final_services = read_normalized(paths["services.py"])
    final_warehouse = read_normalized(paths["api/warehouse.py"])
    if sha256_text(final_services) != EXPECTED_FINAL_HASHES["services.py"]:
        raise SystemExit("PATCH_ABORT: services.py on disk differs from reviewed target.")
    if sha256_text(final_warehouse) != EXPECTED_FINAL_HASHES["api/warehouse.py"]:
        raise SystemExit("PATCH_ABORT: warehouse.py on disk differs from reviewed target.")
    validate_postpatch(
        final_services,
        final_warehouse,
        current["api/dispatch.py"],
        current["api/driver.py"],
    )

    print("STAGE4C_SYNCHRONOUS_BATCH_ELIGIBILITY_OK")
    print(
        "CENTRAL_FEFO_OK: "
        "disposition + expiry + expiry_control_mode + minimum shelf life"
    )
    print("SALE_OK: driver sale path validated against central FEFO")
    print("ROUTE_LOAD_OK: dispatch load paths validated against central FEFO")
    print(
        "LIVE_STOCK_OK: physical stock remains visible; "
        "eligible/blocked projection uses synchronous batch policy"
    )
    print(
        "TRANSFER_SOURCE_OK: ordinary transfer source list "
        "excludes ineligible batches"
    )
    print(
        "FEFO_OVERRIDE_OK: override cannot bypass disposition/expiry/"
        "shelf-life and must exist at source"
    )
    print(
        "CONCURRENCY_OK: selected ProductBatch metadata is read-locked "
        "for FEFO/override decisions"
    )
    print("FILES_CHANGED: services.py + api/warehouse.py")
    print(
        "FILES_VALIDATED_ONLY: "
        "api/dispatch.py + api/driver.py + models.py + schemas.py"
    )


if __name__ == "__main__":
    main()
