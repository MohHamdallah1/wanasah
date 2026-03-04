import { Bell, Search, Menu } from "lucide-react";

const navItems = ["Dashboard", "Drivers", "Inventory", "Settlements"];

interface TopNavProps {
  activeTab: string;
  onTabChange: (tab: string) => void;
  onMenuToggle?: () => void;
}

export function TopNav({ activeTab, onTabChange, onMenuToggle }: TopNavProps) {
  return (
    <header className="flex items-center justify-between animate-fade-in gap-3">
      {/* Mobile hamburger */}
      <button
        onClick={onMenuToggle}
        className="md:hidden w-10 h-10 rounded-full bg-card shadow-card flex items-center justify-center shrink-0"
      >
        <Menu className="w-5 h-5 text-foreground" />
      </button>

      <nav className="hidden md:flex items-center gap-2">
        {navItems.map((item) => (
          <button
            key={item}
            onClick={() => onTabChange(item)}
            className={`px-5 py-2.5 rounded-full text-sm font-medium transition-all duration-200 ${
              activeTab === item
                ? "bg-nav-dark text-nav-dark-foreground shadow-card"
                : "bg-card text-muted-foreground hover:text-foreground shadow-card"
            }`}
          >
            {item}
          </button>
        ))}
      </nav>

      {/* Mobile title */}
      <span className="md:hidden text-base font-bold text-foreground flex-1 text-center">Wanasah</span>

      <div className="flex items-center gap-3">
        <button className="w-10 h-10 rounded-full bg-card shadow-card flex items-center justify-center hover:shadow-card-hover transition-shadow">
          <Search className="w-4 h-4 text-muted-foreground" />
        </button>
        <button className="w-10 h-10 rounded-full bg-card shadow-card flex items-center justify-center hover:shadow-card-hover transition-shadow relative">
          <Bell className="w-4 h-4 text-muted-foreground" />
          <span className="absolute top-2 right-2 w-2 h-2 rounded-full bg-destructive" />
        </button>
        <div className="hidden sm:flex w-10 h-10 rounded-full bg-primary items-center justify-center text-sm font-bold text-primary-foreground shadow-card">
          WA
        </div>
      </div>
    </header>
  );
}
