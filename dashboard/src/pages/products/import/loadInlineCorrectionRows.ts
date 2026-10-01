import {
  MAX_INLINE_CORRECTION_REJECTIONS,
  parseInlineCorrectionPage,
  type InlineCorrectionPage,
} from "@/pages/products/import/inlineCorrectionContracts";

type AuthFetch = (path: string, options?: RequestInit) => Promise<unknown>;

// Each Backend response is at most 256 KiB, even for fewer than 25 rows.
// A short page does not imply the end: only next_after_row === null does.
// Cap the combined local editor as well, independently of Excel bulk imports.
const MAX_INLINE_EDITOR_TRANSFER_BYTES = 512 * 1024;

export async function loadInlineCorrectionRows(
  authFetch: AuthFetch,
  jobId: string,
  signal: AbortSignal,
): Promise<InlineCorrectionPage> {
  const path = "/simple-products/imports/" + encodeURIComponent(jobId) +
    "/correction/rows";
  let collected: InlineCorrectionPage | null = null;
  let cursor = 0;
  let transferredBytes = 0;

  for (let attempt = 0; attempt < MAX_INLINE_CORRECTION_REJECTIONS; attempt += 1) {
    const remaining = MAX_INLINE_CORRECTION_REJECTIONS - (collected?.items.length ?? 0);
    if (remaining <= 0) throw new Error("PRODUCT_IMPORT_INLINE_TOO_MANY_ROWS");

    const params = "?after_row=" + cursor + "&limit=" + remaining +
      (collected ? "&expected_job_version=" + collected.job_version : "");
    const raw = await authFetch(path + params, { signal });
    transferredBytes += new TextEncoder().encode(JSON.stringify(raw)).byteLength;
    if (transferredBytes > MAX_INLINE_EDITOR_TRANSFER_BYTES) {
      throw new Error("PRODUCT_IMPORT_INLINE_DATA_TOO_LARGE");
    }

    const page = parseInlineCorrectionPage(raw, jobId);
    if (!collected) {
      collected = { ...page, items: [] };
    } else if (page.job_version !== collected.job_version ||
               page.fields.join("|") !== collected.fields.join("|")) {
      throw new Error("PRODUCT_IMPORT_CORRECTION_STALE_JOB");
    }

    if (!page.items.length && page.next_after_row !== null) {
      throw new Error("PRODUCT_IMPORT_INLINE_RESPONSE_INVALID");
    }

    const previous = collected.items.at(-1)?.row_number ?? cursor;
    if (page.items.some((row, i) =>
      row.row_number <= (i === 0 ? previous : page.items[i - 1].row_number)
    )) {
      throw new Error("PRODUCT_IMPORT_INLINE_RESPONSE_INVALID");
    }
    collected.items.push(...page.items);
    if (collected.items.length > MAX_INLINE_CORRECTION_REJECTIONS) {
      throw new Error("PRODUCT_IMPORT_INLINE_TOO_MANY_ROWS");
    }

    if (page.next_after_row === null) {
      return { ...collected, next_after_row: null };
    }
    if (page.next_after_row <= cursor ||
        page.items.at(-1)?.row_number !== page.next_after_row) {
      throw new Error("PRODUCT_IMPORT_INLINE_RESPONSE_INVALID");
    }
    cursor = page.next_after_row;
  }

  throw new Error("PRODUCT_IMPORT_INLINE_RESPONSE_INVALID");
}
