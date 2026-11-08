type OptionLoader<T> = (keyword: string) => Promise<T[]>;

const pageOptions = new WeakMap<OptionLoader<any>, Map<string, Promise<any[]>>>();

export function preloadErpSelectOptions<T>(load: OptionLoader<T>, key = ''): Promise<T[]> {
  let entries = pageOptions.get(load);
  if (!entries) {
    entries = new Map();
    pageOptions.set(load, entries);
  }
  const cached = entries.get(key);
  if (cached) return cached;
  const request = load('').catch((error: unknown) => {
    entries.delete(key);
    throw error;
  });
  entries.set(key, request);
  return request;
}

export function invalidateErpSelectOptions<T>(load: OptionLoader<T>, key = ''): void {
  pageOptions.get(load)?.delete(key);
}
