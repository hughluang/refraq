export type AuthProvider = {
  login: () => Promise<void>;
  logout: () => Promise<void>;
  check: () => Promise<{ authenticated: boolean }>;
};

export const authProvider: AuthProvider = {
  async login() {},
  async logout() {},
  async check() {
    return { authenticated: false };
  },
};
