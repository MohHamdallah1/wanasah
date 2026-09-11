import { describe, expect, it, vi } from 'vitest';
vi.mock('@/hooks/useAuthFetch', () => ({useAuthFetch: vi.fn()}));
import { hasInventoryPermission, parseInventoryCapabilities } from '@/hooks/useInventoryAccess';
import { parseCatalogPage } from '@/pages/inventory/catalogParsers';
import { buildVariantPayload, parseMutationMessage } from '@/pages/inventory/catalog/contracts';
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

describe('catalog product and UOM contract', () => {
  const item = {id:7,product_id:3,name:'صنف',sku:'SKU-7',gtin:null,base_uom:{id:1,code:'EACH',name:'حبة'},quantity_scale:0,quantity_step:'1',lot_control_mode:'REQUIRED',expiry_control_mode:'REQUIRED',lifecycle_status:'ACTIVE',operational_hold:'NONE',lifecycle_revision:1,version:1,published_at:'2026-09-12T00:00:00',retired_at:null,archived_at:null};
  it('rejects malformed pagination and duplicate identities', () => {
    expect(() => parseCatalogPage({items: [item], next_cursor: 10, has_more: true})).toThrow();
    expect(() => parseCatalogPage({items: [item], next_cursor: null, has_more: true})).toThrow();
  });
  it('builds a price-free exact-quantity SKU contract', () => {
    const payload=buildVariantPayload({product_id:'3',name:'صنف',sku:'sku-7',gtin:'',base_uom_id:'1',quantity_scale:'3',quantity_step:'0.125',lot_control_mode:'REQUIRED',expiry_control_mode:'REQUIRED'});
    expect(payload).toMatchObject({product_id:3,name:'صنف',sku:'SKU-7',gtin:null,base_uom_id:1,quantity_scale:3,quantity_step:'0.125'});
    expect(parseMutationMessage({message:'تم'})).toBe('تم');
  });
});

describe('inbound contract and draft isolation', () => {
  const draft = JSON.stringify({'7': [{
    row_id: 'row-1', quantity:'27.125', batch_number: ' B-1 ',
    production_date: '2026-01-01', expiry_date: '2027-01-01',
  }]});
  const product = {id:7,product_id:3,name:'صنف',sku:'SKU-7',gtin:null,base_uom:{id:1,code:'EACH',name:'حبة'},quantity_scale:3,quantity_step:'0.125',lot_control_mode:'REQUIRED' as const,expiry_control_mode:'REQUIRED' as const,lifecycle_status:'ACTIVE' as const,operational_hold:'NONE' as const,lifecycle_revision:1,version:1,published_at:'2026-09-12T00:00:00',retired_at:null,archived_at:null};

  it('partitions UX state by tenant, actor, and location', () => {
    expect(inboundStorageKeys(1, 7, 100).drafts).not.toBe(inboundStorageKeys(1, 7, 101).drafts);
    expect(inboundStorageKeys(1, 7, 100).drafts).not.toBe(inboundStorageKeys(2, 7, 100).drafts);
    expect(inboundStorageKeys(1, 7, 100).drafts).not.toBe(inboundStorageKeys(1, 8, 100).drafts);
  });

  it('builds the strict backend batch payload from fresh product metadata', () => {
    const items = buildInboundItems(parseInboundDrafts(draft), new Map([['7', product]]));
    expect(items).toEqual([{
      product_variant_id:7,quantity:'27.125',uom_id:1,batch_number:'B-1',
      production_date: '2026-01-01', expiry_date: '2027-01-01',
    }]);
    expect(parseInboundResponse({message: 'تم'})).toEqual({message: 'تم'});
  });

  it('fails closed for malformed persisted drafts and product snapshots', () => {
    expect(parseInboundDrafts('{bad')).toEqual({});
    expect(parseInboundDrafts(JSON.stringify({'7': [{...JSON.parse(draft)['7'][0], quantity:'1.0000001'}]}))).toEqual({});
    expect(parseInboundDraftProducts(JSON.stringify({'7': {...product, id: 8}}))).toEqual({});
  });
});

describe('live stock response contract', () => {
  const item = {
    id:7,name:'صنف',sku:'SKU-7',base_uom_id:1,base_uom_code:'EACH',base_uom_name:'حبة',quantity_scale:3,quantity_step:'0.125',
    available_quantity:'27.125',reserved_quantity:'3',blocked_quantity:'2',total_quantity:'32.125',damaged_quantity:'1',minimum_quantity:'10',
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
    {...item, available_quantity: '-1'},
    {...item, quantity_scale: 7},
    {...item, quantity_step: '0'},
    {...item, total_quantity: 4.1},
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
    id:44,product_variant_id:7,product_name:'صنف',base_uom_id:1,base_uom_code:'EACH',quantity_scale:3,quantity_step:'0.125',
    type:'INBOUND_SUPPLIER',quantity:'27.125',balance_before:'0',balance_after:'27.125',admin_name:'مدير',reference:'INV-1',notes:null,
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
    {...entry, quantity: '0'},
    {...entry, date: '2026-09-10T05:00:00'},
  ])('rejects malformed movement evidence %#', malformed => {
    expect(() => parseLedgerPage({
      items: [malformed], next_cursor: null, has_more: false,
      total: 1, available_types: ['INBOUND_SUPPLIER'],
    })).toThrow();
  });

  it('builds a DB-safe correction contract and validates its response', () => {
    expect(buildLedgerAdjustmentPayload('27.125', parseLedgerPage({items:[entry],next_cursor:null,has_more:false,total:1,available_types:['INBOUND_SUPPLIER']}).items[0], 'secret')).toEqual({
      password: 'secret', new_total_quantity:'27.125',uom_id:1,
    });
    expect(parseLedgerMutationResponse({message: 'تم التصحيح'})).toEqual({message: 'تم التصحيح'});
  });
});
