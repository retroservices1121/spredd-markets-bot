import { useNavigate } from "react-router-dom";
import { Wallet } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/hooks/useAuth";

export function LoginPage() {
  const navigate = useNavigate();
  const { login } = useAuth();

  const handleTelegramLogin = () => {
    // The Telegram widget will call this with auth data
    // For now, navigate to home with dev bypass
    navigate("/");
  };

  const handleWalletLogin = () => {
    navigate("/signup");
  };

  return (
    <div className="h-[100dvh] flex flex-col bg-spredd-bg mesh-gradient-welcome">
      {/* Top area */}
      <div className="flex-1 flex flex-col items-center justify-center px-8 text-center">
        <h1 className="font-brand text-5xl text-spredd-green mb-4">SPREDD</h1>
        <p className="text-white/50 text-lg">
          Prediction markets in your pocket
        </p>
      </div>

      {/* Login buttons */}
      <div className="px-6 pb-10 space-y-3">
        {/* Telegram Login */}
        <Button
          size="lg"
          className="w-full"
          onClick={handleTelegramLogin}
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
            <path d="M11.944 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0a12 12 0 0 0-.056 0zm4.962 7.224c.1-.002.321.023.465.14a.506.506 0 0 1 .171.325c.016.093.036.306.02.472-.18 1.898-.962 6.502-1.36 8.627-.168.9-.499 1.201-.82 1.23-.696.065-1.225-.46-1.9-.902-1.056-.693-1.653-1.124-2.678-1.8-1.185-.78-.417-1.21.258-1.91.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.14-5.061 3.345-.48.33-.913.49-1.302.48-.428-.008-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.325-.437.893-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635z"/>
          </svg>
          Sign in with Telegram
        </Button>

        {/* Wallet Login */}
        <Button
          variant="outline"
          size="lg"
          className="w-full border-white/10"
          onClick={handleWalletLogin}
        >
          <Wallet size={18} />
          Sign in with Wallet
        </Button>

        <p className="text-white/30 text-xs text-center pt-2">
          By signing in, you agree to our Terms of Service and Privacy Policy
        </p>
      </div>
    </div>
  );
}
