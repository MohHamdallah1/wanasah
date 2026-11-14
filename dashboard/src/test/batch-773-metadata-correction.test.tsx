import {afterEach,beforeEach,describe,expect,it,vi} from "vitest";
import {cleanup,fireEvent,render,screen,waitFor} from "@testing-library/react";
import {BatchMetadataCorrectionPanel,batchCorrectionText} from
  "@/pages/inventory/batches/BatchMetadataCorrectionPanel";

const st=vi.hoisted(()=>({lang:"ar",fetch:vi.fn()}));
vi.mock("react-i18next",()=>({
  useTranslation:()=>({i18n:{language:st.lang,dir:()=>st.lang==="ar"?"rtl":"ltr"}}),
}));
vi.mock("@/hooks/useAuthFetch",()=>({useAuthFetch:()=>st.fetch}));

const present={
  batch_id:12,location_id:8,metadata_revision:1,
  eligible:true,block_code:null,source_invoice:"REAL-2026-128",
  current:{batch_number:"MISTAKEN-LOT",production_date:"2026-01-01",expiry_date:"2027-06-30"},
  disposition:"QUARANTINED",
};
const past={
  revision:2,verified_at:"2026-11-14T12:00:00Z",actor_username:"manager",
  source_invoice:"REAL-2026-128",reason:"Correct printed receipt label",
  before:{batch_number:"MISTAKEN-LOT",production_date:"2026-01-01",expiry_date:"2027-06-30"},
  after:{batch_number:"PRINTED-LOT",production_date:"2026-01-01",expiry_date:"2027-10-30"},
};
beforeEach(()=>{st.fetch.mockReset();st.lang="ar";});
afterEach(()=>cleanup());

describe("B773 approved narrow AR/EN RTL/LTR current Lot correction",()=>{
  for(const [lang,dir] of [["ar","rtl"],["en","ltr"]] as const){
    it("shows server-eligible edit, true invoice, password, consent and append-only history in "+lang,async()=>{
      st.lang=lang;
      st.fetch.mockImplementation(async(path:string)=>{
        if(path.includes("/metadata-corrections/history"))return {items:[past]};
        if(path.includes("/metadata-correction"))return present;
        throw Error("unknown "+path);
      });
      render(<BatchMetadataCorrectionPanel batchId={12} locationId={8} onChanged={vi.fn()}/>);
      const text=batchCorrectionText(lang);
      const button=await screen.findByRole("button",{name:text.edit});
      const panel=button.closest("section");
      expect(panel?.getAttribute("dir")).toBe(dir);
      fireEvent.click(button);
      expect(screen.getAllByText(/REAL-2026-128/).length).toBeGreaterThan(0);
      expect(screen.getByLabelText(text.lot)).toBeTruthy();
      expect((screen.getByLabelText(text.password) as HTMLInputElement).type).toBe("password");
      const save=screen.getByRole("button",{name:text.save}) as HTMLButtonElement;
      expect(save.disabled).toBe(true);
      fireEvent.change(screen.getByLabelText(text.lot),{target:{value:"PRINTED-LOT"}});
      fireEvent.change(screen.getByLabelText(text.reason),{target:{value:"Genuine printed batch correction"}});
      fireEvent.change(screen.getByLabelText(text.password),{target:{value:"SyntheticTestManagerPass"}});
      fireEvent.click(screen.getByRole("checkbox"));
      expect(save.disabled).toBe(false);
      fireEvent.click(screen.getByText(/Correction history|سجل التصحيحات/));
      expect(screen.getAllByText(/PRINTED-LOT/).length).toBeGreaterThan(0);
    });
  }
  it("submits exactly one typed command with signed manager password and fresh UUID",async()=>{
    st.lang="en";
    let posted:Record<string,unknown>|null=null;
    st.fetch.mockImplementation(async(path:string,init?:RequestInit)=>{
      if(init?.method==="POST"){
        expect(path).toBe("/warehouse/batches/12/metadata-correction");
        posted=JSON.parse(String(init.body)) as Record<string,unknown>;
        return {batch_id:12,metadata_revision:2,disposition:present.disposition,
          source_invoice:present.source_invoice,
          current:{...present.current,batch_number:"CORRECT-REAL"}};
      }
      return path.includes("/history")?{items:[]} : present;
    });
    const onChanged=vi.fn();
    render(<BatchMetadataCorrectionPanel batchId={12} locationId={8} onChanged={onChanged}/>);
    fireEvent.click(await screen.findByRole("button",{name:"Correct Lot / expiry"}));
    fireEvent.change(screen.getByLabelText("Actual printed Lot"),{target:{value:"CORRECT-REAL"}});
    fireEvent.change(screen.getByLabelText("Correction reason"),{target:{value:"Actual physical carton label verified"}});
    fireEvent.change(screen.getByLabelText("Current manager account password"),{
      target:{value:"SyntheticBackendPassword"},
    });
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button",{name:"Save correction"}));
    await waitFor(()=>expect(onChanged).toHaveBeenCalledTimes(1));
    expect(st.fetch.mock.calls.filter(call=>call[1]?.method==="POST")).toHaveLength(1);
    expect(posted).toMatchObject({
      location_id:8,expected_revision:1,batch_number:"CORRECT-REAL",
      production_date:"2026-01-01",expiry_date:"2027-06-30",
      reason:"Actual physical carton label verified",password:"SyntheticBackendPassword",
    });
    expect(String(posted?.request_id)).toMatch(/^[0-9a-f-]{36}$/);
    expect(screen.queryByLabelText("Current manager account password")).toBeNull();
  });
  it("hides edit when server rejects shared receipt history",async()=>{
    st.fetch.mockImplementation(async(path:string)=>path.includes("/history")?
      {items:[]}:{...present,eligible:false,block_code:"BATCH_USED_OR_SHARED_RECEIPT"});
    render(<BatchMetadataCorrectionPanel batchId={12} locationId={8} onChanged={vi.fn()}/>);
    await waitFor(()=>expect(screen.getByText(/BATCH_USED_OR_SHARED_RECEIPT/)).toBeTruthy());
    expect(screen.queryByRole("button",{name:batchCorrectionText("ar").edit})).toBeNull();
  });
});
