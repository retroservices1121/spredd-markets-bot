import React from "react";
import { Lock } from "lucide-react";
import { BottomNav, type TabId } from "./BottomNav";

interface PopupShellProps {
  children: React.ReactNode;
  activeTab: TabId;
  onTabChange: (tab: TabId) => void;
  onLock: () => void;
}

export function PopupShell({
  children,
  activeTab,
  onTabChange,
  onLock,
}: PopupShellProps) {
  return (
    <div className="flex flex-col w-[360px] h-[600px] bg-background">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-full bg-spredd-orange" />
          <span className="font-bold text-sm text-foreground">Spredd</span>
        </div>
        <button
          onClick={onLock}
          className="p-2 rounded-lg hover:bg-secondary transition-colors"
          title="Lock wallet"
        >
          <Lock className="w-4 h-4 text-muted-foreground" />
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto">{children}</div>

      {/* Bottom nav */}
      <BottomNav activeTab={activeTab} onTabChange={onTabChange} />
    </div>
  );
}
