import { cn } from "@/lib/utils";

interface AvatarProps {
  src?: string;
  name?: string;
  size?: "sm" | "md" | "lg" | "xl";
  online?: boolean;
  className?: string;
}

const sizeMap = {
  sm: "w-8 h-8 text-xs",
  md: "w-10 h-10 text-sm",
  lg: "w-14 h-14 text-xl",
  xl: "w-20 h-20 text-2xl",
};

const ringSizeMap = {
  sm: "w-2.5 h-2.5",
  md: "w-3 h-3",
  lg: "w-3.5 h-3.5",
  xl: "w-4 h-4",
};

export function Avatar({ src, name, size = "md", online, className }: AvatarProps) {
  const initials = (name || "U")
    .split(" ")
    .map((w) => w[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();

  return (
    <div className={cn("relative shrink-0", className)}>
      {src ? (
        <img
          src={src}
          alt={name || "Avatar"}
          className={cn(
            "rounded-full object-cover bg-white/10",
            sizeMap[size]
          )}
        />
      ) : (
        <div
          className={cn(
            "rounded-full bg-spredd-green/20 flex items-center justify-center font-bold text-spredd-green",
            sizeMap[size]
          )}
        >
          {initials}
        </div>
      )}
      {online !== undefined && (
        <span
          className={cn(
            "absolute bottom-0 right-0 rounded-full border-2 border-spredd-bg",
            ringSizeMap[size],
            online ? "bg-spredd-green" : "bg-white/30"
          )}
        />
      )}
    </div>
  );
}
