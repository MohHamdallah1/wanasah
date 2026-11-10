import { useState } from "react";
// D13: render this component with the company currency returned by the verified tenant endpoint.
vi.mock("@/features/tenantIdentity/useTenantIdentity", () => ({
  useTenantIdentity: () => ({ data: { company_id: 1, currency_code: "QAR" } }),
}));
import { webcrypto } from "node:crypto";
import { act, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ShopFormModal } from "@/components/dispatch/ShopFormModal";
import {
  canCloseShopForm, canOpenShopForm, createPayload, createdShopVerified,
  emptyShopForm, existingShopForm, financeReadback, findCreatedShopAfterUnknownWrite,
  metadataPayload, metadataVerified, preserveUnsavedShopOrder, ShopFormInputError,
  type ShopFormState,
} from "@/features/dispatch/shopForm/contract";
import { useShopFormCommit } from "@/features/dispatch/shopForm/useShopFormCommit";
import { shopFormText } from "@/features/dispatch/shopForm/messages";
import type { Shop, Zone } from "@/types/dispatch";
import type { DashboardSession } from "@/lib/authStorage";
import { setAppLanguage } from "@/i18n";
import { clearLocalStoragePreservingLoginHintsAndPreferences } from "@/lib/authStorage";
import { readDurableCommand } from "@/lib/durableOperations";
import {
  isShopCreateAttempt, shopCreateAttemptScope, shopEditAttemptScope,
  type ShopCreateAttempt, type ShopEditAttempt,
} from "@/features/dispatch/shopForm/contract";

const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }));
const auth = vi.hoisted(() => ({ current: true }));
const heldCreateLocks = new Set<string>();
const fakeWebLocks = {
  request: async <T,>(name: string, _options: unknown, callback: (lock: object | null) => Promise<T>): Promise<T> => {
    // A synchronous cross-context lock claim before the first microtask.
    if (heldCreateLocks.has(name)) return callback(null);
    heldCreateLocks.add(name);
    try { return await callback({ name, mode: "exclusive" }); }
    finally { heldCreateLocks.delete(name); }
  },
};
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
  ...shop, initialDebt: "80.000", maxDebtLimit: "75.125", financeRedacted: false, ...overrides,
});
const fakeError = (status: number, code?: string, requestId = "req-finance-409") =>
  Object.assign(new Error("private backend diagnostic"), {
    status, code, requestId,
    data: { error: { code, request_id: requestId } },
  });

beforeEach(async () => {
  toast.success.mockReset(); toast.error.mockReset(); toast.info.mockReset();
  auth.current = true;
  localStorage.clear();
  localStorage.setItem("company_id", "1");
  localStorage.setItem("principal_id", "11");
  localStorage.setItem("backoffice_user_id", "110");
  vi.stubGlobal("crypto", webcrypto);
  heldCreateLocks.clear();
  Object.defineProperty(navigator, "locks", { configurable: true, value: fakeWebLocks });
  await setAppLanguage("ar");
});

afterEach(() => {
  vi.unstubAllGlobals();
  Object.defineProperty(navigator, "locks", { configurable: true, value: undefined });
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
    expect(createdShopVerified([wire()], "77", payload)).toBe(true);
    // currentDebt may be 80 after a valid 100.125 opening + field collection.
  });

  it.each(["-1", "NaN", "Infinity", "100.1234", "1000000000", "", "1e6", "10.0010"])(
    "rejects invalid opening amount %s without silent rounding/clamp", initialDebt => {
      expect(() => createPayload({ ...form, initialDebt })).toThrow(ShopFormInputError);
    },
  );

  it("cannot claim it cleared a populated phone when the backend intentionally ignores blank phone", () => {
    const edit = existingShopForm(shop);
    expect(() => metadataPayload({ ...edit, phone: "" }))
      .toThrow(ShopFormInputError);
    expect(metadataPayload({ ...edit, phone: "55112233" }).phone).toBe("55112233");
    expect(metadataPayload({ ...emptyShopForm("3"), name: "New Store", phone: "" }).phone)
      .toBe("");
  });

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
    expect(financeReadback([wire({ initialDebt: "-5.125" })], "77")?.initialDebt)
      .toBe("-5.125"); // Reading current receivable is not a create-money validation.
    expect(financeReadback([wire({ initialDebt: null })], "77")).toBeNull();
    expect(metadataVerified([wire({ name: "Updated Grocery" })], "77",
      { ...metadataPayload(form), name: "Updated Grocery" })).toBe(true);
    expect(metadataVerified([wire()], "77", { ...metadataPayload(form), name: "Changed" }))
      .toBe(false);
  });
});

describe("Codex P2: Shop form closure, lost POST identity and order draft", () => {
  it("rejects any close while saving or post-write verification remains open", () => {
    expect(canCloseShopForm(true, false)).toBe(false);
    expect(canCloseShopForm(false, true)).toBe(false);
    expect(canCloseShopForm(true, true)).toBe(false);
    expect(canCloseShopForm(false, false)).toBe(true);
  });

  it.each(["ar", "en"] as const)("header close/backdrop/Escape in %s cannot close in-flight form", async language => {
    await setAppLanguage(language);
    const onClose = vi.fn();
    const modal = render(
      <ShopFormModal isOpen
        onClose={() => { if (canCloseShopForm(true, false)) onClose(); }}
        editingShopId="77" shopForm={form} onShopFormChange={vi.fn()}
        zones={[zone]} onSave={vi.fn()} onVerify={vi.fn()} onLeaveUncertain={vi.fn()}
          needsManualReconciliation={false} restoring={false} recoveryUnreadable={false}
          localTrackingId={null} serverReference={null} language={language}
        saving needsVerification={false} canViewFinances={false} finance={null}
        financeLoading={false} feedback={null}/>,
    );
    const closeX = document.querySelector(".app-modal-header button") as HTMLButtonElement;
    const backdrop = document.querySelector(".app-modal-backdrop") as HTMLElement;
    expect(closeX).toBeTruthy();
    expect(backdrop).toBeTruthy();
    fireEvent.click(closeX);
    fireEvent.click(backdrop);
    fireEvent.keyDown(document, { key: "Escape", code: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    modal.unmount();
  });

  it("blocks creation/metadata edit while reordered Shops require save, preserves fresh authorized IDs", () => {
    expect(canOpenShopForm(true, false)).toBe(false);
    expect(canOpenShopForm(false, true)).toBe(false);
    expect(canOpenShopForm(false, false)).toBe(true);
    const old = [shop, { ...shop, id: "78", sequence: 2 }];
    const draft = [{ ...old[0], sequence: 2 }, { ...old[1], sequence: 1 }];
    const fresh = [
      { ...old[0], sequence: 1, name: "Authorized Updated Name", initialDebt: 80 },
      { ...old[1], sequence: 2 },
      { ...shop, id: "79", sequence: 999 },
    ];
    expect(preserveUnsavedShopOrder(draft, fresh)).toEqual([
      { ...fresh[0], sequence: 2 },
      { ...fresh[1], sequence: 1 },
      fresh[2],
    ]);
    expect(preserveUnsavedShopOrder(draft, fresh.slice(1)).map(s => s.id))
      .toEqual(["78", "79"]); // never keep a row no longer in authorized GET
  });

  it("reconciles lost create response only to unique authorized NEW ID after pre-POST snapshot", () => {
    const sent = createPayload(form);
    const latest = [wire({ id: "77", initialDebt: "100.125", maxDebtLimit: "150.500" })];
    expect(findCreatedShopAfterUnknownWrite(latest, [], sent)).toBe("77");
    expect(findCreatedShopAfterUnknownWrite(latest, ["77"], sent)).toBeNull();
    expect(findCreatedShopAfterUnknownWrite([...latest, { ...latest[0], id: "78" }], [], sent)).toBeNull();
    expect(findCreatedShopAfterUnknownWrite(latest, [], { ...sent, maxDebtLimit: "150.501" }))
      .toBe("77"); // live finance is NOT immutable creation proof
  });

  it.each(["ar", "en"] as const)(
    "a lost POST response in %s remains unknown even when exactly one matching Shop appears; no false success",
    async language => {
      await setAppLanguage(language);
      let reads = 0;
      const fetch = vi.fn().mockImplementation(async (_path: string, opts?: RequestInit) => {
        if (opts?.method === "POST") throw fakeError(500, "INTERNAL_SERVER_ERROR", "req-lost-create");
        reads++;
        return reads === 1 ? [] : [wire({ initialDebt: "100.125", maxDebtLimit: "150.500" })];
      });
      const props = args(fetch, { editId: null, language });
      const hooked = renderHook(() => useShopFormCommit(props));
    await waitFor(() => expect(hooked.result.current.restoring).toBe(false));
      await act(async () => { expect(await hooked.result.current.save()).toBe(false); });
      expect(hooked.result.current.needsVerification).toBe(true);
      expect(fetch.mock.calls.filter(([, o]) => o?.method === "POST")).toHaveLength(1);
      expect(props.onVerified).not.toHaveBeenCalled();
      await act(async () => { expect(await hooked.result.current.verify()).toBe(false); });
      expect(hooked.result.current.needsVerification).toBe(true);
      expect(hooked.result.current.feedback).toBe(shopFormText(language, "createUncorrelated"));
      expect(props.onVerified).not.toHaveBeenCalled();
      expect(toast.success).not.toHaveBeenCalled();
      expect(fetch.mock.calls.filter(([, o]) => o?.method === "POST")).toHaveLength(1);
      expect(reads).toBe(2);
    },
  );

  it("concurrent identical Shop created by another principal cannot falsely confirm our lost POST", async () => {
    let reads = 0;
    const otherPrincipalCreation = wire({
      id: "88", initialDebt: "5.000", maxDebtLimit: "42.000",
    });
    const fetch = vi.fn().mockImplementation(async (_path: string, opts?: RequestInit) => {
      if (opts?.method === "POST") throw fakeError(500, "INTERNAL_SERVER_ERROR", "req-lost");
      reads++;
      return reads === 1 ? [] : [otherPrincipalCreation];
    });
    const props = args(fetch, { editId: null });
    const hooked = renderHook(() => useShopFormCommit(props));
    await waitFor(() => expect(hooked.result.current.restoring).toBe(false));
    await act(async () => { expect(await hooked.result.current.save()).toBe(false); });
    await act(async () => { expect(await hooked.result.current.verify()).toBe(false); });
    expect(hooked.result.current.needsVerification).toBe(true);
    expect(hooked.result.current.feedback).toBe(shopFormText("en", "createUncorrelated"));
    expect(props.onVerified).not.toHaveBeenCalled();
    expect(props.onClose).not.toHaveBeenCalled();
    expect(toast.success).not.toHaveBeenCalled();
    expect(fetch.mock.calls.filter(([, o]) => o?.method === "POST")).toHaveLength(1);
  });

  it("ambiguous lost POST with two new matching Shops fails closed, never claims success or resends", async () => {
    const candidate = wire({ initialDebt: "100.125", maxDebtLimit: "150.500" });
    let reads = 0;
    const fetch = vi.fn().mockImplementation(async (_path: string, opts?: RequestInit) => {
      if (opts?.method === "POST") throw fakeError(500, "INTERNAL_SERVER_ERROR");
      reads++;
      return reads === 1 ? [] : [candidate, { ...candidate, id: "78" }];
    });
    const props = args(fetch, { editId: null });
    const hooked = renderHook(() => useShopFormCommit(props));
    await waitFor(() => expect(hooked.result.current.restoring).toBe(false));
    await act(async () => { expect(await hooked.result.current.save()).toBe(false); });
    await act(async () => { expect(await hooked.result.current.verify()).toBe(false); });
    expect(hooked.result.current.needsVerification).toBe(true);
    expect(hooked.result.current.feedback).toBe(shopFormText("en", "createNotFound"));
    expect(fetch.mock.calls.filter(([, o]) => o?.method === "POST")).toHaveLength(1);
    expect(toast.success).not.toHaveBeenCalled();
  });

  it("a delayed create GET reconciles metadata after real field collection changes the live balance", async () => {
    const postPayload = createPayload(form);
    let reads = 0;
    const live = wire({
      initialDebt: "80.000", maxDebtLimit: "150.500",
      // Current balance must not be equated to the original opening amount.
    });
    const fetch = vi.fn().mockImplementation(async (_path: string, opts?: RequestInit) => {
      if (opts?.method === "POST") throw fakeError(500, "INTERNAL_SERVER_ERROR");
      reads++;
      return reads === 1 ? [] : [live];
    });
    const props = args(fetch, { editId: null });
    const hooked = renderHook(() => useShopFormCommit(props));
    await waitFor(() => expect(hooked.result.current.restoring).toBe(false));
    await act(async () => { expect(await hooked.result.current.save()).toBe(false); });
    expect(hooked.result.current.needsVerification).toBe(true);
    await act(async () => { expect(await hooked.result.current.verify()).toBe(false); });
    expect(createdShopVerified([live], "77", postPayload)).toBe(true);
    expect(hooked.result.current.feedback).toBe(shopFormText("en", "createUncorrelated"));
    expect(props.onVerified).not.toHaveBeenCalled(); // no server operation identity
    expect(fetch.mock.calls.filter(([, o]) => o?.method === "POST")).toHaveLength(1);
    expect(toast.success).not.toHaveBeenCalled();
  });

  it.each(["ar", "en"] as const)(
    "keeps user edits locked in %s until the previous save is verified", async language => {
      await setAppLanguage(language);
      const changes = vi.fn();
      const modal = render(
        <ShopFormModal isOpen onClose={vi.fn()} editingShopId="77"
          shopForm={form} onShopFormChange={changes} zones={[zone]} onSave={vi.fn()}
          onVerify={vi.fn()} onLeaveUncertain={vi.fn()}
          needsManualReconciliation={false} restoring={false} recoveryUnreadable={false}
          localTrackingId={null} serverReference={null} language={language} saving={false}
          needsVerification canViewFinances={false} finance={null}
          financeLoading={false} feedback={null}/>,
      );
      const name = screen.getByDisplayValue(form.name) as HTMLInputElement;
      const phone = screen.getByDisplayValue(form.phone) as HTMLInputElement;
      expect(name).toBeDisabled();
      expect(phone).toBeDisabled();
      fireEvent.change(name, { target: { value: "Unsent new edit" } });
      fireEvent.change(phone, { target: { value: "5559999" } });
      expect(changes).not.toHaveBeenCalled();
      expect(screen.getByRole("button", { name: shopFormText(language, "refresh") }))
        .toBeEnabled(); // only authorized GET verify remains available
      modal.unmount();
    },
  );

  it("offline authorized preflight fails before any POST and never creates impossible pending record", async () => {
    const fetch = vi.fn().mockRejectedValue(new Error("offline before request"));
    const props = args(fetch, { editId: null });
    const hooked = renderHook(() => useShopFormCommit(props));
    await waitFor(() => expect(hooked.result.current.restoring).toBe(false));
    await act(async () => { expect(await hooked.result.current.save()).toBe(false); });
    expect(hooked.result.current.needsVerification).toBe(false);
    expect(hooked.result.current.feedback).toBe(shopFormText("en", "beforeCreateFailed"));
    expect(fetch.mock.calls.filter(([, o]) => o?.method === "POST")).toHaveLength(0);
    expect(toast.success).not.toHaveBeenCalled();
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
        onSave={onSave} onVerify={vi.fn()} onLeaveUncertain={vi.fn()}
          needsManualReconciliation={false} restoring={false} recoveryUnreadable={false}
          localTrackingId={null} serverReference={null} language={language}
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
        onSave={vi.fn()} onVerify={vi.fn()} onLeaveUncertain={vi.fn()}
          needsManualReconciliation={false} restoring={false} recoveryUnreadable={false}
          localTrackingId={null} serverReference={null} language={language}
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
    await waitFor(() => expect(result.current.restoring).toBe(false));
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
    await waitFor(() => expect(result.current.restoring).toBe(false));
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
    await waitFor(() => expect(result.current.restoring).toBe(false));
    await act(async () => { expect(await result.current.save()).toBe(false); });
    expect(result.current.feedback).toContain(shopFormText("en", "financialAuthority"));
    expect(toast.success).not.toHaveBeenCalled();
  });

  it.each(["ar", "en"] as const)(
    "create 400 archived zone and 409 duplicate phone in %s surface safe backend business reasons",
    async language => {
      await setAppLanguage(language);
      for (const [status, reason] of [
        [400, "المنطقة المحددة مؤرشفة ولا تقبل محلات جديدة"],
        [409, "رقم الهاتف مستخدم لمحل آخر داخل الشركة"],
      ] as const) {
        const fetch = vi.fn().mockImplementation(async (_path: string, opts?: RequestInit) => {
          if (opts?.method === "POST") {
            throw Object.assign(new Error("not safe for display"), {
              status, requestId: `req-business-${status}`,
              data: { detail: reason },
            });
          }
          return []; // authorized pre-POST membership snapshot
        });
        const props = args(fetch, { editId: null, language });
        const hooked = renderHook(() => useShopFormCommit(props));
    await waitFor(() => expect(hooked.result.current.restoring).toBe(false));
        await act(async () => { expect(await hooked.result.current.save()).toBe(false); });
        expect(hooked.result.current.feedback).toContain(reason);
        expect(hooked.result.current.feedback).toContain(`req-business-${status}`);
        expect(hooked.result.current.needsVerification).toBe(false);
        expect(props.onVerified).not.toHaveBeenCalled();
        expect(toast.success).not.toHaveBeenCalled();
        hooked.unmount();
      }
    },
  );

  it.each([409, 422])("deterministic create error %s does not lock future saves as uncertain", async status => {
    const fetch = vi.fn().mockImplementation(async (_path: string, opts?: RequestInit) => {
      if (opts?.method === "POST") throw fakeError(status, "BUSINESS_CONFLICT");
      return [];
    });
    const props = args(fetch, { editId: null });
    const { result } = renderHook(() => useShopFormCommit(props));
    await waitFor(() => expect(result.current.restoring).toBe(false));
    await act(async () => { expect(await result.current.save()).toBe(false); });
    expect(result.current.needsVerification).toBe(false);
    expect(props.onClose).not.toHaveBeenCalled();
    expect(toast.success).not.toHaveBeenCalled();
  });

  it("locale/finance permission changes do not erase a pending confirmed PUT verification guard", async () => {
    const fetch = vi.fn().mockImplementation(async (_path: string, opts?: RequestInit) => {
      if (opts?.method === "PUT") return { message: "ok" };
      throw fakeError(403, "FORBIDDEN");
    });
    const props = args(fetch, { form: { ...form, name: "Changed" } });
    const hooked = renderHook(
      (params: typeof props) => useShopFormCommit(params),
      { initialProps: props },
    );
    await waitFor(() => expect(hooked.result.current.restoring).toBe(false));
    await act(async () => { expect(await hooked.result.current.save()).toBe(false); });
    expect(hooked.result.current.needsVerification).toBe(true);
    hooked.rerender({ ...props, language: "ar", canViewFinances: true });
    await waitFor(() => expect(hooked.result.current.financeLoading).toBe(false));
    expect(hooked.result.current.needsVerification).toBe(true);
    expect(fetch.mock.calls.filter(([, opts]) => opts?.method === "PUT")).toHaveLength(1);
  });

  it.each([401, 403])("HTTP %s fails closed, no false success, no financial refresh after denial", async status => {
    const fetch = vi.fn().mockRejectedValue(fakeError(status, "FORBIDDEN"));
    const props = args(fetch);
    const { result } = renderHook(() => useShopFormCommit(props));
    await waitFor(() => expect(result.current.restoring).toBe(false));
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
    await waitFor(() => expect(result.current.restoring).toBe(false));
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
    await waitFor(() => expect(result.current.restoring).toBe(false));
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
    await waitFor(() => expect(result.current.restoring).toBe(false));
    await act(async () => { expect(await result.current.save()).toBe(false); });
    expect(result.current.duplicate?.shopData.name).toBe("Existing Grocery");
    await act(async () => { expect(await result.current.confirmDuplicate()).toBe(true); });
    expect(posts).toBe(2);
    const posted = fetch.mock.calls.filter(([, o]) => o?.method === "POST").map(([, o]) =>
      JSON.parse(o!.body as string));
    expect(posted[0]).toMatchObject({ initialDebt: "100.125", maxDebtLimit: "150.500", force_save: false });
    expect(posted[1]).toMatchObject({ initialDebt: "100.125", maxDebtLimit: "150.500", force_save: true });
  });

  it("a verified edit closing its own modal always releases shared busy state", async () => {
    const fetch = vi.fn().mockImplementation(async (_path: string, options?: RequestInit) =>
      options?.method === "PUT" ? { message: "ok" } : [wire({ name: "Changed" })],
    );
    const props = args(fetch, { form: { ...form, name: "Changed" } });
    const closed = vi.fn();
    const hooked = renderHook(() => {
      const [open, setOpen] = useState(true);
      const [busy, setBusy] = useState(false);
      const formHook = useShopFormCommit({
        ...props, open, busy, setBusy,
        onClose: () => { closed(); setOpen(false); },
      });
      return { ...formHook, open, busy };
    });
    await waitFor(() => expect(hooked.result.current.restoring).toBe(false));
    await act(async () => { expect(await hooked.result.current.save()).toBe(true); });
    expect(closed).toHaveBeenCalledOnce();
    expect(hooked.result.current.open).toBe(false);
    expect(hooked.result.current.busy).toBe(false);
    expect(toast.success).toHaveBeenCalledOnce();
  });

  it("old session response after tenant switch cannot hydrate newer company form", async () => {
    let late!: (rows: unknown) => void;
    const fetch = vi.fn().mockImplementation((_path: string, opts?: RequestInit) =>
      opts?.method === "PUT" ? Promise.resolve({}) :
        new Promise(resolve => { late = resolve; }));
    const props = args(fetch, { form: { ...form, name: "Changed" } });
    const { result, unmount } = renderHook(() => useShopFormCommit(props));
    await waitFor(() => expect(result.current.restoring).toBe(false));
    let promise!: Promise<boolean>;
    await act(async () => { promise = result.current.save(); await Promise.resolve(); });
    // The async save reaches the verification GET after its durable lock;
    // do not revoke before the test's deliberately delayed response exists.
    await waitFor(() => expect(late).toBeTypeOf("function"));
    auth.current = false;
    unmount();
    await act(async () => { late([wire({ name: "Changed" })]); expect(await promise).toBe(false); });
    expect(props.onVerified).not.toHaveBeenCalled();
    expect(toast.success).not.toHaveBeenCalled();
  });
});

describe("Shop unknown-create durable operator escape / relogin / tenant authority", () => {
  function createLostReply(verifyRows: unknown = []) {
    let reads = 0;
    const fetch = vi.fn().mockImplementation(async (_path: string, opts?: RequestInit) => {
      if (opts?.method === "POST") {
        throw fakeError(500, "SERVER_LOST_AFTER_WRITE", "req-sh-500");
      }
      reads++;
      return reads === 1 ? [] : verifyRows;
    });
    return { fetch, reads: () => reads };
  }

  it.each(["ar", "en"] as const)(
    "persists unknown POST before send; explicit leave and same-account reload restore in %s without resending",
    async language => {
      await setAppLanguage(language);
      const transport = createLostReply();
      const onClose = vi.fn();
      const restored = vi.fn();
      const props = args(transport.fetch, { editId: null, language, onClose, onRestoreForm: restored });
      const first = renderHook(() => useShopFormCommit(props));
      await waitFor(() => expect(first.result.current.restoring).toBe(false));
      await act(async () => { expect(await first.result.current.save()).toBe(false); });
      expect(first.result.current.needsManualReconciliation).toBe(true);
      expect(first.result.current.needsVerification).toBe(true);
      expect(first.result.current.localTrackingId).toMatch(/[0-9a-f-]{20,}/i);
      expect(first.result.current.serverReference).toBe("req-sh-500");
      const scope = shopCreateAttemptScope()!;
      const command = await readDurableCommand<ShopCreateAttempt>(scope);
      expect(command?.requestId).toBe(first.result.current.localTrackingId);
      expect(command?.payload.submitted).toMatchObject({
        name: form.name, initialDebt: "100.125", maxDebtLimit: "150.500",
      });
      expect(isShopCreateAttempt(command?.payload)).toBe(true);

      act(() => first.result.current.leaveUncertain());
      expect(onClose).toHaveBeenCalledOnce();
      expect(toast.success).not.toHaveBeenCalled();
      first.unmount();
      // Unmount/reload is not proof of a successful server write.
      const second = renderHook(() => useShopFormCommit(props));
      await waitFor(() => expect(second.result.current.restoring).toBe(false));
      await waitFor(() => expect(second.result.current.needsManualReconciliation).toBe(true));
      expect(restored).toHaveBeenCalledWith(expect.objectContaining({
        name: form.name, phone: form.phone, initialDebt: "100.125",
      }));
      expect(second.result.current.localTrackingId).toBe(command?.requestId);
      expect(second.result.current.serverReference).toBe("req-sh-500");
      await act(async () => { expect(await second.result.current.save()).toBe(false); });
      await act(async () => { expect(await second.result.current.verify()).toBe(false); });
      expect(transport.fetch.mock.calls.filter(([, o]) => o?.method === "POST")).toHaveLength(1);
      expect(toast.success).not.toHaveBeenCalled();
      expect(props.onVerified).not.toHaveBeenCalled();
      second.unmount();
    },
  );

  it.each([390, 700, 1440])(
    "operator-visible bilingual manual exit at %ipx preserves draft and never triggers another POST",
    async width => {
      Object.defineProperty(window, "innerWidth", { configurable: true, value: width });
      const onSave = vi.fn();
      const onVerify = vi.fn();
      const onLeaveUncertain = vi.fn();
      for (const language of ["ar", "en"] as const) {
        await setAppLanguage(language);
        const modal = render(
          <ShopFormModal isOpen onClose={vi.fn()} editingShopId={null}
            shopForm={form} onShopFormChange={vi.fn()} zones={[zone]}
            onSave={onSave} onVerify={onVerify} onLeaveUncertain={onLeaveUncertain}
            needsManualReconciliation restoring={false} recoveryUnreadable={false}
            localTrackingId="local-abc-123" serverReference="req-sh-500"
            language={language} saving={false} needsVerification
            canViewFinances={false} finance={null} financeLoading={false}
            feedback={shopFormText(language, "createUncorrelated")}/>,
        );
        expect(screen.getByTestId("shop-uncertain-create")).toBeInTheDocument();
        expect(screen.getByText(shopFormText(language, "createManualInstructions"))).toBeInTheDocument();
        expect(screen.getByText(/local-abc-123/)).toBeInTheDocument();
        expect(screen.getByText(/req-sh-500/)).toBeInTheDocument();
        expect(screen.getByDisplayValue(form.name)).toBeDisabled();
        expect(screen.getByRole("button", { name: shopFormText(language, "refresh") })).toBeEnabled();
        fireEvent.click(screen.getByRole("button", { name: shopFormText(language, "createLeaveSafely") }));
        expect(onLeaveUncertain).toHaveBeenCalledTimes(language === "ar" ? 1 : 2);
        expect(onSave).not.toHaveBeenCalled();
        modal.unmount();
      }
    },
  );

  it("canonical logout preserves A's pending record but a different company/principal never loads it", async () => {
    const transport = createLostReply();
    const first = renderHook(() => useShopFormCommit(args(transport.fetch, { editId: null })));
    await waitFor(() => expect(first.result.current.restoring).toBe(false));
    await act(async () => { expect(await first.result.current.save()).toBe(false); });
    const originalScope = shopCreateAttemptScope()!;
    const oldId = first.result.current.localTrackingId;
    first.unmount();

    expect(clearLocalStoragePreservingLoginHintsAndPreferences()).toBe(true);
    expect(localStorage.getItem(originalScope)).not.toBeNull(); // persisted across logout
    expect(localStorage.getItem("company_id")).toBeNull();
    localStorage.setItem("company_id", "2");
    localStorage.setItem("principal_id", "22");
    localStorage.setItem("backoffice_user_id", "220");
    const different = renderHook(() => useShopFormCommit(args(vi.fn().mockResolvedValue([]), {
      editId: null, onRestoreForm: vi.fn(),
    })));
    await waitFor(() => expect(different.result.current.restoring).toBe(false));
    expect(different.result.current.needsVerification).toBe(false);
    expect(different.result.current.localTrackingId).toBeNull();
    expect(toast.success).not.toHaveBeenCalled();
    different.unmount();

    // Same authenticated company/principal on a new login generation.
    localStorage.setItem("company_id", "1");
    localStorage.setItem("principal_id", "11");
    localStorage.setItem("backoffice_user_id", "110");
    const restored = vi.fn();
    const same = renderHook(() => useShopFormCommit(args(vi.fn().mockResolvedValue([]), {
      editId: null, onRestoreForm: restored,
    })));
    await waitFor(() => expect(same.result.current.needsManualReconciliation).toBe(true));
    expect(same.result.current.localTrackingId).toBe(oldId);
    expect(restored).toHaveBeenCalledWith(expect.objectContaining({
      name: form.name, maxDebtLimit: "150.500",
    }));
    same.unmount();
  });

  it("reload while POST is still in flight restores the pre-send durable attempt, never makes a second POST", async () => {
    let resolvePost!: (response: unknown) => void;
    const stalled = new Promise<unknown>(yes => { resolvePost = yes; });
    const fetch = vi.fn().mockImplementation(async (_path: string, opts?: RequestInit) =>
      opts?.method === "POST" ? stalled : [],
    );
    const first = renderHook(() => useShopFormCommit(args(fetch, { editId: null })));
    await waitFor(() => expect(first.result.current.restoring).toBe(false));
    let unresolved!: Promise<boolean>;
    act(() => { unresolved = first.result.current.save(); });
    await waitFor(() => expect(fetch.mock.calls.filter(([, o]) => o?.method === "POST")).toHaveLength(1));
    const pendingRecord = await readDurableCommand<ShopCreateAttempt>(shopCreateAttemptScope()!);
    expect(isShopCreateAttempt(pendingRecord?.payload)).toBe(true);
    first.unmount(); // simulates a real page reload with no server response
    const second = renderHook(() => useShopFormCommit(args(fetch, { editId: null })));
    await waitFor(() => expect(second.result.current.needsManualReconciliation).toBe(true));
    expect(second.result.current.localTrackingId).toBe(pendingRecord?.requestId);
    await act(async () => { expect(await second.result.current.save()).toBe(false); });
    expect(fetch.mock.calls.filter(([, o]) => o?.method === "POST")).toHaveLength(1);
    await act(async () => { resolvePost({ shop_id: "77" }); expect(await unresolved).toBe(false); });
    expect(toast.success).not.toHaveBeenCalled();
    second.unmount();
  });

  it("second tab with identical payload cannot POST while first tab has an unresolved durable attempt", async () => {
    let resolvePost!: (response: unknown) => void;
    const pending = new Promise<unknown>(yes => { resolvePost = yes; });
    const fetch = vi.fn().mockImplementation(async (_path: string, opts?: RequestInit) =>
      opts?.method === "POST" ? pending : [],
    );
    const first = renderHook(() => useShopFormCommit(args(fetch, { editId: null })));
    await waitFor(() => expect(first.result.current.restoring).toBe(false));
    let attempt!: Promise<boolean>;
    act(() => { attempt = first.result.current.save(); });
    await waitFor(() => expect(fetch.mock.calls.filter(([, o]) => o?.method === "POST")).toHaveLength(1));
    const second = renderHook(() => useShopFormCommit(args(fetch, { editId: null })));
    await waitFor(() => expect(second.result.current.needsManualReconciliation).toBe(true));
    await act(async () => { expect(await second.result.current.save()).toBe(false); });
    expect(fetch.mock.calls.filter(([, o]) => o?.method === "POST")).toHaveLength(1);
    second.unmount();
    first.unmount();
    await act(async () => { resolvePost({ shop_id: "77" }); expect(await attempt).toBe(false); });
  });

  it("missing canonical principal blocks creation without company-only fallback", async () => {
    localStorage.removeItem("principal_id");
    expect(shopCreateAttemptScope()).toBeNull();
    const fetch = vi.fn().mockResolvedValue([]);
    const hooked = renderHook(() => useShopFormCommit(args(fetch, { editId: null })));
    await waitFor(() => expect(hooked.result.current.restoring).toBe(false));
    expect(hooked.result.current.recoveryUnreadable).toBe(true);
    await act(async () => { expect(await hooked.result.current.save()).toBe(false); });
    expect(fetch).not.toHaveBeenCalled();
  });

  it("a missing/corrupt scoped record blocks any new POST instead of discarding uncertain money", async () => {
    const scope = shopCreateAttemptScope()!;
    localStorage.setItem(scope, "{not valid JSON");
    const fetch = vi.fn().mockResolvedValue([]);
    const hooked = renderHook(() => useShopFormCommit(args(fetch, { editId: null })));
    await waitFor(() => expect(hooked.result.current.restoring).toBe(false));
    expect(hooked.result.current.recoveryUnreadable).toBe(true);
    await act(async () => { expect(await hooked.result.current.save()).toBe(false); });
    expect(fetch).not.toHaveBeenCalled();
    expect(hooked.result.current.needsManualReconciliation).toBe(false);
  });

  it("definitively unsent offline preflight writes no recovery record and permits ordinary safe retry", async () => {
    let first = true;
    const fetch = vi.fn().mockImplementation(async (_path: string, opts?: RequestInit) => {
      if (opts?.method === "POST") return { shop_id: "77" };
      if (first) {
        first = false;
        throw new Error("offline before any POST");
      }
      return [wire()];
    });
    const props = args(fetch, { editId: null });
    const hooked = renderHook(() => useShopFormCommit(props));
    await waitFor(() => expect(hooked.result.current.restoring).toBe(false));
    await act(async () => { expect(await hooked.result.current.save()).toBe(false); });
    expect(await readDurableCommand(shopCreateAttemptScope()!)).toBeNull();
    expect(hooked.result.current.needsVerification).toBe(false);
    await act(async () => { expect(await hooked.result.current.save()).toBe(true); });
    expect(fetch.mock.calls.filter(([, o]) => o?.method === "POST")).toHaveLength(1);
    expect(await readDurableCommand(shopCreateAttemptScope()!)).toBeNull();
    expect(toast.success).toHaveBeenCalledOnce();
  });

  it.each([401, 403])("revoked authority HTTP %s on verification keeps pending draft and permits safe exit", async status => {
    const transport = createLostReply();
    const props = args(transport.fetch, { editId: null });
    const hooked = renderHook(() => useShopFormCommit(props));
    await waitFor(() => expect(hooked.result.current.restoring).toBe(false));
    await act(async () => { expect(await hooked.result.current.save()).toBe(false); });
    transport.fetch.mockImplementation(async (_path: string, opts?: RequestInit) => {
      if (opts?.method === "POST") throw new Error("NO SECOND POST");
      throw fakeError(status, "FORBIDDEN", "req-denied");
    });
    await act(async () => { expect(await hooked.result.current.verify()).toBe(false); });
    expect(hooked.result.current.feedback).toContain(shopFormText("en", "denied"));
    expect(hooked.result.current.needsManualReconciliation).toBe(true);
    expect(props.onVerified).not.toHaveBeenCalled();
    act(() => hooked.result.current.leaveUncertain());
    expect(props.onClose).toHaveBeenCalledOnce();
    expect(await readDurableCommand(shopCreateAttemptScope()!)).not.toBeNull();
    expect(transport.fetch.mock.calls.filter(([, o]) => o?.method === "POST")).toHaveLength(1);
  });

  it.each([0, 1, 2])("zero/one/multiple possible matching new shops (%i) never confirm uncertain POST", async count => {
    let reads = 0;
    const match = wire({ initialDebt: "100.125", maxDebtLimit: "150.500" });
    const fetch = vi.fn().mockImplementation(async (_path: string, opts?: RequestInit) => {
      if (opts?.method === "POST") throw fakeError(500, "SERVER_UNAVAILABLE", "req-unknown");
      reads++;
      return reads === 1 ? [] : Array.from({ length: count }, (_, i) => ({
        ...match, id: String(77 + i),
      }));
    });
    const props = args(fetch, { editId: null });
    const hooked = renderHook(() => useShopFormCommit(props));
    await waitFor(() => expect(hooked.result.current.restoring).toBe(false));
    await act(async () => { expect(await hooked.result.current.save()).toBe(false); });
    await act(async () => { expect(await hooked.result.current.verify()).toBe(false); });
    expect(hooked.result.current.needsManualReconciliation).toBe(true);
    expect(hooked.result.current.feedback).toBe(
      shopFormText("en", count === 1 ? "createUncorrelated" : "createNotFound"),
    );
    expect(props.onClose).not.toHaveBeenCalled();
    expect(props.onVerified).not.toHaveBeenCalled();
    expect(fetch.mock.calls.filter(([, o]) => o?.method === "POST")).toHaveLength(1);
    expect(toast.success).not.toHaveBeenCalled();
  });
});

describe("Codex P2: atomic cross-tab Shop create and canonical POST shop_id restoration", () => {
  it("two tabs concurrently claiming an absent durable record serialize through a real exclusive lock", async () => {
    let release!: (value: unknown) => void;
    const post = new Promise<unknown>(resolve => { release = resolve; });
    const fetch = vi.fn().mockImplementation(async (_path: string, opts?: RequestInit) =>
      opts?.method === "POST" ? post : [],
    );
    const first = renderHook(() => useShopFormCommit(args(fetch, { editId: null })));
    const second = renderHook(() => useShopFormCommit(args(fetch, { editId: null })));
    await waitFor(() => {
      expect(first.result.current.restoring).toBe(false);
      expect(second.result.current.restoring).toBe(false);
    });
    let attemptOne!: Promise<boolean>;
    let attemptTwo!: Promise<boolean>;
    act(() => {
      attemptOne = first.result.current.save();
      attemptTwo = second.result.current.save();
    });
    await act(async () => { expect(await attemptTwo).toBe(false); });
    expect(second.result.current.feedback).toBe(shopFormText("en", "createOtherTab"));
    await waitFor(() => expect(fetch.mock.calls.filter(([, o]) => o?.method === "POST")).toHaveLength(1));
    expect(heldCreateLocks.size).toBe(1);
    await act(async () => { release({ shop_id: "77" }); expect(await attemptOne).toBe(false); });
    expect(heldCreateLocks.size).toBe(0);
    expect(fetch.mock.calls.filter(([, o]) => o?.method === "POST")).toHaveLength(1);
    expect(toast.success).not.toHaveBeenCalled(); // no metadata readback evidence
    first.unmount(); second.unmount();
  });

  it.each(["ar", "en"] as const)(
    "POST-201 canonical shop_id survives locale change and verifies only that ID in %s",
    async language => {
      await setAppLanguage(language);
      let reads = 0;
      const fetch = vi.fn().mockImplementation(async (_path: string, opts?: RequestInit) => {
        if (opts?.method === "POST") return { shop_id: "77" };
        reads++;
        if (reads === 1) return []; // preflight
        if (reads === 2) throw fakeError(403, "FORBIDDEN");
        return [wire()]; // recovers under authorized GET
      });
      const initial = args(fetch, { editId: null, language });
      const hooked = renderHook(
        (props: typeof initial) => useShopFormCommit(props),
        { initialProps: initial },
      );
      await waitFor(() => expect(hooked.result.current.restoring).toBe(false));
      await act(async () => { expect(await hooked.result.current.save()).toBe(false); });
      expect(hooked.result.current.needsManualReconciliation).toBe(true);
      const scope = shopCreateAttemptScope()!;
      expect(JSON.parse(localStorage.getItem(`${scope}:canonical-id`) || "null")).toMatchObject({
        localId: hooked.result.current.localTrackingId, shopId: "77",
      });
      hooked.rerender({ ...initial, language: language === "ar" ? "en" : "ar" });
      await waitFor(() => expect(hooked.result.current.restoring).toBe(false));
      await act(async () => { expect(await hooked.result.current.verify()).toBe(true); });
      expect(initial.onVerified).toHaveBeenCalledWith(expect.any(Array), true, "3");
      expect(fetch.mock.calls.filter(([, o]) => o?.method === "POST")).toHaveLength(1);
      expect(localStorage.getItem(`${scope}:canonical-id`)).toBeNull();
      expect(await readDurableCommand(scope)).toBeNull();
      expect(toast.success).toHaveBeenCalledOnce();
    },
  );

  it("known canonical POST-201 Shop ID persists across explicit leave, reload and same-principal re-login", async () => {
    let reads = 0;
    const fetch = vi.fn().mockImplementation(async (_path: string, opts?: RequestInit) => {
      if (opts?.method === "POST") return { shop_id: "77" };
      reads++;
      if (reads === 1) return [];
      if (reads === 2) throw new Error("offline readback after real POST-201");
      return [wire()];
    });
    const close = vi.fn();
    const old = renderHook(() => useShopFormCommit(args(fetch, { editId: null, onClose: close })));
    await waitFor(() => expect(old.result.current.restoring).toBe(false));
    await act(async () => { expect(await old.result.current.save()).toBe(false); });
    const originalId = old.result.current.localTrackingId;
    act(() => old.result.current.leaveUncertain());
    expect(close).toHaveBeenCalledOnce();
    old.unmount();
    clearLocalStoragePreservingLoginHintsAndPreferences();
    localStorage.setItem("company_id", "1");
    localStorage.setItem("principal_id", "11");
    localStorage.setItem("backoffice_user_id", "110");
    const restoreForm = vi.fn();
    const props = args(fetch, { editId: null, onRestoreForm: restoreForm });
    const fresh = renderHook(() => useShopFormCommit(props));
    await waitFor(() => expect(fresh.result.current.needsManualReconciliation).toBe(true));
    expect(fresh.result.current.localTrackingId).toBe(originalId);
    await act(async () => { expect(await fresh.result.current.verify()).toBe(true); });
    expect(props.onVerified).toHaveBeenCalledOnce();
    expect(fetch.mock.calls.filter(([, o]) => o?.method === "POST")).toHaveLength(1);
    expect(toast.success).toHaveBeenCalledOnce();
    expect(await readDurableCommand(shopCreateAttemptScope()!)).toBeNull();
  });

  it("without cross-context Web Locks, a new create is rejected before sending even a preflight", async () => {
    Object.defineProperty(navigator, "locks", { configurable: true, value: undefined });
    const fetch = vi.fn().mockResolvedValue([]);
    const hooked = renderHook(() => useShopFormCommit(args(fetch, { editId: null })));
    await waitFor(() => expect(hooked.result.current.restoring).toBe(false));
    await act(async () => { expect(await hooked.result.current.save()).toBe(false); });
    expect(hooked.result.current.feedback).toBe(shopFormText("en", "createLockUnavailable"));
    expect(fetch).not.toHaveBeenCalled();
    expect(await readDurableCommand(shopCreateAttemptScope()!)).toBeNull();
    expect(toast.success).not.toHaveBeenCalled();
  });
});

describe("Codex P2: edit PUT with unreconcilable readback has a durable operator exit", () => {
  it.each(["ar", "en"] as const)(
    "offline PUT in %s can be left and reopened with the original metadata draft, no duplicate PUT",
    async language => {
      await setAppLanguage(language);
      const edited = { ...form, name: "Unsent local name", phone: "5551122" };
      const fetch = vi.fn().mockImplementation(async (_path: string, opts?: RequestInit) => {
        if (opts?.method === "PUT") throw new Error("offline before transport");
        return [wire()];
      });
      const onClose = vi.fn();
      const original = args(fetch, {
        editId: "77", form: edited, language, onClose, onRestoreForm: vi.fn(),
      });
      const first = renderHook(() => useShopFormCommit(original));
      await waitFor(() => expect(first.result.current.restoring).toBe(false));
      await act(async () => { expect(await first.result.current.save()).toBe(false); });
      expect(first.result.current.needsEditReview).toBe(true);
      expect(first.result.current.needsVerification).toBe(true);
      const scope = shopEditAttemptScope("77")!;
      const record = await readDurableCommand<ShopEditAttempt>(scope);
      expect(record?.payload).toMatchObject({
        kind: "SHOP_METADATA_EDIT_UNCERTAIN_V1",
        submitted: metadataPayload(edited), draft: edited, shopId: "77",
      });
      await act(async () => { expect(await first.result.current.verify()).toBe(false); });
      expect(first.result.current.needsEditReview).toBe(true);
      expect(original.onVerified).not.toHaveBeenCalled();
      act(() => first.result.current.leaveUncertain());
      expect(onClose).toHaveBeenCalledOnce();
      first.unmount();

      const restoreForm = vi.fn();
      const after = args(fetch, {
        editId: "77", form: existingShopForm(shop), language, onRestoreForm: restoreForm,
      });
      const second = renderHook(() => useShopFormCommit(after));
      await waitFor(() => expect(second.result.current.needsEditReview).toBe(true));
      expect(restoreForm).toHaveBeenCalledWith(edited);
      expect(second.result.current.localTrackingId).toBe(record?.requestId);
      await act(async () => { expect(await second.result.current.save()).toBe(false); });
      expect(fetch.mock.calls.filter(([, o]) => o?.method === "PUT")).toHaveLength(1);
      expect(toast.success).not.toHaveBeenCalled();
      second.unmount();
    },
  );

  it("successful edit PUT but later server conflict stays reviewable without repeating the PUT", async () => {
    const edited = { ...form, name: "Saved originally" };
    const fetch = vi.fn().mockImplementation(async (_path: string, opts?: RequestInit) => {
      if (opts?.method === "PUT") return { message: "ok" };
      return [wire({ name: "Other editor changed this name" })];
    });
    const props = args(fetch, { form: edited });
    const hooked = renderHook(() => useShopFormCommit(props));
    await waitFor(() => expect(hooked.result.current.restoring).toBe(false));
    await act(async () => { expect(await hooked.result.current.save()).toBe(false); });
    expect(hooked.result.current.needsEditReview).toBe(true);
    await act(async () => { expect(await hooked.result.current.verify()).toBe(false); });
    expect(hooked.result.current.needsEditReview).toBe(true);
    act(() => hooked.result.current.leaveUncertain());
    expect(props.onClose).toHaveBeenCalledOnce();
    expect(await readDurableCommand<ShopEditAttempt>(shopEditAttemptScope("77")!)).not.toBeNull();
    expect(fetch.mock.calls.filter(([, o]) => o?.method === "PUT")).toHaveLength(1);
    expect(toast.success).not.toHaveBeenCalled();
  });

  it("verified edit metadata readback clears durable edit record and cannot alter money", async () => {
    const edited = { ...form, name: "Updated Shop", initialDebt: "999999999.999" };
    const fetch = vi.fn().mockImplementation(async (_path: string, opts?: RequestInit) =>
      opts?.method === "PUT" ? { message: "ok" } :
        [wire({ name: "Updated Shop", initialDebt: "80.000", maxDebtLimit: "75.125" })],
    );
    const props = args(fetch, { form: edited });
    const hooked = renderHook(() => useShopFormCommit(props));
    await waitFor(() => expect(hooked.result.current.restoring).toBe(false));
    await act(async () => { expect(await hooked.result.current.save()).toBe(true); });
    expect(props.onVerified).toHaveBeenCalledOnce();
    const put = fetch.mock.calls.find(([, o]) => o?.method === "PUT");
    expect(JSON.parse(put![1]!.body as string)).toEqual(metadataPayload(edited));
    expect(JSON.stringify(put![1]!.body)).not.toMatch(/initialDebt|maxDebtLimit/);
    expect(await readDurableCommand(shopEditAttemptScope("77")!)).toBeNull();
    expect(toast.success).toHaveBeenCalledOnce();
  });

  it.each([401, 403, 409])("definitive edit HTTP %s never leaves an immutable unresolved lock", async status => {
    const fetch = vi.fn().mockImplementation(async (_path: string, opts?: RequestInit) =>
      opts?.method === "PUT" ? Promise.reject(fakeError(status, "FORBIDDEN")) : [wire()],
    );
    const props = args(fetch, { form: { ...form, name: "Changed" } });
    const hooked = renderHook(() => useShopFormCommit(props));
    await waitFor(() => expect(hooked.result.current.restoring).toBe(false));
    await act(async () => { expect(await hooked.result.current.save()).toBe(false); });
    expect(hooked.result.current.needsEditReview).toBe(false);
    expect(await readDurableCommand(shopEditAttemptScope("77")!)).toBeNull();
    expect(props.onVerified).not.toHaveBeenCalled();
  });

  it("edit recovery belongs only to the authorized original company and principal", async () => {
    const fetch = vi.fn().mockImplementation(async (_path: string, opts?: RequestInit) =>
      opts?.method === "PUT" ? Promise.reject(new Error("unconfirmed")) : [wire()],
    );
    const first = renderHook(() => useShopFormCommit(args(fetch, {
      form: { ...form, name: "Private pending data" },
    })));
    await waitFor(() => expect(first.result.current.restoring).toBe(false));
    await act(async () => { expect(await first.result.current.save()).toBe(false); });
    const privateScope = shopEditAttemptScope("77")!;
    first.unmount();
    localStorage.setItem("principal_id", "22");
    const restore = vi.fn();
    const other = renderHook(() => useShopFormCommit(args(vi.fn().mockResolvedValue([wire()]), {
      onRestoreForm: restore,
    })));
    await waitFor(() => expect(other.result.current.restoring).toBe(false));
    expect(other.result.current.needsEditReview).toBe(false);
    expect(restore).not.toHaveBeenCalled();
    expect(localStorage.getItem(privateScope)).not.toBeNull();
    other.unmount();
  });

  it.each([390, 700, 1440])(
    "pending edit at width %i offers bilingual safe exit and locked metadata fields",
    async width => {
      Object.defineProperty(window, "innerWidth", { configurable: true, value: width });
      for (const language of ["ar", "en"] as const) {
        await setAppLanguage(language);
        const onLeave = vi.fn();
        const modal = render(
          <ShopFormModal isOpen onClose={vi.fn()} editingShopId="77"
            shopForm={form} onShopFormChange={vi.fn()} zones={[zone]}
            onSave={vi.fn()} onVerify={vi.fn()} onLeaveUncertain={onLeave}
            needsManualReconciliation={false} needsEditReview
            restoring={false} recoveryUnreadable={false}
            localTrackingId="local-edit-77" serverReference="req-edit-77"
            language={language} saving={false} needsVerification
            canViewFinances={false} finance={null}
            financeLoading={false} feedback={shopFormText(language, "readback")}/>,
        );
        expect(screen.getByTestId("shop-uncertain-edit")).toBeInTheDocument();
        expect(screen.getByText(shopFormText(language, "editManualInstructions"))).toBeInTheDocument();
        expect(screen.getByDisplayValue(form.name)).toBeDisabled();
        fireEvent.click(screen.getByRole("button", { name: shopFormText(language, "editLeaveSafely") }));
        expect(onLeave).toHaveBeenCalledOnce();
        modal.unmount();
      }
    },
  );
});

describe("Codex P2: atomically serialize concurrent metadata edit claims", () => {
  it.each(["ar", "en"] as const)(
    "two %s tabs editing the same shop claim ONE durable edit and ONE PUT, retaining original draft",
    async language => {
      await setAppLanguage(language);
      let releasePut!: (value: unknown) => void;
      const inFlightPut = new Promise<unknown>(resolve => { releasePut = resolve; });
      const fetch = vi.fn().mockImplementation(async (_path: string, opts?: RequestInit) =>
        opts?.method === "PUT" ? inFlightPut : [wire()],
      );
      const primary = { ...form, name: "Original first-tab edit" };
      const competing = { ...form, name: "Competing second-tab edit" };
      const first = renderHook(() => useShopFormCommit(args(fetch, { form: primary, language })));
      const second = renderHook(() => useShopFormCommit(args(fetch, { form: competing, language })));
      await waitFor(() => {
        expect(first.result.current.restoring).toBe(false);
        expect(second.result.current.restoring).toBe(false);
      });
      let firstWrite!: Promise<boolean>;
      let secondWrite!: Promise<boolean>;
      act(() => {
        firstWrite = first.result.current.save();
        secondWrite = second.result.current.save();
      });
      await act(async () => { expect(await secondWrite).toBe(false); });
      expect(second.result.current.feedback).toBe(shopFormText(language, "editOtherTab"));
      await waitFor(() => expect(fetch.mock.calls.filter(([, o]) => o?.method === "PUT")).toHaveLength(1));
      expect(heldCreateLocks.size).toBe(1);
      const scope = shopEditAttemptScope("77")!;
      const original = await readDurableCommand<ShopEditAttempt>(scope);
      expect(original?.payload).toMatchObject({
        submitted: metadataPayload(primary),
        draft: primary,
        shopId: "77",
      });
      await act(async () => { releasePut({ message: "ok" }); expect(await firstWrite).toBe(false); });
      expect(heldCreateLocks.size).toBe(0);
      const retained = await readDurableCommand<ShopEditAttempt>(scope);
      expect(retained?.requestId).toBe(original?.requestId);
      expect(retained?.payload.draft).toEqual(primary);
      expect(fetch.mock.calls.filter(([, o]) => o?.method === "PUT")).toHaveLength(1);
      expect(toast.success).not.toHaveBeenCalled();
      first.unmount(); second.unmount();
    },
  );

  it("unsupported Web Locks for metadata edit fails closed before any PUT", async () => {
    Object.defineProperty(navigator, "locks", { configurable: true, value: undefined });
    const fetch = vi.fn().mockResolvedValue([wire()]);
    const hooked = renderHook(() => useShopFormCommit(args(fetch, {
      form: { ...form, name: "No unsafe edit" },
    })));
    await waitFor(() => expect(hooked.result.current.restoring).toBe(false));
    await act(async () => { expect(await hooked.result.current.save()).toBe(false); });
    expect(hooked.result.current.feedback).toBe(shopFormText("en", "editLockUnavailable"));
    expect(fetch.mock.calls.filter(([, o]) => o?.method === "PUT")).toHaveLength(0);
    expect(await readDurableCommand(shopEditAttemptScope("77")!)).toBeNull();
    expect(toast.success).not.toHaveBeenCalled();
  });
});
