import { reactive } from 'vue';

import type { Alarm } from './client';

export function createAlarmHistory(loadPage: (page: number) => Promise<{ items: Alarm[]; total: number }>) {
  const state = reactive({ items: [] as Alarm[], total: 0, page: 0, loading: false, ended: false, error: '' });
  let epoch = 0;
  function clear() {
    epoch++;
    Object.assign(state, { items: [], total: 0, page: 0, loading: false, ended: false, error: '' });
  }
  async function load(reset = true) {
    if (!reset && (state.loading || state.ended || state.items.length >= state.total)) return;
    const requestEpoch = reset ? ++epoch : epoch;
    const page = reset ? 1 : state.page + 1;
    if (reset) Object.assign(state, { items: [], total: 0, page: 0, ended: false });
    state.loading = true; state.error = '';
    try {
      const result = await loadPage(page);
      if (requestEpoch !== epoch) return;
      const ids = new Set(state.items.map((item) => item.id));
      state.items = [...state.items, ...result.items.filter((item) => !ids.has(item.id))];
      state.total = result.total;
      state.page = page;
      state.ended = result.items.length === 0 || state.items.length >= result.total;
    } catch (cause) {
      if (requestEpoch !== epoch) return;
      state.error = cause instanceof Error ? cause.message : '报警记录加载失败，请重试';
      throw cause;
    } finally {
      if (requestEpoch === epoch) state.loading = false;
    }
  }
  return { state, load, clear };
}
