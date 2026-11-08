import type { Advertisement, Broadcast, OrderTask, TerminalClient, TerminalProfile, TerminalTask } from './client';

export interface TaskEnvelope { list: TerminalTask[]; broadcasts: Broadcast[]; advertisements: Advertisement[]; serverTime?: string; }
export type RefreshArea = 'heartbeat' | 'tasks' | 'orders';

/** Heartbeat owns connectivity; business failures must not overwrite its result. */
export async function refreshTerminal(client: TerminalClient, handlers: {
  profile: (profile: TerminalProfile) => void;
  tasks: (tasks: TaskEnvelope) => void;
  orders: (orders: OrderTask[]) => void;
  failure: (area: RefreshArea, cause: unknown) => void;
}) {
  const heartbeat = client.request<TerminalProfile>('terminal/profile').then(handlers.profile)
    .catch((cause: unknown) => handlers.failure('heartbeat', cause));
  if (!client.staff) { await heartbeat; return; }
  await Promise.all([
    heartbeat,
    client.request<TaskEnvelope>('terminal/tasks').then(handlers.tasks)
      .catch((cause: unknown) => handlers.failure('tasks', cause)),
    client.request<OrderTask[]>('terminal/orders').then(handlers.orders)
      .catch((cause: unknown) => handlers.failure('orders', cause)),
  ]);
}
