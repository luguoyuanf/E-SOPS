import type { Operation } from '../api/esop';

export interface OperationDifference {
  id: string;
  before?: Operation;
  after?: Operation;
  changes: string[];
}

export function compareProductOperations(before: Operation[], after: Operation[]): OperationDifference[] {
  const previous = new Map(before.map((operation) => [operation.id, operation]));
  const current = new Map(after.map((operation) => [operation.id, operation]));
  const previousShared = before.filter((operation) => current.has(operation.id)).map((operation) => operation.id);
  const currentShared = after.filter((operation) => previous.has(operation.id)).map((operation) => operation.id);
  const ids = [...new Set([...after.map((operation) => operation.id), ...before.map((operation) => operation.id)])];
  return ids.map((id) => {
    const old = previous.get(id);
    const next = current.get(id);
    const changes: string[] = [];
    if (!old) changes.push('新增工序');
    else if (!next) changes.push('删除工序');
    else {
      if (old.code !== next.code) changes.push('编码修改');
      if (old.name !== next.name) changes.push('名称修改');
      if ((old.description ?? '') !== (next.description ?? '')) changes.push('说明修改');
      if (previousShared.indexOf(id) !== currentShared.indexOf(id)) changes.push('顺序调整');
      if (JSON.stringify(old.attachments.map((a) => a.file_id)) !== JSON.stringify(next.attachments.map((a) => a.file_id))) changes.push('附件变更');
    }
    return { id, before: old, after: next, changes };
  });
}
