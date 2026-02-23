import { useEffect, useRef, useCallback } from "react";
import { useAuth } from "@/hooks/useAuth";

const BOT_USERNAME = "SpreddBot";

export function TelegramAuth() {
  const { login } = useAuth();
  const containerRef = useRef<HTMLDivElement>(null);

  const handleAuth = useCallback(
    (user: Record<string, string>) => {
      login(user).catch((err) => {
        console.error("Login failed:", err);
      });
    },
    [login]
  );

  useEffect(() => {
    // Expose callback to window for Telegram Login Widget
    (window as unknown as Record<string, unknown>).__spredd_telegram_auth =
      handleAuth;

    // Insert Telegram Login Widget script
    if (!containerRef.current) return;
    containerRef.current.innerHTML = "";

    const script = document.createElement("script");
    script.src = "https://telegram.org/js/telegram-widget.js?22";
    script.setAttribute("data-telegram-login", BOT_USERNAME);
    script.setAttribute("data-size", "large");
    script.setAttribute("data-radius", "12");
    script.setAttribute("data-onauth", "__spredd_telegram_auth(user)");
    script.setAttribute("data-request-access", "write");
    script.async = true;

    containerRef.current.appendChild(script);

    return () => {
      delete (window as unknown as Record<string, unknown>).__spredd_telegram_auth;
    };
  }, [handleAuth]);

  return (
    <div className="min-h-[100dvh] flex flex-col items-center justify-center bg-spredd-black px-6">
      {/* Logo area */}
      <div className="mb-8 text-center">
        <h1 className="text-4xl font-bold text-spredd-orange mb-2">Spredd</h1>
        <p className="text-white/50 text-lg">Trade prediction markets</p>
        <p className="text-white/30 text-sm mt-1">Swipe. Predict. Win.</p>
      </div>

      {/* Telegram widget container */}
      <div ref={containerRef} className="mb-6" />

      <p className="text-white/30 text-xs text-center max-w-xs">
        Sign in with your Telegram account to start trading. Same account as the Spredd bot.
      </p>
    </div>
  );
}
