export type ModuleRoutes = {
  list: string;
  create?: string | null;
  edit?: string | null;
};

export type ModuleActions = {
  list: string;
  create?: string | null;
  edit?: string | null;
  delete?: string | null;
};

export type ModuleIdentity = {
  id: string;
  label_key: string;
  routes: ModuleRoutes;
  actions: ModuleActions;
};

export type ModuleIdentitiesResponse = {
  modules: ModuleIdentity[];
};

export type MatchedModuleAction = {
  resource: string;
  action: string;
};
