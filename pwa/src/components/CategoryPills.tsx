import { useRef } from "react";
import { cn } from "@/lib/utils";

interface CategoryPillsProps {
  categories: string[];
  selected: string;
  onSelect: (category: string) => void;
}

export function CategoryPills({ categories, selected, onSelect }: CategoryPillsProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  return (
    <div
      ref={scrollRef}
      className="flex gap-2 overflow-x-auto hide-scrollbar py-1 px-1"
    >
      {categories.map((cat) => (
        <button
          key={cat}
          onClick={() => onSelect(cat)}
          className={cn(
            "shrink-0 px-4 py-2 rounded-full text-sm font-medium transition-all",
            selected === cat
              ? "bg-spredd-green text-black"
              : "bg-white/6 text-white/60 hover:bg-white/10"
          )}
        >
          {cat}
        </button>
      ))}
    </div>
  );
}
