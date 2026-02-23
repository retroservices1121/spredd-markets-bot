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
  login: (telegramData: Record<string, string>) => Promise<void>;
  logout: () => void;
}

export const AuthContext = createContext<AuthContextValue>({
  user: null,
  loading: true,
  authenticated: false,
  login: async () => {},
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
  }, []);

  const logout = useCallback(() => {
    clearToken();
    setUser(null);
  }, []);

  return {
    user,
    loading,
    authenticated: !!user,
    login,
    logout,
  };
}
