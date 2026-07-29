export type AccessControlProvider = {
  can: (params: { resource: string; action: string }) => Promise<{ can: boolean }>;
};

export const accessControlProvider: AccessControlProvider = {
  async can(_params) {
    return { can: true };
  },
};
