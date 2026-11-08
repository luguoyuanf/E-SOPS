import type { Operation } from '../api/esop';
import { describe, expect, it } from 'vitest';
import { compareProductOperations } from './product-sop-diff';

function operation(id: string, overrides: Partial<Operation> = {}): Operation {
  return { id, product_id: 'product', code: id, name: id, sort_order: 0, attachments: [], ...overrides };
}

describe('产品版本工序对比', () => {
  it('区分新增、删除及已有工序的字段/顺序/附件变更', () => {
    const old = [operation('first'), operation('removed'), operation('last')];
    const next = [operation('last', { name: '新名称', description: '新说明', attachments: [{ file_id: 'file', name: '指导书.pdf', kind: 'pdf', content_type: 'application/pdf', size: 10 }] }), operation('first'), operation('added')];
    const changes = compareProductOperations(old, next);
    expect(changes.find((item) => item.id === 'last')?.changes).toEqual(['名称修改', '说明修改', '顺序调整', '附件变更']);
    expect(changes.find((item) => item.id === 'added')?.changes).toEqual(['新增工序']);
    expect(changes.find((item) => item.id === 'removed')?.changes).toEqual(['删除工序']);
  });
  it('同名附件替换仍识别为变更，相同内容不误报', () => {
    const file = { file_id: 'file', name: '指导书.png', kind: 'image', content_type: 'image/png', size: 10 };
    const old = [operation('step', { attachments: [file] })];
    expect(compareProductOperations(old, [operation('step', { attachments: [{ ...file }] })])[0]?.changes).toEqual([]);
    expect(compareProductOperations(old, [operation('step', { attachments: [{ ...file, file_id: 'replacement' }] })])[0]?.changes).toEqual(['附件变更']);
  });
  it('新增或删除引起的序号顺延不算工序修改，真正调整相对顺序才算', () => {
    const a = operation('a'); const b = operation('b'); const c = operation('c');
    const changes = compareProductOperations([a, b, c], [operation('new'), a, c]);
    expect(changes.filter((item) => item.changes.length).map((item) => item.id)).toEqual(['new', 'b']);
    expect(compareProductOperations([a, b, c], [b, a, c]).filter((item) => item.changes.includes('顺序调整')).map((item) => item.id)).toEqual(['b', 'a']);
  });
});
