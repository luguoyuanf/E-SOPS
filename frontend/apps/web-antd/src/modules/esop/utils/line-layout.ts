import type { ProductionLine, Station } from '../api/production';

export function buildStationColumns(layout: ProductionLine['layout'], count: number, saved: Station[] = [], numberingMode: ProductionLine['numbering_mode'] = 'odd_even') {
  const byPosition = new Map(saved.map((station) => [station.position, station]));
  const columns = [] as (Station & { pending: boolean })[][];
  for (let index = 0; index < count; index++) {
    const position = index + 1;
    const width = Math.ceil(count / 2);
    const sequential = numberingMode === 'sequential';
    const row = layout === 'single' ? 1 : sequential ? Math.floor(index / width) + 1 : (index % 2) + 1;
    const previous = byPosition.get(position);
    const column = layout === 'single' ? index : sequential ? index % width : Math.floor(index / 2);
    (columns[column] ??= []).push({
      id: previous?.id ?? `new-${position}`,
      position, row, column: column + 1, name: previous?.name ?? '',
      terminal_code: previous?.terminal_code ?? null, pending: !previous,
    });
  }
  return columns;
}

export function stationLabel(station: Pick<Station, 'name' | 'position'>) {
  return station.name?.trim() || `工位 ${station.position}`;
}
