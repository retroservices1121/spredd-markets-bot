import { useState } from "react";
import { Button } from "@/components/ui/button";
import { ArrowLeft } from "lucide-react";
import { validateMnemonic } from "@/core/keychain";
import { SetPassword } from "./SetPassword";

interface ImportWalletProps {
  onComplete: () => void;
  onBack: () => void;
}

export function ImportWallet({ onComplete, onBack }: ImportWalletProps) {
  const [input, setInput] = useState("");
  const [error, setError] = useState("");
  const [showPassword, setShowPassword] = useState(false);

  function handleContinue() {
    const trimmed = input.trim();

    // Check if it's a valid mnemonic
    if (validateMnemonic(trimmed)) {
      setShowPassword(true);
      return;
    }

    // Check if it looks like a private key (hex for EVM, base58 for Solana)
    const isEvmKey = /^(0x)?[0-9a-fA-F]{64}$/.test(trimmed);
    const isSolanaKey = /^[1-9A-HJ-NP-Za-km-z]{64,88}$/.test(trimmed);

    if (isEvmKey || isSolanaKey) {
      setShowPassword(true);
      return;
    }

    setError(
      "Invalid input. Enter a 12-word seed phrase or a private key."
    );
  }

  if (showPassword) {
    return (
      <SetPassword
        mnemonic={validateMnemonic(input.trim()) ? input.trim() : null}
        privateKey={!validateMnemonic(input.trim()) ? input.trim() : undefined}
        onComplete={onComplete}
        onBack={() => setShowPassword(false)}
      />
    );
  }

  return (
    <div className="flex flex-col h-full p-4">
      <button
        onClick={onBack}
        className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground mb-4"
      >
        <ArrowLeft className="w-4 h-4" />
        Back
      </button>

      <h2 className="text-lg font-bold text-foreground mb-1">
        Import Wallet
      </h2>
      <p className="text-xs text-muted-foreground mb-4">
        Enter your 12-word seed phrase or private key to restore your wallet.
      </p>

      <textarea
        value={input}
        onChange={(e) => {
          setInput(e.target.value);
          setError("");
        }}
        placeholder="Enter seed phrase or private key..."
        className="w-full h-32 px-3 py-2 rounded-lg bg-secondary border border-input text-sm text-foreground placeholder:text-muted-foreground resize-none focus:outline-none focus:ring-2 focus:ring-ring"
        autoFocus
      />

      {error && <p className="text-xs text-spredd-red mt-2">{error}</p>}

      <div className="mt-auto pt-4">
        <Button
          className="w-full"
          disabled={!input.trim()}
          onClick={handleContinue}
        >
          Continue
        </Button>
      </div>
    </div>
  );
}
