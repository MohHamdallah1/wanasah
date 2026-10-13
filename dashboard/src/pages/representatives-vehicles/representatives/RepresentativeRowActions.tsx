import { KeyRound, MoreHorizontal, Pencil, Power, PowerOff } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { Representative } from "./contracts";

interface RepresentativeRowActionsProps {
  representative: Representative;
  canManage: boolean;
  canResetCredentials: boolean;
  onEdit: (representative: Representative) => void;
  onLifecycle: (representative: Representative) => void;
  onResetCredentials: (representative: Representative) => void;
}

export function RepresentativeRowActions({
  representative,
  canManage,
  canResetCredentials,
  onEdit,
  onLifecycle,
  onResetCredentials,
}: RepresentativeRowActionsProps) {
  const { t, i18n } = useTranslation();
  const direction = i18n.dir();
  const manageDescriptionId = `representative-manage-action-${representative.id}`;
  const credentialsDescriptionId = `representative-credentials-action-${representative.id}`;
  const manageBlocked = t("representativesVehicles.representatives.permissions.manageRequired");
  const credentialsBlocked = t("representativesVehicles.representatives.permissions.credentialsRequired");

  return (
    <DropdownMenu dir={direction} modal={false}>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label={t("representativesVehicles.representatives.actionsMenu", {
            name: representative.full_name,
          })}
          className="inline-grid h-9 w-9 place-items-center rounded-xl text-slate-500 transition hover:bg-white hover:text-slate-900 hover:shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400"
        >
          <MoreHorizontal className="h-4 w-4" aria-hidden="true" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="end"
        sideOffset={6}
        collisionPadding={8}
        className="w-56 rounded-xl border-slate-200 bg-white p-1.5 shadow-xl"
      >
        <DropdownMenuItem
          disabled={!canManage}
          aria-describedby={!canManage ? manageDescriptionId : undefined}
          title={!canManage ? manageBlocked : undefined}
          onSelect={() => onEdit(representative)}
          className="gap-2 rounded-lg px-2.5 py-2 text-xs font-black text-slate-700"
        >
          <Pencil className="h-4 w-4" aria-hidden="true" />
          {t("representativesVehicles.representatives.edit")}
        </DropdownMenuItem>
        <DropdownMenuItem
          disabled={!canManage}
          aria-describedby={!canManage ? manageDescriptionId : undefined}
          title={!canManage ? manageBlocked : undefined}
          onSelect={() => onLifecycle(representative)}
          className={`gap-2 rounded-lg px-2.5 py-2 text-xs font-black ${
            representative.is_active
              ? "text-rose-700 focus:bg-rose-50 focus:text-rose-800"
              : "text-emerald-700 focus:bg-emerald-50 focus:text-emerald-800"
          }`}
        >
          {representative.is_active ? (
            <PowerOff className="h-4 w-4" aria-hidden="true" />
          ) : (
            <Power className="h-4 w-4" aria-hidden="true" />
          )}
          {t(
            representative.is_active
              ? "representativesVehicles.representatives.lifecycle.deactivate"
              : "representativesVehicles.representatives.lifecycle.reactivate",
          )}
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          disabled={!canResetCredentials}
          aria-describedby={!canResetCredentials ? credentialsDescriptionId : undefined}
          title={!canResetCredentials ? credentialsBlocked : undefined}
          onSelect={() => onResetCredentials(representative)}
          className="gap-2 rounded-lg px-2.5 py-2 text-xs font-black text-slate-700"
        >
          <KeyRound className="h-4 w-4" aria-hidden="true" />
          {t("representativesVehicles.representatives.credentials.reset")}
        </DropdownMenuItem>
        <span id={manageDescriptionId} className="sr-only">{manageBlocked}</span>
        <span id={credentialsDescriptionId} className="sr-only">{credentialsBlocked}</span>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
