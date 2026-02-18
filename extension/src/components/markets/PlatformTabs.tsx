import { cn } from "@/lib/utils";
import type { Platform } from "@/core/markets";
import { PLATFORMS } from "@/core/markets";

export type PlatformFilter = Platform | "all";

interface PlatformTabsProps {
  selected: PlatformFilter;
  onChange: (platform: PlatformFilter) => void;
}

const tabs: { id: PlatformFilter; label: string }[] = [
  { id: "all", label: "All" },
  ...PLATFORMS.map((p) => ({ id: p.id as PlatformFilter, label: p.label })),
];

export function PlatformTabs({ selected, onChange }: PlatformTabsProps) {
  return (
    <div className="flex gap-1.5 overflow-x-auto no-scrollbar pb-1">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          onClick={() => onChange(tab.id)}
          className={cn(
            "px-3 py-1.5 text-xs rounded-lg border whitespace-nowrap transition-colors flex-shrink-0",
            selected === tab.id
              ? "border-spredd-orange text-spredd-orange bg-spredd-orange/10"
              : "border-border text-muted-foreground hover:text-foreground hover:border-foreground/30"
          )}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
