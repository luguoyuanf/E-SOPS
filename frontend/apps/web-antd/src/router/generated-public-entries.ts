interface PublicEntry { prefix: string; load: () => Promise<{ bootstrap: () => void | Promise<void> }> }
import esopEntries from '../modules/esop/public-entry';
export const publicEntries: PublicEntry[] = [...esopEntries];
