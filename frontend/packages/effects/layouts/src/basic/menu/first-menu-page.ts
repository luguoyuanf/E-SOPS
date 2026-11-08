import type { MenuRecordRaw } from '@vben/types';

/** Resolve the first visible, enabled leaf in the authorized menu order. */
export function firstMenuPage(menus: MenuRecordRaw[]): string | undefined {
  for (const menu of menus) {
    if (menu.show === false || menu.disabled) continue;
    if (!menu.children?.length) return menu.path;
    const path = firstMenuPage(menu.children);
    if (path) return path;
  }
}
