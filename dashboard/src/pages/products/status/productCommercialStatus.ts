export type ProductLifecycleStatus =
  | "DRAFT"
  | "ACTIVE"
  | "RETIRING"
  | "ARCHIVED";

export type ProductOperationalHold =
  | "NONE"
  | "SALES_HOLD"
  | "RECALL";

export type ProductCommercialState =
  | "available"
  | "stopped"
  | "archived";

export type ProductStopReason =
  | "draft"
  | "temporary"
  | "requiresAction"
  | "pendingArchive";

export type ProductCommercialStatus = {
  state: ProductCommercialState;
  stateKey: string;
  reason: ProductStopReason | null;
  reasonKey: string | null;
  secondaryReasonKey: string | null;
  tone: "good" | "warning" | "blocked" | "muted";
};

type ProductStateSource = {
  lifecycle_status: ProductLifecycleStatus;
  operational_hold: ProductOperationalHold;
};

/**
 * Presentation-only mapping.
 *
 * Backend keeps lifecycle_status and operational_hold as independent authority.
 * The UI intentionally collapses them into one commercial state so operators do
 * not need to understand the internal state machine.
 */
export function productCommercialStatus(
  item: ProductStateSource,
): ProductCommercialStatus {
  if (item.lifecycle_status === "ARCHIVED") {
    return {
      state: "archived",
      stateKey: "products.commercialStatus.archived",
      reason: null,
      reasonKey: null,
      secondaryReasonKey: null,
      tone: "muted",
    };
  }

  const pendingArchive =
    item.lifecycle_status === "RETIRING";

  if (item.operational_hold === "RECALL") {
    return {
      state: "stopped",
      stateKey: "products.commercialStatus.stopped",
      reason: "requiresAction",
      reasonKey:
        "products.commercialStatus.reasons.requiresAction",
      secondaryReasonKey: pendingArchive
        ? "products.commercialStatus.secondary.pendingArchive"
        : null,
      tone: "blocked",
    };
  }

  if (item.operational_hold === "SALES_HOLD") {
    return {
      state: "stopped",
      stateKey: "products.commercialStatus.stopped",
      reason: "temporary",
      reasonKey:
        "products.commercialStatus.reasons.temporary",
      secondaryReasonKey: pendingArchive
        ? "products.commercialStatus.secondary.pendingArchive"
        : null,
      tone: "warning",
    };
  }

  if (pendingArchive) {
    return {
      state: "stopped",
      stateKey: "products.commercialStatus.stopped",
      reason: "pendingArchive",
      reasonKey:
        "products.commercialStatus.reasons.pendingArchive",
      secondaryReasonKey: null,
      tone: "warning",
    };
  }

  if (item.lifecycle_status === "DRAFT") {
    return {
      state: "stopped",
      stateKey: "products.commercialStatus.stopped",
      reason: "draft",
      reasonKey:
        "products.commercialStatus.reasons.draft",
      secondaryReasonKey: null,
      tone: "muted",
    };
  }

  return {
    state: "available",
    stateKey: "products.commercialStatus.available",
    reason: null,
    reasonKey: null,
    secondaryReasonKey: null,
    tone: "good",
  };
}
