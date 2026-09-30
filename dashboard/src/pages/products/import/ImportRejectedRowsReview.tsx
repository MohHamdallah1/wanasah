import { useEffect, useId, useState } from "react";
import { AlertCircle, ChevronLeft, ChevronRight, LoaderCircle } from "lucide-react";
import { useTranslation } from "react-i18next";

import { apiErrorMessage } from "@/lib/apiErrors";
import {
  parseProductImportErrorPage,
  type ProductImportErrorPage,
} from "@/pages/products/contracts";

const PAGE_SIZE = 25;

type AuthFetch = (path: string, options?: RequestInit) => Promise<unknown>;

type Props = {
  jobId: string;
  online: boolean;
  authFetch: AuthFetch;
};

function assertPage(page: ProductImportErrorPage, afterRow: number) {
  if (page.items.length > PAGE_SIZE) {
    throw new Error("PRODUCT_IMPORT_ERROR_PAGE_INVALID");
  }
  let previous = afterRow;
  for (const item of page.items) {
    if (item.row_number <= previous) {
      throw new Error("PRODUCT_IMPORT_ERROR_PAGE_INVALID");
    }
    previous = item.row_number;
  }
  if (
    page.next_after_row !== null &&
    (page.items.length === 0 || page.next_after_row !== previous)
  ) {
    throw new Error("PRODUCT_IMPORT_ERROR_PAGE_INVALID");
  }
  return page;
}

/**
 * Lightweight existing /errors review. Values and edits are intentionally
 * not inferred from this diagnostic DTO; the separate Backend correction
 * contract will own them when available.
 */
export function ImportRejectedRowsReview({ jobId, online, authFetch }: Props) {
  const { t, i18n } = useTranslation();
  const panelId = useId();
  const [expanded, setExpanded] = useState(false);
  const [cursors, setCursors] = useState([0]);
  const [snapshot, setSnapshot] = useState<{
    cursor: number;
    page: ProductImportErrorPage;
  } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const cursor = cursors[cursors.length - 1];

  useEffect(() => {
    if (!expanded || !online) return;
    let disposed = false;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setSnapshot(null);
    void authFetch(
      `/simple-products/imports/${encodeURIComponent(jobId)}/errors?after_row=${cursor}&limit=${PAGE_SIZE}`,
      { signal: controller.signal },
    ).then((raw) => {
      const page = assertPage(parseProductImportErrorPage(raw), cursor);
      if (!disposed) {
        setSnapshot({ cursor, page });
      }
    }).catch((cause) => {
      if (!disposed) {
        setError(
          apiErrorMessage(cause, t("products.rejectedRows.loadFailed")),
        );
      }
    }).finally(() => {
      if (!disposed) setLoading(false);
    });
    return () => {
      disposed = true;
      controller.abort();
    };
  }, [authFetch, cursor, expanded, jobId, online, revision, t]);

  const page = snapshot?.cursor === cursor ? snapshot.page : null;
  const nextCursor = page?.next_after_row ?? null;
  const pageNumber = cursors.length;
  const goNext = () => {
    if (loading || !page || nextCursor === null) return;
    setCursors((current) => [...current, nextCursor]);
  };
  const goPrevious = () => {
    if (loading || pageNumber <= 1) return;
    setCursors((current) => current.slice(0, -1));
  };

  return (
    <section className="rounded-xl border border-slate-200 bg-white">
      <button
        type="button"
        aria-controls={panelId}
        aria-expanded={expanded}
        onClick={() => setExpanded((current) => !current)}
        className="flex min-h-11 w-full items-center justify-between gap-3 rounded-xl px-3 py-2 text-start text-xs font-black text-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500"
      >
        <span>{t("products.rejectedRows.title")}</span>
        <span className="text-xs text-amber-800">
          {t(expanded ? "products.rejectedRows.hide" : "products.rejectedRows.show")}
        </span>
      </button>

      {expanded ? (
        <div id={panelId} className="space-y-2 border-t border-slate-100 p-3">
          <p className="text-xs font-medium leading-5 text-slate-600">
            {t("products.rejectedRows.hint")}
          </p>
          {!online ? (
            <p role="status" className="rounded-lg bg-slate-50 p-2 text-xs text-slate-600">
              {t("network.offline")}
            </p>
          ) : null}
          {loading && online ? (
            <p role="status" className="flex items-center gap-2 text-xs text-slate-500">
              <LoaderCircle className="h-4 w-4 animate-spin" />
              {t("products.rejectedRows.loading")}
            </p>
          ) : null}
          {error && !loading ? (
            <div role="alert" className="flex flex-wrap items-center gap-2 rounded-lg bg-rose-50 p-2 text-xs text-rose-800">
              <AlertCircle className="h-4 w-4 shrink-0" />
              <span className="min-w-0 flex-1">{error}</span>
              <button
                type="button"
                disabled={!online}
                onClick={() => setRevision((current) => current + 1)}
                className="min-h-9 rounded-lg border border-rose-200 bg-white px-3 font-black focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500 disabled:opacity-40"
              >
                {t("common.retry")}
              </button>
            </div>
          ) : null}

          {page && !loading && online ? (
            <>
              {page.items.length === 0 ? (
                <p role="status" className="rounded-lg bg-slate-50 p-3 text-xs text-slate-600">
                  {t("products.rejectedRows.empty")}
                </p>
              ) : (
                <ol className="max-h-64 overflow-y-auto rounded-lg border border-slate-100" aria-label={t("products.rejectedRows.title")}>
                  {page.items.map((item) => {
                    const key = item.code ? `errors.codes.${item.code}` : "";
                    return (
                      <li key={item.row_number} className="flex gap-3 border-b border-slate-100 px-3 py-2 text-xs last:border-b-0">
                        <strong className="min-w-20 shrink-0 tabular-nums text-slate-700">
                          {t("products.rowNumber", { row: item.row_number })}
                        </strong>
                        <span className="min-w-0 font-semibold leading-5 text-rose-800">
                          {key && i18n.exists(key) ? t(key) : t("products.rejectedRows.genericError")}
                        </span>
                      </li>
                    );
                  })}
                </ol>
              )}
              <nav aria-label={t("products.rejectedRows.pagination")} className="flex flex-wrap items-center justify-between gap-2">
                <button
                  type="button"
                  onClick={goPrevious}
                  disabled={pageNumber === 1}
                  className="inline-flex min-h-9 items-center gap-1 rounded-lg border border-slate-200 px-3 text-xs font-bold text-slate-700 disabled:opacity-40"
                >
                  <ChevronRight className="h-4 w-4 rtl:rotate-180" />
                  {t("products.rejectedRows.previous")}
                </button>
                <span aria-live="polite" className="text-xs font-bold tabular-nums text-slate-600">
                  {t("products.rejectedRows.page", { page: pageNumber })}
                </span>
                <button
                  type="button"
                  onClick={goNext}
                  disabled={nextCursor === null}
                  className="inline-flex min-h-9 items-center gap-1 rounded-lg border border-slate-200 px-3 text-xs font-bold text-slate-700 disabled:opacity-40"
                >
                  {t("products.rejectedRows.next")}
                  <ChevronLeft className="h-4 w-4 rtl:rotate-180" />
                </button>
              </nav>
            </>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
