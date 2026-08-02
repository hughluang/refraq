export type RoleRow = {
  id: string;
  key: string;
  name: string;
  permissions: string[];
  locked: boolean;
  user_count: number;
};

export type PermissionCatalogEntry = {
  key: string;
  description: string;
};

export type RoleFormValues = {
  key: string;
  name: string;
  permissions: string[];
};
