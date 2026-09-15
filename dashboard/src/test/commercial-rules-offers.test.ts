import { describe, expect, it } from 'vitest';
import { buildOfferVersionPayload, emptyOfferVersionForm } from '@/features/commercialRules/formUtils';

describe('offer product scope contract', () => {
  it('rejects overlapping all-UOM and UOM-specific scopes for the same product', () => {
    const form = emptyOfferVersionForm();
    form.offer_type = 'PERCENTAGE_DISCOUNT';
    form.effective_from = '2026-09-15T04:00';
    form.scopes = [
      { scope_type: 'PRODUCT_VARIANT', target: '7', uom_id: '' },
      { scope_type: 'PRODUCT_VARIANT', target: '7', uom_id: '2' },
    ];

    expect(() => buildOfferVersionPayload(form)).toThrow('لا يمكن الجمع بين كل الوحدات ووحدة محددة لنفس المنتج.');
  });
  it('rejects quantities outside the shared NUMERIC(20,6) contract', () => {
  const form = emptyOfferVersionForm();
  form.offer_type = 'BUY_X_GET_Y';
  form.effective_from = '2026-09-15T04:00';
  form.buy_quantity = '1.0000001';

  expect(() => buildOfferVersionPayload(form)).toThrow('كمية الشراء لا يقبل أكثر من 6 منازل عشرية.');

  form.buy_quantity = '100000000000000';
  expect(() => buildOfferVersionPayload(form)).toThrow('كمية الشراء يتجاوز سعة NUMERIC(20,6).');
});

it('accepts equivalent quantities with trailing decimal zeros', () => {
  const form = emptyOfferVersionForm();
  form.offer_type = 'BUY_X_GET_Y';
  form.effective_from = '2026-09-15T04:00';
  form.buy_quantity = '1.0000000';
  form.products = [
    { role: 'QUALIFYING', product_variant_id: '7', uom_id: '1', quantity_per_application: '' },
    { role: 'REWARD', product_variant_id: '8', uom_id: '1', quantity_per_application: '2.5000000' },
  ];

  const payload = buildOfferVersionPayload(form);
  expect(payload.payload).toMatchObject({ buy_quantity: '1.0000000' });
  expect(payload.products[1].quantity_per_application).toBe('2.5000000');
});

  it('allows multiple explicit UOM scopes for the same product', () => {
    const form = emptyOfferVersionForm();
    form.offer_type = 'PERCENTAGE_DISCOUNT';
    form.effective_from = '2026-09-15T04:00';
    form.scopes = [
      { scope_type: 'PRODUCT_VARIANT', target: '7', uom_id: '1' },
      { scope_type: 'PRODUCT_VARIANT', target: '7', uom_id: '2' },
    ];

    const payload = buildOfferVersionPayload(form);
    expect(payload.scopes).toHaveLength(2);
  });
});