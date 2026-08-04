export type NavigationModule = {
  id: string;
  label_key: string;
  route: string;
};

export type NavigationGroup = {
  id: string;
  label_key: string;
  modules: NavigationModule[];
};

export type NavigationResponse = {
  groups: NavigationGroup[];
};
