import { describe, expect, it } from 'vitest';
import { buildStationColumns } from './line-layout';

describe('产线工位顺序与终端状态', () => {
  it.each(['single', 'double'] as const)('%s 横向排列保留全部工位编号', (layout) => {
    for (const count of [1, 10, 11, 20, 21, 41, 200]) {
      const columns = buildStationColumns(layout, count);
      expect(columns.flat().map((s) => s.position)).toEqual(Array.from({ length: count }, (_, i) => i + 1));
      expect(columns.every((column) => column.length <= (layout === 'double' ? 2 : 1))).toBe(true);
    }
  });
  it('双排按 1/2、3/4 排列，原工位绑定保持原编号', () => {
    const saved = [{ id: 'station', position: 2, row: 1, column: 2, terminal_code: 'DEVICE-1' }];
    const columns = buildStationColumns('double', 20, saved);
    expect(columns[0]?.map((s) => s.position)).toEqual([1, 2]);
    expect(columns[1]?.map((s) => s.position)).toEqual([3, 4]);
    expect(columns[9]?.map((s) => s.position)).toEqual([19, 20]);
    expect(columns[0]?.[1]).toMatchObject({ id: 'station', row: 2, column: 1, terminal_code: 'DEVICE-1', pending: false });
    expect(columns[1]?.[0]).toMatchObject({ terminal_code: null, pending: true });
    expect(buildStationColumns('single', 0)).toEqual([]);
  });
});

it.each([1, 2, 11, 20, 200])('横向连续双排 %i 个工位，切换不改变ID与名称', (count) => {
  const saved = [{ id: 'bound', position: 2, row: 2, column: 1, name: '装配', terminal_code: 'DEVICE' }];
  const columns = buildStationColumns('double', count, saved, 'sequential');
  const rows = [1, 2].map(row => columns.flat().filter(s => s.row === row).map(s => s.position));
  const width = Math.ceil(count / 2);
  expect(rows[0]).toEqual(Array.from({ length: width }, (_, i) => i + 1));
  expect(rows[1]).toEqual(Array.from({ length: count - width }, (_, i) => width + i + 1));
  expect(new Set(columns.flat().map(s => s.position)).size).toBe(count);
  if (count > 1) expect(columns.flat().find(s => s.position === 2)).toMatchObject({ id: 'bound', name: '装配', terminal_code: 'DEVICE' });
});
