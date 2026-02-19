import { useState } from "react";
import { Button } from "@/components/ui/button";
import { CreateWallet } from "@/components/onboarding/CreateWallet";
import { ImportWallet } from "@/components/onboarding/ImportWallet";
import { Plus, Download } from "lucide-react";

interface OnboardingPageProps {
  onComplete: () => void;
}

type View = "welcome" | "create" | "import";

export function OnboardingPage({ onComplete }: OnboardingPageProps) {
  const [view, setView] = useState<View>("welcome");

  if (view === "create") {
    return (
      <CreateWallet onComplete={onComplete} onBack={() => setView("welcome")} />
    );
  }

  if (view === "import") {
    return (
      <ImportWallet onComplete={onComplete} onBack={() => setView("welcome")} />
    );
  }

  return (
    <div className="flex flex-col items-center justify-center h-full p-6 text-center">
      {/* Logo */}
      <img src="/icons/icon-128.png" alt="Spredd" className="w-16 h-16 rounded-2xl mb-4" />

      <h1 className="text-xl font-bold text-foreground mb-1">Spredd Markets</h1>
      <p className="text-sm text-muted-foreground mb-8">
        Your multi-chain wallet for prediction markets
      </p>

      <div className="w-full space-y-3">
        <Button className="w-full" onClick={() => setView("create")}>
          <Plus className="w-4 h-4" />
          Create New Wallet
        </Button>
        <Button
          variant="outline"
          className="w-full"
          onClick={() => setView("import")}
        >
          <Download className="w-4 h-4" />
          Import Existing Wallet
        </Button>
      </div>
    </div>
  );
}
