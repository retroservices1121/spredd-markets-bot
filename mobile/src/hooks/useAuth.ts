import { useState, useEffect, useCallback, createContext, useContext } from "react";
import {
  isAuthenticated as checkAuth,
  telegramLogin,
  setToken,
  clearToken,
  getUserInfo,
  setOnboarded,
  getOnboarded,
  clearOnboarded,
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
  const [onboarded, setOnboardedState] = useState(false);

  const loadUser = useCallback(async () => {
    const [authed, ob] = await Promise.all([checkAuth(), getOnboarded()]);
    setOnboardedState(ob);

    if (!authed) {
      setLoading(false);
      return;
    }
    try {
      const info = await getUserInfo();
      setUser(info);
    } catch {
      await clearToken();
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
    await setToken(res.token);
    setUser(res.user as unknown as UserInfo);
    await setOnboarded();
    setOnboardedState(true);
  }, []);

  const loginWithWallet = useCallback(
    async (address: string, _signature: string) => {
      const mockToken = btoa(`wallet:${address}:${Date.now()}`);
      await setToken(mockToken);
      setUser({
        id: address.slice(0, 8),
        telegram_id: 0,
        username: `${address.slice(0, 6)}...${address.slice(-4)}`,
        active_platform: "polymarket",
        created_at: new Date().toISOString(),
      });
      await setOnboarded();
      setOnboardedState(true);
    },
    []
  );

  const logout = useCallback(async () => {
    await clearToken();
    await clearOnboarded();
    setUser(null);
    setOnboardedState(false);
  }, []);

  return {
    user,
    loading,
    authenticated: !!user,
    isOnboarded: onboarded,
    login,
    loginWithWallet,
    logout,
  };
}
