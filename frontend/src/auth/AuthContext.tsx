import { useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import * as client from "../lib/api";
import type { Role, User } from "../lib/types";

interface AuthState {
  user: User | null;
  loading: boolean;
  signIn: (email: string, password: string, options?: { staffOnly?: boolean }) => Promise<void>;
  register: (details: client.Registration) => Promise<void>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const queryClient = useQueryClient();

  useEffect(() => {
    client.setSessionLostHandler(() => setUser(null));
    client
      .refreshSession()
      .then(async (ok) => {
        if (ok) setUser(await client.api.get<User>("/auth/me"));
      })
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, []);

  const signIn = useCallback(async (email: string, password: string, options?: { staffOnly?: boolean }) => {
    await client.login(email, password);
    const account = await client.api.get<User>("/auth/me");
    // Only tidies the sign-in page. Every permission is enforced again by the API.
    if (options?.staffOnly && !isStaff(account.role)) {
      await client.logout();
      throw new Error("This account has no staff access. Choose User to sign in.");
    }
    setUser(account);
  }, []);

  const register = useCallback(async (details: client.Registration) => {
    await client.register(details);
    setUser(await client.api.get<User>("/auth/me"));
  }, []);

  const signOut = useCallback(async () => {
    await client.logout();
    setUser(null);
    // Another person may sign in next on this browser.
    queryClient.clear();
  }, [queryClient]);

  const value = useMemo(() => ({ user, loading, signIn, register, signOut }), [user, loading, signIn, register, signOut]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}

export function isStaff(role: Role | undefined): boolean {
  return role === "agent" || role === "manager" || role === "admin";
}

export function isManager(role: Role | undefined): boolean {
  return role === "manager" || role === "admin";
}
