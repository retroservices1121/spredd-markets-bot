import { Wallet, Settings, TrendingUp, BarChart3 } from "lucide-react";
import { motion } from "framer-motion";
import { cn } from "@/lib/utils";

export type TabId = "wallet" | "markets" | "portfolio" | "settings";

interface BottomNavProps {
  activeTab: TabId;
  onTabChange: (tab: TabId) => void;
}

const tabs = [
  { id: "wallet" as const, label: "Wallet", icon: Wallet },
  { id: "markets" as const, label: "Markets", icon: TrendingUp },
  { id: "portfolio" as const, label: "Portfolio", icon: BarChart3 },
  { id: "settings" as const, label: "Settings", icon: Settings },
];

export function BottomNav({ activeTab, onTabChange }: BottomNavProps) {
  return (
    <div className="flex items-center border-t border-border bg-background">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          onClick={() => onTabChange(tab.id)}
          className={cn(
            "relative flex-1 flex flex-col items-center gap-1 py-3 text-xs transition-colors",
            activeTab === tab.id
              ? "text-spredd-orange"
              : "text-muted-foreground hover:text-foreground"
          )}
        >
          {activeTab === tab.id && (
            <motion.div
              layoutId="bottomNavIndicator"
              className="absolute top-0 left-1/4 right-1/4 h-0.5 bg-spredd-orange rounded-full"
              transition={{ type: "spring", stiffness: 500, damping: 30 }}
            />
          )}
          <tab.icon className="w-5 h-5" />
          <span>{tab.label}</span>
        </button>
      ))}
    </div>
  );
}
