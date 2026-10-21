import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import {
  ChevronLeft,
  ChevronRight,
  Eraser,
  FilePlus,
  Plus,
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
  type InboundDocumentDefaults,
  type InboundDraftMap,
  type InboundField,
  type InboundRowValidationError,
  type InboundVariantOptions,
} from "./inbound/contracts";
import {
  clearHiddenInboundTrackingValues,
  inboundTrackingPolicy,
} from "./inbound/trackingPolicy";

interface Props {
  companyId: number;
  actorId: number;
  locationId: number;
  isAuditLocked: boolean;
  authenticatedFetch: (
    url: string,
    opts?: RequestInit
  ) => Promise<unknown>;
  onSuccess: () => void | Promise<void>;
}

const freshRowId = () => crypto.randomUUID();

type InboundRowControl = InboundField | "add_line";

const controlKey = (rowId: string, control: InboundRowControl) =>
  `${rowId}:${control}`;

const rowControlOrder = (variant: CatalogVariant): InboundRowControl[] => {
  const policy = inboundTrackingPolicy(variant);
  return [
    ...(policy.lot.visible ? (["batch_number"] as const) : []),
    ...(policy.production.visible ? (["production_date"] as const) : []),
    ...(policy.expiry.visible ? (["expiry_date"] as const) : []),
    "quantity",
    "uom_id",
    "unit_cost",
    "add_line",
  ];
};

export function Tab2Inbound({
  companyId,
  actorId,
  locationId,
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
  const [uomOptions, setUomOptions] = useState<
    Map<number, InboundVariantOptions>
  >(new Map());
  const [costPolicy, setCostPolicy] = useState<CostPolicy | null>(null);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [cursor, setCursor] = useState<string | null>(null);
  const [history, setHistory] = useState<Array<string | null>>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [optionsLoading, setOptionsLoading] = useState(false);
  const [referenceChoices, setReferenceChoices] = useState<Map<number, InboundReferenceSelection[]>>(new Map());
  const [selectedReferences, setSelectedReferences] = useState<Map<number, InboundReferenceSelection>>(new Map());
  const [submitting, setSubmitting] = useState(false);
  const [savingPolicy, setSavingPolicy] = useState(false);
  const [clearOpen, setClearOpen] = useState(false);
  const [validationError, setValidationError] =
    useState<InboundRowValidationError | null>(null);
  const [referenceId, setReferenceId] = useState(
    () => localStorage.getItem(keys.reference) || ""
  );
  const [notes, setNotes] = useState(
    () => localStorage.getItem(keys.notes) || ""
  );
  const [documentDefaults, setDocumentDefaults] =
    useState<InboundDocumentDefaults>(() => ({
      batch_number: localStorage.getItem(keys.batchDefault) || "",
    }));
  const request = useRef(0);
  const optionsRequest = useRef(0);
  const rowRefs = useRef(new Map<string, HTMLTableRowElement>());
  const controlRefs = useRef(new Map<string, HTMLElement>());
  const supplierKey = `${keys.drafts}:supplier`;
  const [supplierId, setSupplierId] = useState<number | null>(() => {
    const saved = Number(localStorage.getItem(supplierKey));
    return Number.isSafeInteger(saved) && saved > 0 ? saved : null;
  });
  const posting = useInboundPosting({ companyId, actorId, locationId, authenticatedFetch, legacyRequestKey: keys.requestId, legacyPayloadKey: keys.fingerprint });
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
    if (documentDefaults.batch_number) {
      localStorage.setItem(keys.batchDefault, documentDefaults.batch_number);
    } else {
      localStorage.removeItem(keys.batchDefault);
    }
  }, [documentDefaults.batch_number, keys]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const clean = searchInput.trim();
      setSearch(clean.length >= 2 ? clean : "");
      setCursor(null);
      setHistory([]);
    }, 300);
    return () => clearTimeout(timer);
  }, [searchInput]);

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
          setCatalog(page.items);
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
    if (!catalog.length) return;
    setDrafts((current) => {
      let changed = false;
      const next = { ...current };
      for (const variant of catalog) {
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
  }, [catalog]);

  useEffect(() => {
    const ids = catalog.map((item) => item.id);
    if (!ids.length) {
      setUomOptions(new Map());
      return;
    }
    const id = ++optionsRequest.current;
    setOptionsLoading(true);
    authenticatedFetch("/warehouse/inbound/options", {
      method: "POST",
      body: JSON.stringify({ ids }),
    })
      .then(parseInboundOptions)
      .then((response) => {
        if (id !== optionsRequest.current) return;
        setUomOptions(
          new Map(
            response.items.map((item) => [item.product_variant_id, item])
          )
        );
      })
      .catch((error) => {
        if (id === optionsRequest.current) {
          setUomOptions(new Map());
          toast.error(
            apiErrorMessage(error, t("inventoryInbound.errors.optionsLoad"))
          );
        }
      })
      .finally(() => {
        if (id === optionsRequest.current) setOptionsLoading(false);
      });
  }, [authenticatedFetch, catalog, t]);

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
        rows.push({ ...prefilledInboundRow(rowId, defaultUom, variantOptions), ...patch });
      } else {
        // A cost belongs to its purchase unit. Changing UOM must not silently
        // reuse the old cost under a different unit.
        const changingUom = patch.uom_id !== undefined && patch.uom_id !== rows[index].uom_id;
        rows[index] = {
          ...rows[index],
          ...(changingUom ? { unit_cost: "" } : {}),
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
    const next = order[order.indexOf(current) + 1];
    if (!next) return;
    event.preventDefault();
    event.stopPropagation();
    focusControl(rowId, next);
  };

  const focusValidation = (error: InboundRowValidationError) =>
    focusControl(error.row_id, error.field);

  const fieldHasError = (rowId: string, field: InboundField) =>
    validationError?.row_id === rowId && validationError.field === field;

  const clear = (reconciled = false) => {
    if (!reconciled && (posting.pending || posting.recoveryError)) return;
    setDrafts({});
    setReferenceId("");
    setNotes("");
    localStorage.removeItem(keys.drafts);
    localStorage.removeItem(keys.reference);
    localStorage.removeItem(keys.notes);
    localStorage.removeItem(keys.requestId);
    localStorage.removeItem(keys.fingerprint);
    localStorage.removeItem(keys.batchDefault);
    setDocumentDefaults({ batch_number: "" });
    setValidationError(null);
    setReferenceChoices(new Map());
    setSelectedReferences(new Map());
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
    if (!costPolicy?.is_selected || savingPolicy) {
      return toast.error(t("inventoryInbound.errors.policyRequired"));
    }
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
        documentDefaults
      );
      const choices = inboundReferenceChoices(items);
      const selections: InboundReferenceSelection[] = [];
      let missingSelection = false;
      for (const [variantId, alternatives] of choices) {
        const selected = selectedReferences.get(variantId);
        if (!selected || !alternatives.some((choice) =>
          choice.uom_id === selected.uom_id && choice.unit_cost === selected.unit_cost
        )) {
          missingSelection = true;
        } else selections.push(selected);
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
  const isRtl = i18n.dir() === "rtl";

  return (
    <div
      className="inventory-view inventory-inbound flex flex-col h-full min-h-0 pt-1"
      dir={i18n.dir()}
    >
      <div className="inventory-surface relative bg-white rounded-2xl border flex flex-col flex-1 min-h-0">
        <div className="mx-4 mt-6">
          <SupplierSelector value={supplierId} onChange={setSupplierId} disabled={submitting || posting.pending !== null} />
          {!posting.online ? <p role="status">{t("suppliers.offline")}</p> : null}
          {posting.pending || posting.recoveryError ? <div role="alert">
            <p>{posting.recoveryError ?? t("suppliers.pending")}</p>
            <button type="button" disabled={submitting || !posting.online || !!posting.recoveryError} onClick={async () => {
              setSubmitting(true);
              try { if (await posting.post()) { toast.success(t("inventoryInbound.received")); clear(true); await onSuccess(); } }
              catch (error) { toast.error(apiErrorMessage(error, t("suppliers.pending"))); }
              finally { setSubmitting(false); }
            }}>{t("common.retry")}</button>
          </div> : null}
        </div>
        <div className="absolute -top-3.5 right-6 rtl:right-6 rtl:left-auto ltr:left-6 ltr:right-auto bg-emerald-600 text-white px-4 py-1.5 rounded-lg text-sm font-black flex gap-2">
          <FilePlus className="w-4 h-4" />
          {t("inventoryInbound.title")}
        </div>

        <div className="mx-4 mt-6 rounded-2xl border border-emerald-100 bg-emerald-50/60 p-4">
          <label className="block text-xs font-black text-slate-700">
            {t("inventoryInbound.defaultBatchTitle")}
            <input
              value={documentDefaults.batch_number}
              onChange={(event) =>
                setDocumentDefaults({ batch_number: event.target.value })
              }
              placeholder={t("inventoryInbound.defaultBatchPlaceholder")}
              className="mt-1.5 w-full max-w-md rounded-xl border bg-white p-2.5"
            />
          </label>
          <p className="mt-2 text-xs font-semibold text-emerald-800/80">
            {t("inventoryInbound.defaultBatchHint")}
          </p>
        </div>

        {referenceChoices.size > 0 && (
          <div className="mx-4 mt-3 rounded-xl border border-amber-300 bg-amber-50 p-3">
            <p className="mb-2 text-xs font-bold text-amber-900">
              {t("inventoryInbound.referenceSelectionRequired")}
            </p>
            {[...referenceChoices.entries()].map(([variantId, choices]) => (
              <label key={variantId} className="mb-2 block text-xs font-semibold text-slate-700">
                {catalog.find((item) => item.id === variantId)?.name ?? String(variantId)}
                <select
                  aria-label={t("inventoryInbound.referenceSelectionFor", { id: variantId })}
                  className="mt-1 block w-full rounded-lg border border-amber-300 bg-white p-2"
                  value={selectedReferences.has(variantId)
                    ? choices.findIndex((choice) =>
                      choice.uom_id === selectedReferences.get(variantId)?.uom_id &&
                      choice.unit_cost === selectedReferences.get(variantId)?.unit_cost
                    ) : ""}
                  onChange={(event) => {
                    const option = choices[Number(event.target.value)];
                    if (!option) return;
                    setSelectedReferences((previous) => new Map(previous).set(variantId, option));
                  }}
                >
                  <option value="">{t("inventoryInbound.referenceSelectPlaceholder")}</option>
                  {choices.map((choice, index) => (
                    <option key={choice.uom_id + "|" + choice.unit_cost} value={index}>
                      {choice.unit_cost} {costPolicy?.currency_code ?? ""} / {uomOptions.get(variantId)?.uoms.find((unit) =>
                        unit.id === choice.uom_id
                      )?.code ?? String(choice.uom_id)}
                    </option>
                  ))}
                </select>
              </label>
            ))}
          </div>
        )}

        <div className="flex-1 min-h-0 overflow-auto mt-3">
          <table className="w-full text-sm min-w-[1120px]">
            <thead className="sticky top-0 bg-slate-50 border-b z-10">
              <tr>
                <th className="p-3 text-start">
                  <div className="flex gap-2 items-center">
                    {t("inventoryInbound.product")}
                    <div className="relative">
                      <Search className="absolute start-2 top-2 w-4 h-4 text-slate-400" />
                      <input
                        value={searchInput}
                        onChange={(event) => setSearchInput(event.target.value)}
                        className="rounded-lg border py-1.5 ps-8 pe-2"
                        placeholder={t("inventoryInbound.search")}
                      />
                    </div>
                  </div>
                </th>
                <th className="p-3 text-start">{t("inventoryInbound.batchAndDates")}</th>
                <th className="p-3 text-start">{t("inventoryInbound.quantityAndUnit")}</th>
                <th className="p-3 text-start">{t("inventoryInbound.purchaseCost")}</th>
                <th className="p-3">
                  <button
                    type="button"
                    onClick={() => setClearOpen(true)}
                    className="text-red-600"
                    title={t("inventoryInbound.clearDraft")}
                  >
                    <Eraser className="w-4 h-4" />
                  </button>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {!catalog.length && (
                <tr>
                  <td colSpan={5} className="py-12 text-center text-slate-400">
                    {loading
                      ? t("common.loading")
                      : t("inventoryInbound.noProducts")}
                  </td>
                </tr>
              )}
              {catalog.flatMap((variant) => {
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
                  const trackingFieldCount = [
                    tracking.lot.visible,
                    tracking.production.visible,
                    tracking.expiry.visible,
                  ].filter(Boolean).length;
                  return (
                    <tr
                      key={`${variant.id}-${row.row_id}`}
                      ref={(node) => setRowRef(row.row_id, node)}
                      data-inbound-row-id={row.row_id}
                    >
                      <td className="p-3 font-bold">{variant.name}</td>
                      <td className="p-3">
                        {trackingFieldCount > 0 ? (
                          <div
                            className="grid gap-2"
                            style={{
                              gridTemplateColumns: `repeat(${trackingFieldCount}, minmax(0, 1fr))`,
                            }}
                          >
                            {tracking.lot.visible && (
                              <label className="min-w-0 text-xs font-bold text-slate-600">
                                <span className="mb-1 flex items-center gap-1">
                                  {t("inventoryInbound.batchNumber")}
                                  <span className="font-semibold text-slate-400">
                                    {t(
                                      tracking.lot.required
                                        ? "inventoryInbound.required"
                                        : "inventoryInbound.optional"
                                    )}
                                  </span>
                                </span>
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
                                  placeholder={
                                    tracking.lot.required && documentDefaults.batch_number
                                      ? t("inventoryInbound.overrideBatchPlaceholder", {
                                          batch: documentDefaults.batch_number,
                                        })
                                      : tracking.lot.required
                                        ? t("inventoryInbound.batchNumber")
                                        : t("inventoryInbound.optionalLotPlaceholder")
                                  }
                                  title={t(
                                    tracking.lot.required
                                      ? "inventoryInbound.rowBatchRequiredHint"
                                      : "inventoryInbound.rowBatchOptionalHint"
                                  )}
                                  className={`w-full rounded-lg border p-2 ${
                                    fieldHasError(row.row_id, "batch_number")
                                      ? "border-red-500 ring-1 ring-red-200"
                                      : ""
                                  }`}
                                />
                                {fieldHasError(row.row_id, "batch_number") && (
                                  <span
                                    role="alert"
                                    className="mt-1 block text-xs font-semibold text-red-600"
                                  >
                                    {validationMessage}
                                  </span>
                                )}
                              </label>
                            )}
                            {tracking.production.visible && (
                              <label className="min-w-0 text-xs font-bold text-slate-600">
                                <span className="mb-1 flex items-center gap-1">
                                  {t("inventoryInbound.productionDate")}
                                  <span className="font-semibold text-slate-400">
                                    {t("inventoryInbound.optional")}
                                  </span>
                                </span>
                                <input
                                  ref={(node) =>
                                    setControlRef(row.row_id, "production_date", node)
                                  }
                                  type="date"
                                  value={row.production_date}
                                  aria-invalid={fieldHasError(row.row_id, "production_date")}
                                  onKeyDown={(event) =>
                                    handleRowEnter(
                                      event,
                                      row.row_id,
                                      variant,
                                      "production_date"
                                    )
                                  }
                                  onChange={(event) =>
                                    update(variant, row.row_id, {
                                      production_date: event.target.value,
                                    })
                                  }
                                  className={`w-full rounded-lg border p-2 ${
                                    fieldHasError(row.row_id, "production_date")
                                      ? "border-red-500 ring-1 ring-red-200"
                                      : ""
                                  }`}
                                  aria-label={t("inventoryInbound.productionDate")}
                                />
                                {fieldHasError(row.row_id, "production_date") && (
                                  <span
                                    role="alert"
                                    className="mt-1 block text-xs font-semibold text-red-600"
                                  >
                                    {validationMessage}
                                  </span>
                                )}
                              </label>
                            )}
                            {tracking.expiry.visible && (
                              <label className="min-w-0 text-xs font-bold text-slate-600">
                                <span className="mb-1 flex items-center gap-1">
                                  {t("inventoryInbound.expiryDate")}
                                  <span className="font-semibold text-slate-400">
                                    {t(
                                      tracking.expiry.required
                                        ? "inventoryInbound.required"
                                        : "inventoryInbound.optional"
                                    )}
                                  </span>
                                </span>
                                <input
                                  ref={(node) =>
                                    setControlRef(row.row_id, "expiry_date", node)
                                  }
                                  type="date"
                                  value={row.expiry_date}
                                  required={tracking.expiry.required}
                                  aria-required={tracking.expiry.required}
                                  aria-invalid={fieldHasError(row.row_id, "expiry_date")}
                                  onKeyDown={(event) =>
                                    handleRowEnter(
                                      event,
                                      row.row_id,
                                      variant,
                                      "expiry_date"
                                    )
                                  }
                                  onChange={(event) =>
                                    update(variant, row.row_id, {
                                      expiry_date: event.target.value,
                                    })
                                  }
                                  className={`w-full rounded-lg border p-2 ${
                                    fieldHasError(row.row_id, "expiry_date")
                                      ? "border-red-500 ring-1 ring-red-200"
                                      : ""
                                  }`}
                                  aria-label={t("inventoryInbound.expiryDate")}
                                />
                                {fieldHasError(row.row_id, "expiry_date") && (
                                  <span
                                    role="alert"
                                    className="mt-1 block text-xs font-semibold text-red-600"
                                  >
                                    {validationMessage}
                                  </span>
                                )}
                              </label>
                            )}
                          </div>
                        ) : (
                          <span className="text-xs font-semibold text-slate-400">
                            {t("inventoryInbound.noTrackingFields")}
                          </span>
                        )}
                      </td>
                      <td className="p-3">
                        <div className="flex items-center gap-2">
                          <input
                            ref={(node) => setControlRef(row.row_id, "quantity", node)}
                            inputMode="decimal"
                            value={row.quantity}
                            aria-label={t("inventoryInbound.quantity")}
                            aria-invalid={fieldHasError(row.row_id, "quantity")}
                            onKeyDown={(event) =>
                              handleRowEnter(event, row.row_id, variant, "quantity")
                            }
                            onChange={(event) =>
                              update(variant, row.row_id, {
                                quantity: event.target.value.replace(/[^0-9.]/g, ""),
                              })
                            }
                            className={`w-28 rounded-lg border p-2 text-center ${
                              fieldHasError(row.row_id, "quantity")
                                ? "border-red-500 ring-1 ring-red-200"
                                : ""
                            }`}
                          />
                          <select
                            ref={(node) => setControlRef(row.row_id, "uom_id", node)}
                            value={selectedUom}
                            aria-label={t("inventoryInbound.purchaseUnit")}
                            aria-invalid={fieldHasError(row.row_id, "uom_id")}
                            onKeyDown={(event) =>
                              handleRowEnter(event, row.row_id, variant, "uom_id")
                            }
                            onChange={(event) =>
                              update(variant, row.row_id, {
                                uom_id: event.target.value,
                              })
                            }
                            disabled={optionsLoading || !option}
                            className={`rounded-lg border p-2 min-w-28 bg-white ${
                              fieldHasError(row.row_id, "uom_id")
                                ? "border-red-500 ring-1 ring-red-200"
                                : ""
                            }`}
                          >
                            {(option?.uoms ?? []).map((uom) => (
                              <option key={uom.id} value={uom.id}>
                                {uomLabel(uom.code, uom.name)}
                              </option>
                            ))}
                          </select>
                          {selectedOption && selectedOption.id !== option?.base_uom_id && (
                            <span className="text-xs text-slate-400 whitespace-nowrap">
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
                          <p
                            role="alert"
                            className="mt-1 text-xs font-semibold text-red-600"
                          >
                            {validationMessage}
                          </p>
                        )}
                      </td>
                      <td className="p-3">
                        <div className="flex items-center gap-2">
                          <input
                            ref={(node) => setControlRef(row.row_id, "unit_cost", node)}
                            inputMode="decimal"
                            value={row.unit_cost}
                            aria-label={t("inventoryInbound.unitCostPlaceholder")}
                            aria-invalid={fieldHasError(row.row_id, "unit_cost")}
                            onKeyDown={(event) =>
                              handleRowEnter(event, row.row_id, variant, "unit_cost")
                            }
                            onChange={(event) =>
                              update(variant, row.row_id, {
                                unit_cost: event.target.value.replace(/[^0-9.]/g, ""),
                              })
                            }
                            placeholder={t("inventoryInbound.unitCostPlaceholder")}
                            className={`w-32 rounded-lg border p-2 text-center ${
                              fieldHasError(row.row_id, "unit_cost")
                                ? "border-red-500 ring-1 ring-red-200"
                                : ""
                            }`}
                          />
                          <span className="text-xs font-bold text-slate-500">
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
                          <p
                            role="alert"
                            className="mt-1 text-xs font-semibold text-red-600"
                          >
                            {validationMessage}
                          </p>
                        )}
                      </td>
                      <td className="p-3">
                        <div className="flex gap-2">
                          <button
                            ref={(node) => setControlRef(row.row_id, "add_line", node)}
                            type="button"
                            title={t("inventoryInbound.addReceiptLine")}
                            aria-label={t("inventoryInbound.addReceiptLine")}
                            onClick={() => {
                              const baseUom = String(
                                option?.base_uom_id ?? variant.base_uom.id
                              );
                              const nextUom =
                                selectedUom !== baseUom
                                  ? baseUom
                                  : commercialUoms.length === 1
                                    ? String(commercialUoms[0].id)
                                    : defaultUom;
                              const nextRowId = freshRowId();
                              const nextRow = clearHiddenInboundTrackingValues(
                                {
                                  ...emptyInboundBatch(nextRowId, nextUom),
                                  batch_number: row.batch_number,
                                  production_date: row.production_date,
                                  expiry_date: row.expiry_date,
                                },
                                variant
                              );
                              setDrafts((current) => ({
                                ...current,
                                [String(variant.id)]: [
                                  ...(current[String(variant.id)] ?? [row]),
                                  nextRow,
                                ],
                              }));
                              const firstControl =
                                rowControlOrder(variant)[0] ?? "quantity";
                              window.setTimeout(() =>
                                focusControl(nextRowId, firstControl),
                                0
                              );
                            }}
                          >
                            <Plus className="w-4 h-4" />
                          </button>
                          {index > 0 && (
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
                                if (validationError?.row_id === row.row_id) {
                                  setValidationError(null);
                                }
                              }}
                            >
                              <Trash2 className="w-4 h-4 text-red-500" />
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                });
              })}
            </tbody>
          </table>
        </div>

        {(history.length || nextCursor) && (
          <div className="flex justify-end gap-2 p-2 border-t">
            <button
              type="button"
              aria-label={t("inventoryInbound.previousPage")}
              disabled={!history.length}
              onClick={() => {
                const previous = history.at(-1) ?? null;
                setHistory((value) => value.slice(0, -1));
                setCursor(previous);
              }}
            >
              {isRtl ? <ChevronRight /> : <ChevronLeft />}
            </button>
            <button
              type="button"
              aria-label={t("inventoryInbound.nextPage")}
              disabled={!nextCursor}
              onClick={() => {
                if (nextCursor) {
                  setHistory((value) => [...value, cursor]);
                  setCursor(nextCursor);
                }
              }}
            >
              {isRtl ? <ChevronLeft /> : <ChevronRight />}
            </button>
          </div>
        )}

        <div className="p-3 bg-slate-50 border-t grid xl:grid-cols-[1fr_1fr_auto_auto] gap-3 items-center">
          <input
            value={referenceId}
            onChange={(event) => setReferenceId(event.target.value)}
            placeholder={t("inventoryInbound.reference")}
            className="rounded-xl border p-2"
          />
          <input
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
            placeholder={t("inventoryInbound.notes")}
            className="rounded-xl border p-2"
          />
          <div className="flex items-center gap-2 whitespace-nowrap">
            <span className="text-xs font-bold text-slate-500">
              {t("inventoryInbound.costMethod")}
            </span>
            <select
              value={costPolicy?.method ?? ""}
              aria-label={t("inventoryInbound.costMethod")}
              aria-describedby={
                costPolicy && !costPolicy.is_selected
                  ? "inbound-cost-policy-hint"
                  : undefined
              }
              disabled={!costPolicy?.can_change || savingPolicy}
              onChange={(event) => {
                const selected = event.target.value;
                if (selected === "MOVING_AVERAGE" || selected === "FIFO") {
                  void saveCostPolicy(selected);
                }
              }}
              className="rounded-xl border bg-white p-2 text-sm"
            >
              <option value="" disabled>
                {t("inventoryInbound.chooseCostMethod")}
              </option>
              <option value="MOVING_AVERAGE">
                {t("inventoryInbound.methods.MOVING_AVERAGE")}
              </option>
              <option value="FIFO">{t("inventoryInbound.methods.FIFO")}</option>
            </select>
            {costPolicy?.is_locked && (
              <span className="text-xs text-slate-400">
                {t("inventoryInbound.costMethodLocked")}
              </span>
            )}
            {costPolicy && !costPolicy.is_selected && (
              <span
                id="inbound-cost-policy-hint"
                role="alert"
                className="max-w-72 whitespace-normal text-xs font-semibold text-amber-800"
              >
                {t(
                  costPolicy.can_change
                    ? "inventoryInbound.costMethodRequired"
                    : "inventoryInbound.costMethodNoPermission"
                )}
              </span>
            )}
          </div>
          <button
            type="button"
            onClick={() => void submit()}
            disabled={
              submitting ||
              isAuditLocked ||
              optionsLoading ||
              !costPolicy?.is_selected ||
              savingPolicy
            }
            className="rounded-xl bg-emerald-600 text-white px-6 py-2 font-black disabled:opacity-50"
          >
            {submitting
              ? t("inventoryInbound.submitting")
              : t("inventoryInbound.submit")}
          </button>
        </div>

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
