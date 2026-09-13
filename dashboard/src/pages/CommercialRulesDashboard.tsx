import {
  BadgePercent,
  FlaskConical,
  Gauge,
  Scale,
  ShieldCheck,
} from "lucide-react";

import CommercialRulesWorkspace from "@/features/commercialRules/CommercialRulesWorkspace";
import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import "@/components/operations/commercial-rules.css";

export default function CommercialRulesDashboard() {
  const access = useInventoryAccess();
  const canOffers = access.isCompanyAdmin || access.canAny("offers.view");
  const canTax = access.isCompanyAdmin || access.canAny("tax.view");

  if (!canOffers && !canTax) {
    return (
      <div className="commercial-rules-page" dir="rtl">
        <div className="commercial-rules-denied">
          <ShieldCheck className="h-9 w-9" />
          <h1>لا تملك صلاحية إدارة القواعد التجارية</h1>
          <p>الوصول لهذه الصفحة يتطلب offers.view أو tax.view.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="commercial-rules-page" dir="rtl">
      <header className="commercial-rules-hero">
        <div className="commercial-rules-hero__copy">
          <p className="commercial-rules-eyebrow">
            <Gauge className="h-4 w-4" />
            مركز القواعد التجارية
          </p>
          <h1>العروض والضرائب</h1>
          <p>
            إدارة النسخ التجارية المؤرخة والاعتماد والمعاينة، مع بقاء
            الحساب والقرار المالي بالكامل داخل السيرفر.
          </p>
        </div>

        <div className="commercial-rules-hero__signals">
          {canOffers ? (
            <div>
              <BadgePercent className="h-5 w-5" />
              <strong>العروض</strong>
              <small>Offer Engine</small>
            </div>
          ) : null}
          {canTax ? (
            <div>
              <Scale className="h-5 w-5" />
              <strong>الضرائب</strong>
              <small>Tax Rules</small>
            </div>
          ) : null}
          <div>
            <FlaskConical className="h-5 w-5" />
            <strong>المعاينة</strong>
            <small>Read only</small>
          </div>
        </div>
      </header>

      <CommercialRulesWorkspace />
    </div>
  );
}
