import { Outlet } from "react-router-dom";
import { BottomNav } from "./BottomNav";

export function AppLayout() {
  return (
    <div className="relative min-h-[100dvh]">
      <Outlet />
      <BottomNav />
    </div>
  );
}
