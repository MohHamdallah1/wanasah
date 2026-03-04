import { CheckCircle } from "lucide-react";
import type { Driver } from "@/data/dashboard-data";

interface HeroSettlementProps {
  driver: Driver;
}

export function HeroSettlement({ driver }: HeroSettlementProps) {
  return (
    <div className="bg-primary rounded-3xl shadow-card p-6 md:p-8 flex flex-col gap-5 animate-scale-in">
      {/* Driver info */}
      <div className="flex items-center gap-3">
        <div className="w-12 h-12 rounded-full bg-nav-dark text-nav-dark-foreground flex items-center justify-center font-bold text-sm">
          {driver.avatar}
        </div>
        <div>
          <p className="text-base font-bold text-primary-foreground">{driver.name}</p>
          <p className="text-xs text-primary-foreground/60">{driver.route} • {driver.status}</p>
        </div>
      </div>

      {/* Financial breakdown */}
      <div className="flex flex-col gap-1">
        <div className="flex justify-between text-sm text-primary-foreground/80">
          <span>Cash from Sales</span>
          <span className="font-semibold">{driver.cashFromSales.toFixed(2)} JOD</span>
        </div>
        <div className="flex justify-between text-sm text-primary-foreground/80">
          <span>Cash from Debts</span>
          <span className="font-semibold">{driver.cashFromDebts.toFixed(2)} JOD</span>
        </div>
        <div className="h-px bg-primary-foreground/15 my-2" />
        <p className="text-xs font-medium text-primary-foreground/50 uppercase tracking-wider">Total Expected in Hand</p>
        <p className="text-4xl md:text-5xl font-bold text-primary-foreground leading-tight">
          {driver.totalCash.toFixed(2)} <span className="text-xl font-semibold">JOD</span>
        </p>
      </div>

      {/* Inventory */}
      <div className="bg-nav-dark/10 rounded-2xl px-4 py-3">
        <p className="text-xs text-primary-foreground/60 uppercase tracking-wider mb-1">Inventory</p>
        <p className="text-sm font-semibold text-primary-foreground">
          Started: {driver.startedCartons} &nbsp;|&nbsp; Sold: {driver.soldCartons} &nbsp;|&nbsp; Remaining: {driver.remainingCartons}
        </p>
      </div>

      {/* Action */}
      <button className="w-full flex items-center justify-center gap-2 bg-nav-dark text-nav-dark-foreground rounded-full px-8 py-4 text-sm font-bold hover:opacity-90 transition-opacity shadow-card">
        <CheckCircle className="w-5 h-5" />
        Approve Settlement & Close Session
      </button>
    </div>
  );
}
