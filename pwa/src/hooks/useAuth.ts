import { useState, useEffect, useCallback, createContext, useContext } from "react";
import {
  isAuthenticated,
  telegramLogin,
  setToken,
  clearToken,
  getUserInfo,
  type UserInfo,
} from "@/api/client";

interface AuthContextValue {
  user: UserInfo | null;
  loading: boolean;
  authenticated: boolean;
  isOnboarded: boolean;
  login: (telegramData: Record<string, string>) => Promise<void>;
  loginWithWallet: (address: string, signature: string) => Promise<void>;
  logout: () => void;
}

export const AuthContext = createContext<AuthContextValue>({
  user: null,
  loading: true,
  authenticated: false,
  isOnboarded: false,
  login: async () => {},
  loginWithWallet: async () => {},
  logout: () => {},
});

export function useAuth() {
  return useContext(AuthContext);
}

export function useAuthProvider(): AuthContextValue {
  const [user, setUser] = useState<UserInfo | null>(null);
  const [loading, setLoading] = useState(true);

  const loadUser = useCallback(async () => {
    if (!isAuthenticated()) {
      setLoading(false);
      return;
    }
    try {
      const info = await getUserInfo();
      setUser(info);
    } catch {
      clearToken();
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadUser();
  }, [loadUser]);

  const login = useCallback(async (telegramData: Record<string, string>) => {
    const res = await telegramLogin(telegramData);
    setToken(res.token);
    setUser(res.user as unknown as UserInfo);
    localStorage.setItem("spredd_onboarded", "true");
  }, []);

  const loginWithWallet = useCallback(async (address: string, signature: string) => {
    // Wallet auth — will be implemented when backend supports it
    // For now, store a placeholder
    const mockToken = btoa(`wallet:${address}:${Date.now()}`);
    setToken(mockToken);
    setUser({
      id: address.slice(0, 8),
      telegram_id: 0,
      username: `${address.slice(0, 6)}...${address.slice(-4)}`,
      active_platform: "polymarket",
      created_at: new Date().toISOString(),
    });
    localStorage.setItem("spredd_onboarded", "true");
  }, []);

  const logout = useCallback(() => {
    clearToken();
    setUser(null);
    localStorage.removeItem("spredd_onboarded");
  }, []);

  const isOnboarded = !!localStorage.getItem("spredd_onboarded");

  return {
    user,
    loading,
    authenticated: !!user,
    isOnboarded,
    login,
    loginWithWallet,
    logout,
  };
}
