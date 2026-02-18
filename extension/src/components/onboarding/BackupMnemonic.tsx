import { useState } from "react";
import { Button } from "@/components/ui/button";
import { ArrowLeft, Eye, EyeOff } from "lucide-react";

interface BackupMnemonicProps {
  mnemonic: string;
  onConfirmed: () => void;
  onBack: () => void;
}

export function BackupMnemonic({
  mnemonic,
  onConfirmed,
  onBack,
}: BackupMnemonicProps) {
  const [revealed, setRevealed] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const words = mnemonic.split(" ");

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
        Back Up Your Seed Phrase
      </h2>
      <p className="text-xs text-muted-foreground mb-4">
        Write these 12 words down and store them safely. This is the only way to
        recover your wallet.
      </p>

      <div className="relative">
        <div className="grid grid-cols-3 gap-2 mb-4">
          {words.map((word, i) => (
            <div
              key={i}
              className="flex items-center gap-1.5 px-2 py-2 rounded-lg bg-secondary text-sm"
            >
              <span className="text-muted-foreground text-xs w-4">
                {i + 1}.
              </span>
              <span className={revealed ? "text-foreground" : "blur-sm select-none"}>
                {word}
              </span>
            </div>
          ))}
        </div>

        {!revealed && (
          <div className="absolute inset-0 flex items-center justify-center bg-card/60 backdrop-blur-sm rounded-xl">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setRevealed(true)}
            >
              <Eye className="w-4 h-4 mr-1" />
              Reveal Seed Phrase
            </Button>
          </div>
        )}
      </div>

      {revealed && (
        <button
          onClick={() => setRevealed(false)}
          className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground mb-4 self-end"
        >
          <EyeOff className="w-3 h-3" />
          Hide
        </button>
      )}

      <div className="mt-auto space-y-3">
        <label className="flex items-start gap-2 text-xs text-muted-foreground cursor-pointer">
          <input
            type="checkbox"
            checked={confirmed}
            onChange={(e) => setConfirmed(e.target.checked)}
            className="mt-0.5 rounded"
          />
          I have written down my seed phrase and stored it securely.
        </label>

        <Button
          className="w-full"
          disabled={!confirmed || !revealed}
          onClick={onConfirmed}
        >
          Continue
        </Button>
      </div>
    </div>
  );
}
