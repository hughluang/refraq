"use client";

import type { ComponentType } from "react";
import {
  IconAdjustments,
  IconAlertTriangle,
  IconApps,
  IconArrowBackUp,
  IconArrowForwardUp,
  IconArrowsExchange,
  IconBook,
  IconBox,
  IconBrain,
  IconCategory,
  IconCheck,
  IconChevronLeft,
  IconChevronRight,
  IconCircleFilled,
  IconCircleX,
  IconClock,
  IconDatabase,
  IconDeviceDesktop,
  IconDotsVertical,
  IconInbox,
  IconFlask,
  IconIdBadge,
  IconInfoCircle,
  IconKey,
  IconLanguage,
  IconLayoutDashboard,
  IconList,
  IconListCheck,
  IconMoon,
  IconPalette,
  IconPencil,
  IconPlayerPlayFilled,
  IconPlug,
  IconPlus,
  IconRoute,
  IconSearch,
  IconSettings,
  IconShieldLock,
  IconStack2,
  IconSun,
  IconTable,
  IconUserCircle,
  IconUsers,
  IconUsersGroup,
  IconVariable,
  IconX,
  type IconProps,
} from "@tabler/icons-react";

export const ICON_SIZE = 16;
export const ICON_STROKE = 1.5;

type IconComponent = ComponentType<IconProps>;

function withDefaults(Component: IconComponent) {
  function ConsoleIcon({
    size = ICON_SIZE,
    stroke = ICON_STROKE,
    ...props
  }: IconProps) {
    return <Component size={size} stroke={stroke} {...props} />;
  }
  return ConsoleIcon;
}

export const AdjustmentsIcon = withDefaults(IconAdjustments);
export const AlertIcon = withDefaults(IconAlertTriangle);
export const CheckIcon = withDefaults(IconCheck);
export const ErrorIcon = withDefaults(IconCircleX);
export const UndoIcon = withDefaults(IconArrowBackUp);
export const RedoIcon = withDefaults(IconArrowForwardUp);
export const StatusDotIcon = withDefaults(IconCircleFilled);
export const DesktopIcon = withDefaults(IconDeviceDesktop);
export const DotsIcon = withDefaults(IconDotsVertical);
export const EmptyIcon = withDefaults(IconInbox);
export const TestIcon = withDefaults(IconFlask);
export const InfoIcon = withDefaults(IconInfoCircle);
export const LanguageIcon = withDefaults(IconLanguage);
export const ListIcon = withDefaults(IconList);
export const MoonIcon = withDefaults(IconMoon);
export const PencilIcon = withDefaults(IconPencil);
export const PlayIcon = withDefaults(IconPlayerPlayFilled);
export const PlusIcon = withDefaults(IconPlus);
export const VersionsIcon = withDefaults(IconStack2);
export const SunIcon = withDefaults(IconSun);
export const CloseIcon = withDefaults(IconX);
export const SearchIcon = withDefaults(IconSearch);
export const NavCollapseIcon = withDefaults(IconChevronLeft);
export const NavExpandIcon = withDefaults(IconChevronRight);

/** Kebab-case Tabler names emitted by the Console Module catalog seed. */
const MODULE_ICONS: Record<string, ReturnType<typeof withDefaults>> = {
  "layout-dashboard": withDefaults(IconLayoutDashboard),
  users: withDefaults(IconUsers),
  "users-group": withDefaults(IconUsersGroup),
  "id-badge": withDefaults(IconIdBadge),
  plug: withDefaults(IconPlug),
  "shield-lock": withDefaults(IconShieldLock),
  key: withDefaults(IconKey),
  database: withDefaults(IconDatabase),
  table: withDefaults(IconTable),
  category: withDefaults(IconCategory),
  "arrows-exchange": withDefaults(IconArrowsExchange),
  box: withDefaults(IconBox),
  book: withDefaults(IconBook),
  route: withDefaults(IconRoute),
  variable: withDefaults(IconVariable),
  "list-check": withDefaults(IconListCheck),
  clock: withDefaults(IconClock),
  settings: withDefaults(IconSettings),
  palette: withDefaults(IconPalette),
  brain: withDefaults(IconBrain),
  "user-circle": withDefaults(IconUserCircle),
};

const ModuleFallbackIcon = withDefaults(IconApps);

export function moduleIcon(name: string | null | undefined) {
  if (!name) return ModuleFallbackIcon;
  return MODULE_ICONS[name] ?? ModuleFallbackIcon;
}
