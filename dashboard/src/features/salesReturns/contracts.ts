export interface SalesReturnSourceComponent {
  price_component_id: number;
  uom_id: number;
  uom_code: string;
  uom_name: string;
  sold_quantity: string;
  returned_quantity: string;
  available_quantity: string;
  unit_price: string;
}

export interface SalesReturnSourceLine {
  visit_item_id: number;
  product_variant_id: number;
  product_name: string;
  net_amount: string;
  components: SalesReturnSourceComponent[];
}

export interface SalesReturnSource {
  visit_id: number;
  sales_revision_id: number;
  shop: { id: number; name: string };
  transaction_currency_code: string;
  final_amount: string;
  lines: SalesReturnSourceLine[];
}

export interface SalesReturnListItem {
  id: number;
  original_visit_id: number;
  original_sales_revision_id: number;
  shop_id: number;
  shop_name: string;
  transaction_currency_code: string;
  credit_amount: string;
  settlement_status: "UNSETTLED";
  reason: string;
  posted_at: string;
}

export interface SalesReturnPage {
  items: SalesReturnListItem[];
  has_more: boolean;
  next_cursor: string | null;
}

export interface SalesReturnDetail extends SalesReturnListItem {
  status: "POSTED";
  functional_currency_code: string;
  rounding_reversal: string;
  shop: { id: number; name: string };
  lines: Array<{
    id: number;
    original_visit_item_id: number;
    product_variant_id: number;
    product_name: string;
    returned_base_quantity: string;
    gross_reversal: string;
    discount_reversal: string;
    post_offer_reversal: string;
    taxable_reversal: string;
    tax_reversal: string;
    line_total_reversal: string;
    credit_amount: string;
    components: Array<{
      original_price_component_id: number;
      uom_id: number;
      uom_code: string;
      uom_name: string;
      quantity: string;
      base_quantity: string;
      gross_reversal: string;
    }>;
  }>;
}
export interface SalesReturnEligibleSource {
  visit_id: number;
  sales_revision_id: number;
  shop_id: number;
  shop_name: string;
  transaction_currency_code: string;
  final_amount: string;
  sold_at: string;
  operational_date: string;
}

export interface SalesReturnEligibleSourcePage {
  items: SalesReturnEligibleSource[];
  has_more: boolean;
  next_cursor: number | null;
}
