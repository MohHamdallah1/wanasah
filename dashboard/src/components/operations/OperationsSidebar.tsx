import { Radar, Truck, Package, FileText, Settings, AlertTriangle, X } from "lucide-react";
import { systemAlerts } from "@/data/operations-data";
import { toast } from "sonner";
import { useNavigate, useLocation } from "react-router-dom";

interface OperationsSidebarProps {
  open: boolean;
  onClose: () => void;
}

const navItems = [
  { label: "الصفحة الرئيسية", icon: Radar, path: "/" },//غرفة العمليات الشاشة الرئيسية لمراقبة النشاط الحالي
  { label: "التوزيع والمناطق", icon: Truck, path: "/dispatch" },//إدارة التوزيع التحكم في حركة المناديب والسيارات
  { label: "المخزون والعروض", icon: Package, path: "/inventory" },//المخزون والعروض جرد المنتجات وإدارة العروض الترويجية
  { label: "الأرشيف والتقارير", icon: FileText, path: "/reports" },//الأرشيف والتقارير عرض السجلات التاريخية والتقارير التفصيلية
  { label: "الإعدادات", icon: Settings, path: "/settings" },//الإعدادات
];

const alertColors = {
  warning: "text-warning",
  danger: "text-destructive",
  info: "text-info",
};

export function OperationsSidebar({ open, onClose }: OperationsSidebarProps) {
  const navigate = useNavigate();
  const location = useLocation();

  const handleNav = (item: typeof navItems[0]) => {
    if (item.path === "/" || item.path === "/dispatch") {
      navigate(item.path);
    } else {
      toast("قريباً", {
        description: `صفحة "${item.label}" قيد التطوير`,
        duration: 2000,
      });
    }
  };

  return (
    <>
      {open && (
        <div className="fixed inset-0 z-40 bg-foreground/20 backdrop-blur-sm lg:hidden" onClick={onClose} />
      )}

      <aside
        className={`
          fixed inset-y-0 end-0 z-50 w-[280px] glass-sidebar p-5 flex flex-col gap-4 transition-transform duration-300
          lg:static lg:translate-x-0 lg:rounded-2xl lg:border lg:z-auto
          ${open ? "translate-x-0" : "translate-x-full lg:translate-x-0"}
        `}
      >
        {/* Logo */}
        <div className="flex items-center justify-between mb-1">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-primary to-warning flex items-center justify-center shadow-command">
              <Truck className="w-5 h-5 text-primary-foreground" strokeWidth={1.5} />
            </div>
            <span className="text-lg font-extrabold text-foreground tracking-tight">وناسة أدمن</span>
          </div>
          <button onClick={onClose} className="lg:hidden w-8 h-8 rounded-full bg-muted flex items-center justify-center">
            <X className="w-4 h-4 text-muted-foreground" />
          </button>
        </div>

        {/* Nav */}
        <nav className="flex flex-col gap-1">
          {navItems.map((item) => (
            <button
              key={item.label}
              onClick={() => handleNav(item)}
              className={`flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-medium transition-all duration-200 ${location.pathname === item.path
                ? "bg-primary/15 text-primary-foreground font-bold shadow-sm"
                : "text-muted-foreground hover:bg-white/60 hover:text-foreground"
                }`}
            >
              <item.icon className="w-[18px] h-[18px]" strokeWidth={1.5} />
              {item.label}
            </button>
          ))}
        </nav>

        {/* Alerts - pushed to bottom */}
        <div className="mt-auto">
          <div className="rounded-xl border border-destructive/30 bg-white/30 backdrop-blur-md p-4 pulse-border-red">
            <div className="flex items-center gap-2 mb-3">
              <AlertTriangle className="w-4 h-4 text-destructive" strokeWidth={1.5} />
              <span className="text-xs font-bold text-foreground">تنبيهات النظام</span>
            </div>
            <div className="flex flex-col gap-2">
              {systemAlerts.map((alert) => (
                <p key={alert.id} className={`text-xs leading-relaxed ${alertColors[alert.type]}`}>
                  • {alert.text}
                </p>
              ))}
            </div>
          </div>
        </div>
      </aside>
    </>
  );
}
