import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { useSearchParams } from "react-router-dom";

import {
  parseVariants,
  type CatalogVariant,
} from "@/features/catalog/contracts";
import type { SimpleProduct } from "@/pages/products/contracts";
import {
  parseWarehouseFilterPage,
  type ProductWarehouseFilterOption,
} from "@/pages/products/list/warehouseFilterContract";

type AuthFetch = (
  path: string,
  opts?: RequestInit,
) => Promise<unknown>;

type Params = {
  accessReady: boolean;
  canReadAssignments: boolean;
  canManageAssignments: boolean;
  canDiscoverLocations: boolean;
  authFetch: AuthFetch;
  onChanged: () => void | Promise<void>;
};

type FocusTarget = {
  variantId: number;
  locationId?: number;
  assignmentId?: number;
};

const focusKeys = [
  "productLocationVariantId",
  "productLocationLocationId",
  "productLocationAssignmentId",
] as const;

const positiveInteger = (value: string | null): number | null => {
  if (!value || !/^\d+$/.test(value)) return null;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null;
};

const parseFocusTarget = (params: URLSearchParams): FocusTarget | null => {
  const variantRaw = params.get("productLocationVariantId");
  if (variantRaw === null) return null;
  const variantId = positiveInteger(variantRaw);
  const locationRaw = params.get("productLocationLocationId");
  const assignmentRaw = params.get("productLocationAssignmentId");
  const locationId = locationRaw === null ? undefined : positiveInteger(locationRaw);
  const assignmentId =
    assignmentRaw === null ? undefined : positiveInteger(assignmentRaw);

  if (
    variantId === null ||
    (locationRaw !== null && locationId === null) ||
    (assignmentRaw !== null && assignmentId === null)
  ) {
    return null;
  }

  return {
    variantId,
    ...(typeof locationId === "number" ? { locationId } : {}),
    ...(typeof assignmentId === "number" ? { assignmentId } : {}),
  };
};

export function useProductLocationWorkflow({
  accessReady,
  canReadAssignments,
  canManageAssignments,
  canDiscoverLocations,
  authFetch,
  onChanged,
}: Params) {
  const [searchParams, setSearchParams] = useSearchParams();
  const requestSequence = useRef(0);
  const [isOpen, setIsOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [candidateLocationsUnavailable, setCandidateLocationsUnavailable] =
    useState(false);
  const [variant, setVariant] = useState<CatalogVariant | null>(null);
  const [locations, setLocations] = useState<ProductWarehouseFilterOption[]>([]);
  const [targetVariantId, setTargetVariantId] = useState<number | null>(null);
  const [focusLocationId, setFocusLocationId] = useState<number | undefined>();
  const [focusAssignmentId, setFocusAssignmentId] = useState<number | undefined>();

  const focusSignature = focusKeys
    .map((key) => searchParams.get(key) ?? "")
    .join(":");

  const clearFocusParams = useCallback(() => {
    const next = new URLSearchParams(searchParams);
    let changed = false;
    for (const key of focusKeys) {
      if (next.has(key)) {
        next.delete(key);
        changed = true;
      }
    }
    if (changed) setSearchParams(next, { replace: true });
  }, [searchParams, setSearchParams]);

  const loadTarget = useCallback(
    async (target: FocusTarget) => {
      if (!canReadAssignments) return;
      const sequence = ++requestSequence.current;
      setIsOpen(true);
      setLoading(true);
      setLoadError(false);
      setCandidateLocationsUnavailable(false);
      setVariant(null);
      setLocations([]);
      setTargetVariantId(target.variantId);
      setFocusLocationId(target.locationId);
      setFocusAssignmentId(target.assignmentId);

      try {
        const page = parseVariants(
          await authFetch("/catalog/variants/resolve", {
            method: "POST",
            body: JSON.stringify({ ids: [target.variantId] }),
          }),
        );
        if (sequence !== requestSequence.current) return;
        const resolved = page.items.find((item) => item.id === target.variantId);
        if (!resolved) throw new Error("PRODUCT_LOCATION_VARIANT_UNAVAILABLE");
        setVariant(resolved);

        if (canManageAssignments && canDiscoverLocations) {
          try {
            const candidatePage = parseWarehouseFilterPage(
              await authFetch(
                "/warehouse/locations?include_inactive=false&limit=200",
              ),
            );
            if (sequence !== requestSequence.current) return;
            if (candidatePage.has_more) {
              setCandidateLocationsUnavailable(true);
              setLocations([]);
            } else {
              setLocations(candidatePage.items);
            }
          } catch {
            if (sequence !== requestSequence.current) return;
            setCandidateLocationsUnavailable(true);
            setLocations([]);
          }
        }
      } catch {
        if (sequence !== requestSequence.current) return;
        setVariant(null);
        setLocations([]);
        setLoadError(true);
      } finally {
        if (sequence === requestSequence.current) setLoading(false);
      }
    },
    [
      authFetch,
      canDiscoverLocations,
      canManageAssignments,
      canReadAssignments,
    ],
  );

  useEffect(() => {
    if (!accessReady) return;
    const hasFocus = searchParams.has("productLocationVariantId");
    if (!hasFocus) return;
    const target = parseFocusTarget(searchParams);
    if (!target || !canReadAssignments) {
      clearFocusParams();
      return;
    }
    void loadTarget(target);
  }, [
    accessReady,
    canReadAssignments,
    clearFocusParams,
    focusSignature,
    loadTarget,
    searchParams,
  ]);

  const openProductLocations = useCallback(
    (product: SimpleProduct) => {
      if (!canReadAssignments) return;
      void loadTarget({ variantId: product.id });
    },
    [canReadAssignments, loadTarget],
  );

  const closeProductLocations = useCallback(() => {
    requestSequence.current += 1;
    setIsOpen(false);
    setLoading(false);
    setLoadError(false);
    setCandidateLocationsUnavailable(false);
    setVariant(null);
    setLocations([]);
    setTargetVariantId(null);
    setFocusLocationId(undefined);
    setFocusAssignmentId(undefined);
    clearFocusParams();
  }, [clearFocusParams]);

  const retry = useCallback(() => {
    if (targetVariantId === null || !canReadAssignments) return;
    void loadTarget({
      variantId: targetVariantId,
      ...(typeof focusLocationId === "number" ? { locationId: focusLocationId } : {}),
      ...(typeof focusAssignmentId === "number"
        ? { assignmentId: focusAssignmentId }
        : {}),
    });
  }, [
    canReadAssignments,
    focusAssignmentId,
    focusLocationId,
    loadTarget,
    targetVariantId,
  ]);

  return {
    openProductLocations,
    modalProps: {
      isOpen,
      variant,
      locations,
      loading,
      loadError,
      candidateLocationsUnavailable,
      focusLocationId,
      focusAssignmentId,
      onClose: closeProductLocations,
      onRetry: retry,
      onChanged,
    },
  };
}
