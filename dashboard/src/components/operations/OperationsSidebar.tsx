import { useState, useRef, useEffect } from "react";
import { Radar, Truck, Package, FileText, Settings, X, User, ChevronDown, LogOut, Calendar, MapPin } from "lucide-react";
import { toast } from "sonner";
import { useNavigate, useLocation } from "react-router-dom";

interface OperationsSidebarProps {
  open: boolean;
  onClose: () => void;
}

const navItems = [
  { label: "الصفحة الرئيسية", icon: Radar, path: "/" },
  { label: "التوزيع والمناطق", icon: Truck, path: "/dispatch" },
  { label: "المخزون والمستودع", icon: Package, path: "/inventory" },
  { label: "الأرشيف والتقارير", icon: FileText, path: "/reports" },
  { label: "الإعدادات", icon: Settings, path: "/settings" },
];

export function OperationsSidebar({ open, onClose }: OperationsSidebarProps) {
  const navigate = useNavigate();
  const location = useLocation();
  
  // +++ حالات نظام الملف الشخصي +++
  const adminName = localStorage.getItem('admin_name') || 'المدير';
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // إغلاق القائمة المنسدلة عند النقر خارجها
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsDropdownOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const handleNav = (item: typeof navItems[0]) => {
    if (item.path === "/" || item.path === "/dispatch" || item.path === "/inventory") {
      navigate(item.path);
      onClose(); 
    } else {
      toast("قريباً", { description: `صفحة "${item.label}" قيد التطوير`, duration: 2000 });
    }
  };

  // +++ منطق تسجيل الخروج المنسوخ من التوب بار +++
  const handleLogout = async () => {
    const API_URL = (import.meta.env.VITE_API_URL || "").replace(/\/$/, "");
    const adminToken = localStorage.getItem('admin_token');
    const refreshToken = localStorage.getItem('refresh_token');
    if (API_URL && adminToken) {
      try {
        await Promise.race([
          fetch(`${API_URL}/logout`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'Authorization': `Bearer ${adminToken}`,
              ...(refreshToken ? { 'X-Refresh-Token': refreshToken } : {}),
            },
          }),
          new Promise((_, reject) => setTimeout(() => reject(new Error('logout timeout')), 1500)),
        ]);
      } catch { /* صمت */ }
    }
    localStorage.clear();
    sessionStorage.clear();
    window.location.replace('/login');
  };

  return (
    <>
      {open && (
        <div className="fixed inset-0 z-40 bg-foreground/20 backdrop-blur-sm lg:hidden" onClick={onClose} />
      )}

      <aside
        className={`
          fixed inset-y-0 end-0 z-50 w-[280px] glass-sidebar p-5 flex flex-col transition-transform duration-300
          /* +++ الكي الجراحي 3: تحويل القائمة من static إلى sticky لتبقى ملتصقة بالشاشة، مع تقييد ارتفاعها ليناسب المتصفح والسماح بسكرول داخلي مخفي إذا صغرت الشاشة +++ */
          lg:sticky lg:top-4 lg:h-[calc(100vh-2rem)] overflow-y-auto custom-scrollbar lg:translate-x-0 lg:rounded-2xl lg:border lg:z-auto
          ${open ? "translate-x-0" : "translate-x-full lg:translate-x-0"}
        `}
      >
        {/* +++ رأس القائمة الجديد: نظام الملف الشخصي الأنيق بدل اللوجو التقليدي +++ */}
        <div className="relative mb-6" ref={dropdownRef}>
          <button
            onClick={() => setIsDropdownOpen(!isDropdownOpen)}
            className="flex items-center justify-between w-full p-2.5 bg-white/40 hover:bg-white/60 rounded-2xl transition-all border border-white/50 shadow-sm"
          >
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-primary to-warning flex items-center justify-center shadow-command">
                <User className="w-5 h-5 text-primary-foreground" strokeWidth={1.5} />
              </div>
              <div className="flex flex-col items-start">
                <span className="text-sm font-extrabold text-foreground tracking-tight">{adminName}</span>
                <span className="text-[10px] font-bold text-muted-foreground">مدير النظام</span>
              </div>
            </div>
            <ChevronDown className={`w-4 h-4 text-muted-foreground transition-transform duration-300 ${isDropdownOpen ? "rotate-180" : ""}`} />
          </button>

          {/* القائمة المنسدلة للتسجيل الخروج */}
          {isDropdownOpen && (
            <div className="absolute top-full end-0 mt-2 w-full bg-white border border-border rounded-xl shadow-lg overflow-hidden animate-in fade-in slide-in-from-top-2 z-50">
              <div className="p-2">
                <button className="w-full flex items-center gap-2 px-3 py-2 text-sm font-medium text-muted-foreground hover:text-foreground hover:bg-muted rounded-lg transition-colors">
                  <Settings className="w-4 h-4" /> إعدادات الحساب
                </button>
                <div className="h-px bg-border my-1" />
                <button onClick={handleLogout} className="w-full flex items-center gap-2 px-3 py-2 text-sm font-bold text-destructive hover:bg-destructive/10 rounded-lg transition-colors">
                  <LogOut className="w-4 h-4" strokeWidth={2} /> تسجيل خروج
                </button>
              </div>
            </div>
          )}
        </div>

        {/* روابط التنقل (كما هي بدون تغيير بالألوان) */}
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

        {/* +++ ذيل القائمة الجديد: التاريخ والمكان بتصميم زجاجي احترافي بدلاً من التنبيهات المزعجة +++ */}
        <div className="mt-auto pt-6">
          <div className="flex flex-col gap-3 p-4 rounded-2xl bg-white/40 border border-white/50 shadow-sm backdrop-blur-md">
            <div className="flex items-center gap-2.5 text-sm font-bold text-slate-700">
              <div className="p-1.5 bg-primary/10 rounded-lg">
                <Calendar className="w-4 h-4 text-primary" strokeWidth={2} />
              </div>
              <span className="tracking-tight">
                {new Date().toLocaleDateString("ar-JO", { weekday: "long", year: "numeric", month: "long", day: "numeric" })}
              </span>
            </div>
            <div className="flex items-center gap-2.5 text-xs font-bold text-slate-500">
              <div className="p-1.5 bg-warning/10 rounded-lg">
                <MapPin className="w-4 h-4 text-warning" strokeWidth={2} />
              </div>
              الأردن - عمان
            </div>
          </div>
        </div>
      </aside>
    </>
  );
}