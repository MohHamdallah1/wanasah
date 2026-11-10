import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { setAppLanguage } from "@/i18n";
import { DispatchAccessNotice } from "@/features/dispatch/DispatchAccessNotice";

describe("Dispatch D09 fail-closed UI", () => {
  it("shows an Arabic permission denial without leaking prior shop, zone or financial rows", async () => {
    await setAppLanguage("ar");
    const retry = vi.fn();
    render(<DispatchAccessNotice state="denied" onRetry={retry} />);
    expect(screen.getByRole("alert").textContent).toContain("لا تملك صلاحية");
    expect(screen.getByRole("alert").textContent).not.toMatch(/اسم المحل|الرصيد|credit cap|private/i);
    fireEvent.click(screen.getByRole("button", { name: "إعادة المحاولة" }));
    expect(retry).toHaveBeenCalledOnce();
  });

  it("shows distinct English pending and error states", async () => {
    await setAppLanguage("en");
    const { rerender } = render(<DispatchAccessNotice state="loading" />);
    expect(screen.getByRole("status").textContent).toContain("Checking access permissions");
    rerender(<DispatchAccessNotice state="error" />);
    expect(screen.getByRole("alert").textContent).toContain("Unable to verify access");
    expect(screen.getByRole("alert").textContent).toContain("Previously loaded data is hidden");
  });
});
