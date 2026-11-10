import { useState, type ReactNode } from "react";
// D13: render this component with the company currency returned by the verified tenant endpoint.
vi.mock("@/features/tenantIdentity/useTenantIdentity", () => ({
  useTenantIdentity: () => ({ data: { company_id: 1, currency_code: "QAR" } }),
}));
import { act, fireEvent, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { setAppLanguage } from "@/i18n";
import type { Shop, Zone } from "@/types/dispatch";
import { ShopTable } from "@/components/dispatch/ShopTable";
import { ShopOrderScopeNotice } from "@/features/dispatch/shopOrder/ShopOrderScopeNotice";
import { shopOrderText } from "@/features/dispatch/shopOrder/messages";
import {
  buildShopOrderChanges, canReorderShop, hasShopOrderChanges, moveShopBeforeInSelectedZone,
  moveShopInSelectedZone, verifyShopOrderReadback, canReconcileUncertainShopOrder,
  compareShopSequence,
} from "@/features/dispatch/shopOrder/scope";
import { commitShopOrder, ShopOrderUncertainError, ShopOrderVerificationError } from "@/features/dispatch/shopOrder/persist";
import { useShopOrderCommit } from "@/features/dispatch/shopOrder/useShopOrderCommit";
import {
  clearShopOrderRecoveryIfAttempt, loadShopOrderRecovery, loadShopOrderRecoveryRecord,
  stageShopOrderRecoveryDraft, storeShopOrderRecovery, updateShopOrderRecoveryIfAttempt, useShopOrderDraft,
} from "@/features/dispatch/shopOrder/useShopOrderDraft";

const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }));
vi.mock("sonner", () => ({ toast }));
const shop = (id: string, zoneId: string, sequence: number, archived = false): Shop => ({
  id, zoneId, sequence, archived, name: "Shop " + id, owner: "Owner",
  phone: "", mapLink: "", initialDebt: 0, maxDebtLimit: 0,
});
const zone = (id: string): Zone => ({
  id, name: "Zone " + id, scheduleStatus: "null", frequency: "",
  visitDay: "", startDate: "", intervalDays: null,
});
const original = [
  shop("A1", "A", 1), shop("A2", "A", 2), shop("A3", "A", 3),
  shop("B1", "B", 5), shop("B2", "B", 6), shop("OLD", "A", 9, true),
];
const snapshot = () => original.map(x => ({ ...x }));
const zoneList = [zone("A"), zone("B")];

beforeEach(async () => {
  toast.success.mockReset(); toast.error.mockReset(); toast.info.mockReset();
  sessionStorage.clear();
  await setAppLanguage("ar");
});

describe("Dispatch #843 selected-zone Shop order: immutable scope", () => {
  it("search in B while A selected never changes B via sequence or drag; A reorders against ALL A active rows", () => {
    const before = snapshot();
    expect(canReorderShop(before[3], "A")).toBe(false);
    expect(moveShopInSelectedZone(before, "A", "B1", 1)).toBe(before);
    expect(moveShopBeforeInSelectedZone(before, "A", "B1", "A1")).toBe(before);
    expect(moveShopBeforeInSelectedZone(before, "A", "A1", "B1")).toBe(before);
    expect(buildShopOrderChanges(before, before, "A")).toEqual([]);
    const after = moveShopInSelectedZone(before, "A", "A3", 0);
    expect(after.filter(s => s.zoneId === "A" && !s.archived).sort((a, b) => a.sequence - b.sequence)
      .map(x => x.id)).toEqual(["A3", "A1", "A2"]);
    expect(after.filter(s => s.zoneId === "B")).toEqual(before.filter(s => s.zoneId === "B"));
    expect(buildShopOrderChanges(before, after, "A")).toEqual([
      { id: "A1", sequence: 2 }, { id: "A2", sequence: 3 }, { id: "A3", sequence: 1 },
    ]);
  });

  it("normalizes noncontiguous legacy 999 ranks when first row receives rank 1", () => {
    const before = [shop("A1", "A", 999), shop("A2", "A", 1000), shop("B1", "B", 1)];
    const after = moveShopInSelectedZone(before, "A", "A1", 0);
    expect(after).not.toBe(before);
    expect(after.map(s => s.sequence)).toEqual([1, 2, 1]);
    expect(buildShopOrderChanges(before, after, "A"))
      .toEqual([{ id: "A1", sequence: 1 }, { id: "A2", sequence: 2 }]);
  });

  it.each(["ar", "en"] as const)(
    "tied 999 Shop ids 1,2,10 in %s reorder exactly as displayed, not lexical 1,10,2",
    async language => {
      await setAppLanguage(language);
      const before = [shop("1", "A", 999), shop("2", "A", 999),
        shop("10", "A", 999), shop("20", "B", 999)];
      const displayed = before.filter(s => s.zoneId === "A").sort(compareShopSequence);
      expect(displayed.map(s => s.id)).toEqual(["1", "2", "10"]);
      const after = moveShopInSelectedZone(before, "A", "1", 1);
      expect(after.filter(s => s.zoneId === "A").sort(compareShopSequence).map(s => s.id))
        .toEqual(["2", "1", "10"]);
      expect(after.find(s => s.id === "10")?.sequence).toBe(3);
      expect(after.find(s => s.id === "20")).toEqual(before[3]);
      expect(buildShopOrderChanges(before, after, "A")).toEqual([
        { id: "1", sequence: 2 }, { id: "2", sequence: 1 }, { id: "10", sequence: 3 },
      ]);
      const dragged = moveShopBeforeInSelectedZone(before, "A", "1", "2");
      expect(dragged).toEqual(after);
      const normalized = moveShopInSelectedZone(before, "A", "1", 0);
      expect(normalized.filter(s => s.zoneId === "A").sort(compareShopSequence).map(s => s.id))
        .toEqual(["1", "2", "10"]);
      expect(normalized.filter(s => s.zoneId === "A").map(s => s.sequence))
        .toEqual([1, 2, 3]); // tied rank normalization is not a no-op
    },
  );

  it("does not confirm a concurrent update of an unsubmitted row", async () => {
    const draft = moveShopInSelectedZone(snapshot(), "A", "A3", 1);
    const changes = buildShopOrderChanges(original, draft, "A");
    expect(changes.map(c => c.id)).toEqual(["A2", "A3"]);
    const concurrent = draft.map(s => s.id === "A1" ? { ...s, sequence: 3 } : s);
    expect(verifyShopOrderReadback(changes, concurrent, "A", draft)).toBe(false);
    await expect(commitShopOrder({
      original, draft, selectedZoneId: "A",
      send: vi.fn().mockResolvedValue({}), read: vi.fn().mockResolvedValue(concurrent),
    })).rejects.toBeInstanceOf(ShopOrderVerificationError);
  });

  it("an explicit B switch enables reordering B only, never mutating selected Zone A", () => {
    const before = snapshot();
    const after = moveShopInSelectedZone(before, "B", "B2", 0);
    expect(after.filter(s => s.zoneId === "A")).toEqual(before.filter(s => s.zoneId === "A"));
    expect(buildShopOrderChanges(before, after, "B")).toEqual([
      { id: "B1", sequence: 2 }, { id: "B2", sequence: 1 },
    ]);
    expect(buildShopOrderChanges(before, after, "A")).toEqual([]);
  });

  it("does not introduce fake dirty work for invalid target, same rank, archived row, or absent zone", () => {
    const before = snapshot();
    expect(moveShopInSelectedZone(before, "A", "A1", 0)).toBe(before);
    expect(moveShopInSelectedZone(before, "A", "OLD", 0)).toBe(before);
    expect(moveShopInSelectedZone(before, "", "A1", 1)).toBe(before);
    expect(moveShopInSelectedZone(before, "A", "A1", Number.NaN)).toBe(before);
    expect(hasShopOrderChanges(before, before, "A")).toBe(false);
  });

  it("preserves selected-zone staged archive and excludes B and pre-existing archived rows", () => {
    const after = snapshot().map(s => s.id === "A2" ? { ...s, archived: true } : s);
    expect(buildShopOrderChanges(original, after, "A")).toEqual([{ id: "A2", archived: true }]);
    const read = snapshot().map(s => s.id === "A2" ? { ...s, archived: true } : s);
    expect(verifyShopOrderReadback([{ id: "A2", archived: true }], read, "A", after)).toBe(true);
    expect(verifyShopOrderReadback([{ id: "A2", archived: true }], snapshot(), "A", after)).toBe(false);
  });

  it("commits ONLY exact changed selected-zone IDs and verifies fresh GET; no false success for 200 mismatch", async () => {
    const after = moveShopInSelectedZone(snapshot(), "A", "A3", 0);
    const send = vi.fn().mockResolvedValue({ message: "OK" });
    const read = vi.fn().mockResolvedValue(after);
    const result = await commitShopOrder({ original, draft: after, selectedZoneId: "A", send, read });
    expect(result.kind).toBe("confirmed");
    expect(send).toHaveBeenCalledOnce();
    expect(send.mock.calls[0][0].map((x: { id: string }) => x.id)).toEqual(["A1", "A2", "A3"]);
    expect(send.mock.calls[0][0].some((x: { id: string }) => x.id === "B1")).toBe(false);
    expect(read).toHaveBeenCalledOnce();
    read.mockResolvedValue(snapshot());
    await expect(commitShopOrder({ original, draft: after, selectedZoneId: "A", send, read }))
      .rejects.toBeInstanceOf(ShopOrderVerificationError);
  });

  it.each([403, 409])("a rejected HTTP %s retains unsaved state, does not read/announce success", async status => {
    const draft = moveShopInSelectedZone(snapshot(), "A", "A3", 0);
    const send = vi.fn().mockRejectedValue(Object.assign(new Error("request failed"), { status }));
    const read = vi.fn();
    await expect(commitShopOrder({ original, draft, selectedZoneId: "A", send, read }))
      .rejects.toMatchObject({ status });
    expect(read).not.toHaveBeenCalled();
    expect(toast.success).not.toHaveBeenCalled();
  });

  it("a failed authorized readback or abort never yields confirmed order; unchanged/no-op sends nothing", async () => {
    const draft = moveShopInSelectedZone(snapshot(), "A", "A3", 0);
    const send = vi.fn().mockResolvedValue({});
    const read = vi.fn().mockRejectedValue(Object.assign(new Error("network error"), { name: "AbortError" }));
    await expect(commitShopOrder({ original, draft, selectedZoneId: "A", send, read })).rejects.toThrow();
    expect(send).toHaveBeenCalledOnce();
    send.mockClear();
    const noop = await commitShopOrder({ original, draft: snapshot(), selectedZoneId: "A", send, read });
    expect(noop).toEqual({ kind: "no_changes" });
    expect(send).not.toHaveBeenCalled();
  });
});

describe.each(["ar", "en"] as const)("Shop ordering UI %s", language => {
  it.each([390, 700, 1440])("at %ipx: foreign Shop sequence and drag disabled, selected Zone still keyboard-editable", async width => {
    await setAppLanguage(language);
    Object.defineProperty(window, "innerWidth", { configurable: true, value: width });
    const onSequenceChange = vi.fn();
    const onDrop = vi.fn();
    const displayed = [shop("A1", "A", 1), shop("B1", "B", 2)];
    const { container, rerender } = render(<>
      <ShopOrderScopeNotice language={language} selectedZoneName="Zone A"
        hasOutsideZoneMatches isEditMode />
      <ShopTable shops={displayed} zones={zoneList} language={language}
        isEditMode isSaving={false} selectedShopIds={[]} allFilteredShops={displayed}
        selectedZoneIdForZones="A" onToggleSelectAll={vi.fn()}
        onToggleSelectShop={vi.fn()} onSequenceChange={onSequenceChange}
        onEditShop={vi.fn()} onArchiveShop={vi.fn()} onDragStart={vi.fn()} onDrop={onDrop} />
    </>);
    expect(screen.getByRole("status")).toHaveTextContent(
      shopOrderText(language, "selectedZone", { zone: "Zone A" }));
    const bRow = screen.getByText("Shop B1").closest("tr")!;
    expect(bRow).toHaveAttribute("draggable", "false");
    const disabled = within(bRow).getByRole("spinbutton");
    expect(disabled).toBeDisabled();
    expect(disabled).toHaveValue(2);
    fireEvent.drop(bRow, { dataTransfer: { getData: () => "A1" } });
    expect(onDrop).not.toHaveBeenCalled();
    const aRow = screen.getByText("Shop A1").closest("tr")!;
    expect(aRow).toHaveAttribute("draggable", "true");
    const input = within(aRow).getByRole("spinbutton");
    expect(input).toBeEnabled();
    fireEvent.change(input, { target: { value: "2" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSequenceChange).toHaveBeenCalledWith("A1", 2);
    rerender(<ShopTable shops={displayed} zones={zoneList} language={language}
      isEditMode isSaving={false} selectedShopIds={[]} allFilteredShops={displayed}
      selectedZoneIdForZones="B" onToggleSelectAll={vi.fn()}
      onToggleSelectShop={vi.fn()} onSequenceChange={onSequenceChange}
      onEditShop={vi.fn()} onArchiveShop={vi.fn()} onDragStart={vi.fn()} onDrop={onDrop} />);
    expect(within(screen.getByText("Shop B1").closest("tr")!).getByRole("spinbutton")).toBeEnabled();
    expect(within(screen.getByText("Shop A1").closest("tr")!).getByRole("spinbutton")).toBeDisabled();
    expect(container.querySelectorAll('input[type="checkbox"]')).toHaveLength(3);
  });
});

describe("Shop order confirm feedback", () => {
  it("hook does not show success for failed readback, 403 or failed cancel; preserves draft", async () => {
    const draft = moveShopInSelectedZone(snapshot(), "A", "A3", 0);
    const read = vi.fn().mockResolvedValueOnce(snapshot()).mockRejectedValueOnce(new Error("denied"));
    const send = vi.fn().mockResolvedValue({ message: "OK" });
    const props = {
      draft, baseline: { current: snapshot() }, zoneId: "A",
      language: "en", saving: false, setSaving: vi.fn(),
      setShops: vi.fn(), setDirty: vi.fn(), setEditMode: vi.fn(),
      clearSelection: vi.fn(), send, read,
    };
    const { result } = renderHook(() => useShopOrderCommit(props));
    let saved = true;
    await act(async () => { saved = await result.current.save(); });
    expect(saved).toBe(false);
    expect(toast.success).not.toHaveBeenCalled();
    expect(props.setDirty).not.toHaveBeenCalledWith(false);
    let cancelled = true;
    await act(async () => { cancelled = await result.current.cancel(); });
    expect(cancelled).toBe(false);
    expect(props.setShops).not.toHaveBeenCalled();
    expect(toast.error).toHaveBeenCalledTimes(2);
  });

  it("ambiguous committed PUT + failed GET reconciles before a changed retry (not against stale baseline)", async () => {
    const first = moveShopInSelectedZone(snapshot(), "A", "A3", 0);
    const revised = moveShopInSelectedZone(first, "A", "A3", 1);
    const send = vi.fn().mockResolvedValue({});
    const read = vi.fn().mockRejectedValueOnce(new Error("lost readback"))
      .mockResolvedValueOnce(first).mockResolvedValueOnce(revised);
    const props = {
      baseline: { current: snapshot() }, zoneId: "A", language: "ar",
      saving: false, setSaving: vi.fn(), setShops: vi.fn(), setDirty: vi.fn(),
      setEditMode: vi.fn(), clearSelection: vi.fn(), send, read,
    };
    const { result, rerender } = renderHook(
      ({ draft }: { draft: Shop[] }) => useShopOrderCommit({ ...props, draft }),
      { initialProps: { draft: first } },
    );
    await act(async () => { expect(await result.current.save()).toBe(false); });
    expect(result.current.needsReconciliation).toBe(true);
    expect(toast.success).not.toHaveBeenCalled();
    expect(props.baseline.current).toEqual(snapshot());
    rerender({ draft: revised });
    await act(async () => { expect(await result.current.save()).toBe(true); });
    expect(result.current.needsReconciliation).toBe(false);
    expect(send).toHaveBeenCalledTimes(2);
    expect(send.mock.calls[1][0].map((row: { id: string }) => row.id)).toEqual(["A1", "A3"]);
    expect(read).toHaveBeenCalledTimes(3); // first lost, recovery GET, final confirm GET
    expect(props.baseline.current).toEqual(revised);
    expect(toast.success).toHaveBeenCalledOnce();
  });

  it("after an ambiguous save, undoing the draft still reconciles and compensates the server", async () => {
    const first = moveShopInSelectedZone(snapshot(), "A", "A3", 0);
    const send = vi.fn().mockResolvedValue({});
    const read = vi.fn().mockRejectedValueOnce(new Error("lost readback"))
      .mockResolvedValueOnce(first).mockResolvedValueOnce(snapshot());
    const props = {
      baseline: { current: snapshot() }, zoneId: "A", language: "en",
      saving: false, setSaving: vi.fn(), setShops: vi.fn(), setDirty: vi.fn(),
      setEditMode: vi.fn(), clearSelection: vi.fn(), send, read,
    };
    const { result, rerender } = renderHook(
      ({ draft }: { draft: Shop[] }) => useShopOrderCommit({ ...props, draft }),
      { initialProps: { draft: first } },
    );
    await act(async () => { expect(await result.current.save()).toBe(false); });
    expect(result.current.needsReconciliation).toBe(true);
    rerender({ draft: snapshot() }); // UI's ordinary dirty comparator is now false
    await act(async () => { expect(await result.current.save()).toBe(true); });
    expect(send).toHaveBeenCalledTimes(2);
    expect(send.mock.calls[1][0].map((row: { id: string }) => row.id))
      .toEqual(["A1", "A2", "A3"]);
    expect(result.current.needsReconciliation).toBe(false);
  });

  it("denied recovery GET never retries the write or claims saved", async () => {
    const draft = moveShopInSelectedZone(snapshot(), "A", "A3", 0);
    const send = vi.fn().mockResolvedValue({});
    const read = vi.fn().mockRejectedValueOnce(new Error("first failed GET"))
      .mockRejectedValueOnce(Object.assign(new Error("revoked"), { status: 403 }));
    const props = {
      draft, baseline: { current: snapshot() }, zoneId: "A", language: "en",
      saving: false, setSaving: vi.fn(), setShops: vi.fn(), setDirty: vi.fn(),
      setEditMode: vi.fn(), clearSelection: vi.fn(), send, read,
    };
    const { result } = renderHook(() => useShopOrderCommit(props));
    await act(async () => { expect(await result.current.save()).toBe(false); });
    await act(async () => { expect(await result.current.save()).toBe(false); });
    expect(send).toHaveBeenCalledOnce();
    expect(result.current.needsReconciliation).toBe(true);
    expect(toast.success).not.toHaveBeenCalled();
  });


  it.each(["ar", "en"] as const)(
    "PUT 200 plus GET 401 in %s blocks replay on a concurrent untouched row",
    async language => {
      await setAppLanguage(language);
      const first = moveShopInSelectedZone(snapshot(), "A", "A3", 1);
      const revised = moveShopInSelectedZone(first, "A", "A3", 0);
      const thirdParty = first.map(s => s.id === "A1" ? { ...s, sequence: 3 } : s);
      const send = vi.fn().mockResolvedValue({});
      const read = vi.fn()
        .mockRejectedValueOnce(Object.assign(new Error("unauthorized readback"), { status: 401 }))
        .mockResolvedValue(thirdParty);
      const props = {
        baseline: { current: snapshot() }, zoneId: "A", language,
        saving: false, setSaving: vi.fn(), setShops: vi.fn(), setDirty: vi.fn(),
        setEditMode: vi.fn(), clearSelection: vi.fn(), send, read,
      };
      const { result, rerender } = renderHook(
        ({ draft }: { draft: Shop[] }) => useShopOrderCommit({ ...props, draft }),
        { initialProps: { draft: first } },
      );
      await act(async () => { expect(await result.current.save()).toBe(false); });
      expect(result.current.needsReconciliation).toBe(true);
      expect(toast.success).not.toHaveBeenCalled();
      rerender({ draft: revised });
      await act(async () => { expect(await result.current.save()).toBe(false); });
      expect(send).toHaveBeenCalledOnce(); // no stale-diff resend or duplicate rank
      expect(props.setShops).not.toHaveBeenCalled();
      expect(props.baseline.current).toEqual(snapshot());
      expect(result.current.needsReconciliation).toBe(true);
      expect(toast.error).toHaveBeenLastCalledWith(shopOrderText(language, "reconcileConflict"));
      const attempted = {
        zoneId: "A", outcome: "put_confirmed" as const, before: snapshot().filter(s => s.zoneId === "A"),
        intended: first.filter(s => s.zoneId === "A"),
      };
      expect(canReconcileUncertainShopOrder(attempted, thirdParty, "A")).toBe(false);
      expect(canReconcileUncertainShopOrder(attempted, first, "B")).toBe(false);
      await act(async () => { expect(await result.current.save()).toBe(false); });
      expect(send).toHaveBeenCalledOnce(); // repeated explicit Save stays fail-closed
    },
  );

  it("a timed-out PUT cannot rebase on old GET while the first server transaction may still finish", async () => {
    const first = moveShopInSelectedZone(snapshot(), "A", "A3", 0);
    const revised = moveShopInSelectedZone(first, "A", "A3", 1);
    let server = snapshot();
    const send = vi.fn()
      .mockRejectedValueOnce(Object.assign(new Error("PUT transport timed out"), { status: 408 }));
    const read = vi.fn().mockImplementation(async () => server);
    const props = {
      baseline: { current: snapshot() }, zoneId: "A", language: "en",
      saving: false, setSaving: vi.fn(), setShops: vi.fn(), setDirty: vi.fn(),
      setEditMode: vi.fn(), clearSelection: vi.fn(), send, read,
    };
    const { result, rerender } = renderHook(
      ({ draft }: { draft: Shop[] }) => useShopOrderCommit({ ...props, draft }),
      { initialProps: { draft: first } },
    );
    await act(async () => { expect(await result.current.save()).toBe(false); });
    expect(result.current.needsReconciliation).toBe(true);
    rerender({ draft: revised });
    await act(async () => { expect(await result.current.save()).toBe(false); });
    expect(read).toHaveBeenCalledOnce(); // old GET is NOT a completion fence
    expect(send).toHaveBeenCalledOnce();
    server = first; // the original timed-out PUT finishes *after* the old GET
    await act(async () => { expect(await result.current.save()).toBe(false); });
    await act(async () => { expect(await result.current.cancel()).toBe(false); });
    expect(send).toHaveBeenCalledOnce(); // never send a competing partial update
    expect(result.current.needsReconciliation).toBe(true);
    expect(props.setShops).not.toHaveBeenCalled();
    expect(toast.success).not.toHaveBeenCalled();
    expect(toast.error).toHaveBeenLastCalledWith(shopOrderText("en", "unresolvedTransport"));
  });

  it.each(["ar", "en"] as const)(
    "HTTP 500 unknown in %s retains safe code/context and request reference; no retry or raw internals",
    async language => {
      await setAppLanguage(language);
      const draft = moveShopInSelectedZone(snapshot(), "A", "A3", 0);
      const cause = Object.assign(new Error("secret-internal-db-message"), {
        status: 500, code: "INTERNAL_SERVER_ERROR",
        context: { internal: "private-connection-details" },
        requestId: "req-500-safe-ref",
      });
      const send = vi.fn().mockRejectedValue(cause);
      const read = vi.fn().mockResolvedValue(snapshot());
      const props = {
        draft, baseline: { current: snapshot() }, zoneId: "A", language,
        recoveryScope: "10:22", setZoneId: vi.fn(), saving: false,
        setSaving: vi.fn(), setShops: vi.fn(), setDirty: vi.fn(),
        setEditMode: vi.fn(), clearSelection: vi.fn(), send, read,
      };
      let wrapped: ShopOrderUncertainError | null = null;
      try {
        await commitShopOrder({ original, draft, selectedZoneId: "A", send, read });
      } catch (error) {
        expect(error).toBeInstanceOf(ShopOrderUncertainError);
        wrapped = error as ShopOrderUncertainError;
      }
      expect(wrapped).toMatchObject({
        status: 500, code: "INTERNAL_SERVER_ERROR",
        context: { internal: "private-connection-details" },
        requestId: "req-500-safe-ref",
        command: { outcome: "transport_unknown", zoneId: "A", requestId: "req-500-safe-ref" },
      });
      expect(wrapped?.cause).toBe(cause);
      const { result } = renderHook(() => useShopOrderCommit(props));
      await act(async () => { expect(await result.current.save()).toBe(false); });
      expect(result.current.needsReconciliation).toBe(true);
      expect(loadShopOrderRecovery("10:22")?.requestId).toBe("req-500-safe-ref");
      await act(async () => { expect(await result.current.save()).toBe(false); });
      expect(send).toHaveBeenCalledTimes(2); // direct + hook, never a second hook PUT
      expect(read).toHaveBeenCalledOnce(); // only authorization, NOT completion proof
      expect(toast.success).not.toHaveBeenCalled();
      const messages = toast.error.mock.calls.map(([message]) => String(message));
      expect(messages.some(message => message.includes("req-500-safe-ref"))).toBe(true);
      for (const message of messages) {
        expect(message).not.toContain("secret-internal-db-message");
        expect(message).not.toContain("private-connection-details");
        expect(message).not.toContain("INTERNAL_SERVER_ERROR");
      }
    },
  );

  it.each(["ar", "en"] as const)(
    "PUT200 GET401 retains the canonical GET reference in %s and through reauthentication",
    async language => {
      await setAppLanguage(language);
      const draft = moveShopInSelectedZone(snapshot(), "A", "A3", 0);
      const send = vi.fn().mockResolvedValue({});
      const read = vi.fn().mockRejectedValueOnce(Object.assign(new Error("hidden-session-error"), {
        status: 401, code: "AUTH_SESSION_EXPIRED",
        context: { private: "do-not-leak" }, requestId: "req-get401-safe",
      }));
      const props = {
        draft, baseline: { current: snapshot() }, zoneId: "A", language,
        recoveryScope: "4:55", setZoneId: vi.fn(), saving: false,
        setSaving: vi.fn(), setShops: vi.fn(), setDirty: vi.fn(),
        setEditMode: vi.fn(), clearSelection: vi.fn(), send, read,
      };
      const first = renderHook(() => useShopOrderCommit(props));
      await act(async () => { expect(await first.result.current.save()).toBe(false); });
      expect(first.result.current.needsReconciliation).toBe(true);
      expect(loadShopOrderRecovery("4:55")?.requestId).toBe("req-get401-safe");
      const rendered = String(toast.error.mock.calls.at(-1)?.[0]);
      expect(rendered).toContain("req-get401-safe");
      expect(rendered).not.toContain("hidden-session-error");
      expect(rendered).not.toContain("do-not-leak");
      expect(rendered).not.toContain("AUTH_SESSION_EXPIRED");
      first.unmount(); // production forceLogout unmounts DispatchSession on exhausted 401

      const newProps = {
        ...props, draft: snapshot(), read: vi.fn().mockResolvedValue(draft),
        setShops: vi.fn(), setZoneId: vi.fn(), setEditMode: vi.fn(),
      };
      const nextSession = renderHook(() => useShopOrderCommit(newProps));
      await waitFor(() => expect(nextSession.result.current.needsReconciliation).toBe(true));
      expect(newProps.setShops).toHaveBeenCalledWith(draft);
      expect(loadShopOrderRecovery("4:55")?.requestId).toBe("req-get401-safe");
      expect(send).toHaveBeenCalledOnce(); // no automatic replay after re-login
    },
  );

  it.each([403, 409])("definitely rejected PUT %s does not create an uncertain pending command", async status => {
    const draft = moveShopInSelectedZone(snapshot(), "A", "A3", 0);
    const send = vi.fn().mockRejectedValue(Object.assign(new Error("denied"), { status }));
    const read = vi.fn();
    const props = {
      draft, baseline: { current: snapshot() }, zoneId: "A", language: "ar",
      saving: false, setSaving: vi.fn(), setShops: vi.fn(), setDirty: vi.fn(),
      setEditMode: vi.fn(), clearSelection: vi.fn(), send, read,
    };
    const { result } = renderHook(() => useShopOrderCommit(props));
    await act(async () => { expect(await result.current.save()).toBe(false); });
    expect(result.current.needsReconciliation).toBe(false);
    expect(read).not.toHaveBeenCalled();
    expect(props.setDirty).not.toHaveBeenCalledWith(false);
    expect(toast.success).not.toHaveBeenCalled();
    await act(async () => { expect(await result.current.save()).toBe(false); });
    expect(send).toHaveBeenCalledTimes(2); // rejected commands need no old-write reconciliation
  });

  it("PUT 200 plus failed GET keeps the command pending after cancel GET fails", async () => {
    const first = moveShopInSelectedZone(snapshot(), "A", "A3", 0);
    const send = vi.fn().mockResolvedValue({});
    const read = vi.fn().mockRejectedValueOnce(new Error("read timeout"))
      .mockRejectedValueOnce(Object.assign(new Error("access revoked"), { status: 403 }));
    const props = {
      draft: first, baseline: { current: snapshot() }, zoneId: "A", language: "en",
      saving: false, setSaving: vi.fn(), setShops: vi.fn(), setDirty: vi.fn(),
      setEditMode: vi.fn(), clearSelection: vi.fn(), send, read,
    };
    const { result } = renderHook(() => useShopOrderCommit(props));
    await act(async () => { expect(await result.current.save()).toBe(false); });
    expect(result.current.needsReconciliation).toBe(true);
    await act(async () => { expect(await result.current.cancel()).toBe(false); });
    expect(result.current.needsReconciliation).toBe(true);
    expect(props.setShops).not.toHaveBeenCalled();
    expect(send).toHaveBeenCalledOnce();
    expect(toast.success).not.toHaveBeenCalled();
  });

  it("a mismatched complete readback is uncertain; nothing can confirm only changed-row ranks", async () => {
    const before = snapshot();
    const intended = moveShopInSelectedZone(before, "A", "A3", 1);
    const otherOperator = intended.map(s => s.id === "A1" ? { ...s, sequence: 3 } : s);
    const send = vi.fn().mockResolvedValue({});
    const read = vi.fn().mockResolvedValue(otherOperator);
    await expect(commitShopOrder({
      original: before, draft: intended, selectedZoneId: "A", send, read,
    })).rejects.toBeInstanceOf(ShopOrderUncertainError);
    expect(send).toHaveBeenCalledOnce();
    expect(toast.success).not.toHaveBeenCalled();
    expect(canReconcileUncertainShopOrder({
      zoneId: "A", outcome: "put_confirmed", before, intended,
    }, otherOperator, "A")).toBe(false);
  });

  it("PUT 200 + GET 401 preserves a scoped draft across simulated auth logout and restores only after an authorized login GET", async () => {
    const first = moveShopInSelectedZone(snapshot(), "A", "A3", 0);
    const send = vi.fn().mockResolvedValue({});
    const read = vi.fn().mockRejectedValueOnce(Object.assign(new Error("session expired"), { status: 401 }));
    const originalProps = {
      draft: first, baseline: { current: snapshot() }, zoneId: "A", language: "en",
      recoveryScope: "1:22", setZoneId: vi.fn(), saving: false,
      setSaving: vi.fn(), setShops: vi.fn(), setDirty: vi.fn(),
      setEditMode: vi.fn(), clearSelection: vi.fn(), send, read,
    };
    const initial = renderHook(() => useShopOrderCommit(originalProps));
    await act(async () => { expect(await initial.result.current.save()).toBe(false); });
    expect(loadShopOrderRecovery("1:22")?.outcome).toBe("put_confirmed");
    expect(toast.success).not.toHaveBeenCalled();
    initial.unmount(); // useAuthFetch forceLogout unmounts DispatchSession

    const restoredProps = {
      ...originalProps, draft: snapshot(), setShops: vi.fn(), setDirty: vi.fn(),
      setEditMode: vi.fn(), setZoneId: vi.fn(),
      read: vi.fn().mockResolvedValue(first),
    };
    const restored = renderHook(() => useShopOrderCommit(restoredProps));
    await waitFor(() => expect(restored.result.current.needsReconciliation).toBe(true));
    expect(restoredProps.setZoneId).toHaveBeenCalledWith("A");
    expect(restoredProps.setEditMode).toHaveBeenCalledWith(true);
    expect(restoredProps.setShops).toHaveBeenCalledWith(first);
    expect(send).toHaveBeenCalledOnce(); // never automatically replay on login

    restored.unmount();
    const otherUser = { ...restoredProps, recoveryScope: "1:23", setShops: vi.fn() };
    renderHook(() => useShopOrderCommit(otherUser));
    expect(otherUser.setShops).not.toHaveBeenCalled(); // principal isolation
    expect(loadShopOrderRecovery("1:22")).not.toBeNull();
    expect(loadShopOrderRecovery("1:23")).toBeNull();
  });

  it.each(["ar", "en"] as const)(
    "failed authorized recovery GET in %s keeps the prior command and blocks all new writes",
    async language => {
      await setAppLanguage(language);
      const intended = moveShopInSelectedZone(snapshot(), "A", "A3", 0);
      storeShopOrderRecovery("1:22", {
        zoneId: "A", outcome: "put_confirmed",
        before: snapshot().filter(s => s.zoneId === "A")
          .map(({ id, zoneId, sequence, archived }) => ({ id, zoneId, sequence, archived })),
        intended: intended.filter(s => s.zoneId === "A")
          .map(({ id, zoneId, sequence, archived }) => ({ id, zoneId, sequence, archived })),
      });
      const send = vi.fn();
      const read = vi.fn()
        .mockRejectedValueOnce(Object.assign(new Error("expired session"), { status: 401 }))
        .mockRejectedValueOnce(Object.assign(new Error("access revoked"), { status: 403 }));
      const props = {
        draft: snapshot(), baseline: { current: snapshot() }, zoneId: "A", language,
        recoveryScope: "1:22", setZoneId: vi.fn(), saving: false,
        setSaving: vi.fn(), setShops: vi.fn(), setDirty: vi.fn(),
        setEditMode: vi.fn(), clearSelection: vi.fn(), send, read,
      };
      const { result } = renderHook(() => useShopOrderCommit(props));
      await waitFor(() => expect(read).toHaveBeenCalledOnce());
      expect(result.current.needsReconciliation).toBe(true);
      await act(async () => { expect(await result.current.save()).toBe(false); });
      await act(async () => { expect(await result.current.cancel()).toBe(false); });
      expect(send).not.toHaveBeenCalled();
      expect(props.setShops).not.toHaveBeenCalled();
      expect(loadShopOrderRecovery("1:22")?.outcome).toBe("put_confirmed");
      expect(toast.success).not.toHaveBeenCalled();
    },
  );

  it("a failed membership recovery cannot replace the pending command with another PUT", async () => {
    const intended = moveShopInSelectedZone(snapshot(), "A", "A3", 0);
    storeShopOrderRecovery("1:44", {
      zoneId: "A", outcome: "transport_unknown",
      before: snapshot().filter(s => s.zoneId === "A")
        .map(({ id, zoneId, sequence, archived }) => ({ id, zoneId, sequence, archived })),
      intended: intended.filter(s => s.zoneId === "A")
        .map(({ id, zoneId, sequence, archived }) => ({ id, zoneId, sequence, archived })),
    });
    const altered = snapshot().filter(s => s.id !== "A2");
    const read = vi.fn().mockResolvedValue(altered);
    const send = vi.fn();
    const props = {
      draft: snapshot(), baseline: { current: snapshot() }, zoneId: "A", language: "en",
      recoveryScope: "1:44", setZoneId: vi.fn(), saving: false,
      setSaving: vi.fn(), setShops: vi.fn(), setDirty: vi.fn(),
      setEditMode: vi.fn(), clearSelection: vi.fn(), send, read,
    };
    const { result } = renderHook(() => useShopOrderCommit(props));
    await waitFor(() => expect(read).toHaveBeenCalledOnce());
    expect(result.current.needsReconciliation).toBe(true);
    await act(async () => { expect(await result.current.save()).toBe(false); });
    expect(send).not.toHaveBeenCalled();
    expect(props.setShops).not.toHaveBeenCalled();
    expect(loadShopOrderRecovery("1:44")?.outcome).toBe("transport_unknown");
  });

  it("successful recovery after a failed GET restores draft without sending in the same click", async () => {
    const intended = moveShopInSelectedZone(snapshot(), "A", "A3", 0);
    storeShopOrderRecovery("1:22", {
      zoneId: "A", outcome: "put_confirmed",
      before: snapshot().filter(s => s.zoneId === "A")
        .map(({ id, zoneId, sequence, archived }) => ({ id, zoneId, sequence, archived })),
      intended: intended.filter(s => s.zoneId === "A")
        .map(({ id, zoneId, sequence, archived }) => ({ id, zoneId, sequence, archived })),
    });
    const send = vi.fn();
    const read = vi.fn().mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce(snapshot());
    const props = {
      draft: snapshot(), baseline: { current: snapshot() }, zoneId: "A", language: "en",
      recoveryScope: "1:22", setZoneId: vi.fn(), saving: false,
      setSaving: vi.fn(), setShops: vi.fn(), setDirty: vi.fn(),
      setEditMode: vi.fn(), clearSelection: vi.fn(), send, read,
    };
    const { result } = renderHook(() => useShopOrderCommit(props));
    await waitFor(() => expect(read).toHaveBeenCalledOnce());
    await act(async () => { expect(await result.current.save()).toBe(false); });
    expect(props.setShops).toHaveBeenCalledWith(intended);
    expect(props.setEditMode).toHaveBeenCalledWith(true);
    expect(send).not.toHaveBeenCalled(); // no silent replay after restoring
    expect(result.current.needsReconciliation).toBe(true); // verify on next click
    expect(loadShopOrderRecovery("1:22")).not.toBeNull();
  });


  it.each([403, 409])(
    "reconciled PUT then definitively rejected replacement %s clears stale recovery before re-login",
    async status => {
      const first = moveShopInSelectedZone(snapshot(), "A", "A3", 0);
      const revised = moveShopInSelectedZone(first, "A", "A3", 1);
      const send = vi.fn().mockResolvedValueOnce({})
        .mockRejectedValueOnce(Object.assign(new Error("definitive rejection"), { status }));
      const read = vi.fn().mockRejectedValueOnce(new Error("lost first GET"))
        .mockResolvedValueOnce(first);
      const props = {
        baseline: { current: snapshot() }, zoneId: "A", language: "en",
        recoveryScope: "5:30", setZoneId: vi.fn(), saving: false,
        setSaving: vi.fn(), setShops: vi.fn(), setDirty: vi.fn(),
        setEditMode: vi.fn(), clearSelection: vi.fn(), send, read,
      };
      const initial = renderHook(
        ({ draft }: { draft: Shop[] }) => useShopOrderCommit({ ...props, draft }),
        { initialProps: { draft: first } },
      );
      await act(async () => { expect(await initial.result.current.save()).toBe(false); });
      expect(loadShopOrderRecovery("5:30")?.outcome).toBe("put_confirmed");
      initial.rerender({ draft: revised });
      await act(async () => { expect(await initial.result.current.save()).toBe(false); });
      expect(read).toHaveBeenCalledTimes(2);
      expect(send).toHaveBeenCalledTimes(2);
      expect(loadShopOrderRecovery("5:30")).toBeNull();
      expect(initial.result.current.needsReconciliation).toBe(false);
      expect(toast.success).not.toHaveBeenCalled();

      initial.unmount();
      const nextRead = vi.fn().mockResolvedValue(first);
      const subsequent = renderHook(() => useShopOrderCommit({
        ...props, draft: first, read: nextRead,
      }));
      expect(subsequent.result.current.needsReconciliation).toBe(false);
      expect(nextRead).not.toHaveBeenCalled(); // rejected request cannot resurrect
    },
  );

  it("a revised draft survives forced logout DURING the reconciliation GET, not only the first readback", async () => {
    const first = moveShopInSelectedZone(snapshot(), "A", "A3", 0);
    const revised = moveShopInSelectedZone(first, "A", "A3", 1);
    const send = vi.fn().mockResolvedValue({});
    const read = vi.fn()
      .mockRejectedValueOnce(new Error("lost first readback"))
      .mockRejectedValueOnce(Object.assign(new Error("GET forces logout"), { status: 401 }));
    const props = {
      baseline: { current: snapshot() }, zoneId: "A", language: "en",
      recoveryScope: "5:19", setZoneId: vi.fn(), saving: false,
      setSaving: vi.fn(), setShops: vi.fn(), setDirty: vi.fn(),
      setEditMode: vi.fn(), clearSelection: vi.fn(), send, read,
    };
    const initial = renderHook(
      ({ draft }: { draft: Shop[] }) => useShopOrderCommit({ ...props, draft }),
      { initialProps: { draft: first } },
    );
    await act(async () => { expect(await initial.result.current.save()).toBe(false); });
    expect(loadShopOrderRecoveryRecord("5:19")?.command.intended.map(x => x.sequence))
      .toEqual(first.filter(x => x.zoneId === "A").map(x => x.sequence));
    initial.rerender({ draft: revised });
    await act(async () => { expect(await initial.result.current.save()).toBe(false); });
    const saved = loadShopOrderRecoveryRecord("5:19");
    expect(saved?.command.outcome).toBe("put_confirmed");
    expect(saved?.command.intended.map(x => x.sequence))
      .toEqual(first.filter(x => x.zoneId === "A").map(x => x.sequence)); // immutable attempt
    expect(saved?.latestDraft.map(x => x.sequence))
      .toEqual(revised.filter(x => x.zoneId === "A").map(x => x.sequence)); // updated intent
    expect(send).toHaveBeenCalledOnce(); // failed GET must not submit revised payload
    initial.unmount();

    const recovered = { ...props, draft: snapshot(), setShops: vi.fn(),
      setZoneId: vi.fn(), setEditMode: vi.fn(), read: vi.fn().mockResolvedValue(first) };
    const nextSession = renderHook(() => useShopOrderCommit(recovered));
    await waitFor(() => expect(recovered.setShops).toHaveBeenCalledWith(revised));
    expect(nextSession.result.current.needsReconciliation).toBe(true);
    expect(send).toHaveBeenCalledOnce(); // restored, not replayed
    expect(toast.success).not.toHaveBeenCalled();
  });

  it("each uncertain keyboard reorder persists latest visual intent without rewriting original PUT evidence", () => {
    const first = moveShopInSelectedZone(snapshot(), "A", "A3", 0);
    const revised = moveShopInSelectedZone(first, "A", "A3", 1);
    const onlyRows = (rows: Shop[]) => rows.filter(x => x.zoneId === "A")
      .map(({ id, zoneId, sequence, archived }) => ({ id, zoneId, sequence, archived }));
    storeShopOrderRecovery("5:20", {
      zoneId: "A", outcome: "put_confirmed",
      before: onlyRows(snapshot()), intended: onlyRows(first),
    });
    const setShops = vi.fn(), setDirty = vi.fn();
    const props = { shops: first, zoneId: "A", baseline: { current: snapshot() },
      setShops, setDirty, saving: false, recoveryScope: "5:20", uncertain: true };
    const { result } = renderHook(() => useShopOrderDraft(props));
    act(() => result.current.changeSequence("A3", 2));
    expect(setShops).toHaveBeenCalledWith(revised);
    expect(loadShopOrderRecoveryRecord("5:20")?.latestDraft).toEqual(onlyRows(revised));
    expect(loadShopOrderRecoveryRecord("5:20")?.command.intended).toEqual(onlyRows(first));
  });

  it.each(["ar", "en"] as const)(
    "late prior-login GET in %s cannot recreate cleared recovery or overwrite a newer attempt",
    async language => {
      await setAppLanguage(language);
      const first = moveShopInSelectedZone(snapshot(), "A", "A3", 0);
      const revised = moveShopInSelectedZone(first, "A", "A3", 1);
      const scope = "71:32";
      let rejectOldRead: ((error: unknown) => void) | undefined;
      const oldRead = vi.fn().mockImplementation(() => new Promise<Shop[]>((_resolve, reject) => {
        rejectOldRead = reject;
      }));
      const firstSend = vi.fn().mockResolvedValue({});
      const oldProps = {
        draft: first, baseline: { current: snapshot() }, zoneId: "A", language,
        recoveryScope: scope, setZoneId: vi.fn(), saving: false,
        setSaving: vi.fn(), setShops: vi.fn(), setDirty: vi.fn(),
        setEditMode: vi.fn(), clearSelection: vi.fn(), send: firstSend, read: oldRead,
      };
      const oldSession = renderHook(() => useShopOrderCommit(oldProps));
      let oldSave: Promise<boolean> | undefined;
      await act(async () => {
        oldSave = oldSession.result.current.save();
        await Promise.resolve();
      });
      await waitFor(() => expect(oldRead).toHaveBeenCalledOnce());
      const originalRecord = loadShopOrderRecoveryRecord(scope);
      expect(originalRecord?.command.outcome).toBe("put_confirmed");
      expect(originalRecord?.command.attemptId).toBeTruthy();
      expect(firstSend).toHaveBeenCalledOnce();

      // The original fetch is STILL pending when the old DispatchSession unmounts.
      oldSession.unmount();
      const freshRead = vi.fn().mockResolvedValue(first);
      const replacementSend = vi.fn().mockRejectedValue(Object.assign(
        new Error("server response unknown"), { status: 500, requestId: "req-NEW-attempt" },
      ));
      const newProps = {
        ...oldProps, draft: snapshot(), setZoneId: vi.fn(), setShops: vi.fn(),
        setDirty: vi.fn(), setEditMode: vi.fn(), setSaving: vi.fn(),
        read: freshRead, send: replacementSend,
      };
      const active = renderHook(
        ({ draft }: { draft: Shop[] }) => useShopOrderCommit({ ...newProps, draft }),
        { initialProps: { draft: snapshot() } },
      );
      await waitFor(() => expect(newProps.setShops).toHaveBeenCalledWith(first));
      expect(active.result.current.needsReconciliation).toBe(true);
      expect(replacementSend).not.toHaveBeenCalled();

      // New session resolves the confirmed earlier write. In one case it
      // clears old recovery; in the other it creates a NEW pending command.
      const replaceWithNewCommand = language === "en";
      active.rerender({ draft: replaceWithNewCommand ? revised : first });
      await act(async () => {
        expect(await active.result.current.save()).toBe(!replaceWithNewCommand);
      });
      const latestBeforeOldResponse = loadShopOrderRecoveryRecord(scope);
      if (replaceWithNewCommand) {
        expect(replacementSend).toHaveBeenCalledOnce();
        expect(latestBeforeOldResponse?.command.outcome).toBe("transport_unknown");
        expect(latestBeforeOldResponse?.command.attemptId)
          .not.toBe(originalRecord?.command.attemptId);
        expect(latestBeforeOldResponse?.latestDraft.map(x => x.sequence))
          .toEqual(revised.filter(s => s.zoneId === "A").map(s => s.sequence));
      } else {
        expect(latestBeforeOldResponse).toBeNull();
        expect(replacementSend).not.toHaveBeenCalled();
      }
      const newSessionShopsCount = newProps.setShops.mock.calls.length;
      const newSessionDirtyCount = newProps.setDirty.mock.calls.length;

      // useAuthFetch rejects the obsolete 401 AFTER new session's work.
      await act(async () => {
        rejectOldRead?.(Object.assign(new Error("obsolete old session GET"), {
          status: 401, code: "SESSION_EXPIRED", requestId: "req-OLD-attempt",
        }));
        expect(await oldSave).toBe(false);
      });
      expect(loadShopOrderRecoveryRecord(scope)).toEqual(latestBeforeOldResponse);
      expect(newProps.setShops).toHaveBeenCalledTimes(newSessionShopsCount);
      expect(newProps.setDirty).toHaveBeenCalledTimes(newSessionDirtyCount);
      expect(firstSend).toHaveBeenCalledOnce(); // no auto-replay of old PUT
      expect(toast.success).not.toHaveBeenCalled();
    },
  );

  it("attempt-owned metadata updates preserve newer visual intent and never revive or erase a replaced command", () => {
    const first = moveShopInSelectedZone(snapshot(), "A", "A3", 0);
    const revised = moveShopInSelectedZone(first, "A", "A3", 1);
    const rows = (shops: Shop[]) => shops.filter(s => s.zoneId === "A")
      .map(({ id, zoneId, sequence, archived }) => ({ id, zoneId, sequence, archived }));
    const scope = "71:33";
    const attempt = {
      attemptId: "prior-generation", zoneId: "A", outcome: "transport_unknown" as const,
      before: rows(snapshot()), intended: rows(first),
    };
    storeShopOrderRecovery(scope, attempt);
    stageShopOrderRecoveryDraft(scope, revised, attempt.attemptId);
    expect(updateShopOrderRecoveryIfAttempt(scope, {
      ...attempt, outcome: "put_confirmed", requestId: "req-prior",
    })).toBe(true);
    expect(loadShopOrderRecoveryRecord(scope)?.latestDraft).toEqual(rows(revised));
    expect(loadShopOrderRecoveryRecord(scope)?.command.outcome).toBe("put_confirmed");
    expect(updateShopOrderRecoveryIfAttempt(scope, attempt)).toBe(false);
    expect(loadShopOrderRecoveryRecord(scope)?.command.outcome).toBe("put_confirmed");
    expect(clearShopOrderRecoveryIfAttempt(scope, "wrong-generation")).toBe(false);
    expect(clearShopOrderRecoveryIfAttempt(scope, attempt.attemptId)).toBe(true);
    expect(updateShopOrderRecoveryIfAttempt(scope, attempt)).toBe(false);
    expect(loadShopOrderRecoveryRecord(scope)).toBeNull();

    storeShopOrderRecovery(scope, { ...attempt, attemptId: "new-generation", intended: rows(revised) });
    expect(updateShopOrderRecoveryIfAttempt(scope, attempt)).toBe(false);
    expect(clearShopOrderRecoveryIfAttempt(scope, attempt.attemptId)).toBe(false);
    expect(loadShopOrderRecoveryRecord(scope)?.command.attemptId).toBe("new-generation");
    expect(loadShopOrderRecoveryRecord(scope)?.latestDraft).toEqual(rows(revised));
  });

  it("stores only selected-zone identifiers, ranks and archive flags, with no customer or authentication data", () => {
    const command = {
      zoneId: "A", outcome: "put_confirmed" as const,
      before: snapshot().filter(s => s.zoneId === "A"),
      intended: moveShopInSelectedZone(snapshot(), "A", "A3", 0).filter(s => s.zoneId === "A"),
    };
    storeShopOrderRecovery("2:44", {
      ...command,
      before: command.before.map(({ id, zoneId, sequence, archived }) => ({ id, zoneId, sequence, archived })),
      intended: command.intended.map(({ id, zoneId, sequence, archived }) => ({ id, zoneId, sequence, archived })),
    });
    const raw = sessionStorage.getItem("wanasah:dispatch:shop-order-recovery:v1:2:44") || "";
    expect(raw).not.toContain("Owner");
    expect(raw).not.toContain("Shop A1");
    expect(raw).toContain("put_confirmed");
    expect(loadShopOrderRecovery("2:44")?.zoneId).toBe("A");
  });

  it("hook confirms saved order ONLY on matching authorized readback and permits clean cancel", async () => {
    const draft = moveShopInSelectedZone(snapshot(), "A", "A3", 0);
    const send = vi.fn().mockResolvedValue({ message: "OK" });
    const read = vi.fn().mockResolvedValue(draft);
    const props = {
      draft, baseline: { current: snapshot() }, zoneId: "A",
      language: "ar", saving: false, setSaving: vi.fn(),
      setShops: vi.fn(), setDirty: vi.fn(), setEditMode: vi.fn(),
      clearSelection: vi.fn(), send, read,
    };
    const { result } = renderHook(() => useShopOrderCommit(props));
    await act(async () => { expect(await result.current.save()).toBe(true); });
    expect(toast.success).toHaveBeenCalledOnce();
    expect(props.setShops).toHaveBeenCalledWith(draft);
    expect(props.baseline.current).toBe(draft);
    expect(props.setDirty).toHaveBeenCalledWith(false);
  });
});
