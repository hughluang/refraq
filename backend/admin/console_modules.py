"""Code-seeded Console Module catalog for Management Console navigation and UX identity."""

from __future__ import annotations

from dataclasses import dataclass

from backend.admin.permissions import Permission, permissions_include


@dataclass(frozen=True, slots=True)
class ModuleRoutes:
    """Page routes for a module. `list` may be None for identity-only modules (no Console page)."""

    list: str | None
    create: str | None = None
    edit: str | None = None
    show: str | None = None


@dataclass(frozen=True, slots=True)
class ModuleActions:
    list: Permission
    create: Permission | None = None
    edit: Permission | None = None
    delete: Permission | None = None
    show: Permission | None = None
    sample: Permission | None = None


@dataclass(frozen=True, slots=True)
class ConsoleModuleSeed:
    id: str
    group_id: str
    group_label_key: str
    label_key: str
    routes: ModuleRoutes
    actions: ModuleActions
    group_order: int
    module_order: int


CONSOLE_MODULE_CATALOG: tuple[ConsoleModuleSeed, ...] = (
    ConsoleModuleSeed(
        id="dashboard",
        group_id="workbench",
        group_label_key="layout.navGroup.workbench",
        label_key="layout.nav.home",
        routes=ModuleRoutes(list="/console"),
        actions=ModuleActions(list="dashboard:read"),
        group_order=10,
        module_order=10,
    ),
    ConsoleModuleSeed(
        id="users",
        group_id="admin",
        group_label_key="layout.navGroup.admin",
        label_key="users.title",
        routes=ModuleRoutes(
            list="/console/users",
            create="/console/users/new",
        ),
        actions=ModuleActions(
            list="users:read",
            create="users:write",
            edit="users:write",
            delete="users:write",
        ),
        group_order=20,
        module_order=10,
    ),
    ConsoleModuleSeed(
        id="identity-providers",
        group_id="admin",
        group_label_key="layout.navGroup.admin",
        label_key="identityProviders.title",
        routes=ModuleRoutes(list="/console/identity-providers"),
        actions=ModuleActions(
            list="identity_providers:read",
            create="identity_providers:write",
            edit="identity_providers:write",
            delete="identity_providers:write",
        ),
        group_order=20,
        module_order=15,
    ),
    ConsoleModuleSeed(
        id="roles",
        group_id="admin",
        group_label_key="layout.navGroup.admin",
        label_key="roles.title",
        routes=ModuleRoutes(
            list="/console/roles",
            create="/console/roles/new",
            edit="/console/roles/:id",
        ),
        actions=ModuleActions(
            list="roles:read",
            create="roles:write",
            edit="roles:write",
            delete="roles:write",
        ),
        group_order=20,
        module_order=20,
    ),
    ConsoleModuleSeed(
        id="tokens",
        group_id="admin",
        group_label_key="layout.navGroup.admin",
        label_key="tokens.title",
        routes=ModuleRoutes(list=None),
        actions=ModuleActions(
            list="tokens:read",
            create="tokens:write",
            edit="tokens:write",
            delete="tokens:write",
        ),
        group_order=20,
        module_order=30,
    ),
    ConsoleModuleSeed(
        id="sources",
        group_id="metadata",
        group_label_key="layout.navGroup.metadata",
        label_key="sources.title",
        routes=ModuleRoutes(
            list="/console/sources",
            show="/console/sources/:id/structure-diffs",
        ),
        actions=ModuleActions(
            list="sources:read",
            create="sources:write",
            edit="sources:write",
            delete="sources:write",
            show="metadata:read",
        ),
        group_order=25,
        module_order=10,
    ),
    ConsoleModuleSeed(
        id="catalog",
        group_id="metadata",
        group_label_key="layout.navGroup.metadata",
        label_key="catalog.title",
        routes=ModuleRoutes(
            list="/console/catalog",
            show="/console/catalog/:id",
        ),
        actions=ModuleActions(
            list="metadata:read",
            edit="metadata:write",
            show="metadata:read",
            sample="catalog:sample",
        ),
        group_order=25,
        module_order=20,
    ),
    ConsoleModuleSeed(
        id="business-domains",
        group_id="metadata",
        group_label_key="layout.navGroup.metadata",
        label_key="businessDomains.title",
        routes=ModuleRoutes(
            list="/console/business-domains",
            create="/console/business-domains",
            edit="/console/business-domains",
        ),
        actions=ModuleActions(
            list="metadata:read",
            create="metadata:write",
            edit="metadata:write",
            delete="metadata:write",
        ),
        group_order=25,
        module_order=25,
    ),
    ConsoleModuleSeed(
        id="type-mappings",
        group_id="metadata",
        group_label_key="layout.navGroup.metadata",
        label_key="typeMappings.title",
        routes=ModuleRoutes(
            list="/console/type-mappings",
            edit="/console/type-mappings",
        ),
        actions=ModuleActions(
            list="metadata:read",
            edit="metadata:write",
        ),
        group_order=25,
        module_order=27,
    ),
    ConsoleModuleSeed(
        id="jobs",
        group_id="operations",
        group_label_key="layout.navGroup.operations",
        label_key="jobs.title",
        routes=ModuleRoutes(list="/console/jobs"),
        actions=ModuleActions(list="jobs:run"),
        group_order=27,
        module_order=10,
    ),
    ConsoleModuleSeed(
        id="schedules",
        group_id="operations",
        group_label_key="layout.navGroup.operations",
        label_key="schedules.title",
        routes=ModuleRoutes(
            list="/console/schedules",
            edit="/console/schedules",
        ),
        actions=ModuleActions(
            list="jobs:run",
            edit="jobs:run",
            delete="jobs:run",
        ),
        group_order=27,
        module_order=20,
    ),
    ConsoleModuleSeed(
        id="settings",
        group_id="settings",
        group_label_key="layout.navGroup.settings",
        label_key="settings.title",
        routes=ModuleRoutes(list="/console/settings"),
        actions=ModuleActions(
            list="settings:read",
            edit="settings:write",
        ),
        group_order=30,
        module_order=10,
    ),
    ConsoleModuleSeed(
        id="branding",
        group_id="settings",
        group_label_key="layout.navGroup.settings",
        label_key="branding.title",
        routes=ModuleRoutes(list="/console/branding"),
        actions=ModuleActions(
            list="branding:read",
            edit="branding:write",
        ),
        group_order=30,
        module_order=20,
    ),
)


@dataclass(frozen=True, slots=True)
class NavigationModule:
    id: str
    label_key: str
    route: str


@dataclass(frozen=True, slots=True)
class NavigationGroup:
    id: str
    label_key: str
    modules: tuple[NavigationModule, ...]


@dataclass(frozen=True, slots=True)
class ModuleIdentity:
    id: str
    label_key: str
    routes: ModuleRoutes
    actions: ModuleActions


def build_navigation(permissions: list[str] | tuple[str, ...]) -> list[NavigationGroup]:
    """Return grouped modules the caller may see (permission-filtered)."""
    visible = [
        module
        for module in CONSOLE_MODULE_CATALOG
        if module.routes.list is not None
        and permissions_include(permissions, module.actions.list)
    ]
    visible.sort(key=lambda item: (item.group_order, item.module_order, item.id))

    groups: list[NavigationGroup] = []
    current_group_id: str | None = None
    buffer: list[NavigationModule] = []
    group_label_key = ""

    def flush() -> None:
        nonlocal buffer, current_group_id, group_label_key
        if current_group_id is None or not buffer:
            buffer = []
            return
        groups.append(
            NavigationGroup(
                id=current_group_id,
                label_key=group_label_key,
                modules=tuple(buffer),
            )
        )
        buffer = []

    for module in visible:
        if module.group_id != current_group_id:
            flush()
            current_group_id = module.group_id
            group_label_key = module.group_label_key
        assert module.routes.list is not None
        buffer.append(
            NavigationModule(
                id=module.id,
                label_key=module.label_key,
                route=module.routes.list,
            )
        )
    flush()
    return groups


def build_module_identities() -> list[ModuleIdentity]:
    """Return the full Foundation module identity catalog (unfiltered, no groups)."""
    return [
        ModuleIdentity(
            id=module.id,
            label_key=module.label_key,
            routes=module.routes,
            actions=module.actions,
        )
        for module in CONSOLE_MODULE_CATALOG
    ]
