import { shopOrderText } from "./messages";

interface ShopOrderScopeNoticeProps {
  language: string;
  selectedZoneName: string;
  hasOutsideZoneMatches: boolean;
  isEditMode: boolean;
}

/** In-context notice, not another state or business owner. */
export function ShopOrderScopeNotice({
  language, selectedZoneName, hasOutsideZoneMatches, isEditMode,
}: ShopOrderScopeNoticeProps) {
  if (!isEditMode || !hasOutsideZoneMatches) return null;
  return (
    <p role="status" data-testid="shop-order-scope-notice"
      className="border-b border-amber-200 bg-amber-50 px-4 py-2 text-xs font-medium text-amber-900">
      {shopOrderText(language, "selectedZone", { zone: selectedZoneName })}{" "}
      {shopOrderText(language, "otherZone")}
    </p>
  );
}
