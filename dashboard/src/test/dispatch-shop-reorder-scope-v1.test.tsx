import { useState, type ReactNode } from "react";
import { act, fireEvent, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { setAppLanguage } from "@/i18n";
import type { Shop, Zone } from "@/types/dispatch";
import { ShopTable } from "@/components/dispatch/ShopTable";
import { ShopOrderScopeNotice } from "@/features/dispatch/shopOrder/ShopOrderScopeNotice";
import { shopOrderText } from "@/features/dispatch/shopOrder/messages";
import {
  buildShopOrderChanges, canReorderShop, hasShopOrderChanges, moveShopBeforeInSelectedZone,
  moveShopInSelectedZone, verifyShopOrderReadback,
} from "@/features/dispatch/shopOrder/scope";
import { commitShopOrder, ShopOrderVerificationError } from "@/features/dispatch/shopOrder/persist";
import { useShopOrderCommit } from "@/features/dispatch/shopOrder/useShopOrderCommit";

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

  it.each([403, 409, 500])("a rejected HTTP %s retains unsaved state, does not read/announce success", async status => {
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
