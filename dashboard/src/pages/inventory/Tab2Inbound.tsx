import { useEffect, useMemo, useRef, useState } from "react";
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
import {
  completeDurableOperation,
  durableScope,
  getOrCreateDurableRequestId,
} from "@/lib/durableOperations";
import {
  parseVariants,
  type CatalogVariant,
} from "./catalog/contracts";
import {
  buildInboundItems,
  emptyInboundBatch,
  inboundProductIds,
  inboundStorageKeys,
  parseCostPolicy,
  parseInboundDrafts,
  parseInboundOptions,
  parseInboundResponse,
  type CostPolicy,
  type InboundBatchDraft,
  type InboundDraftMap,
  type InboundVariantOptions,
} from "./inbound/contracts";

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
  const [submitting, setSubmitting] = useState(false);
  const [savingPolicy, setSavingPolicy] = useState(false);
  const [clearOpen, setClearOpen] = useState(false);
  const [referenceId, setReferenceId] = useState(
    () => localStorage.getItem(keys.reference) || ""
  );
  const [notes, setNotes] = useState(
    () => localStorage.getItem(keys.notes) || ""
  );
  const request = useRef(0);
  const optionsRequest = useRef(0);

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
    authenticatedFetch("/warehouse/costing-policy")
      .then(parseCostPolicy)
      .then((policy) => {
        if (active) setCostPolicy(policy);
      })
      .catch((error) => {
        if (active) {
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
  ) =>
    setDrafts((current) => {
      const key = String(variant.id);
      const defaultUom = String(
        uomOptions.get(variant.id)?.base_uom_id ?? variant.base_uom.id
      );
      const rows = current[key]?.length
        ? [...current[key]]
        : [emptyInboundBatch(rowId, defaultUom)];
      const index = rows.findIndex((row) => row.row_id === rowId);
      if (index < 0) {
        rows.push({ ...emptyInboundBatch(rowId, defaultUom), ...patch });
      } else {
        rows[index] = { ...rows[index], ...patch };
      }
      return { ...current, [key]: rows };
    });

  const clear = () => {
    setDrafts({});
    setReferenceId("");
    setNotes("");
    localStorage.removeItem(keys.drafts);
    localStorage.removeItem(keys.reference);
    localStorage.removeItem(keys.notes);
    localStorage.removeItem(keys.requestId);
    localStorage.removeItem(keys.fingerprint);
    setClearOpen(false);
  };

  const saveCostPolicy = async (method: CostPolicy["method"]) => {
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
        uomOptions
      );
      const businessPayload = {
        location_id: locationId,
        reference_id: referenceId.trim(),
        notes: notes.trim() || null,
        items,
      };
      const fingerprint = JSON.stringify(businessPayload);
      let requestId = localStorage.getItem(keys.requestId);
      if (!requestId || localStorage.getItem(keys.fingerprint) !== fingerprint) {
        requestId = crypto.randomUUID();
        localStorage.setItem(keys.requestId, requestId);
        localStorage.setItem(keys.fingerprint, fingerprint);
      }
      parseInboundResponse(
        await authenticatedFetch("/warehouse/inbound", {
          method: "POST",
          body: JSON.stringify({ request_id: requestId, ...businessPayload }),
        })
      );
      toast.success(t("inventoryInbound.received"));
      clear();
      await onSuccess();
    } catch (error) {
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

  const uomLabel = (code: string, fallback: string) =>
    t(`uom.${code}`, { defaultValue: fallback });

  return (
    <div
      className="inventory-view inventory-inbound flex flex-col h-full min-h-0 pt-1"
      dir={i18n.dir()}
    >
      <div className="inventory-surface relative bg-white rounded-2xl border flex flex-col flex-1 min-h-0">
        <div className="absolute -top-3.5 right-6 rtl:right-6 rtl:left-auto ltr:left-6 ltr:right-auto bg-emerald-600 text-white px-4 py-1.5 rounded-lg text-sm font-black flex gap-2">
          <FilePlus className="w-4 h-4" />
          {t("inventoryInbound.title")}
        </div>

        <div className="flex-1 min-h-0 overflow-auto mt-5">
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
                const defaultUom = String(
                  option?.base_uom_id ?? variant.base_uom.id
                );
                const rows = drafts[String(variant.id)]?.length
                  ? drafts[String(variant.id)]
                  : [emptyInboundBatch(`base-${variant.id}`, defaultUom)];

                return rows.map((row, index) => {
                  const selectedUom = row.uom_id || defaultUom;
                  const selectedOption = option?.uoms.find(
                    (uom) => String(uom.id) === selectedUom
                  );
                  return (
                    <tr key={`${variant.id}-${row.row_id}`}>
                      <td className="p-3 font-bold">{variant.name}</td>
                      <td className="p-3">
                        <div className="grid grid-cols-3 gap-2">
                          <input
                            value={row.batch_number}
                            onChange={(event) =>
                              update(variant, row.row_id, {
                                batch_number: event.target.value,
                              })
                            }
                            placeholder={t("inventoryInbound.batchNumber")}
                            className="rounded-lg border p-2"
                          />
                          <input
                            type="date"
                            value={row.production_date}
                            onChange={(event) =>
                              update(variant, row.row_id, {
                                production_date: event.target.value,
                              })
                            }
                            className="rounded-lg border p-2"
                            aria-label={t("inventoryInbound.productionDate")}
                          />
                          <input
                            type="date"
                            value={row.expiry_date}
                            onChange={(event) =>
                              update(variant, row.row_id, {
                                expiry_date: event.target.value,
                              })
                            }
                            className="rounded-lg border p-2"
                            aria-label={t("inventoryInbound.expiryDate")}
                          />
                        </div>
                      </td>
                      <td className="p-3">
                        <div className="flex items-center gap-2">
                          <input
                            inputMode="decimal"
                            value={row.quantity}
                            onChange={(event) =>
                              update(variant, row.row_id, {
                                quantity: event.target.value.replace(/[^0-9.]/g, ""),
                              })
                            }
                            className="w-28 rounded-lg border p-2 text-center"
                          />
                          <select
                            value={selectedUom}
                            onChange={(event) =>
                              update(variant, row.row_id, {
                                uom_id: event.target.value,
                              })
                            }
                            disabled={optionsLoading || !option}
                            className="rounded-lg border p-2 min-w-28 bg-white"
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
                                unit: uomLabel(variant.base_uom.code, variant.base_uom.name),
                              })}
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="p-3">
                        <div className="flex items-center gap-2">
                          <input
                            inputMode="decimal"
                            value={row.unit_cost}
                            onChange={(event) =>
                              update(variant, row.row_id, {
                                unit_cost: event.target.value.replace(/[^0-9.]/g, ""),
                              })
                            }
                            placeholder={t("inventoryInbound.unitCostPlaceholder")}
                            className="w-32 rounded-lg border p-2 text-center"
                          />
                          <span className="text-xs font-bold text-slate-500">
                            {costPolicy?.currency_code ?? ""}
                          </span>
                        </div>
                      </td>
                      <td className="p-3">
                        <div className="flex gap-2">
                          <button
                            type="button"
                            title={t("inventoryInbound.addBatch")}
                            onClick={() =>
                              setDrafts((current) => ({
                                ...current,
                                [String(variant.id)]: [
                                  ...(current[String(variant.id)] ?? [row]),
                                  emptyInboundBatch(freshRowId(), defaultUom),
                                ],
                              }))
                            }
                          >
                            <Plus className="w-4 h-4" />
                          </button>
                          {index > 0 && (
                            <button
                              type="button"
                              title={t("inventoryInbound.removeBatch")}
                              onClick={() =>
                                setDrafts((current) => ({
                                  ...current,
                                  [String(variant.id)]: (
                                    current[String(variant.id)] ?? []
                                  ).filter((value) => value.row_id !== row.row_id),
                                }))
                              }
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
              <ChevronRight />
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
              <ChevronLeft />
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
              value={costPolicy?.method ?? "MOVING_AVERAGE"}
              disabled={!costPolicy?.can_change || savingPolicy}
              onChange={(event) =>
                void saveCostPolicy(event.target.value as CostPolicy["method"])
              }
              className="rounded-xl border bg-white p-2 text-sm"
            >
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
          </div>
          <button
            type="button"
            onClick={() => void submit()}
            disabled={
              submitting ||
              isAuditLocked ||
              optionsLoading ||
              !costPolicy
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
                onClick={clear}
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
