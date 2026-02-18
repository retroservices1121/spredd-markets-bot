import { useState } from "react";
import { generateMnemonic } from "@/core/keychain";
import { BackupMnemonic } from "./BackupMnemonic";
import { SetPassword } from "./SetPassword";

interface CreateWalletProps {
  onComplete: () => void;
  onBack: () => void;
}

type Step = "backup" | "password";

export function CreateWallet({ onComplete, onBack }: CreateWalletProps) {
  const [mnemonic] = useState(() => generateMnemonic());
  const [step, setStep] = useState<Step>("backup");

  if (step === "backup") {
    return (
      <BackupMnemonic
        mnemonic={mnemonic}
        onConfirmed={() => setStep("password")}
        onBack={onBack}
      />
    );
  }

  return (
    <SetPassword
      mnemonic={mnemonic}
      onComplete={onComplete}
      onBack={() => setStep("backup")}
    />
  );
}
