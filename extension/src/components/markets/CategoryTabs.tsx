import { cn } from "@/lib/utils";

interface CategoryTabsProps {
  categories: string[];
  selected: string;
  onChange: (category: string) => void;
}

const TAB_LABELS: Record<string, string> = {
  all: "All",
  Trending: "Trending",
  Rapid: "Rapid",
};

export function CategoryTabs({ categories, selected, onChange }: CategoryTabsProps) {
  const tabs = ["all", ...categories];

  return (
    <div className="flex gap-1.5 overflow-x-auto no-scrollbar pb-1">
      {tabs.map((cat) => (
        <button
          key={cat}
          onClick={() => onChange(cat)}
          className={cn(
            "px-3 py-1.5 text-xs rounded-lg border whitespace-nowrap transition-colors flex-shrink-0",
            selected === cat
              ? "border-spredd-orange text-spredd-orange bg-spredd-orange/10"
              : cat === "Rapid"
                ? "border-amber-500/40 text-amber-400 hover:bg-amber-500/10 hover:border-amber-500/60"
                : cat === "Trending"
                  ? "border-sky-500/40 text-sky-400 hover:bg-sky-500/10 hover:border-sky-500/60"
                  : "border-border text-muted-foreground hover:text-foreground hover:border-foreground/30"
          )}
        >
          {TAB_LABELS[cat] ?? cat}
        </button>
      ))}
    </div>
  );
}
