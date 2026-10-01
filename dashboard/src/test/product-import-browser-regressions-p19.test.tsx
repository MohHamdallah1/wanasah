import { useState } from "react";
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import i18n from "@/i18n";
import { toast } from "sonner";
import { useDialogFocusTrap } from "@/hooks/useDialogFocusTrap";
import { useImportProductWorkflow } from "@/pages/products/import/useImportProductWorkflow";
import { productImportSessionKey } from "@/pages/products/import/productImportSessionKey";
import { productDurableScope } from "@/pages/products/productDurableScope";

const JOB = "11111111-1111-4111-8111-111111111111";
const OTHER = "44444444-4444-4444-8444-444444444444";
const t = i18n.t.bind(i18n);
function FocusDialog() {
  const [open, setOpen] = useState(false);
  const ref = useDialogFocusTrap<HTMLDivElement>(open, () => setOpen(false));
  return <>
    <button onClick={() => setOpen(true)}>{t("products.importFile")}</button>
    {open ? <div ref={ref} tabIndex={-1} role="dialog" aria-label={t("products.importTitle")}>
      <button onClick={() => setOpen(false)}>{t("common.close")}</button>
    </div> : null}
  </>;
}
class SilentSocket {
  static OPEN = 1;
  static CONNECTING = 0;
  readyState = 0;
  close() { this.readyState = 3; }
}
beforeEach(async () => {
  await i18n.changeLanguage("en");
  vi.stubGlobal("WebSocket", SilentSocket);
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});
afterEach(() => {
  cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals();
  localStorage.clear(); sessionStorage.clear();
});
describe("regressions for browser-confirmed Phase 19 defects", () => {
  it("keeps a dialog open for an already consumed Escape, then restores focus for its own Escape", async () => {
    render(<FocusDialog />);
    const trigger = screen.getByRole("button", { name: t("products.importFile") });
    trigger.focus();
    fireEvent.click(trigger);
    const dialog = await screen.findByRole("dialog", { name: t("products.importTitle") });
    await waitFor(() => expect(dialog.contains(document.activeElement)).toBe(true));
    const event = new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true });
    event.preventDefault();
    act(() => document.dispatchEvent(event));
    expect(dialog).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it("dismisses only the old job's completion notification when company changes", async () => {
    const notification = vi.spyOn(toast, "warning").mockReturnValue("old-job-notification");
    const dismiss = vi.spyOn(toast, "dismiss");
    sessionStorage.setItem(productImportSessionKey(91001, 91011)!, JOB);
    const query = new QueryClient();
    const authFetch = vi.fn(async () => ({
      job_id: JOB, status: "COMPLETED_WITH_ERRORS", file_name: "synthetic.xlsx",
      total_rows: 3, processed_rows: 3, valid_rows: 2, failed_rows: 1,
      imported_rows: 2, invalid_rows: 1, import_failed_rows: 0, pending_rows: 0,
      detected_headers: [], suggested_mapping: {}, column_mapping: {},
      default_lot_control_mode: "NONE", default_expiry_control_mode: "OPTIONAL",
      error_summary: {}, errors: [],
    }));
    const view = renderHook((identity) => useImportProductWorkflow({
      ...identity, authFetch, queryClient: query, t, i18n, online: true,
      trackingDefaults: undefined, trackingDefaultsLoading: false, trackingDefaultsError: false,
      retryTrackingDefaults: () => undefined,
    }), {
      initialProps: { companyId: 91001, driverId: 91011 },
      wrapper: ({ children }) => <QueryClientProvider client={query}>{children}</QueryClientProvider>,
    });
    await waitFor(() => expect(view.result.current.modalProps.jobId).toBe(JOB));
    act(() => view.result.current.openImport());
    await waitFor(() => expect(notification).toHaveBeenCalledTimes(1));
    view.rerender({ companyId: 91002, driverId: 91011 });
    expect(dismiss).toHaveBeenCalledWith("old-job-notification");
    expect(notification).toHaveBeenCalledTimes(1);
    view.unmount(); query.clear();
  });

  it.each([
    { companyId: 91002, driverId: 91011 },
    { companyId: 91001, driverId: 91012 },
  ])("clears the old import on identity change, preserving its scoped draft/command: %o", async (next) => {
    const query = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const oldSession = productImportSessionKey(91001, 91011)!;
    const draft = productDurableScope(91001, 91011, "product-import-inline-correction", JOB) + ":draft";
    const command = productDurableScope(91001, 91011, "product-import-inline-correction", JOB);
    sessionStorage.setItem(oldSession, JOB);
    sessionStorage.setItem(draft, "original-draft");
    localStorage.setItem(command, "original-command");
    const authFetch = vi.fn(async () => { throw new Error("NO_BROWSER_HTTP_IN_UNIT_TEST"); });
    const defaults = { lot_control_mode: "NONE", expiry_control_mode: "OPTIONAL",
      lot_control_source: "COMPANY", expiry_control_source: "COMPANY" } as const;
    const view = renderHook((identity) => useImportProductWorkflow({
      ...identity, authFetch, queryClient: query, t, i18n, online: true,
      trackingDefaults: defaults, trackingDefaultsLoading: false, trackingDefaultsError: false,
      retryTrackingDefaults: () => undefined,
    }), {
      initialProps: { companyId: 91001, driverId: 91011 },
      wrapper: ({ children }) => <QueryClientProvider client={query}>{children}</QueryClientProvider>,
    });
    await waitFor(() => expect(view.result.current.modalProps.jobId).toBe(JOB));
    act(() => view.result.current.openImport());
    expect(view.result.current.modalProps.open).toBe(true);
    view.rerender(next);
    expect(view.result.current.modalProps.open).toBe(false);
    expect(view.result.current.modalProps.jobId).toBeNull();
    expect(view.result.current.modalProps.status).toBeNull();
    expect(sessionStorage.getItem(oldSession)).toBe(JOB);
    expect(sessionStorage.getItem(draft)).toBe("original-draft");
    expect(localStorage.getItem(command)).toBe("original-command");
    sessionStorage.setItem(productImportSessionKey(next.companyId, next.driverId)!, OTHER);
    // Switching away and back resumes only the new identity's saved session.
    view.rerender({ companyId: 91003, driverId: 91013 });
    view.rerender(next);
    await waitFor(() => expect(view.result.current.modalProps.jobId).toBe(OTHER));
    expect(view.result.current.modalProps.open).toBe(false);
    view.unmount(); query.clear();
  });
});
