import { useLocation, useNavigate } from "react-router-dom";
import { Home, Newspaper, Trophy, User, Plus } from "lucide-react";
import { cn } from "@/lib/utils";

const tabs = [
  { path: "/", icon: Home, label: "Home" },
  { path: "/feed", icon: Newspaper, label: "Feed" },
  { path: "/create", icon: Plus, label: "Create", isCenter: true },
  { path: "/ranking", icon: Trophy, label: "Ranking" },
  { path: "/profile", icon: User, label: "Profile" },
];

export function BottomNav() {
  const location = useLocation();
  const navigate = useNavigate();

  return (
    <nav className="fixed bottom-0 left-0 right-0 z-40 glass-tab-bar pb-[env(safe-area-inset-bottom)]">
      <div className="flex items-center justify-around h-16 max-w-lg mx-auto">
        {tabs.map(({ path, icon: Icon, label, isCenter }) => {
          const active = location.pathname === path;

          if (isCenter) {
            return (
              <button
                key={path}
                onClick={() => navigate(path)}
                className="flex items-center justify-center -mt-4"
              >
                <div className="w-12 h-12 rounded-full bg-spredd-green flex items-center justify-center shadow-lg shadow-spredd-green/30">
                  <Plus size={24} strokeWidth={2.5} className="text-black" />
                </div>
              </button>
            );
          }

          return (
            <button
              key={path}
              onClick={() => navigate(path)}
              className={cn(
                "flex flex-col items-center justify-center gap-0.5 w-16 py-1 transition-colors",
                active ? "text-spredd-green" : "text-white/40"
              )}
            >
              <Icon size={22} strokeWidth={active ? 2.5 : 1.5} />
              <span className="text-[10px] font-medium">{label}</span>
            </button>
          );
        })}
      </div>
    </nav>
  );
}
