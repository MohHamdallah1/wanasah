import { useEffect, useState } from "react";
import { BadgePercent, CheckCircle2, FlaskConical, Scale } from "lucide-react";
import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import OfferManagement from "./OfferManagement";
import TaxManagement from "./TaxManagement";
import PreviewLab from "./PreviewLab";

type Tab = "offers" | "tax" | "preview";
export default function CommercialRulesWorkspace() {
  const access = useInventoryAccess(); const canOffers = access.isCompanyAdmin || access.canAny("offers.view"); const canTax = access.isCompanyAdmin || access.canAny("tax.view"); const [tab, setTab] = useState<Tab>(canOffers ? "offers" : "tax");
  useEffect(() => { if (tab === "offers" && !canOffers && canTax) setTab("tax"); if (tab === "tax" && !canTax && canOffers) setTab("offers"); }, [canOffers, canTax, tab]);
  const tabs = [...(canOffers ? [{ id: "offers" as const, label: "العروض", icon: BadgePercent }] : []), ...(canTax ? [{ id: "tax" as const, label: "الضرائب", icon: Scale }] : []), { id: "preview" as const, label: "Preview Lab", icon: FlaskConical }];
  return <div className="commercial-rules-workspace"><div className="commercial-rules-tabs-shell"><div className="commercial-rules-tabs">{tabs.map((item) => <button key={item.id} onClick={() => setTab(item.id)} className={tab === item.id ? "commercial-rules-tab commercial-rules-tab--active" : "commercial-rules-tab"}><item.icon className="h-4 w-4" />{item.label}</button>)}</div><div className="commercial-rules-authority-note"><CheckCircle2 className="h-4 w-4" />القرار التجاري والحساب من السيرفر</div></div>{tab === "offers" && canOffers ? <OfferManagement /> : null}{tab === "tax" && canTax ? <TaxManagement /> : null}{tab === "preview" ? <PreviewLab canOffers={canOffers} canTax={canTax} /> : null}</div>;
}
