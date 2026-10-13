import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Pencil, RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { updateRepresentative } from "./api";
import type { Representative, UpdateRepresentativeInput } from "./contracts";
import { RepresentativeCredentialAction } from "./RepresentativeCredentialAction";
import { representativeErrorMessage } from "./representativeErrorMessage";
import { RepresentativeForm } from "./RepresentativeForm";
import { RepresentativeLifecycleActions } from "./RepresentativeLifecycleActions";
import { useRepresentativeDetail } from "./useRepresentativeDetail";

interface RepresentativeDrawerProps {
  representative: Representative | null;
  open: boolean;
  canManage: boolean;
  canResetCredentials: boolean;
  onOpenChange: (open: boolean) => void;
}

export function RepresentativeDrawer({
  representative,
  open,
  canManage,
  canResetCredentials,
  onOpenChange,
}: RepresentativeDrawerProps) {
  const { t, i18n } = useTranslation();
  const authFetch = useAuthFetch();
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const detail = useRepresentativeDetail(representative?.id ?? null, open);

  if (!representative) return null;

  const current = detail.data;

  const stopEditing = () => {
    if (busy) return;
    setEditing(false);
  };

  const handleOpenChange = (next: boolean) => {
    if (!next) setEditing(false);
    onOpenChange(next);
  };

  const save = async (input: UpdateRepresentativeInput, requestId: string) => {
    if (!current) return;
    setBusy(true);
    try {
      const updated = await updateRepresentative(authFetch, current.id, input, requestId);
      queryClient.setQueryData(["representative-detail", current.id], updated);
      await queryClient.invalidateQueries({ queryKey: ["representatives"] });
      toast.success(t("representativesVehicles.representatives.updateSuccess"));
      setEditing(false);
      onOpenChange(false);
    } catch (error) {
      toast.error(
        representativeErrorMessage(
          error,
          t("representativesVehicles.representatives.saveFailed"),
        ),
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <Sheet open={open} onOpenChange={handleOpenChange}>
      <SheetContent side={i18n.dir() === "rtl" ? "right" : "left"} className="w-[min(94vw,430px)] overflow-y-auto border-slate-200 bg-white p-5 sm:max-w-[430px]">
        <SheetHeader className="pe-8 text-start">
          <SheetTitle className="text-lg font-black text-slate-900">{t("representativesVehicles.representatives.details")}</SheetTitle>
          <SheetDescription>{current?.full_name ?? representative.full_name}</SheetDescription>
        </SheetHeader>

        <div className="mt-5 space-y-4">
          {detail.isFetching && !current ? (
            <div role="status" className="space-y-3 rounded-2xl border border-slate-200 bg-white p-4">
              <p className="text-xs font-bold text-slate-500">{t("representativesVehicles.representatives.detailLoading")}</p>
              <div className="h-16 animate-pulse rounded-xl bg-slate-100" />
              <div className="h-24 animate-pulse rounded-xl bg-slate-100" />
            </div>
          ) : detail.isError || !current ? (
            <div role="alert" className="rounded-2xl border border-rose-200 bg-rose-50/70 p-4 text-center">
              <AlertTriangle className="mx-auto h-6 w-6 text-rose-500" />
              <p className="mt-2 text-sm font-bold text-rose-700">
                {representativeErrorMessage(
                  detail.error,
                  t("representativesVehicles.representatives.detailFailed"),
                )}
              </p>
              <button
                type="button"
                onClick={() => void detail.refetch()}
                className="mt-3 inline-flex h-9 items-center gap-2 rounded-xl bg-slate-900 px-3 text-xs font-black text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400"
              >
                <RefreshCw className="h-3.5 w-3.5" />
                {t("common.retry")}
              </button>
            </div>
          ) : editing ? (
            <RepresentativeForm
              representative={current}
              busy={busy}
              onCancel={stopEditing}
              onSubmit={(input, requestId) => save(input as UpdateRepresentativeInput, requestId)}
            />
          ) : (
            <>
              <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate text-base font-black text-slate-900">{current.full_name}</p>
                    <p className="mt-1 text-sm font-semibold text-slate-500" dir="ltr">{current.username}</p>
                  </div>
                  <span className={`rounded-full px-2.5 py-1 text-[11px] font-black ${current.is_active ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-600"}`}>
                    {t(current.is_active ? "representativesVehicles.representatives.active" : "representativesVehicles.representatives.inactive")}
                  </span>
                </div>
                <dl className="mt-4 grid gap-3 text-sm">
                  <div><dt className="text-[11px] font-black text-slate-400">{t("representativesVehicles.representatives.fields.phone")}</dt><dd className="mt-0.5 font-semibold text-slate-700" dir="ltr">{current.phone_number || "—"}</dd></div>
                  <div><dt className="text-[11px] font-black text-slate-400">{t("representativesVehicles.representatives.fields.debtPermission")}</dt><dd className="mt-0.5 font-semibold text-slate-700">{t(current.can_allow_debt ? "representativesVehicles.representatives.fields.enabled" : "representativesVehicles.representatives.fields.disabled")}</dd></div>
                  <div><dt className="text-[11px] font-black text-slate-400">{t("representativesVehicles.representatives.fields.debtLimit")}</dt><dd className="mt-0.5 font-semibold text-slate-700" dir="ltr">{current.max_debt_limit}</dd></div>
                </dl>
                <button
                  type="button"
                  onClick={() => setEditing(true)}
                  disabled={!canManage}
                  aria-describedby={!canManage ? "representative-edit-blocked" : undefined}
                  className="mt-4 inline-flex h-9 items-center gap-2 rounded-xl bg-slate-900 px-3 text-xs font-black text-white transition hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <Pencil className="h-3.5 w-3.5" />{t("representativesVehicles.representatives.edit")}
                </button>
                {!canManage ? (
                  <p id="representative-edit-blocked" className="mt-2 text-[11px] font-semibold text-slate-500">
                    {t("representativesVehicles.representatives.permissions.manageRequired")}
                  </p>
                ) : null}
              </div>
              <RepresentativeLifecycleActions
                representative={current}
                allowed={canManage}
                onChanged={() => onOpenChange(false)}
              />
              <RepresentativeCredentialAction
                representative={current}
                allowed={canResetCredentials}
              />
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
