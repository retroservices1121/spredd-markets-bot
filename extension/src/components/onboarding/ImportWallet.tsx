import { useState } from "react";
import { Button } from "@/components/ui/button";
import { ArrowLeft } from "lucide-react";
import { validateMnemonic } from "@/core/keychain";
import { SetPassword } from "./SetPassword";

interface ImportWalletProps {
  onComplete: () => void;
  onBack: () => void;
}

type ImportMode = "choose" | "seed" | "keys" | "password";

export function ImportWallet({ onComplete, onBack }: ImportWalletProps) {
  const [mode, setMode] = useState<ImportMode>("choose");
  const [seedInput, setSeedInput] = useState("");
  const [evmKey, setEvmKey] = useState("");
  const [solanaKey, setSolanaKey] = useState("");
  const [error, setError] = useState("");

  function handleSeedContinue() {
    const trimmed = seedInput.trim();
    if (!validateMnemonic(trimmed)) {
      setError("Invalid seed phrase. Please enter a valid 12 or 24 word phrase.");
      return;
    }
    setMode("password");
  }

  function handleKeysContinue() {
    const evmTrimmed = evmKey.trim();
    const solanaTrimmed = solanaKey.trim();

    if (!evmTrimmed && !solanaTrimmed) {
      setError("Enter at least one private key.");
      return;
    }

    if (evmTrimmed && !/^(0x)?[0-9a-fA-F]{64}$/.test(evmTrimmed)) {
      setError("Invalid EVM private key. Must be a 64-character hex string.");
      return;
    }

    if (solanaTrimmed && !/^[1-9A-HJ-NP-Za-km-z]{64,88}$/.test(solanaTrimmed)) {
      setError("Invalid Solana private key. Must be a base58-encoded key.");
      return;
    }

    setMode("password");
  }

  if (mode === "password") {
    const isSeed = mode === "password" && validateMnemonic(seedInput.trim());
    return (
      <SetPassword
        mnemonic={isSeed ? seedInput.trim() : null}
        evmPrivateKey={!isSeed && evmKey.trim() ? evmKey.trim() : undefined}
        solanaPrivateKey={!isSeed && solanaKey.trim() ? solanaKey.trim() : undefined}
        onComplete={onComplete}
        onBack={() => setMode(seedInput.trim() && validateMnemonic(seedInput.trim()) ? "seed" : "keys")}
      />
    );
  }

  return (
    <div className="flex flex-col h-full p-4">
      <button
        onClick={() => {
          if (mode === "choose") onBack();
          else { setMode("choose"); setError(""); }
        }}
        className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground mb-4"
      >
        <ArrowLeft className="w-4 h-4" />
        Back
      </button>

      {mode === "choose" && (
        <>
          <h2 className="text-lg font-bold text-foreground mb-1">
            Import Wallet
          </h2>
          <p className="text-xs text-muted-foreground mb-6">
            Choose how to import your wallet.
          </p>

          <div className="space-y-3">
            <button
              onClick={() => setMode("seed")}
              className="w-full p-4 rounded-lg bg-secondary hover:bg-secondary/80 transition-colors text-left"
            >
              <p className="text-sm font-medium text-foreground">Seed Phrase</p>
              <p className="text-xs text-muted-foreground mt-1">
                Import with a 12 or 24 word phrase. Derives both EVM and Solana wallets.
              </p>
            </button>

            <button
              onClick={() => setMode("keys")}
              className="w-full p-4 rounded-lg bg-secondary hover:bg-secondary/80 transition-colors text-left"
            >
              <p className="text-sm font-medium text-foreground">Private Keys</p>
              <p className="text-xs text-muted-foreground mt-1">
                Import EVM and/or Solana private keys directly.
              </p>
            </button>
          </div>
        </>
      )}

      {mode === "seed" && (
        <>
          <h2 className="text-lg font-bold text-foreground mb-1">
            Seed Phrase
          </h2>
          <p className="text-xs text-muted-foreground mb-4">
            Enter your 12 or 24 word seed phrase. This will derive both your EVM and Solana wallets.
          </p>

          <textarea
            value={seedInput}
            onChange={(e) => { setSeedInput(e.target.value); setError(""); }}
            placeholder="word1 word2 word3 ..."
            className="w-full h-28 px-3 py-2 rounded-lg bg-secondary border border-input text-sm text-foreground placeholder:text-muted-foreground resize-none focus:outline-none focus:ring-2 focus:ring-ring"
            autoFocus
          />

          {error && <p className="text-xs text-spredd-red mt-2">{error}</p>}

          <div className="mt-auto pt-4">
            <Button className="w-full" disabled={!seedInput.trim()} onClick={handleSeedContinue}>
              Continue
            </Button>
          </div>
        </>
      )}

      {mode === "keys" && (
        <>
          <h2 className="text-lg font-bold text-foreground mb-1">
            Private Keys
          </h2>
          <p className="text-xs text-muted-foreground mb-4">
            Enter one or both private keys.
          </p>

          <div className="space-y-4">
            <div>
              <label className="text-xs font-medium text-muted-foreground mb-1.5 block">
                EVM Private Key
                <span className="text-muted-foreground/50 ml-1">(optional)</span>
              </label>
              <input
                value={evmKey}
                onChange={(e) => { setEvmKey(e.target.value); setError(""); }}
                placeholder="0x... (64 hex characters)"
                className="w-full px-3 py-2 rounded-lg bg-secondary border border-input text-xs font-mono text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
              />
              <p className="text-[10px] text-muted-foreground/60 mt-1">
                Polygon, Base, Arbitrum, BNB Chain, Abstract
              </p>
            </div>

            <div>
              <label className="text-xs font-medium text-muted-foreground mb-1.5 block">
                Solana Private Key
                <span className="text-muted-foreground/50 ml-1">(optional)</span>
              </label>
              <input
                value={solanaKey}
                onChange={(e) => { setSolanaKey(e.target.value); setError(""); }}
                placeholder="Base58-encoded key"
                className="w-full px-3 py-2 rounded-lg bg-secondary border border-input text-xs font-mono text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
              />
              <p className="text-[10px] text-muted-foreground/60 mt-1">
                Solana mainnet
              </p>
            </div>
          </div>

          {error && <p className="text-xs text-spredd-red mt-2">{error}</p>}

          <div className="mt-auto pt-4">
            <Button
              className="w-full"
              disabled={!evmKey.trim() && !solanaKey.trim()}
              onClick={handleKeysContinue}
            >
              Continue
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
