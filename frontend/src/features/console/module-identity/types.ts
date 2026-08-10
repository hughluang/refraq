export type ModuleRoutes = {
  /** Null for identity-only modules with no Console page (e.g. tokens in Account Center). */
  list: string | null;
  create?: string | null;
  edit?: string | null;
  show?: string | null;
};

export type ModuleActions = {
  list: string;
  create?: string | null;
  edit?: string | null;
  delete?: string | null;
  show?: string | null;
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
