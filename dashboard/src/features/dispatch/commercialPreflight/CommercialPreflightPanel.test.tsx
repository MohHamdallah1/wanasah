import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  PREFLIGHT_AREAS, type CommercialPreflight, type PreflightArea,
} from "./contract";
import { CommercialPreflightPanel } from "./CommercialPreflightPanel";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const advisory = (blocked: Partial<Record<PreflightArea, string>> = {}): CommercialPreflight => {
  const checks = Object.fromEntries(PREFLIGHT_AREAS.map(area => [
    area, { ready: !(area in blocked), code: blocked[area] ?? "READY", context: {} },
  ])) as CommercialPreflight["checks"];
  return { advisory: true, currency_code: "QAR",
    ready: Object.keys(blocked).length === 0, checks };
};

function show(
  status: "choose" | "loading" | "ready" | "blocked" | "error" | "denied",
  language = "ar", evidence: CommercialPreflight | null = null, onRefresh = vi.fn(),
) {
  return render(<MemoryRouter><CommercialPreflightPanel language={language}
    status={status} evidence={evidence} onRefresh={onRefresh} /></MemoryRouter>);
}

describe("D15 compact preflight panel — presentation only, canonical advisory unchanged", () => {
  it("renders nothing at all when selection is incomplete, even if old evidence was supplied", () => {
    const view = show("choose", "ar", advisory());
    expect(view.container).toBeEmptyDOMElement();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByText(/اختر المنطقة/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("renders just a small accessible in-progress indicator without card or retry button", () => {
    const view = show("loading");
    expect(screen.getByRole("status")).toHaveTextContent("جاري التحقق");
    expect(screen.getByRole("status")).toHaveAttribute("aria-live", "polite");
    expect(screen.queryByText("جاهزية إطلاق خط السير")).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(view.container.querySelector(".shadow-sm, .rounded-2xl, .border-slate-200"))
      .not.toBeInTheDocument();
  });

  it("shows a short ready check from server-ready 0% published tax evidence, never a large card", () => {
    const verifiedTaxZero = advisory(); // Contract accepts published tax READY even when 0%.
    verifiedTaxZero.checks.tax = { ready: true, code: "READY", context: { published_rate: "0" } };
    const view = show("ready", "ar", verifiedTaxZero);
    expect(screen.getByRole("status")).toHaveAttribute("aria-label", expect.stringContaining("التحقق ناجح"));
    expect(screen.getByRole("status")).toHaveTextContent("تم التحقق");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(view.container.querySelector(".shadow-sm, .rounded-2xl")).not.toBeInTheDocument();
  });

  it("never shows a positive check if ready status arrives without authoritative positive evidence", () => {
    const retry = vi.fn();
    show("ready", "ar", null, retry);
    expect(screen.queryByText("تم التحقق")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("تعذّر التحقق");
    fireEvent.click(screen.getByRole("button", { name: "إعادة التحقق" }));
    expect(retry).toHaveBeenCalledOnce();
  });

  it("shows ALL actual blockers with actionable real destinations at 390px in AR, no raw codes", () => {
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 390 });
    const retry = vi.fn();
    const current = advisory({
      pricing: "PRICE_NOT_RESOLVED",
      tax: "TAX_CONFIGURATION_REQUIRED",
      rounding: "COMMERCIAL_ROUNDING_NOT_CONFIGURED",
      warehouse: "SOURCE_WAREHOUSE_AUDIT_LOCK",
      vehicle: "VEHICLE_NOT_OPERATIONAL",
      custody: "VEHICLE_CUSTODY_UNAVAILABLE",
    });
    const view = show("blocked", "ar", current, retry);
    expect(screen.getByRole("status")).toHaveTextContent("الإطلاق ممنوع");
    expect(screen.getByRole("list").querySelectorAll("li")).toHaveLength(6);
    expect(screen.getByText(/نسبة 0% المنشورة صالحة/)).toBeInTheDocument();
    expect(screen.getByText(/جرد شامل/)).toBeInTheDocument();
    expect(screen.getByText(/عهدة المركبة/)).toBeInTheDocument();
    const links = screen.getAllByRole("link", { name: "اذهب للإعداد" });
    expect(links.map(a => a.getAttribute("href"))).toEqual([
      "/products", "/commercial-rules", "/commercial-rules",
      "/inventory", "/representatives-vehicles", "/representatives-vehicles",
    ]);
    expect(view.container.textContent).not.toContain("PRICE_NOT_RESOLVED");
    expect(view.container.querySelector("section")).toHaveAttribute("dir", "rtl");
    expect(view.container.querySelector("ul")).toHaveClass("min-w-0");
    fireEvent.click(screen.getByRole("button", { name: "إعادة التحقق" }));
    expect(retry).toHaveBeenCalledOnce();
  });

  it("keeps English LTR blocker and keyboard-accessible correction links", () => {
    const view = show("blocked", "en", advisory({
      tax: "TAX_CONFIGURATION_REQUIRED", custody: "VEHICLE_CUSTODY_LOCATION_MISSING",
    }));
    expect(view.container.querySelector("section")).toHaveAttribute("dir", "ltr");
    expect(screen.getByRole("status")).toHaveTextContent("Launch is blocked");
    expect(screen.getByText(/published 0% tax is valid/)).toBeInTheDocument();
    const links = screen.getAllByRole("link", { name: "Open settings" });
    expect(links).toHaveLength(2);
    links[0].focus();
    expect(links[0]).toHaveFocus();
    expect(screen.getByRole("button", { name: "Recheck readiness" })).toBeEnabled();
  });

  it("shows a recoverable read error without success, and a denied state without fake retry", () => {
    const retry = vi.fn();
    const error = show("error", "ar", null, retry);
    expect(screen.getByRole("status")).toHaveTextContent("تعذّر التحقق");
    fireEvent.click(screen.getByRole("button", { name: "إعادة التحقق" }));
    expect(retry).toHaveBeenCalledOnce();
    error.rerender(<MemoryRouter><CommercialPreflightPanel language="en"
      status="denied" evidence={null} onRefresh={retry} /></MemoryRouter>);
    expect(screen.getByRole("status")).toHaveTextContent("Access was revoked");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByText("Verified")).not.toBeInTheDocument();
  });
});
