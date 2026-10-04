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
  hintKey: string;
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
      hintKey: "products.commercialStatus.hints.archived",
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
      hintKey: "products.commercialStatus.hints.stopped",
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
      hintKey: "products.commercialStatus.hints.stopped",
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
      stateKey: "products.commercialStatus.outOfUse",
      hintKey: "products.commercialStatus.hints.outOfUse",
      reason: null,
      reasonKey: null,
      secondaryReasonKey: null,
      tone: "muted",
    };
  }

  if (item.lifecycle_status === "DRAFT") {
    return {
      state: "stopped",
      stateKey: "products.commercialStatus.stopped",
      hintKey: "products.commercialStatus.hints.stopped",
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
    hintKey: "products.commercialStatus.hints.available",
    reason: null,
    reasonKey: null,
    secondaryReasonKey: null,
    tone: "good",
  };
}
