export type BatchIssueFocus = {
  variantId: number;
  productName: string;
};

const focusKey = (companyId: string) =>
  `inventory_batch_issue_focus:${companyId}`;

export function prepareBatchIssueNavigation(
  companyId: string,
  focus: BatchIssueFocus,
) {
  localStorage.setItem(
    `inventory_active_tab:${companyId}`,
    "batches",
  );
  sessionStorage.setItem(
    focusKey(companyId),
    JSON.stringify(focus),
  );
}

export function takeBatchIssueFocus(
  companyId: string,
): BatchIssueFocus | null {
  const key = focusKey(companyId);
  const raw = sessionStorage.getItem(key);
  sessionStorage.removeItem(key);
  if (!raw) return null;

  try {
    const parsed = JSON.parse(raw) as Record<
      string,
      unknown
    >;
    if (
      typeof parsed.variantId !== "number" ||
      !Number.isSafeInteger(parsed.variantId) ||
      parsed.variantId <= 0 ||
      typeof parsed.productName !== "string" ||
      !parsed.productName.trim()
    ) {
      return null;
    }
    return {
      variantId: parsed.variantId,
      productName: parsed.productName,
    };
  } catch {
    return null;
  }
}
