import { useState } from "react";
import { act, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ShopFormModal } from "@/components/dispatch/ShopFormModal";
import {
  createPayload, createdShopVerified, emptyShopForm, existingShopForm, financeReadback,
  metadataPayload, metadataVerified, ShopFormInputError, type ShopFormState,
} from "@/features/dispatch/shopForm/contract";
import { useShopFormCommit } from "@/features/dispatch/shopForm/useShopFormCommit";
import { shopFormText } from "@/features/dispatch/shopForm/messages";
import type { Shop, Zone } from "@/types/dispatch";
import type { DashboardSession } from "@/lib/authStorage";
import { setAppLanguage } from "@/i18n";

const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }));
const auth = vi.hoisted(() => ({ current: true }));
vi.mock("sonner", () => ({ toast }));
vi.mock("@/lib/authStorage", async importOriginal => {
  const original = await importOriginal<typeof import("@/lib/authStorage")>();
  return { ...original, isDashboardSessionCurrent: () => auth.current };
});
const session = { identity: "company-principal", generation: 1 } as unknown as DashboardSession;
const form: ShopFormState = {
  name: "Al Rayyan Grocery", owner: "Amal", phone: "55771234",
  mapLink: "https://maps.google.com/example", zoneId: "3",
  initialDebt: "100.125", maxDebtLimit: "150.500",
};
const shop: Shop = {
  ...form, id: "77", initialDebt: 100.125, maxDebtLimit: 150.5, sequence: 1, archived: false,
};
const zone: Zone = {
  id: "3", name: "Zone Three", scheduleStatus: "null",
  frequency: "", visitDay: "", startDate: "", intervalDays: null,
};
const wire = (overrides: Record<string, unknown> = {}) => ({
  ...shop, initialDebt: "80.000", maxDebtLimit: "75.125", ...overrides,
});
const fakeError = (status: number, code?: string, requestId = "req-finance-409") =>
  Object.assign(new Error("private backend diagnostic"), {
    status, code, requestId,
    data: { error: { code, request_id: requestId } },
  });

beforeEach(async () => {
  toast.success.mockReset(); toast.error.mockReset(); toast.info.mockReset();
  auth.current = true;
  await setAppLanguage("ar");
});

describe("Shop metadata-only allowlist and create financial truth", () => {
  it("never sends money, aliases or unrelated fields in metadata PUT even with stale high draft", () => {
    const payload = metadataPayload({
      ...existingShopForm(shop), name: "Updated Grocery",
      initialDebt: "999999999.999", maxDebtLimit: "999999999.999",
    });
    expect(payload).toEqual({ name: "Updated Grocery", owner: "Amal",
      phone: "55771234", mapLink: form.mapLink, zoneId: 3 });
    expect(JSON.stringify(payload)).not.toMatch(/initialDebt|maxDebtLimit|initial_debt|max_debt_limit|force_save/);
  });

  it("retains exact 100.125 / 150.500 strings for allowed creation", () => {
    const payload = createPayload(form);
    expect(payload).toEqual({ ...metadataPayload(form),
      initialDebt: "100.125", maxDebtLimit: "150.500", force_save: false });
    expect(createPayload({ ...form, initialDebt: "100", maxDebtLimit: "0" }))
      .toMatchObject({ initialDebt: "100.000", maxDebtLimit: "0.000" });
    expect(createdShopVerified([wire({ initialDebt: "100.125", maxDebtLimit: "150.500" })],
      "77", payload)).toBe(true);
    expect(createdShopVerified([wire()], "77", payload)).toBe(false);
  });

  it.each(["-1", "NaN", "Infinity", "100.1234", "1000000000", "", "1e6", "10.0010"])(
    "rejects invalid opening amount %s without silent rounding/clamp", initialDebt => {
      expect(() => createPayload({ ...form, initialDebt })).toThrow(ShopFormInputError);
    },
  );

  it("requires valid zone/name but does not depend on stale money for metadata changes", () => {
    expect(() => metadataPayload({ ...form, zoneId: "0" })).toThrow(ShopFormInputError);
    expect(() => metadataPayload({ ...form, name: "x" })).toThrow(ShopFormInputError);
    expect(metadataPayload({ ...form, initialDebt: "BAD", maxDebtLimit: "BAD" }).name)
      .toBe(form.name);
  });

  it("reads current balances only from fresh authorized GET data, not stale edit form", () => {
    expect(financeReadback([wire()], "77"))
      .toEqual({ initialDebt: "80.000", maxDebtLimit: "75.125" });
    expect(financeReadback([], "77")).toBeNull();
    expect(financeReadback([wire({ initialDebt: null })], "77")).toBeNull();
    expect(metadataVerified([wire({ name: "Updated Grocery" })], "77",
      { ...metadataPayload(form), name: "Updated Grocery" })).toBe(true);
    expect(metadataVerified([wire()], "77", { ...metadataPayload(form), name: "Changed" }))
      .toBe(false);
  });
});

describe.each(["ar", "en"] as const)("Shop form %s UI, finance isolation", language => {
  it.each([390, 700, 1440])("at %ipx edit exposes only read-only current finances, keyboard save and no money inputs", async width => {
    await setAppLanguage(language);
    Object.defineProperty(window, "innerWidth", { configurable: true, value: width });
    const onSave = vi.fn();
    const renderModal = (edit: boolean) => render(
      <ShopFormModal isOpen onClose={vi.fn()} editingShopId={edit ? "77" : null}
        shopForm={form} onShopFormChange={vi.fn()} zones={[zone]}
        onSave={onSave} onVerify={vi.fn()} language={language}
        saving={false} needsVerification={false} canViewFinances
        finance={{ initialDebt: "80.000", maxDebtLimit: "75.125" }}
        financeLoading={false} feedback={null}/>,
    );
    const edit = renderModal(true);
    expect(screen.getByText(shopFormText(language, "titleEdit"))).toBeInTheDocument();
    expect(screen.getByTestId("shop-current-debt")).toBeInTheDocument();
    expect(screen.getByTestId("shop-current-cap")).toBeInTheDocument();
    expect(screen.queryByLabelText(shopFormText(language, "openingDebt"))).not.toBeInTheDocument();
    expect(screen.getByText(shopFormText(language, "financeReadOnly"))).toBeInTheDocument();
    fireEvent.submit(document.getElementById("shop-form")!);
    expect(onSave).toHaveBeenCalledOnce();
    edit.unmount();
    const create = renderModal(false);
    expect(screen.getByLabelText(shopFormText(language, "openingDebt"))).toHaveValue("100.125");
    expect(screen.getByLabelText(shopFormText(language, "maxDebt"))).toHaveValue("150.500");
    create.unmount();
  });

  it("hides financial figures when existing viewing authority is unavailable", async () => {
    await setAppLanguage(language);
    render(
      <ShopFormModal isOpen onClose={vi.fn()} editingShopId="77"
        shopForm={form} onShopFormChange={vi.fn()} zones={[zone]}
        onSave={vi.fn()} onVerify={vi.fn()} language={language}
        saving={false} needsVerification={false} canViewFinances={false}
        finance={null} financeLoading={false} feedback={null}/>,
    );
    expect(screen.getByText(shopFormText(language, "financeUnavailable"))).toBeInTheDocument();
    expect(screen.queryByTestId("shop-current-debt")).not.toBeInTheDocument();
  });
});

const args = (fetch: (path: string, opts?: RequestInit) => Promise<unknown>, overrides: Record<string, unknown> = {}) => ({
  open: true, editId: "77" as string | null, form, language: "en",
  session, canViewFinances: false, busy: false,
  setBusy: vi.fn(), fetch, onVerified: vi.fn(), onClose: vi.fn(), ...overrides,
});

describe("Shop authenticated save/readback & financial denial", () => {
  it("after FIELD debt 100->80 sends metadata-only PUT, proves 80.000 and 75.125 remain on new GET", async () => {
    const live = wire({ name: "Updated Grocery" });
    const fetch = vi.fn().mockImplementation(async (path: string, opts?: RequestInit) => {
      if (opts?.method === "PUT") return { message: "ok" };
      if (path === "/dispatch/shops") return [live];
      throw new Error("unexpected request");
    });
    const props = args(fetch, { form: { ...form, name: "Updated Grocery" } });
    const { result } = renderHook(() => useShopFormCommit(props));
    await act(async () => { expect(await result.current.save()).toBe(true); });
    const put = fetch.mock.calls.find(([path, opts]) => path.includes("/shops/") && opts?.method === "PUT");
    expect(JSON.parse(put![1]!.body as string)).toEqual(metadataPayload(props.form));
    expect(JSON.stringify(put![1]!.body)).not.toMatch(/Debt|debt|initial/);
    expect(props.onVerified).toHaveBeenCalledWith([live], false, "3");
    expect(props.onClose).toHaveBeenCalledOnce();
    expect(toast.success).toHaveBeenCalledOnce();
  });

  it.each(["ar", "en"] as const)("financial stale 409 in %s refreshes authorized live finance and keeps metadata", async language => {
    const latest = wire({ name: form.name, initialDebt: "80.000" });
    const fetch = vi.fn().mockImplementation(async (_path: string, opts?: RequestInit) => {
      if (opts?.method === "PUT") throw fakeError(409, "SHOP_FINANCIAL_STALE_FORM");
      return [latest];
    });
    const props = args(fetch, { language, canViewFinances: true,
      form: { ...form, name: "New Shop Name", phone: "55997711" } });
    const { result } = renderHook(() => useShopFormCommit(props));
    await waitFor(() => expect(result.current.finance).toEqual({
      initialDebt: "80.000", maxDebtLimit: "75.125",
    }));
    await act(async () => { expect(await result.current.save()).toBe(false); });
    expect(result.current.feedback).toContain("req-finance-409");
    expect(result.current.finance?.initialDebt).toBe("80.000");
    expect(result.current.needsVerification).toBe(false);
    expect(props.form.name).toBe("New Shop Name");
    expect(props.form.phone).toBe("55997711");
    expect(fetch.mock.calls.filter(([, opts]) => opts?.method === "PUT")).toHaveLength(1);
    expect(toast.success).not.toHaveBeenCalled();
  });

  it("409 required financial authority cannot be bypassed or treated as success", async () => {
    const fetch = vi.fn().mockImplementation(async (_path: string, opts?: RequestInit) => {
      if (opts?.method === "PUT") throw fakeError(409, "SHOP_FINANCIAL_ACTION_REQUIRES_AUTHORITY");
      return [wire()];
    });
    const props = args(fetch, { canViewFinances: true });
    const { result } = renderHook(() => useShopFormCommit(props));
    await act(async () => { expect(await result.current.save()).toBe(false); });
    expect(result.current.feedback).toContain(shopFormText("en", "financialAuthority"));
    expect(toast.success).not.toHaveBeenCalled();
  });

  it.each([401, 403])("HTTP %s fails closed, no false success, no financial refresh after denial", async status => {
    const fetch = vi.fn().mockRejectedValue(fakeError(status, "FORBIDDEN"));
    const props = args(fetch);
    const { result } = renderHook(() => useShopFormCommit(props));
    await act(async () => { expect(await result.current.save()).toBe(false); });
    expect(result.current.finance).toBeNull();
    expect(result.current.feedback).toContain(shopFormText("en", "denied"));
    expect(fetch).toHaveBeenCalledOnce();
    expect(props.onVerified).not.toHaveBeenCalled();
    expect(props.onClose).not.toHaveBeenCalled();
  });

  it("PUT200 with unauthorized GET only offers GET retry, never re-sends PUT", async () => {
    const updated = wire({ name: "Changed" });
    const fetch = vi.fn().mockImplementation(async (_path: string, opts?: RequestInit) => {
      if (opts?.method === "PUT") return { message: "ok" };
      if (fetch.mock.calls.filter(([, x]) => x?.method === "PUT").length === 1 &&
        fetch.mock.calls.filter(([, x]) => !x?.method).length === 1) {
        throw fakeError(403, "FORBIDDEN");
      }
      return [updated];
    });
    const props = args(fetch, { form: { ...form, name: "Changed" } });
    const { result } = renderHook(() => useShopFormCommit(props));
    await act(async () => { expect(await result.current.save()).toBe(false); });
    expect(result.current.needsVerification).toBe(true);
    expect(toast.success).not.toHaveBeenCalled();
    await act(async () => { expect(await result.current.verify()).toBe(true); });
    expect(fetch.mock.calls.filter(([, opts]) => opts?.method === "PUT")).toHaveLength(1);
    expect(toast.success).toHaveBeenCalledOnce();
  });

  it("POST retains exact 100.125/150.500 and verifies fresh response before adding row", async () => {
    const fetch = vi.fn().mockImplementation(async (_path: string, opts?: RequestInit) => {
      if (opts?.method === "POST") return { shop_id: "77" };
      return [wire({ initialDebt: "100.125", maxDebtLimit: "150.500" })];
    });
    const props = args(fetch, { editId: null });
    const { result } = renderHook(() => useShopFormCommit(props));
    await act(async () => { expect(await result.current.save()).toBe(true); });
    const post = fetch.mock.calls.find(([, opts]) => opts?.method === "POST");
    expect(JSON.parse(post![1]!.body as string)).toMatchObject({
      initialDebt: "100.125", maxDebtLimit: "150.500", force_save: false,
    });
    expect(props.onVerified).toHaveBeenCalledWith(expect.any(Array), true, "3");
  });

  it("duplicate-create 409 retains exact opening money through explicit confirmation", async () => {
    let posts = 0;
    const fetch = vi.fn().mockImplementation(async (_path: string, opts?: RequestInit) => {
      if (opts?.method === "POST") {
        posts += 1;
        if (posts === 1) throw Object.assign(new Error("duplicate"), {
          status: 409, data: { is_duplicate: true, existing_shop: { name: "Existing Grocery" } },
        });
        return { shop_id: "77" };
      }
      return [wire({ initialDebt: "100.125", maxDebtLimit: "150.500" })];
    });
    const props = args(fetch, { editId: null });
    const { result } = renderHook(() => useShopFormCommit(props));
    await act(async () => { expect(await result.current.save()).toBe(false); });
    expect(result.current.duplicate?.shopData.name).toBe("Existing Grocery");
    await act(async () => { expect(await result.current.confirmDuplicate()).toBe(true); });
    expect(posts).toBe(2);
    const posted = fetch.mock.calls.filter(([, o]) => o?.method === "POST").map(([, o]) =>
      JSON.parse(o!.body as string));
    expect(posted[0]).toMatchObject({ initialDebt: "100.125", maxDebtLimit: "150.500", force_save: false });
    expect(posted[1]).toMatchObject({ initialDebt: "100.125", maxDebtLimit: "150.500", force_save: true });
  });

  it("old session response after tenant switch cannot hydrate newer company form", async () => {
    let late!: (rows: unknown) => void;
    const fetch = vi.fn().mockImplementation((_path: string, opts?: RequestInit) =>
      opts?.method === "PUT" ? Promise.resolve({}) :
        new Promise(resolve => { late = resolve; }));
    const props = args(fetch, { form: { ...form, name: "Changed" } });
    const { result, unmount } = renderHook(() => useShopFormCommit(props));
    let promise!: Promise<boolean>;
    await act(async () => { promise = result.current.save(); await Promise.resolve(); });
    auth.current = false;
    unmount();
    await act(async () => { late([wire({ name: "Changed" })]); expect(await promise).toBe(false); });
    expect(props.onVerified).not.toHaveBeenCalled();
    expect(toast.success).not.toHaveBeenCalled();
  });
});
