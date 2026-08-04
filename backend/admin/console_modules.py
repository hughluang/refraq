"""Code-seeded Console Module catalog for Management Console navigation."""

from __future__ import annotations

from dataclasses import dataclass

from backend.admin.permissions import Permission, permissions_include


@dataclass(frozen=True, slots=True)
class ConsoleModuleSeed:
    id: str
    group_id: str
    group_label_key: str
    label_key: str
    route: str
    nav_permission: Permission
    group_order: int
    module_order: int


CONSOLE_MODULE_CATALOG: tuple[ConsoleModuleSeed, ...] = (
    ConsoleModuleSeed(
        id="dashboard",
        group_id="workbench",
        group_label_key="layout.navGroup.workbench",
        label_key="layout.nav.home",
        route="/console",
        nav_permission="dashboard:read",
        group_order=10,
        module_order=10,
    ),
    ConsoleModuleSeed(
        id="users",
        group_id="admin",
        group_label_key="layout.navGroup.admin",
        label_key="users.title",
        route="/console/users",
        nav_permission="users:read",
        group_order=20,
        module_order=10,
    ),
    ConsoleModuleSeed(
        id="roles",
        group_id="admin",
        group_label_key="layout.navGroup.admin",
        label_key="roles.title",
        route="/console/roles",
        nav_permission="roles:read",
        group_order=20,
        module_order=20,
    ),
    ConsoleModuleSeed(
        id="settings",
        group_id="settings",
        group_label_key="layout.navGroup.settings",
        label_key="settings.title",
        route="/console/settings",
        nav_permission="settings:read",
        group_order=30,
        module_order=10,
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


def build_navigation(permissions: list[str] | tuple[str, ...]) -> list[NavigationGroup]:
    """Return grouped modules the caller may see (permission-filtered)."""
    visible = [
        module
        for module in CONSOLE_MODULE_CATALOG
        if permissions_include(permissions, module.nav_permission)
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
        buffer.append(
            NavigationModule(
                id=module.id,
                label_key=module.label_key,
                route=module.route,
            )
        )
    flush()
    return groups
