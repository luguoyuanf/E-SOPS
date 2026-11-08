import { createApp, defineComponent, h } from 'vue';
import { describe, expect, it, vi } from 'vitest';

import { useVbenDrawer } from '../drawer/use-drawer';
import { useVbenModal } from '../modal/use-modal';

vi.mock('../modal/modal.vue', () => ({ default: defineComponent(() => () => h('div')) }));
vi.mock('../drawer/drawer.vue', () => ({ default: defineComponent(() => () => h('div')) }));
// A saved shortcut preference must not disable the dialog's Escape behavior.
vi.mock('@vben-core/preferences', () => ({
  usePreferences: () => ({ globalEscapeShortcutKey: { value: false } }),
}));

describe('dialog Escape defaults', () => {
  for (const [name, usePopup] of [['modal', useVbenModal], ['drawer', useVbenDrawer]] as const) {
    it(`${name} supports Escape with shortcuts disabled and preserves close guards`, async () => {
      let api: ReturnType<typeof usePopup>[1];
      const onBeforeClose = vi.fn(() => false);
      const app = createApp(defineComponent({
        setup() {
          [, api] = usePopup({ onBeforeClose });
          return () => h('div');
        },
      }));
      app.mount(document.createElement('div'));
      try {
        expect(api!.store.state.closeOnPressEscape).toBe(true);
        api!.open();
        await api!.close();
        expect(onBeforeClose).toHaveBeenCalledOnce();
        expect(api!.store.state.isOpen).toBe(true);
        onBeforeClose.mockReturnValue(true);
        await api!.close();
        expect(api!.store.state.isOpen).toBe(false);
      } finally {
        app.unmount();
      }
    });
  }
});
