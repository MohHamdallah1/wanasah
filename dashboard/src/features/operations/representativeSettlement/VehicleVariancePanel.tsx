import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { apiErrorMessage } from "@/lib/apiErrors";
import type { SettlementAuthFetch } from "./api";
import {
  readVehicleRecount, readVehicleVariance, submitVehicleVariance,
  type SignedVehicleRecount, type SignedVehicleVariance,
} from "./vehicleCountCommand";

export function VehicleVariancePanel({
  authFetch, sessionId, vehicleId, onReviewed,
}: {
  authFetch: SettlementAuthFetch;
  sessionId: number;
  vehicleId: number;
  onReviewed: () => void;
}) {
  const { i18n } = useTranslation();
  const ar = i18n.language.startsWith("ar");
  const [review, setReview] = useState<SignedVehicleVariance | null>(null);
  const [count, setCount] = useState<SignedVehicleRecount | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [password, setPassword] = useState("");
  const [username, setUsername] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    setReview(null); setCount(null); setError("");
    void readVehicleVariance(authFetch, sessionId, vehicleId)
      .then(data => { if (active) setReview(data); })
      .catch(e => { if (active) setError(apiErrorMessage(e, "Signed review unavailable")); });
    return () => { active = false; };
  }, [authFetch, sessionId, vehicleId]);

  const execute = async (action: "approve" | "recount" | "count") => {
    if (busy || !review) return;
    setBusy(true); setError("");
    try {
      if (action === "approve") {
        if (!password || review.requires_independent_recount && !review.independent_recount_satisfied) {
          throw new Error("Independent recount or authorization required");
        }
        await submitVehicleVariance(authFetch, sessionId, vehicleId, "approve",
          { review_token: review.review_token, password, notes: null });
      } else if (action === "recount") {
        if (!username || !password || !reason.trim()) {
          throw new Error("Independent recount authorization is required");
        }
        await submitVehicleVariance(authFetch, sessionId, vehicleId, "recount", {
          review_token: review.review_token, reason: reason.trim(),
          authorizer_username: username, authorizer_password: password,
        });
      } else {
        if (!count || count.lines.some(x => !values[x.line_key]?.trim())) {
          throw new Error("Complete all independent recount quantities");
        }
        await submitVehicleVariance(authFetch, sessionId, vehicleId, "count", {
          count_token: count.count_token,
          items: count.lines.map(x => ({ line_key: x.line_key, actual_quantity: values[x.line_key] })),
          notes: null,
        });
      }
      setPassword(""); setUsername(""); setReason(""); setValues({});
      onReviewed(); // authoritative vehicle list and review refetch
      if (action === "recount") {
        const newCount = await readVehicleRecount(authFetch, sessionId, vehicleId);
        setCount(newCount);
      } else if (action === "count") {
        setCount(null);
        setReview(await readVehicleVariance(authFetch, sessionId, vehicleId));
      } else {
        setCount(null);
        setReview(null); // operator must re-open signed exact car sheet
      }
    } catch (e) {
      setError(apiErrorMessage(e, ar ? "تعذر إتمام مراجعة السيارة" : "Vehicle review was not completed"));
    } finally { setBusy(false); }
  };

  return <section className="space-y-3 rounded-lg border p-3" dir={i18n.dir()}
    data-testid="m05-m04-vehicle-variance">
    <h3 className="font-bold">{ar ? "مراجعة فروقات السيارة" : "Vehicle variance review"}</h3>
    {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
    {!review && !error && <p role="status">{ar ? "التحقق من المراجعة" : "Checking review"}</p>}
    {review && <>
      <p className="text-sm">{review.reconciliation_reference} · {review.status}</p>
      {review.lines.map((line, index) => <div key={index} className="grid grid-cols-2 gap-1 border-b py-1 text-xs sm:grid-cols-4">
        <span>{line.product_name} · {line.batch_number || "—"} · {line.stock_status}</span>
        <span>{ar ? "المتوقع" : "Expected"}: {line.expected_quantity}</span>
        <span>{ar ? "المعدود" : "Counted"}: {line.actual_quantity}</span>
        <span>{ar ? "الفرق" : "Variance"}: {line.variance_quantity}</span>
      </div>)}
      {count ? <>
        {count.lines.map(line => <label key={line.line_key} className="flex items-center justify-between gap-2 text-sm">
          <span>{line.product_name} · {line.stock_status} · {line.batch_number || "—"}</span>
          <input className="w-28 min-w-0 rounded border p-2" type="text" inputMode="decimal"
            aria-label={line.line_key} value={values[line.line_key] || ""}
            disabled={busy} onChange={e => setValues(old => ({ ...old, [line.line_key]: e.target.value }))}/>
        </label>)}
        <button type="button" disabled={busy} onClick={() => void execute("count")}
          className="rounded-lg border px-3 py-2">{ar ? "إرسال إعادة العد" : "Submit independent recount"}</button>
      </> : <>
        <input type="password" className="w-full rounded border p-2" value={password}
          onChange={e => setPassword(e.target.value)} autoComplete="off"
          placeholder={ar ? "كلمة مرور المعتمِد" : "Authorizer password"}/>
        <button type="button" disabled={busy || review.requires_independent_recount && !review.independent_recount_satisfied}
          onClick={() => void execute("approve")} className="rounded-lg border px-3 py-2">
          {ar ? "اعتماد الفروقات المسموح بها" : "Approve authorized variance"}
        </button>
        <div className="grid gap-2 sm:grid-cols-2">
          <input className="min-w-0 rounded border p-2" value={username} onChange={e => setUsername(e.target.value)}
            placeholder={ar ? "اسم المعتمِد المستقل" : "Independent authorizer"}/>
          <input className="min-w-0 rounded border p-2" value={reason} onChange={e => setReason(e.target.value)}
            placeholder={ar ? "سبب إعادة العد" : "Recount reason"}/>
        </div>
        <button type="button" disabled={busy} onClick={() => void execute("recount")}
          className="rounded-lg border px-3 py-2">{ar ? "طلب إعادة عد مستقلة" : "Request independent recount"}</button>
      </>}
    </>}
  </section>;
}
