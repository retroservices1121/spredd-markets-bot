import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Loader2 } from "lucide-react";

interface UnlockPageProps {
  onUnlock: (password: string) => Promise<boolean>;
  error: string | null;
}

export function UnlockPage({ onUnlock, error }: UnlockPageProps) {
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!password) return;
    setLoading(true);
    await onUnlock(password);
    setLoading(false);
  }

  return (
    <div className="flex flex-col items-center justify-center h-full p-6">
      {/* Logo */}
      <div className="w-14 h-14 rounded-2xl bg-spredd-orange flex items-center justify-center mb-4">
        <span className="text-xl font-bold text-white">S</span>
      </div>

      <h1 className="text-lg font-bold text-foreground mb-1">Welcome Back</h1>
      <p className="text-sm text-muted-foreground mb-6">
        Enter your password to unlock
      </p>

      <form onSubmit={handleSubmit} className="w-full space-y-3">
        <Input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Password"
          autoFocus
        />

        {error && <p className="text-xs text-spredd-red">{error}</p>}

        <Button className="w-full" disabled={loading || !password} type="submit">
          {loading ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              Unlocking...
            </>
          ) : (
            "Unlock"
          )}
        </Button>
      </form>
    </div>
  );
}
