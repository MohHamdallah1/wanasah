import { describe, expect, it, vi } from 'vitest';
vi.mock('@/hooks/useAuthFetch', () => ({useAuthFetch: vi.fn()}));
import { hasInventoryPermission, parseInventoryCapabilities } from '@/hooks/useInventoryAccess';
import { parseCatalogItems, parseCatalogPage } from '@/pages/inventory/catalogParsers';
import { buildProductVariantCreatePayload, parseProductVariantMutationResponse } from '@/pages/inventory/catalog/contracts';
import {
  buildInboundItems,
  inboundStorageKeys,
  parseInboundDraftProducts,
  parseInboundDrafts,
  parseInboundResponse,
} from '@/pages/inventory/inbound/contracts';
import { parseLiveStockPage } from '@/pages/inventory/liveStock/contracts';
import {
  buildLedgerAdjustmentPayload,
  parseLedgerMutationResponse,
  parseLedgerPage,
} from '@/pages/inventory/ledger/contracts';

const capabilities = {
  company_id: 1, driver_id: 7, is_company_admin: false, location_id: 101,
  permissions: ['catalog.read'], any_permissions: ['catalog.read', 'stocktake.count'],
  location_permissions: ['stocktake.count'],
};

describe('inventory permission contract', () => {
  it('does not infer review/approval or all-location rights from counting', () => {
    const data = parseInventoryCapabilities(capabilities);
    expect(hasInventoryPermission(data, 'stocktake.count')).toBe(true);
    expect(hasInventoryPermission(data, 'stocktake.review')).toBe(false);
    expect(hasInventoryPermission(data, 'stocktake.approve')).toBe(false);
    expect(hasInventoryPermission(data, 'catalog.read')).toBe(true);
  });
  it('does not use any-location grants as permission at the selected location', () => {
    const data = parseInventoryCapabilities({...capabilities, location_permissions: []});
    expect(hasInventoryPermission(data, 'stocktake.count')).toBe(false);
  });
  it.each([
    {...capabilities, company_id: '1'}, {...capabilities, driver_id: 0},
    {...capabilities, is_company_admin: 'true'}, {...capabilities, location_id: -1},
    {...capabilities, permissions: null}, {...capabilities, location_permissions: [true]},
  ])('rejects malformed authority contracts', raw => {
    expect(() => parseInventoryCapabilities(raw)).toThrow();
  });
});

describe('catalog contract used before carton conversion', () => {
  const item = {id: 7, name: 'صنف', sku: null, packs_per_carton: 12};
  it('preserves the server conversion factor', () => {
    expect(parseCatalogItems([item])).toEqual([item]);
  });
  it.each([0, -1, 1.5, '12', NaN])('rejects invalid carton conversion %s', factor => {
    expect(() => parseCatalogItems([{...item, packs_per_carton: factor}])).toThrow();
  });
  it('rejects malformed pagination and duplicate identities', () => {
    expect(() => parseCatalogPage({items: [item], next_cursor: 10, has_more: true, total: null})).toThrow();
    expect(() => parseCatalogPage({items: [item], next_cursor: null, has_more: true, total: 1})).toThrow();
    expect(() => parseCatalogPage({items: [item, item], next_cursor: null, has_more: false, total: 2})).toThrow();
  });
  it('builds the exact product-create contract and validates the mutation response', () => {
    expect(buildProductVariantCreatePayload({
      variant_name: '  منتج جديد  ', sku: ' ', price_per_carton: '12.5',
      packs_per_carton: '12', price_per_pack: '1.250', min_threshold_packs: '5', max_samples: '2',
    })).toEqual({
      variant_name: 'منتج جديد', sku: null, price_per_carton: '12.500',
      packs_per_carton: 12, price_per_pack: '1.250', min_threshold_packs: 5, max_samples: 2,
    });
    expect(parseProductVariantMutationResponse({message: 'تم', product_id: 9})).toEqual({message: 'تم', product_id: 9});
    expect(() => buildProductVariantCreatePayload({
      variant_name: 'منتج', sku: '', price_per_carton: '1.2345', packs_per_carton: '1',
      price_per_pack: '', min_threshold_packs: '0', max_samples: '0',
    })).toThrow();
  });
});

describe('inbound contract and draft isolation', () => {
  const draft = JSON.stringify({'7': [{
    row_id: 'row-1', cartons: 2, loose_packs: 3, batch_number: ' B-1 ',
    production_date: '2026-01-01', expiry_date: '2027-01-01',
  }]});
  const product = {id: 7, name: 'صنف', sku: null, packs_per_carton: 12};

  it('partitions UX state by tenant, actor, and location', () => {
    expect(inboundStorageKeys(1, 7, 100).drafts).not.toBe(inboundStorageKeys(1, 7, 101).drafts);
    expect(inboundStorageKeys(1, 7, 100).drafts).not.toBe(inboundStorageKeys(2, 7, 100).drafts);
    expect(inboundStorageKeys(1, 7, 100).drafts).not.toBe(inboundStorageKeys(1, 8, 100).drafts);
  });

  it('builds the strict backend batch payload from fresh product metadata', () => {
    const items = buildInboundItems(parseInboundDrafts(draft), new Map([['7', product]]));
    expect(items).toEqual([{
      product_variant_id: 7, quantity_packs: 27, batch_number: 'B-1',
      production_date: '2026-01-01', expiry_date: '2027-01-01',
    }]);
    expect(parseInboundResponse({message: 'تم'})).toEqual({message: 'تم'});
  });

  it('fails closed for malformed persisted drafts and product snapshots', () => {
    expect(parseInboundDrafts('{bad')).toEqual({});
    expect(parseInboundDrafts(JSON.stringify({'7': [{...JSON.parse(draft)['7'][0], cartons: 1.5}]}))).toEqual({});
    expect(parseInboundDraftProducts(JSON.stringify({'7': {...product, id: 8}}))).toEqual({});
  });
});

describe('live stock response contract', () => {
  const item = {
    id: 7, name: 'صنف', sku: 'SKU-7', packs_per_carton: 12,
    available_packs: 27, reserved_packs: 3, blocked_packs: 2,
    total_packs: 40, damaged_packs: 1, available_cartons: 2,
    available_loose_packs: 3, min_threshold: 10,
  };

  it('accepts the exact cursor page and preserves base-unit quantities', () => {
    expect(parseLiveStockPage({
      items: [item], next_cursor: 'next', has_more: true,
      total: 4, alert_count: 1, alert_samples: ['صنف'],
    })).toEqual({
      items: [item], next_cursor: 'next', has_more: true,
      total: 4, alert_count: 1, alert_samples: ['صنف'],
    });
  });

  it.each([
    {...item, available_packs: -1},
    {...item, packs_per_carton: 0},
    {...item, available_cartons: 3},
    {...item, available_loose_packs: 12},
  ])('rejects malformed stock quantities %#', malformed => {
    expect(() => parseLiveStockPage({
      items: [malformed], next_cursor: null, has_more: false,
      total: 1, alert_count: 0, alert_samples: [],
    })).toThrow();
  });

  it('rejects pagination and duplicate identity mismatches', () => {
    expect(() => parseLiveStockPage({
      items: [item, item], next_cursor: null, has_more: true,
      total: 2, alert_count: null, alert_samples: [],
    })).toThrow();
  });
});

describe('unified ledger response contract', () => {
  const entry = {
    id: 44, product_variant_id: 7, product_name: 'صنف', packs_per_carton: 12,
    type: 'INBOUND_SUPPLIER', quantity_packs: 27, balance_before: 0,
    balance_after: 27, admin_name: 'مدير', reference: 'INV-1', notes: null,
    date: '2026-09-10T05:00:00+00:00',
  };

  it('parses a location-scoped cursor page without losing movement snapshots', () => {
    expect(parseLedgerPage({
      items: [entry], next_cursor: null, has_more: false,
      total: 1, available_types: ['INBOUND_SUPPLIER'],
    })).toEqual({
      items: [entry], next_cursor: null, has_more: false,
      total: 1, available_types: ['INBOUND_SUPPLIER'],
    });
  });

  it.each([
    {...entry, balance_after: 26},
    {...entry, balance_before: null},
    {...entry, quantity_packs: 0},
    {...entry, date: '2026-09-10T05:00:00'},
  ])('rejects malformed movement evidence %#', malformed => {
    expect(() => parseLedgerPage({
      items: [malformed], next_cursor: null, has_more: false,
      total: 1, available_types: ['INBOUND_SUPPLIER'],
    })).toThrow();
  });

  it('builds a DB-safe correction contract and validates its response', () => {
    expect(buildLedgerAdjustmentPayload(2, 3, 12, 'secret')).toEqual({
      password: 'secret', new_total_packs: 27,
    });
    expect(() => buildLedgerAdjustmentPayload(2, 12, 12, 'secret')).toThrow();
    expect(() => buildLedgerAdjustmentPayload(2147483647, 0, 12, 'secret')).toThrow();
    expect(parseLedgerMutationResponse({message: 'تم التصحيح'})).toEqual({message: 'تم التصحيح'});
  });
});
