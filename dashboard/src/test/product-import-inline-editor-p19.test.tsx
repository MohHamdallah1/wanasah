import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ImportInlineCorrectionPanel } from "@/pages/products/import/ImportInlineCorrectionPanel";
import { ImportProductStatusPanel } from "@/pages/products/import/ImportProductStatusPanel";
import type { ProductImportState } from "@/pages/products/contracts";
import { productDurableScope } from "@/pages/products/productDurableScope";

const ids = vi.hoisted(() => ({
  request: "33333333-3333-4333-8333-333333333333",
  pending: null as null | { requestId: string; payload: unknown; createdAt: number },
}));
vi.mock("react-i18next", async (importOriginal) => {
  const original = await importOriginal<typeof import("react-i18next")>();
  return {
    ...original,
    useTranslation: () => ({
      t: (key: string, opts?: { row?: number; count?: number }) => {
        if (opts?.row) return "Row " + opts.row;
        if (opts?.count !== undefined) return key + " " + opts.count;
        return key;
      },
      i18n: { exists: () => false },
    }),
  };
});
vi.mock("@/lib/durableOperations", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/durableOperations")>();
  return {
    ...original,
    readDurableCommand: vi.fn(async () => ids.pending),
    getOrCreateDurableCommand: vi.fn(async (_scope: string, payload: unknown) => {
      ids.pending ??= { requestId: ids.request, payload, createdAt: 1 };
      return ids.pending;
    }),
    completeDurableOperation: vi.fn(() => { ids.pending = null; }),
    abandonDurableOperation: vi.fn(() => { ids.pending = null; }),
  };
});

const JOB = "11111111-1111-4111-8111-111111111111";
const ROW = "22222222-2222-4222-8222-222222222222";
const page = {
  job_id: JOB,
  job_version: 7,
  status: "VALIDATION_FAILED",
  fields: ["name", "unit_barcode"],
  items: [{
    row_identity: ROW,
    row_number: 14,
    version: 3,
    status: "INVALID",
    values: { name: "", unit_barcode: "000123" },
    errors: [{
      row_number: 14,
      code: "IMPORT_NAME_REQUIRED",
      field: "name",
      message: "Product name is required.",
    }],
    editable: true,
    unavailable_reason: null,
  }],
  next_after_row: null,
};
const props = {
  jobId: JOB,
  companyId: 38,
  driverId: 17,
  online: true,
  onAccepted: vi.fn(),
};
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.restoreAllMocks();
  ids.pending = null;
  sessionStorage.clear();
  localStorage.clear();
});

describe("inline correction UI uses the server-owned failed-row contract", () => {
  it("follows a short Backend page caused by byte limits without opening bulk editing", async () => {
    const anotherRow = {
      ...page.items[0],
      row_identity: "44444444-4444-4444-8444-444444444444",
      row_number: 28,
      values: { name: "Another rejected row", unit_barcode: "000999" },
    };
    const authFetch = vi.fn()
      .mockResolvedValueOnce({ ...page, next_after_row: 14 })
      .mockResolvedValueOnce({ ...page, items: [anotherRow], next_after_row: null });
    render(<ImportInlineCorrectionPanel {...props} authFetch={authFetch} />);
    expect(await screen.findByText(/Row 28/)).not.toBeNull();
    expect(screen.getByText("Row 14")).not.toBeNull();
    expect(authFetch).toHaveBeenCalledTimes(2);
    expect(authFetch).toHaveBeenNthCalledWith(2,
      "/simple-products/imports/" + JOB +
      "/correction/rows?after_row=14&limit=24&expected_job_version=7",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });

  it("prevents inline submission while another same-job Excel correction is unresolved", async () => {
    const fileScope = productDurableScope(38, 17, "product-import-correction", JOB);
    const authFetch = vi.fn(async (_url: string, opts?: RequestInit) => {
      if (opts?.method === "POST") throw new Error("unexpected inline POST");
      return page;
    });
    render(<ImportInlineCorrectionPanel {...props} authFetch={authFetch} />);
    expect(await screen.findByText("Row 14")).not.toBeNull();
    fireEvent.change(screen.getByLabelText("products.fields.name"), { target: { value: "Corrected" } });
    localStorage.setItem(fileScope, "pending-file-operation");
    fireEvent.click(screen.getByRole("button", { name: "products.inlineCorrection.submit" }));
    await waitFor(() => expect(screen.getByRole("alert")).not.toBeNull());
    expect(authFetch.mock.calls.filter(([, options]) => options?.method === "POST")).toHaveLength(0);
  });

  it("shows original row and field error, and posts only changed literal cells with the same job/row versions", async () => {
    const authFetch = vi.fn(async (url: string, opts?: RequestInit) => {
      if (!opts?.method) return page;
      return { job_id: JOB, status: "VALIDATING", corrected_rows: 1, replayed: false };
    });
    render(<ImportInlineCorrectionPanel {...props} authFetch={authFetch} />);
    expect(await screen.findByText("Row 14")).not.toBeNull();
    expect(screen.getAllByText("products.inlineCorrection.genericError").length).toBeGreaterThan(0);
    fireEvent.change(screen.getByLabelText("products.fields.name"), { target: { value: "Corrected name" } });
    fireEvent.click(screen.getByRole("button", { name: "products.inlineCorrection.submit" }));
    await waitFor(() => expect(props.onAccepted).toHaveBeenCalledTimes(1));
    const [, options] = authFetch.mock.calls.find(([, request]) => request?.method === "POST")!;
    expect(JSON.parse(String(options?.body))).toEqual({
      request_id: ids.request,
      expected_job_version: 7,
      rows: [{ row_identity: ROW, expected_version: 3, values: { name: "Corrected name" } }],
    });
    expect(authFetch.mock.calls[0][0]).toBe(
      "/simple-products/imports/" + JOB + "/correction/rows?after_row=0&limit=25",
    );
    expect(props.onAccepted).toHaveBeenCalledWith({
      job_id: JOB, status: "VALIDATING", corrected_rows: 1, replayed: false,
    });
  });

  it("keeps one stable request identity and exact patch body after an ambiguous response", async () => {
    const bodies: string[] = [];
    const authFetch = vi.fn(async (_url: string, opts?: RequestInit) => {
      if (!opts?.method) return page;
      bodies.push(String(opts.body));
      if (bodies.length === 1) throw { status: 0, code: "NETWORK_UNAVAILABLE" };
      return { job_id: JOB, status: "VALIDATING", corrected_rows: 1, replayed: true };
    });
    render(<ImportInlineCorrectionPanel {...props} authFetch={authFetch} />);
    expect(await screen.findByText("Row 14")).not.toBeNull();
    fireEvent.change(screen.getByLabelText("products.fields.name"), { target: { value: "New name" } });
    fireEvent.click(screen.getByRole("button", { name: "products.inlineCorrection.submit" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "products.inlineCorrection.retrySame" })).not.toBeNull());
    fireEvent.click(screen.getByRole("button", { name: "products.inlineCorrection.retrySame" }));
    await waitFor(() => expect(props.onAccepted).toHaveBeenCalledTimes(1));
    expect(bodies).toHaveLength(2);
    expect(bodies[0]).toBe(bodies[1]);
  });

  it("preserves a valid draft after GET failure and permits only confirmed discard", async () => {
    const key = productDurableScope(38, 17, "product-import-inline-correction", JOB) + ":draft";
    const original = JSON.stringify({
      jobVersion: 7,
      rowVersions: { [ROW]: 3 },
      edits: { [ROW]: { name: "Do not lose this name" } },
    });
    sessionStorage.setItem(key, original);
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const authFetch = vi.fn().mockRejectedValue({ status: 503, code: "PRODUCT_IMPORT_WORKER_HEALTH_UNAVAILABLE" });
    render(<ImportInlineCorrectionPanel {...props} authFetch={authFetch} />);
    expect(await screen.findByText("products.inlineCorrection.draftNeedsReload")).not.toBeNull();
    expect(sessionStorage.getItem(key)).toBe(original);
    expect(screen.queryByRole("button", {
      name: "products.inlineCorrection.submit",
    })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "products.inlineCorrection.discardDraft" }));
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(sessionStorage.getItem(key)).toBe(original);
    expect(authFetch).toHaveBeenCalledTimes(1);
    confirm.mockReturnValue(true);
    fireEvent.click(screen.getByRole("button", { name: "products.inlineCorrection.discardDraft" }));
    await waitFor(() => expect(sessionStorage.getItem(key)).toBeNull());
    await waitFor(() => expect(screen.queryByText("products.inlineCorrection.draftNeedsReload")).toBeNull());
    expect(authFetch.mock.calls.filter(([, options]) => options?.method === "POST")).toHaveLength(0);
  });

  it("offers confirmed draft discard offline without fetching or changing the job", async () => {
    const key = productDurableScope(38, 17, "product-import-inline-correction", JOB) + ":draft";
    sessionStorage.setItem(key, JSON.stringify({
      jobVersion: 7,
      rowVersions: { [ROW]: 3 },
      edits: { [ROW]: { name: "My offline changes" } },
    }));
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    const authFetch = vi.fn();
    render(<ImportInlineCorrectionPanel {...props} online={false} authFetch={authFetch} />);
    expect(await screen.findByText("products.inlineCorrection.draftNeedsReload")).not.toBeNull();
    expect(screen.getByText("products.inlineCorrection.offline")).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "products.inlineCorrection.discardDraft" }));
    expect(confirm).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(sessionStorage.getItem(key)).toBeNull());
    expect(authFetch).not.toHaveBeenCalled();
  });

  it("fails closed and offers confirmed recovery for an unreadable saved draft", async () => {
    const scope = productDurableScope(38, 17, "product-import-inline-correction", JOB);
    const key = scope + ":draft";
    sessionStorage.setItem(key, "{broken-json");
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const authFetch = vi.fn(async () => page);
    render(<ImportInlineCorrectionPanel {...props} authFetch={authFetch} />);
    expect(await screen.findByText("products.inlineCorrection.unreadableDraft")).not.toBeNull();
    expect((screen.getByRole("button", {
      name: "products.inlineCorrection.submit",
    }) as HTMLButtonElement).disabled).toBe(true);
    expect(sessionStorage.getItem(key)).toBe("{broken-json");
    fireEvent.click(screen.getByRole("button", {
      name: "products.inlineCorrection.discardDraft",
    }));
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(sessionStorage.getItem(key)).toBe("{broken-json");
    confirm.mockReturnValue(true);
    fireEvent.click(screen.getByRole("button", {
      name: "products.inlineCorrection.discardDraft",
    }));
    await waitFor(() => expect(sessionStorage.getItem(key)).toBeNull());
    await waitFor(() => expect(screen.queryByText(
      "products.inlineCorrection.unreadableDraft",
    )).toBeNull());
    expect(authFetch).toHaveBeenCalledTimes(2);
  });

  it("does not discard a stale typed draft unless the user confirms", async () => {
    const scope = productDurableScope(38, 17, "product-import-inline-correction", JOB);
    const draftKey = scope + ":draft";
    sessionStorage.setItem(draftKey, JSON.stringify({
      jobVersion: 6,
      rowVersions: { [ROW]: 3 },
      edits: { [ROW]: { name: "Unsaved corrected name" } },
    }));
    const accept = vi.spyOn(window, "confirm").mockReturnValue(false);
    const authFetch = vi.fn().mockResolvedValue(page);
    render(<ImportInlineCorrectionPanel {...props} authFetch={authFetch} />);
    expect(await screen.findByText("products.inlineCorrection.staleDraft")).not.toBeNull();
    expect(screen.getByDisplayValue("Unsaved corrected name")).not.toBeNull();
    fireEvent.click(screen.getByRole("button", {
      name: "products.inlineCorrection.discardDraft",
    }));
    expect(accept).toHaveBeenCalledTimes(1);
    expect(sessionStorage.getItem(draftKey)).not.toBeNull();
    accept.mockReturnValue(true);
    fireEvent.click(screen.getByRole("button", {
      name: "products.inlineCorrection.discardDraft",
    }));
    await waitFor(() => expect(sessionStorage.getItem(draftKey)).toBeNull());
  });

  it("releases an exact pending id after a known zero-write 409 conflict", async () => {
    const authFetch = vi.fn()
      .mockResolvedValueOnce(page)
      .mockRejectedValueOnce({
        status: 409, code: "PRODUCT_IMPORT_CORRECTION_CONFLICT",
      });
    render(<ImportInlineCorrectionPanel {...props} authFetch={authFetch} />);
    expect(await screen.findByText("Row 14")).not.toBeNull();
    fireEvent.change(screen.getByLabelText("products.fields.name"), {
      target: { value: "Corrected name" },
    });
    fireEvent.click(screen.getByRole("button", {
      name: "products.inlineCorrection.submit",
    }));
    await waitFor(() => expect(authFetch).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(ids.pending).toBeNull());
    expect(screen.queryByRole("button", {
      name: "products.inlineCorrection.retrySame",
    })).toBeNull();
  });

  it("ignores a late acknowledged correction after the editor was unmounted", async () => {
    let accept!: (value: unknown) => void;
    const postResponse = new Promise<unknown>((resolve) => { accept = resolve; });
    const authFetch = vi.fn(async (_url: string, options?: RequestInit) =>
      options?.method === "POST" ? postResponse : page);
    const onAccepted = vi.fn();
    const view = render(<ImportInlineCorrectionPanel
      {...props} onAccepted={onAccepted} authFetch={authFetch}
    />);
    expect(await screen.findByText("Row 14")).not.toBeNull();
    fireEvent.change(screen.getByLabelText("products.fields.name"), {
      target: { value: "Edited" },
    });
    fireEvent.click(screen.getByRole("button", {
      name: "products.inlineCorrection.submit",
    }));
    await waitFor(() => expect(authFetch).toHaveBeenCalledTimes(2));
    view.unmount();
    await act(async () => {
      accept({ job_id: JOB, status: "VALIDATING", corrected_rows: 1, replayed: false });
      await postResponse;
    });
    expect(onAccepted).not.toHaveBeenCalled();
  });

  it("blocks any rejected-row editor when there are more than 25 failures", () => {
    const authFetch = vi.fn(async () => page);
    const status = {
      job_id: JOB, status: "VALIDATION_FAILED",
      imported_rows: 35, invalid_rows: 15000, import_failed_rows: 0, failed_rows: 15000,
      errors: [], valid_rows: 35,
    } as ProductImportState;
    render(<ImportProductStatusPanel
      status={status}
      jobId={JOB}
      companyId={38}
      driverId={17}
      onInlineCorrectionAccepted={vi.fn()}
      authFetch={authFetch}
      online
      pollError={null}
      progress={0}
      retryPending={false}
      cancelPending={false}
      onCancelImport={vi.fn()}
      onRetryPoll={vi.fn()}
      onDownloadErrorReport={vi.fn()}
      correctionFile={null}
      correctionFileRef={{ current: null }}
      downloadingCorrection={false}
      uploadingCorrection={false}
      onChooseCorrectionFile={vi.fn()}
      onDownloadCorrection={vi.fn()}
      onUploadCorrection={vi.fn()}
      onResetImport={vi.fn()}
      onRetryImport={vi.fn()}
      onCompletedClose={vi.fn()}
    />);
    expect(screen.getByText(/products.inlineCorrection.bulkOnly/)).not.toBeNull();
    expect(screen.queryByRole("button", { name: "products.inlineCorrection.submit" })).toBeNull();
    expect(authFetch).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "products.correction.download" })).not.toBeNull();
  });
});
