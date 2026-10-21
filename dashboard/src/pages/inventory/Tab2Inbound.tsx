import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import {
  CalendarDays,
  Eraser,
  Pencil,
  Search,
  Trash2,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { Modal } from "@/components/ui/modal";
import { currentLocale } from "@/i18n";
import { apiErrorMessage } from "@/lib/apiErrors";
import { SupplierSelector } from "@/features/suppliers/SupplierSelector";
import { useInboundPosting } from "./inbound/useInboundPosting";
import {
  completeDurableOperation,
  durableScope,
  getOrCreateDurableRequestId,
} from "@/lib/durableOperations";
import {
  parseVariants,
  type CatalogVariant,
} from "@/features/catalog/contracts";
import {
  buildInboundItems,
  emptyInboundBatch,
  inboundReferenceChoices,
  prefilledInboundRow,
  type InboundReferenceSelection,
  inboundProductIds,
  inboundStorageKeys,
  isInboundRowValidationError,
  parseCostPolicy,
  parseInboundDrafts,
  parseInboundOptions,
  type CostMethod,
  type CostPolicy,
  type InboundBatchDraft,
  type InboundDraftMap,
  type InboundField,
  type InboundRowValidationError,
  type InboundVariantOptions,
} from "./inbound/contracts";
import {
  clearHiddenInboundTrackingValues,
  inboundTrackingPolicy,
} from "./inbound/trackingPolicy";

interface InboundWarehouseOption {
  id: number;
  name: string;
  code?: string;
}

interface Props {
  companyId: number;
  actorId: number;
  locationId: number;
  locations?: InboundWarehouseOption[];
  onLocationChange?: (value: string) => void;
  isAuditLocked: boolean;
  authenticatedFetch: (
    url: string,
    opts?: RequestInit
  ) => Promise<unknown>;
  onSuccess: () => void | Promise<void>;
}

type InboundRowControl = InboundField;

const controlKey = (rowId: string, control: InboundRowControl) =>
  `${rowId}:${control}`;

const cleanQuantityEntry = (value: string) => {
  const cleaned = value.replace(/[^0-9.]/g, "");
  if (/^\d+$/.test(cleaned)) {
    return cleaned.replace(/^0+(?=\d)/, "");
  }
  return cleaned;
};

const normalizeDateEntry = (value: string) => {
  const text = value.trim();
  if (!text) return "";
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) return text;

  const compact = text.replace(/[^0-9]/g, "");
  if (compact.length !== 8) return text;

  const firstFour = Number(compact.slice(0, 4));
  if (firstFour >= 1900 && firstFour <= 2200) {
    return `${compact.slice(0, 4)}-${compact.slice(4, 6)}-${compact.slice(6, 8)}`;
  }

  const month = Number(compact.slice(0, 2));
  const day = Number(compact.slice(2, 4));
  const year = Number(compact.slice(4, 8));
  if (
    month >= 1 &&
    month <= 12 &&
    day >= 1 &&
    day <= 31 &&
    year >= 1900 &&
    year <= 2200
  ) {
    return `${compact.slice(4, 8)}-${compact.slice(0, 2)}-${compact.slice(2, 4)}`;
  }
  return text;
};

type InboundDateInputProps = {
  value: string;
  label: string;
  required?: boolean;
  invalid: boolean;
  placeholder?: string;
  onChange: (value: string) => void;
  onEnter?: (event: KeyboardEvent<HTMLInputElement>) => void;
  inputRef?: (node: HTMLInputElement | null) => void;
};

function InboundDateInput({
  value,
  label,
  required = false,
  invalid,
  placeholder,
  onChange,
  onEnter,
  inputRef,
}: InboundDateInputProps) {
  return (
    <div className="inventory-inbound-date-entry">
      <input
        ref={inputRef}
        type="text"
        inputMode="numeric"
        value={value}
        placeholder={placeholder}
        required={required}
        aria-required={required}
        aria-invalid={invalid}
        aria-label={label}
        onChange={(event) => onChange(event.target.value)}
        onBlur={(event) => onChange(normalizeDateEntry(event.target.value))}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            onChange(normalizeDateEntry(event.currentTarget.value));
          }
          onEnter?.(event);
        }}
        className={invalid ? "is-error" : ""}
      />
      <span className="inventory-inbound-date-picker">
        <CalendarDays className="h-3.5 w-3.5" aria-hidden="true" />
        <input
          type="date"
          tabIndex={-1}
          aria-label={`${label} calendar`}
          value={/^\d{4}-\d{2}-\d{2}$/.test(value) ? value : ""}
          onChange={(event) => onChange(event.target.value)}
        />
      </span>
    </div>
  );
}

const rowControlOrder = (variant: CatalogVariant): InboundRowControl[] => {
  const policy = inboundTrackingPolicy(variant);
  return [
    "quantity",
    "unit_cost",
    ...(policy.lot.required ? (["batch_number"] as const) : []),
    ...(policy.expiry.required ? (["expiry_date"] as const) : []),
  ];
};

export function Tab2Inbound({
  companyId,
  actorId,
  locationId,
  locations = [],
  onLocationChange,
  isAuditLocked,
  authenticatedFetch,
  onSuccess,
}: Props) {
  const { t, i18n } = useTranslation();
  const keys = useMemo(
    () => inboundStorageKeys(companyId, actorId, locationId),
    [companyId, actorId, locationId]
  );
  const [drafts, setDrafts] = useState<InboundDraftMap>(() =>
    parseInboundDrafts(localStorage.getItem(keys.drafts))
  );
  const [catalog, setCatalog] = useState<CatalogVariant[]>([]);
  // The paginated catalog does not necessarily contain a saved draft's product.
  // Restore only those specific variants; never load the entire catalog.
  const [restoredCatalog, setRestoredCatalog] = useState<Map<number, CatalogVariant>>(
    () => new Map()
  );
  const requestedDraftVariantIds = useRef(new Set<number>());
  const [uomOptions, setUomOptions] = useState<
    Map<number, InboundVariantOptions>
  >(new Map());
  // TODO(V2 Settings): move this company-level policy to the Settings workspace.
  // Inbound only guards first use until that workspace exists.
  const [costPolicy, setCostPolicy] = useState<CostPolicy | null>(null);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [cursor, setCursor] = useState<string | null>(null);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [optionsLoading, setOptionsLoading] = useState(false);
  const [referenceChoices, setReferenceChoices] = useState<Map<number, InboundReferenceSelection[]>>(new Map());
  const [selectedReferences, setSelectedReferences] = useState<Map<number, InboundReferenceSelection>>(new Map());
  // Cost is read-only until the operator explicitly edits this receipt line.
  // It is UI-only state: actual costs, saved drafts and reference history are untouched.
  const [editingCostRows, setEditingCostRows] = useState<Set<string>>(() => new Set());
  const [submitting, setSubmitting] = useState(false);
  const [savingPolicy, setSavingPolicy] = useState(false);
  const [costPolicyOpen, setCostPolicyOpen] = useState(false);
  const [clearOpen, setClearOpen] = useState(false);
  const [validationError, setValidationError] =
    useState<InboundRowValidationError | null>(null);
  const [referenceId, setReferenceId] = useState(
    () => localStorage.getItem(keys.reference) || ""
  );
  const [notes, setNotes] = useState(
    () => localStorage.getItem(keys.notes) || ""
  );
  const request = useRef(0);
  const requestedOptionIds = useRef(new Set<number>());
  const optionsInFlight = useRef(0);
  const rowRefs = useRef(new Map<string, HTMLTableRowElement>());
  const controlRefs = useRef(new Map<string, HTMLElement>());
  const supplierKey = `${keys.drafts}:supplier`;
  const [supplierId, setSupplierId] = useState<number | null>(() => {
    const saved = Number(localStorage.getItem(supplierKey));
    return Number.isSafeInteger(saved) && saved > 0 ? saved : null;
  });
  const posting = useInboundPosting({ companyId, actorId, locationId, authenticatedFetch, legacyRequestKey: keys.requestId, legacyPayloadKey: keys.fingerprint });

  const visibleCatalog = useMemo(() => {
    const pagedIds = new Set(catalog.map((variant) => variant.id));
    const saved = Object.keys(drafts)
      .map(Number)
      .filter((id) => Number.isSafeInteger(id) && id > 0 && !pagedIds.has(id))
      .map((id) => restoredCatalog.get(id))
      .filter((variant): variant is CatalogVariant =>
        variant !== undefined && variant.lifecycle_status === "ACTIVE"
      );
    return [...saved, ...catalog];
  }, [catalog, drafts, restoredCatalog]);

  useEffect(() => {
    const pagedIds = new Set(catalog.map((variant) => variant.id));
    const ids = Object.keys(drafts)
      .map(Number)
      .filter((id) =>
        Number.isSafeInteger(id) && id > 0 &&
        !pagedIds.has(id) && !restoredCatalog.has(id) &&
        !requestedDraftVariantIds.current.has(id)
      )
      .slice(0, 200);
    if (!ids.length) return;
    ids.forEach((id) => requestedDraftVariantIds.current.add(id));
    const controller = new AbortController();
    let active = true;
    let finished = false;
    authenticatedFetch("/catalog/variants/resolve", {
      method: "POST",
      body: JSON.stringify({ ids }),
      signal: controller.signal,
    })
      .then(parseVariants)
      .then((page) => {
        if (!active) return;
        setRestoredCatalog((current) => {
          const next = new Map(current);
          for (const variant of page.items) {
            if (ids.includes(variant.id)) next.set(variant.id, variant);
          }
          return next;
        });
      })
      .catch((error) => {
        if (active && !(error instanceof Error && error.name === "AbortError")) {
          toast.error(apiErrorMessage(error, t("inventoryInbound.errors.catalogLoad")));
        }
      })
      .finally(() => { finished = true; });
    return () => {
      active = false;
      controller.abort();
      // Cancelled requests may be safely retried. Missing/inactive IDs must
      // not cause an endless resolve loop.
      if (!finished) ids.forEach((id) => requestedDraftVariantIds.current.delete(id));
    };
  }, [authenticatedFetch, catalog, drafts, restoredCatalog, t]);
  useEffect(() => {
    if (supplierId === null) localStorage.removeItem(supplierKey);
    else localStorage.setItem(supplierKey, String(supplierId));
  }, [supplierId, supplierKey]);

  useEffect(() => {
    localStorage.setItem(keys.drafts, JSON.stringify(drafts));
  }, [drafts, keys]);
  useEffect(() => {
    localStorage.setItem(keys.reference, referenceId);
  }, [referenceId, keys]);
  useEffect(() => {
    localStorage.setItem(keys.notes, notes);
  }, [notes, keys]);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      const clean = searchInput.trim();
      const nextSearch = clean.length >= 2 ? clean : "";
      if (nextSearch === search) return;
      setSearch(nextSearch);
      setCursor(null);
      setNextCursor(null);
      setCatalog([]);
    }, 300);
    return () => clearTimeout(timer);
  }, [searchInput, search]);

  useEffect(() => {
    const id = ++request.current;
    const controller = new AbortController();
    setLoading(true);
    const params = new URLSearchParams({
      limit: "50",
      lifecycle_status: "ACTIVE",
    });
    if (cursor) params.set("cursor", cursor);
    if (search) params.set("search", search);

    authenticatedFetch(`/catalog/variants?${params}`, {
      signal: controller.signal,
    })
      .then(parseVariants)
      .then((page) => {
        if (id === request.current) {
          setCatalog((current) => {
            if (!cursor) return page.items;
            const seen = new Set(current.map((item) => item.id));
            return [
              ...current,
              ...page.items.filter((item) => !seen.has(item.id)),
            ];
          });
          setNextCursor(page.next_cursor);
        }
      })
      .catch((error) => {
        if (
          id === request.current &&
          !(error instanceof Error && error.name === "AbortError")
        ) {
          toast.error(
            apiErrorMessage(error, t("inventoryInbound.errors.catalogLoad"))
          );
        }
      })
      .finally(() => {
        if (id === request.current) setLoading(false);
      });

    return () => {
      request.current += 1;
      controller.abort();
    };
  }, [authenticatedFetch, cursor, search, t]);

  useEffect(() => {
    if (!visibleCatalog.length) return;
    setDrafts((current) => {
      let changed = false;
      const next = { ...current };
      for (const variant of visibleCatalog) {
        const key = String(variant.id);
        const rows = current[key];
        if (!rows?.length) continue;
        let variantChanged = false;
        const normalized = rows.map((row) => {
          const clean = clearHiddenInboundTrackingValues(row, variant);
          if (
            clean.batch_number !== row.batch_number ||
            clean.production_date !== row.production_date ||
            clean.expiry_date !== row.expiry_date
          ) {
            changed = true;
            variantChanged = true;
          }
          return clean;
        });
        if (variantChanged) next[key] = normalized;
      }
      return changed ? next : current;
    });
  }, [visibleCatalog]);

  useEffect(() => {
    const ids = visibleCatalog
      .map((item) => item.id)
      .filter((id) => !uomOptions.has(id) && !requestedOptionIds.current.has(id))
      .slice(0, 200);
    if (!ids.length) return;
    ids.forEach((id) => requestedOptionIds.current.add(id));

    optionsInFlight.current += 1;
    setOptionsLoading(true);
    authenticatedFetch("/warehouse/inbound/options", {
      method: "POST",
      body: JSON.stringify({ ids }),
    })
      .then(parseInboundOptions)
      .then((response) => {
        setUomOptions((current) => {
          const next = new Map(current);
          for (const item of response.items) {
            if (ids.includes(item.product_variant_id)) {
              next.set(item.product_variant_id, item);
            }
          }
          return next;
        });
      })
      .catch((error) => {
        toast.error(apiErrorMessage(error, t("inventoryInbound.errors.optionsLoad")));
      })
      .finally(() => {
        optionsInFlight.current -= 1;
        if (optionsInFlight.current === 0) setOptionsLoading(false);
      });
  }, [authenticatedFetch, visibleCatalog, uomOptions, t]);

  useEffect(() => {
    let active = true;
    setCostPolicy(null);
    authenticatedFetch("/warehouse/costing-policy")
      .then(parseCostPolicy)
      .then((policy) => {
        if (active) setCostPolicy(policy);
      })
      .catch((error) => {
        if (active) {
          setCostPolicy(null);
          toast.error(
            apiErrorMessage(error, t("inventoryInbound.errors.policyLoad"))
          );
        }
      });
    return () => {
      active = false;
    };
  }, [authenticatedFetch, companyId, t]);

  const update = (
    variant: CatalogVariant,
    rowId: string,
    patch: Partial<Omit<InboundBatchDraft, "row_id">>
  ) => {
    setDrafts((current) => {
      const key = String(variant.id);
      const variantOptions = uomOptions.get(variant.id);
      const commercialUoms =
        variantOptions?.uoms.filter(
          (uom) => uom.id !== variantOptions.base_uom_id
        ) ?? [];
      const defaultUom = String(
        commercialUoms.length === 1
          ? commercialUoms[0].id
          : variantOptions?.base_uom_id ?? variant.base_uom.id
      );
      const rows = current[key]?.length
        ? [...current[key]]
        : [prefilledInboundRow(rowId, defaultUom, variantOptions)];
      const index = rows.findIndex((row) => row.row_id === rowId);
      if (index < 0) {
        const initial = prefilledInboundRow(rowId, defaultUom, variantOptions);
        const changedUom = patch.uom_id !== undefined && patch.uom_id !== initial.uom_id;
        rows.push({
          ...initial,
          ...(changedUom && patch.unit_cost === undefined ? { unit_cost: "" } : {}),
          ...patch,
        });
      } else {
        const changedUom = patch.uom_id !== undefined && patch.uom_id !== rows[index].uom_id;
        rows[index] = {
          ...rows[index],
          ...(changedUom && patch.unit_cost === undefined ? { unit_cost: "" } : {}),
          ...patch,
        };
      }
      return { ...current, [key]: rows };
    });
    setReferenceChoices(new Map());
    setSelectedReferences(new Map());
    const patchFields = Object.keys(patch) as InboundField[];
    if (
      validationError?.row_id === rowId &&
      patchFields.includes(validationError.field)
    ) {
      setValidationError(null);
    }
  };

  const setRowRef = (rowId: string, node: HTMLTableRowElement | null) => {
    if (node) rowRefs.current.set(rowId, node);
    else rowRefs.current.delete(rowId);
  };

  const setControlRef = (
    rowId: string,
    control: InboundRowControl,
    node: HTMLElement | null,
  ) => {
    const key = controlKey(rowId, control);
    if (node) controlRefs.current.set(key, node);
    else controlRefs.current.delete(key);
  };

  const enableCostEditing = (rowId: string) => {
    setEditingCostRows((current) => new Set(current).add(rowId));
    focusControl(rowId, "unit_cost");
  };

  const stopCostEditing = (rowId: string) => {
    setEditingCostRows((current) => {
      if (!current.has(rowId)) return current;
      const next = new Set(current);
      next.delete(rowId);
      return next;
    });
  };

  const focusControl = (rowId: string, control: InboundRowControl) => {
    window.requestAnimationFrame(() => {
      rowRefs.current.get(rowId)?.scrollIntoView({
        block: "nearest",
        behavior: "smooth",
      });
      controlRefs.current.get(controlKey(rowId, control))?.focus();
    });
  };

  const handleRowEnter = (
    event: KeyboardEvent<HTMLElement>,
    rowId: string,
    variant: CatalogVariant,
    current: InboundRowControl,
  ) => {
    if (
      event.key !== "Enter" ||
      event.altKey ||
      event.ctrlKey ||
      event.metaKey
    ) return;
    const order = rowControlOrder(variant);
    const currentIndex = order.indexOf(current);
    if (currentIndex < 0) return;
    const next = order[currentIndex + 1];
    event.preventDefault();
    event.stopPropagation();
    if (next) {
      focusControl(rowId, next);
      return;
    }
    const rowIndex = keyboardRowIds.indexOf(rowId);
    const nextRowId = rowIndex >= 0 ? keyboardRowIds[rowIndex + 1] : undefined;
    if (nextRowId) focusControl(nextRowId, "quantity");
  };

  const keyboardRowIds = useMemo(
    () =>
      visibleCatalog.flatMap((variant) => {
        const rows = drafts[String(variant.id)];
        return rows?.length
          ? rows.map((row) => row.row_id)
          : [`base-${variant.id}`];
      }),
    [visibleCatalog, drafts],
  );

  const focusValidation = (error: InboundRowValidationError) =>
    focusControl(error.row_id, error.field);

  const fieldHasError = (rowId: string, field: InboundField) =>
    validationError?.row_id === rowId && validationError.field === field;

  const clear = (reconciled = false) => {
    if (!reconciled && (posting.pending || posting.recoveryError)) return;
    setDrafts({});
    setReferenceId("");
    setNotes("");
    setSupplierId(null);
    localStorage.removeItem(supplierKey);
    localStorage.removeItem(keys.drafts);
    localStorage.removeItem(keys.reference);
    localStorage.removeItem(keys.notes);
    localStorage.removeItem(keys.requestId);
    localStorage.removeItem(keys.fingerprint);
    setValidationError(null);
    setReferenceChoices(new Map());
    setSelectedReferences(new Map());
    setEditingCostRows(new Set());
    setClearOpen(false);
  };

  const saveCostPolicy = async (method: CostMethod) => {
    if (!costPolicy || !costPolicy.can_change || savingPolicy) return;
    const scope = durableScope(
      companyId,
      actorId,
      "inventory-cost-policy"
    );
    const businessPayload = {
      method,
      expected_version: costPolicy.version,
    };
    setSavingPolicy(true);
    try {
      const requestId = await getOrCreateDurableRequestId(scope, businessPayload);
      const next = parseCostPolicy(
        await authenticatedFetch("/warehouse/costing-policy", {
          method: "PUT",
          body: JSON.stringify({ request_id: requestId, ...businessPayload }),
        })
      );
      completeDurableOperation(scope, requestId);
      setCostPolicy(next);
      setCostPolicyOpen(false);
      toast.success(t("inventoryInbound.policySaved"));
    } catch (error) {
      toast.error(
        apiErrorMessage(error, t("inventoryInbound.errors.policySave"))
      );
    } finally {
      setSavingPolicy(false);
    }
  };

  const submit = async () => {
    if (!posting.online || supplierId === null) return toast.error(t("suppliers.choose"));
    if (posting.pending || posting.recoveryError || localStorage.getItem(keys.requestId)) return toast.error(t("suppliers.pending"));
    if (isAuditLocked) {
      return toast.error(t("inventoryInbound.errors.auditLocked"));
    }
    const ids = inboundProductIds(drafts);
    if (!ids.length) {
      return toast.error(t("inventoryInbound.errors.quantityRequired"));
    }
    if (!referenceId.trim()) {
      return toast.error(t("inventoryInbound.errors.referenceRequired"));
    }
    if (ids.some((id) => !uomOptions.has(id))) {
      return toast.error(t("inventoryInbound.errors.optionsNotReady"));
    }
    if (!costPolicy) {
      return toast.error(t("inventoryInbound.errors.policyLoad"));
    }
    if (!costPolicy.is_selected) {
      setCostPolicyOpen(true);
      return;
    }
    if (savingPolicy) return;

    setValidationError(null);
    setSubmitting(true);
    try {
      const variants = parseVariants(
        await authenticatedFetch("/catalog/variants/resolve", {
          method: "POST",
          body: JSON.stringify({ ids }),
        })
      ).items;
      if (variants.length !== ids.length) {
        const error = new Error("INBOUND_VARIANT_UNAVAILABLE") as Error & {
          code: string;
        };
        error.code = "INBOUND_VARIANT_UNAVAILABLE";
        throw error;
      }
      const items = buildInboundItems(
        drafts,
        new Map(variants.map((item) => [String(item.id), item])),
        uomOptions,
      );
      const choices = inboundReferenceChoices(items);
      const selections: InboundReferenceSelection[] = [];
      let missingSelection = false;
      for (const [variantId, alternatives] of choices) {
        const selected = selectedReferences.get(variantId);
        if (!selected || !alternatives.some((item) =>
          item.uom_id === selected.uom_id && item.unit_cost === selected.unit_cost
        )) {
          missingSelection = true;
        } else {
          selections.push(selected);
        }
      }
      if (missingSelection) {
        setReferenceChoices(choices);
        toast.error(t("inventoryInbound.referenceSelectionRequired"));
        return;
      }
      const businessPayload = {
        supplier_id: supplierId,
        location_id: locationId,
        reference_id: referenceId.trim(),
        notes: notes.trim() || null,
        items,
        ...(selections.length ? { purchase_reference_selections: selections } : {}),
      };
      if (!(await posting.post(businessPayload))) return;
      toast.success(t("inventoryInbound.received"));
      clear(true);
      await onSuccess();
    } catch (error) {
      if (isInboundRowValidationError(error)) {
        setValidationError(error);
        focusValidation(error);
      }
      toast.error(
        apiErrorMessage(error, t("inventoryInbound.errors.submit"))
      );
    } finally {
      setSubmitting(false);
    }
  };

  const formatFactor = (factor: string) => {
    const numeric = Number(factor);
    if (!Number.isFinite(numeric)) return factor;
    return new Intl.NumberFormat(currentLocale(), {
      maximumFractionDigits: 6,
    }).format(numeric);
  };

  const uomLabel = (code: string, _fallback: string) =>
    t(`uom.${code}`, { defaultValue: t("inventoryCommon.unit") });

  const validationMessage = validationError
    ? t(`errors.codes.${validationError.code}`, {
        defaultValue: t("inventoryInbound.errors.submit"),
      })
    : "";
  return (
    <div
      className="inventory-view inventory-inbound flex h-full min-h-0 flex-col"
      dir={i18n.dir()}
    >
      <div className="inventory-surface inventory-inbound-surface flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border bg-white">
        <div className="inventory-inbound-setup">
          <label className="inventory-inbound-search-field">
            <span>{t("inventoryInbound.searchLabel")}</span>
            <div className="inventory-inbound-search">
              <Search className="h-4 w-4" />
              <input
                value={searchInput}
                onChange={(event) => setSearchInput(event.target.value)}
                placeholder={t("inventoryInbound.search")}
              />
            </div>
          </label>

          <div className="inventory-inbound-supplier">
            <SupplierSelector
              value={supplierId}
              onChange={setSupplierId}
              disabled={submitting || posting.pending !== null}
              searchInControl
            />
            {!posting.online ? <p role="status">{t("suppliers.offline")}</p> : null}
            {posting.pending || posting.recoveryError ? <div role="alert" className="inventory-inbound-recovery">
              <p>{posting.recoveryError ?? t("suppliers.pending")}</p>
              <button type="button" disabled={submitting || !posting.online || !!posting.recoveryError} onClick={async () => {
                setSubmitting(true);
                try { if (await posting.post()) { toast.success(t("inventoryInbound.received")); clear(true); await onSuccess(); } }
                catch (error) { toast.error(apiErrorMessage(error, t("suppliers.pending"))); }
                finally { setSubmitting(false); }
              }}>{t("common.retry")}</button>
            </div> : null}
          </div>

          <div className="inventory-inbound-warehouse">
            <span>{t("inventoryShell.warehouseSelectLabel")}</span>
            <div className="inventory-inbound-warehouse-controls">
              <select
                aria-label={t("inventoryShell.warehouseSelectLabel")}
                value={locationId}
                onChange={(event) => onLocationChange?.(event.target.value)}
                disabled={!onLocationChange || locations.length === 0}
              >
                {locations.map((location) => (
                  <option key={location.id} value={location.id}>
                    {location.name}
                  </option>
                ))}
              </select>
              <button
                type="button"
                onClick={() => setClearOpen(true)}
                className="inventory-inbound-clear"
                title={t("inventoryInbound.clearDraft")}
                aria-label={t("inventoryInbound.clearDraft")}
              >
                <Eraser className="h-4 w-4" />
              </button>
            </div>
          </div>
        </div>

        {referenceChoices.size > 0 && (
          <div className="mx-3 mt-2 rounded-lg border border-amber-300 bg-amber-50 p-3">
            <p className="mb-2 text-xs font-bold text-amber-900">
              {t("inventoryInbound.referenceSelectionRequired")}
            </p>
            {[...referenceChoices.entries()].map(([variantId, choices]) => (
              <label key={variantId} className="mb-2 block text-xs font-semibold text-slate-700">
                {visibleCatalog.find((item) => item.id === variantId)?.name ?? String(variantId)}
                <select
                  aria-label={t("inventoryInbound.referenceSelectionFor", { id: variantId })}
                  className="mt-1 block w-full rounded-lg border border-amber-300 bg-white p-2"
                  value={selectedReferences.has(variantId)
                    ? choices.findIndex((choice) =>
                        choice.uom_id === selectedReferences.get(variantId)?.uom_id &&
                        choice.unit_cost === selectedReferences.get(variantId)?.unit_cost
                      ) : ""}
                  onChange={(event) => {
                    const chosen = choices[Number(event.target.value)];
                    if (!chosen) return;
                    setSelectedReferences((current) => new Map(current).set(variantId, chosen));
                  }}
                >
                  <option value="">{t("inventoryInbound.referenceSelectPlaceholder")}</option>
                  {choices.map((choice, index) => (
                    <option key={choice.uom_id + "|" + choice.unit_cost} value={index}>
                      {choice.unit_cost} {costPolicy?.currency_code ?? ""} / {
                        uomOptions.get(variantId)?.uoms.find((unit) => unit.id === choice.uom_id)?.code
                        ?? String(choice.uom_id)
                      }
                    </option>
                  ))}
                </select>
              </label>
            ))}
          </div>
        )}

        <div
          className="inventory-inbound-table-wrap"
          onScroll={(event) => {
            const element = event.currentTarget;
            const nearEnd =
              element.scrollTop + element.clientHeight >=
              element.scrollHeight - 180;
            if (nearEnd && !loading && nextCursor && cursor !== nextCursor) {
              setCursor(nextCursor);
            }
          }}
        >
          <table className="inventory-inbound-table">
            <colgroup>
              <col className="inventory-inbound-col-number" />
              <col className="inventory-inbound-col-product" />
              <col className="inventory-inbound-col-quantity" />
              <col className="inventory-inbound-col-cost" />
              <col className="inventory-inbound-col-lot" />
              <col className="inventory-inbound-col-production" />
              <col className="inventory-inbound-col-expiry" />
            </colgroup>
            <thead>
              <tr>
                <th className="inventory-inbound-number-head">#</th>
                <th className="text-start">{t("inventoryInbound.product")}</th>
                <th className="text-start">{t("inventoryInbound.quantityAndUnit")}</th>
                <th className="text-start">{t("inventoryInbound.purchaseCost")}</th>
                <th className="text-start">{t("inventoryInbound.batchNumber")}</th>
                <th className="text-start">{t("inventoryInbound.productionDate")}</th>
                <th className="text-start">{t("inventoryInbound.expiryDate")}</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {!visibleCatalog.length && (
                <tr>
                  <td colSpan={7} className="py-12 text-center text-slate-400">
                    {loading
                      ? t("common.loading")
                      : t("inventoryInbound.noProducts")}
                  </td>
                </tr>
              )}
              {visibleCatalog.flatMap((variant, variantIndex) => {
                const option = uomOptions.get(variant.id);
                const commercialUoms =
                  option?.uoms.filter((uom) => uom.id !== option.base_uom_id) ?? [];
                const defaultUom = String(
                  commercialUoms.length === 1
                    ? commercialUoms[0].id
                    : option?.base_uom_id ?? variant.base_uom.id
                );
                const rows = drafts[String(variant.id)]?.length
                  ? drafts[String(variant.id)]
                  : [prefilledInboundRow(`base-${variant.id}`, defaultUom, option)];

                return rows.map((row, index) => {
                  const selectedUom = row.uom_id || defaultUom;
                  const selectedOption = option?.uoms.find(
                    (uom) => String(uom.id) === selectedUom
                  );
                  const tracking = inboundTrackingPolicy(variant);
                  return (
                    <tr
                      key={`${variant.id}-${row.row_id}`}
                      ref={(node) => setRowRef(row.row_id, node)}
                      data-inbound-row-id={row.row_id}
                    >
                      <td className="inventory-inbound-number-cell">
                        {variantIndex + 1}
                      </td>
                      <td className="inventory-inbound-product-cell">
                        <div className="inventory-inbound-product-name">
                          <strong>{variant.name}</strong>
                          {index > 0 ? (
                            <button
                              type="button"
                              title={t("inventoryInbound.removeBatch")}
                              aria-label={t("inventoryInbound.removeBatch")}
                              onClick={() => {
                                setDrafts((current) => ({
                                  ...current,
                                  [String(variant.id)]: (
                                    current[String(variant.id)] ?? []
                                  ).filter((value) => value.row_id !== row.row_id),
                                }));
                                setReferenceChoices(new Map());
                                setSelectedReferences(new Map());
                                if (validationError?.row_id === row.row_id) {
                                  setValidationError(null);
                                }
                              }}
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          ) : null}
                        </div>
                      </td>
                      <td className="inventory-inbound-quantity-cell">
                        <div className="inventory-inbound-quantity-controls">
                          <input
                            ref={(node) => setControlRef(row.row_id, "quantity", node)}
                            inputMode="decimal"
                            value={row.quantity === "0" ? "" : cleanQuantityEntry(row.quantity)}
                            aria-label={t("inventoryInbound.quantity")}
                            aria-invalid={fieldHasError(row.row_id, "quantity")}
                            onFocus={(event) => event.currentTarget.select()}
                            onKeyDown={(event) =>
                              handleRowEnter(event, row.row_id, variant, "quantity")
                            }
                            onChange={(event) =>
                              update(variant, row.row_id, {
                                quantity: cleanQuantityEntry(event.target.value),
                              })
                            }
                            className={fieldHasError(row.row_id, "quantity") ? "is-error" : ""}
                          />
                          <select
                            ref={(node) => setControlRef(row.row_id, "uom_id", node)}
                            value={selectedUom}
                            aria-label={t("inventoryInbound.purchaseUnit")}
                            aria-invalid={fieldHasError(row.row_id, "uom_id")}
                            onChange={(event) =>
                              update(variant, row.row_id, {
                                uom_id: event.target.value,
                              })
                            }
                            disabled={optionsLoading || !option}
                            className={fieldHasError(row.row_id, "uom_id") ? "is-error" : ""}
                          >
                            {(option?.uoms ?? []).map((uom) => (
                              <option key={uom.id} value={uom.id}>
                                {uomLabel(uom.code, uom.name)}
                              </option>
                            ))}
                          </select>
                          {selectedOption && selectedOption.id !== option?.base_uom_id && (
                            <span className="inventory-inbound-factor">
                              {t("inventoryInbound.factorToBase", {
                                factor: formatFactor(selectedOption.factor_to_base),
                                unit: uomLabel(
                                  variant.base_uom.code,
                                  variant.base_uom.name
                                ),
                              })}
                            </span>
                          )}
                        </div>
                        {(fieldHasError(row.row_id, "quantity") ||
                          fieldHasError(row.row_id, "uom_id")) && (
                          <p role="alert" className="inventory-inbound-field-error">
                            {validationMessage}
                          </p>
                        )}
                      </td>
                      <td className="inventory-inbound-cost-cell">
                        <div className="inventory-inbound-cost-control">
                          <input
                            ref={(node) => setControlRef(row.row_id, "unit_cost", node)}
                            inputMode="decimal"
                            value={row.unit_cost}
                            readOnly={!editingCostRows.has(row.row_id)}
                            aria-label={t("inventoryInbound.unitCostPlaceholder")}
                            aria-invalid={fieldHasError(row.row_id, "unit_cost")}
                            onFocus={(event) => event.currentTarget.select()}
                            onKeyDown={(event) => {
                              // Keep Enter-to-next-field navigation; F2 opens cost
                              // entry for keyboard-only operators.
                              if (event.key === "F2") {
                                event.preventDefault();
                                enableCostEditing(row.row_id);
                                return;
                              }
                              if (event.key === "Escape" && editingCostRows.has(row.row_id)) {
                                event.preventDefault();
                                stopCostEditing(row.row_id);
                                return;
                              }
                              handleRowEnter(event, row.row_id, variant, "unit_cost");
                            }}
                            onBlur={() => stopCostEditing(row.row_id)}
                            onChange={(event) => {
                              if (!editingCostRows.has(row.row_id)) return;
                              update(variant, row.row_id, {
                                unit_cost: event.target.value.replace(/[^0-9.]/g, ""),
                              });
                            }}
                            className={fieldHasError(row.row_id, "unit_cost") ? "is-error" : ""}
                          />
                          <button
                            type="button"
                            aria-label={t("inventoryInbound.editPurchaseCost")}
                            title={t("inventoryInbound.editPurchaseCost")}
                            disabled={submitting || posting.pending !== null}
                            onClick={() => enableCostEditing(row.row_id)}
                            className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-slate-600 hover:bg-slate-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-amber-500 disabled:opacity-50"
                          >
                            <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
                          </button>
                          <span>
                            {costPolicy?.currency_code ?? ""}
                            {selectedOption
                              ? ` / ${uomLabel(selectedOption.code, selectedOption.name)}`
                              : ""}
                          </span>
                        </div>
                        {option?.purchase_cost_reference && (
                          <button
                            type="button"
                            disabled={submitting || posting.pending !== null}
                            onClick={() => update(variant, row.row_id, {
                              uom_id: String(option.purchase_cost_reference!.purchase_uom_id),
                              unit_cost: option.purchase_cost_reference!.amount,
                            })}
                            className="mt-1 text-xs font-semibold text-emerald-800 underline"
                          >
                            {t("inventoryInbound.useReferenceSuggestion", {
                              cost: option.purchase_cost_reference.amount,
                              currency: option.purchase_cost_reference.currency_code,
                            })}
                          </button>
                        )}
                        {fieldHasError(row.row_id, "unit_cost") && (
                          <p role="alert" className="inventory-inbound-field-error">
                            {validationMessage}
                          </p>
                        )}
                      </td>
                      <td className="inventory-inbound-lot-cell">
                        {tracking.lot.visible ? (
                          <>
                            <input
                              ref={(node) =>
                                setControlRef(row.row_id, "batch_number", node)
                              }
                              value={row.batch_number}
                              required={tracking.lot.required}
                              aria-required={tracking.lot.required}
                              aria-invalid={fieldHasError(row.row_id, "batch_number")}
                              aria-label={t("inventoryInbound.batchNumber")}
                              onKeyDown={(event) =>
                                handleRowEnter(
                                  event,
                                  row.row_id,
                                  variant,
                                  "batch_number"
                                )
                              }
                              onChange={(event) =>
                                update(variant, row.row_id, {
                                  batch_number: event.target.value,
                                })
                              }
                              title={t(
                                tracking.lot.required
                                  ? "inventoryInbound.rowBatchRequiredHint"
                                  : "inventoryInbound.rowBatchOptionalHint"
                              )}
                              className={
                                fieldHasError(row.row_id, "batch_number")
                                  ? "is-error"
                                  : ""
                              }
                            />
                            {fieldHasError(row.row_id, "batch_number") && (
                              <small role="alert" className="inventory-inbound-field-error">
                                {validationMessage}
                              </small>
                            )}
                          </>
                        ) : (
                          <span className="inventory-inbound-not-applicable">{"\u2014"}</span>
                        )}
                      </td>
                      <td className="inventory-inbound-production-cell">
                        {tracking.production.visible ? (
                          <>
                            <InboundDateInput
                              inputRef={(node) =>
                                setControlRef(row.row_id, "production_date", node)
                              }
                              value={row.production_date}
                              label={t("inventoryInbound.productionDate")}
                              invalid={fieldHasError(row.row_id, "production_date")}
                              placeholder={
                                variantIndex === 0 && index === 0
                                  ? t("inventoryInbound.dateQuickPlaceholder")
                                  : undefined
                              }
                              onChange={(value) =>
                                update(variant, row.row_id, {
                                  production_date: value,
                                })
                              }
                            />
                            {fieldHasError(row.row_id, "production_date") && (
                              <small role="alert" className="inventory-inbound-field-error">
                                {validationMessage}
                              </small>
                            )}
                          </>
                        ) : (
                          <span className="inventory-inbound-not-applicable">{"\u2014"}</span>
                        )}
                      </td>
                      <td className="inventory-inbound-expiry-cell">
                        {tracking.expiry.visible ? (
                          <>
                            <InboundDateInput
                              inputRef={(node) =>
                                setControlRef(row.row_id, "expiry_date", node)
                              }
                              value={row.expiry_date}
                              label={t("inventoryInbound.expiryDate")}
                              required={tracking.expiry.required}
                              invalid={fieldHasError(row.row_id, "expiry_date")}
                              placeholder={
                                variantIndex === 0 && index === 0
                                  ? t("inventoryInbound.dateQuickPlaceholder")
                                  : undefined
                              }
                              onEnter={(event) =>
                                handleRowEnter(
                                  event,
                                  row.row_id,
                                  variant,
                                  "expiry_date"
                                )
                              }
                              onChange={(value) =>
                                update(variant, row.row_id, {
                                  expiry_date: value,
                                })
                              }
                            />
                            {fieldHasError(row.row_id, "expiry_date") && (
                              <small role="alert" className="inventory-inbound-field-error">
                                {validationMessage}
                              </small>
                            )}
                          </>
                        ) : (
                          <span className="inventory-inbound-not-applicable">{"\u2014"}</span>
                        )}
                      </td>
                    </tr>
                  );
                });
              })}
            </tbody>
          </table>
        </div>

        <div className="inventory-inbound-footer">
          <input
            value={referenceId}
            onChange={(event) => setReferenceId(event.target.value)}
            placeholder={t("inventoryInbound.reference")}
            aria-label={t("inventoryInbound.reference")}
            className="inventory-inbound-footer-input inventory-inbound-footer-reference"
          />
          <input
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
            placeholder={t("inventoryInbound.notes")}
            aria-label={t("inventoryInbound.notes")}
            className="inventory-inbound-footer-input inventory-inbound-footer-notes"
          />
          <button
            type="button"
            onClick={() => void submit()}
            disabled={
              submitting ||
              isAuditLocked ||
              optionsLoading ||
              !costPolicy ||
              savingPolicy
            }
            className="inventory-inbound-submit disabled:opacity-50"
          >
            {submitting
              ? t("inventoryInbound.submitting")
              : t("inventoryInbound.submit")}
          </button>
        </div>

        <Modal
          isOpen={costPolicyOpen}
          onClose={() => {
            if (!savingPolicy) setCostPolicyOpen(false);
          }}
          title={t("inventoryInbound.costSetupTitle")}
          subtitle={t("inventoryInbound.costSetupSubtitle")}
          maxWidth="max-w-xl"
        >
          {costPolicy?.can_change ? (
            <div className="inventory-inbound-cost-setup">
              <button
                type="button"
                disabled={savingPolicy}
                onClick={() => void saveCostPolicy("MOVING_AVERAGE")}
              >
                <strong>{t("inventoryInbound.methods.MOVING_AVERAGE")}</strong>
                <span>{t("inventoryInbound.costSetupMovingAverage")}</span>
              </button>
              <button
                type="button"
                disabled={savingPolicy}
                onClick={() => void saveCostPolicy("FIFO")}
              >
                <strong>{t("inventoryInbound.methods.FIFO")}</strong>
                <span>{t("inventoryInbound.costSetupFifo")}</span>
              </button>
              <p>{t("inventoryInbound.costSetupSettingsNote")}</p>
            </div>
          ) : (
            <p role="alert" className="text-sm font-bold text-amber-800">
              {t("inventoryInbound.costMethodNoPermission")}
            </p>
          )}
        </Modal>

        <Modal
          isOpen={clearOpen}
          onClose={() => setClearOpen(false)}
          title={t("inventoryInbound.clearTitle")}
          footer={
            <>
              <button type="button" onClick={() => setClearOpen(false)}>
                {t("common.cancel")}
              </button>
              <button
                type="button"
                onClick={() => clear()}
                className="rounded-xl bg-red-600 text-white px-5 py-2"
              >
                {t("inventoryInbound.clearConfirm")}
              </button>
            </>
          }
        >
          <p>{t("inventoryInbound.clearBody")}</p>
        </Modal>
      </div>
    </div>
  );
}