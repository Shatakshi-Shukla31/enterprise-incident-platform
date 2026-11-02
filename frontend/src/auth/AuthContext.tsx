import { useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import * as client from "../lib/api";
import type { Role, User } from "../lib/types";

interface AuthState {
  user: User | null;
  loading: boolean;
  signIn: (email: string, password: string) => Promise<void>;
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

  const signIn = useCallback(async (email: string, password: string) => {
    await client.login(email, password);
    setUser(await client.api.get<User>("/auth/me"));
  }, []);

  const signOut = useCallback(async () => {
    await client.logout();
    setUser(null);
    // Another person may sign in next on this browser.
    queryClient.clear();
  }, [queryClient]);

  const value = useMemo(() => ({ user, loading, signIn, signOut }), [user, loading, signIn, signOut]);
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
