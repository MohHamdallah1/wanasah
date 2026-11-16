import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setAppLanguage } from "@/i18n";
import type { Shop, Zone } from "@/types/dispatch";
import { ZoneListItem } from "@/features/dispatch/zones/ZoneListItem";
import { ZoneBulkSelectionBar } from "@/features/dispatch/zones/ZoneBulkSelectionBar";
import { zoneShopSelection } from "@/features/dispatch/zones/zoneShopSelection";
import { zoneText, daysFromFrequency, frequencyFromDays } from "@/features/dispatch/zones/zoneUi";
import { scheduleCommand, verifiedSchedule, verifiedZoneSave, zoneSaveFailureKind } from "@/features/dispatch/zones/zoneCommands";
import { ZoneModal } from "@/components/dispatch/ZoneModal";
import { ScheduleModal } from "@/components/dispatch/ScheduleModal";
import { ZoneRecycleBinModal } from "@/components/dispatch/ZoneRecycleBinModal";
import { ShopTable } from "@/components/dispatch/ShopTable";

vi.mock("@/features/tenantIdentity/useTenantIdentity", () => ({
  useTenantIdentity: () => ({ data: { company_id: 33, currency_code: "QAR" } }),
}));

const zone = (id: string, intervalDays: number | null = null, startDate = ""): Zone => ({
  id, name: "Zone " + id, scheduleStatus: "null", frequency: "",
  visitDay: "", startDate, intervalDays, shopsCount: 2,
});
const shop = (id: string, zoneId: string): Shop => ({
  id, zoneId, name: "Shop " + id, sequence: 1, owner: "Owner",
  phone: "", mapLink: "", archived: false, initialDebt: null, maxDebtLimit: null,
  financeRedacted: true,
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
beforeEach(async () => { await setAppLanguage("en"); });

describe("ZV1-F #1038 keyboard, global search, safe zones", () => {
  it("zone selector is a native focusable Enter/Space button with separate always-visible actions, AR/EN", async () => {
    const select=vi.fn(),edit=vi.fn(),schedule=vi.fn(),archive=vi.fn();
    const actions={ onSelect:select,onEdit:edit,onSchedule:schedule,onArchive:archive };
    const view=render(<ZoneListItem zone={zone("A")} language="en" selected disabled={false} canManage {...actions}/>);
    const selector=screen.getByRole("button",{name:"Select zone Zone A"});
    selector.focus();
    expect(selector).toHaveFocus();
    expect(selector).toHaveAttribute("aria-current","true");
    expect(selector).not.toContainElement(screen.getByRole("button",{name:"Edit Zone A"}));
    fireEvent.click(selector);
    expect(select).toHaveBeenCalledExactlyOnceWith("A");
    fireEvent.click(screen.getByRole("button",{name:"Schedule Zone A"}));
    fireEvent.click(screen.getByRole("button",{name:"Archive Zone A"}));
    expect(schedule).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({id:"A"}));
    expect(archive).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({id:"A"}));
    expect(edit).not.toHaveBeenCalled();
    expect(view.container.querySelectorAll("button")).toHaveLength(4);
    view.rerender(<ZoneListItem zone={zone("A")} language="ar" selected={false}
      disabled={false} canManage {...actions}/>);
    expect(screen.getByRole("button",{name:zoneText("ar","zoneArchive",{name:"Zone A"})})).toBeEnabled();
    expect(view.container.querySelector('button button')).toBeNull();
  });

  it("company-wide visible matches are not scoped to the zone, but bulk selection cannot include hidden/outside IDs", () => {
    const visible=[shop("A1","A"),shop("B1","B"),shop("A2","A")];
    const scope=zoneShopSelection(visible,["A1","B1","A2","HIDDEN"],"A");
    expect(visible.map(row=>row.zoneId)).toEqual(["A","B","A"]); // global search unchanged
    expect(scope.eligibleVisible.map(row=>row.id)).toEqual(["A1","A2"]);
    expect(scope.visibleSelectedIds).toEqual(["A1","A2"]);
    expect(scope.hiddenSelectedCount).toBe(2);
    expect(scope.blocked).toBe(true);
    expect(zoneShopSelection(visible,scope.visibleSelectedIds,"A").blocked).toBe(false);

    const onMove=vi.fn(),onArchive=vi.fn(),onKeepVisible=vi.fn();
    render(<ZoneBulkSelectionBar language="en" visibleSelected={2} totalSelected={4}
      visibleRows={3} eligibleVisibleRows={2} hiddenSelected={2}
      draftBlocked={false} draftReason="" onMove={onMove} onArchive={onArchive}
      onKeepVisible={onKeepVisible} onClear={vi.fn()}/>);
    expect(screen.getByText(/2 visible selected of 4/)).toBeInTheDocument();
    expect(screen.getByRole("button",{name:"Move selected"})).toBeDisabled();
    expect(screen.getByRole("button",{name:"Archive selected"})).toBeDisabled();
    fireEvent.click(screen.getByRole("button",{name:"Keep visible only"}));
    expect(onKeepVisible).toHaveBeenCalledOnce();
    expect(onMove).not.toHaveBeenCalled();
  });

  it("ShopTable global search still shows Zone B while Zone A selected; outside-zone checkbox disabled", () => {
    const edit=vi.fn(),archive=vi.fn(),toggle=vi.fn();
    render(<ShopTable shops={[shop("A1","A"),shop("B1","B")]}
      zones={[zone("A"),zone("B")]} isEditMode isSaving={false} language="en"
      selectedShopIds={["A1"]} allFilteredShops={[shop("A1","A"),shop("B1","B")]}
      selectedZoneIdForZones="A" onToggleSelectAll={vi.fn()}
      onToggleSelectShop={toggle} onSequenceChange={vi.fn()} onEditShop={edit}
      onArchiveShop={archive} onDragStart={vi.fn()} onDrop={vi.fn()}/>);
    expect(screen.getByText("Shop B1")).toBeInTheDocument();
    expect(screen.getAllByText("Zone B").length).toBeGreaterThan(0);
    const bSelect=screen.getByRole("checkbox",{name:"Select shop Shop B1"});
    expect(bSelect).toBeDisabled();
    fireEvent.click(bSelect);
    expect(toggle).not.toHaveBeenCalled();
    expect(screen.getByRole("checkbox",{name:"Select shop Shop A1"})).toBeEnabled();
    expect(screen.getByRole("checkbox",{name:"Select visible shops in current zone only"})).toBeChecked();
  });

  it("real zone Save draft stays present on uncertain result and only Verify is available; busy blocks duplicate submit", () => {
    const save=vi.fn(),verify=vi.fn();
    const props={isOpen:true,onClose:vi.fn(),editingZoneId:null,zoneFormName:"West",
      onZoneFormNameChange:vi.fn(),onSave:save,onVerify:verify,busy:false,uncertain:true};
    const view=render(<ZoneModal {...props}/>);
    expect(screen.getByRole("textbox",{name:"Zone name"})).toHaveValue("West");
    expect(screen.getByRole("textbox",{name:"Zone name"})).toBeDisabled();
    expect(screen.queryByRole("button",{name:"Save zone"})).toBeNull();
    expect(screen.getByRole("alert")).toHaveTextContent("Save outcome is uncertain");
    fireEvent.click(screen.getByRole("button",{name:"Verify save"}));
    expect(verify).toHaveBeenCalledOnce();
    expect(save).not.toHaveBeenCalled();
    view.rerender(<ZoneModal {...props} busy uncertain={false}/>);
    expect(screen.getByRole("button",{name:"Saving zone..."})).toBeDisabled();
    expect(screen.getByRole("textbox",{name:"Zone name"})).toHaveValue("West");
  });

  it("original create/edit readback requires exact zone identity and does not claim false success on an old matching name", () => {
    const existing=[zone("3"),zone("4")];
    expect(verifiedZoneSave(existing,{name:"Zone 3",editingId:null,initialIds:["3"],responseId:null})).toBeUndefined();
    expect(verifiedZoneSave(existing,{name:"Zone 3",editingId:null,initialIds:[],responseId:"3"})?.id).toBe("3");
    expect(verifiedZoneSave(existing,{name:"Zone 3",editingId:"4",initialIds:[],responseId:null})).toBeUndefined();
    expect(verifiedZoneSave(existing,{name:"Zone 3",editingId:"3",initialIds:[],responseId:null})?.id).toBe("3");
  });

  it("maps duplicate 409 to a rejected name and lost-response timeout to read-only verification, not automatic resubmit", () => {
    expect(zoneSaveFailureKind({status:409,code:"ZONE_EXISTS"})).toBe("duplicate");
    expect(zoneSaveFailureKind({status:0,code:"NETWORK_UNAVAILABLE"})).toBe("uncertain");
    expect(zoneSaveFailureKind({status:408,code:"REQUEST_TIMEOUT"})).toBe("uncertain");
    expect(zoneSaveFailureKind({status:503})).toBe("uncertain");
    expect(zoneSaveFailureKind({status:403})).toBe("rejected");
  });

  it("schedule contract uses numeric locale-independent values, clearSchedule only; verifies partial/missing readback", () => {
    expect(frequencyFromDays(10)).toBe("custom");
    expect(daysFromFrequency("custom",10)).toBe(10);
    expect(daysFromFrequency("custom",0)).toBeNull();
    expect(scheduleCommand("clear",null,"")).toEqual({clearSchedule:true});
    expect(scheduleCommand("update",10,"2026-12-01")).toEqual({
      intervalDays:10,startDate:"2026-12-01",
    });
    expect(verifiedSchedule(zone("3",10,"2026-12-01"),"update",10,"2026-12-01")).toBe(true);
    expect(verifiedSchedule(zone("3",7,"2026-12-01"),"update",10,"2026-12-01")).toBe(false);
    expect(verifiedSchedule(zone("3"),"clear",null,"")).toBe(true);
    expect(verifiedSchedule(undefined,"clear",null,"")).toBe(false);
  });

  it("localized Schedule modal clears existing schedule, keeps failure names visible, and supports custom days", async () => {
    const clear=vi.fn(),update=vi.fn(),change=vi.fn();
    const props={
      isOpen:true,onClose:vi.fn(),schedulingType:"local" as const,
      zones:[zone("A",7,"2026-12-01")],selectedZoneIdForZones:"A",
      bulkZoneSearch:"",onBulkZoneSearchChange:vi.fn(),selectedBulkZoneIds:[],
      onToggleBulkZoneSelection:vi.fn(),onToggleAllBulkZones:vi.fn(),
      schedulingForm:{frequency:"7",startDate:"2026-12-01"},
      onSchedulingFormChange:change,customDays:10,onCustomDaysChange:vi.fn(),
      onUpdateScheduling:update,onClearScheduling:clear,busy:false,
      feedback:"Succeeded: Zone A. Failed: Zone B. Verify results, then retry failed zones only.",
    };
    const view=render(<ScheduleModal {...props}/>);
    expect(screen.getByRole("status")).toHaveTextContent("Zone B");
    fireEvent.click(screen.getByRole("button",{name:"Clear existing schedule"}));
    expect(clear).toHaveBeenCalledOnce();
    fireEvent.change(screen.getByRole("combobox",{name:"Visit frequency"}),{
      target:{value:"custom"},
    });
    expect(change).toHaveBeenCalledWith({frequency:"custom",startDate:"2026-12-01"});
    view.rerender(<ScheduleModal {...props} busy/>);
    expect(screen.getByRole("button",{name:"Clear existing schedule"})).toBeDisabled();
    expect(screen.getByRole("button",{name:"Saving schedule..."})).toBeDisabled();
  });

  it("archive and restore explain that cancelled pending visits do not return; restoration is explicit", async () => {
    expect(zoneText("en","zoneArchiveWarning")).toContain("cancelled visits");
    const restore=vi.fn();
    render(<ZoneRecycleBinModal isOpen onClose={vi.fn()} recycleSearchQuery=""
      onRecycleSearchQueryChange={vi.fn()} filteredRecycleBin={[zone("A")]}
      onRestoreZone={restore}/>);
    expect(screen.getByText(/does not restore pending visits/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button",{name:"Restore zone Zone A"}));
    expect(restore).toHaveBeenCalledExactlyOnceWith("A");
  });
});
