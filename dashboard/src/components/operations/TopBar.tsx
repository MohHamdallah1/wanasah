import { useState, useRef, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Menu, LogOut, User, MapPin, Calendar, ChevronDown, Settings } from "lucide-react";

interface TopBarProps {
  onMenuToggle: () => void;
}

export function TopBar({ onMenuToggle }: TopBarProps) {
  const adminName = localStorage.getItem('admin_name') || 'المدير';
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();

  // إغلاق القائمة عند النقر خارجها
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsDropdownOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const handleLogout = () => {
    // 1. مسح كل البيانات من المتصفح
    localStorage.clear();
    sessionStorage.clear();
    
    // 2. الخيار النووي: طرد المتصفح بالكامل وإعادة تحميل الصفحة من الصفر
    window.location.replace('/login');
  };

  return (
    <div className="glass-card rounded-2xl h-16 md:h-20 px-4 md:px-6 flex items-center justify-between gap-3 relative z-50">
      {/* اليمين: التاريخ والمكان */}
      <div className="flex items-center gap-3">
        <button onClick={onMenuToggle} className="lg:hidden w-10 h-10 rounded-xl bg-muted/60 flex items-center justify-center">
          <Menu className="w-5 h-5 text-foreground" strokeWidth={1.5} />
        </button>
        <div className="hidden md:flex items-center gap-2 text-sm text-muted-foreground">
          <Calendar className="w-4 h-4" strokeWidth={1.5} />
          <span className="font-medium">{new Date().toLocaleDateString("ar-JO", { weekday: "long", year: "numeric", month: "long", day: "numeric" })}</span>
        </div>
        <div className="hidden lg:flex items-center gap-1.5 bg-muted/60 rounded-full px-3 py-1.5 text-xs font-medium text-muted-foreground">
          <MapPin className="w-3.5 h-3.5" strokeWidth={1.5} />
          الأردن - عمان
        </div>
      </div>

      {/* اليسار: الملف الشخصي والقائمة المنسدلة */}
      <div className="flex items-center relative" ref={dropdownRef}>
        <button 
          onClick={() => setIsDropdownOpen(!isDropdownOpen)}
          className="flex items-center gap-2 hover:bg-muted/50 p-1.5 rounded-full transition-colors"
        >
          <span className="hidden sm:block text-sm font-bold ms-2">{adminName}</span>
          <div className="w-10 h-10 rounded-full bg-gradient-to-br from-primary to-warning flex items-center justify-center ring-2 ring-primary/20">
            <User className="w-4 h-4 text-primary-foreground" strokeWidth={1.5} />
          </div>
          <ChevronDown className={`w-4 h-4 text-muted-foreground transition-transform ${isDropdownOpen ? "rotate-180" : ""}`} />
        </button>

        {/* القائمة المنسدلة */}
        {isDropdownOpen && (
          <div className="absolute top-full end-0 mt-2 w-48 bg-white dark:bg-slate-900 border border-border rounded-xl shadow-xl overflow-hidden animate-in fade-in slide-in-from-top-2">
            <div className="p-2">
              <button className="w-full flex items-center gap-2 px-3 py-2 text-sm font-medium text-muted-foreground hover:text-foreground hover:bg-muted rounded-lg transition-colors">
                <Settings className="w-4 h-4" />
                إعدادات الحساب
              </button>
              <div className="h-px bg-border my-1" />
              <button 
                onClick={handleLogout}
                className="w-full flex items-center gap-2 px-3 py-2 text-sm font-bold text-destructive hover:bg-destructive/10 rounded-lg transition-colors"
              >
                <LogOut className="w-4 h-4" strokeWidth={2} />
                تسجيل خروج
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}