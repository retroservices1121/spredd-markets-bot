import { useState, useRef, useEffect } from "react";
import { cn } from "@/lib/utils";

interface Tab {
  id: string;
  label: string;
}

interface TabsProps {
  tabs: Tab[];
  activeTab: string;
  onTabChange: (id: string) => void;
  className?: string;
}

export function Tabs({ tabs, activeTab, onTabChange, className }: TabsProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [indicator, setIndicator] = useState({ left: 0, width: 0 });

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const activeEl = container.querySelector(`[data-tab-id="${activeTab}"]`) as HTMLElement;
    if (activeEl) {
      setIndicator({
        left: activeEl.offsetLeft,
        width: activeEl.offsetWidth,
      });
    }
  }, [activeTab]);

  return (
    <div
      ref={containerRef}
      className={cn("relative flex bg-white/5 rounded-xl p-1", className)}
    >
      {/* Animated indicator */}
      <div
        className="absolute top-1 h-[calc(100%-8px)] bg-spredd-green/20 rounded-lg transition-all duration-200"
        style={{ left: indicator.left, width: indicator.width }}
      />

      {tabs.map((tab) => (
        <button
          key={tab.id}
          data-tab-id={tab.id}
          onClick={() => onTabChange(tab.id)}
          className={cn(
            "relative z-10 flex-1 py-2 px-3 text-sm font-medium rounded-lg transition-colors",
            activeTab === tab.id
              ? "text-spredd-green"
              : "text-white/50 hover:text-white/70"
          )}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
