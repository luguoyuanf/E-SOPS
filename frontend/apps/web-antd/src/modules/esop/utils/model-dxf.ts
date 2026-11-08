import DxfParser from 'dxf-parser';
import { BufferGeometry, CanvasTexture, Color, DoubleSide, EllipseCurve, Float32BufferAttribute, Group, Line, LineBasicMaterial, Mesh, MeshStandardMaterial, Sprite, SpriteMaterial, Vector2, Vector3 } from 'three';
import { NURBSCurve } from 'three/addons/curves/NURBSCurve.js';
import { Vector4 } from 'three';

interface Point { x: number; y: number; z?: number; bulge?: number; }
interface Entity {
  type: string; text?: string; startPoint?: Point; textHeight?: number; height?: number; block?: string; name?: string; layer?: string; color?: number; vertices?: Point[];
  center?: Point; radius?: number; startAngle?: number; endAngle?: number; shape?: boolean;
  position?: Point; rotation?: number; xScale?: number; yScale?: number; zScale?: number;
  majorAxisEndPoint?: Point; axisRatio?: number; startParameter?: number; endParameter?: number;
  controlPoints?: Point[]; knotValues?: number[]; degreeOfSplineCurve?: number; weights?: number[];
}
interface Drawing { entities: Entity[]; blocks: Record<string, { entities: Entity[]; position?: Point }>; }
const point = (p: Point) => new Vector3(p.x, p.y, p.z ?? 0);

export function parseDxfModel(text: string): Group {
  if (text.startsWith('AutoCAD Binary DXF')) throw new Error('暂不支持二进制 DXF，请导出为 ASCII DXF 后上传');
  if (/(?:^|\r?\n)\s*3DSOLID\s*(?:\r?\n|$)/.test(text)) throw new Error('DXF 包含未支持的 ACIS 实体，请将三维实体导出为 STEP 或 GLB');
  const drawing = new DxfParser().parseSync(text) as unknown as Drawing;
  if (!drawing?.entities?.length) throw new Error('DXF 没有可显示的图形');
  const root = new Group();
  root.name = 'DXF';
  const plainGroups: Group[] = [];
  const batchSize = Math.max(1, Math.ceil(drawing.entities.length / 256));
  let count = 0;
  const unsupported = new Set<string>();
  function line(points: Vector3[], entity: Entity, group: Group) {
    if (points.length < 2) return;
    const color = entity.color && entity.color !== 0xffffff ? new Color(entity.color) : new Color(0x2563eb);
    group.add(new Line(new BufferGeometry().setFromPoints(points), new LineBasicMaterial({ color })));
  }
  function append(entities: Entity[], group: Group, depth = 0) {
    if (depth > 16) throw new Error('DXF 块引用层级过深或存在循环');
    for (const entity of entities) {
      if (++count > 100_000) throw new Error('DXF 图形过于复杂，请精简后预览');
      const vertices = entity.vertices ?? [];
      if ((entity.type === 'TEXT' || entity.type === 'MTEXT' || entity.type === 'ATTDEF') && entity.text) {
        const canvas = document.createElement('canvas'); const context = canvas.getContext('2d');
        if (!context) { unsupported.add(entity.type); continue; }
        const text = entity.text.slice(0, 1024).replace(/\\P/g, ' ').replace(/\\[^;]*;/g, '').replace(/[{}]/g, '');
        context.font = '32px sans-serif'; canvas.width = Math.min(8192, Math.ceil(context.measureText(text).width) + 8); canvas.height = 48;
        context.font = '32px sans-serif'; context.fillStyle = '#1e3a5f'; context.fillText(text, 4, 35);
        const label = new Sprite(new SpriteMaterial({ map: new CanvasTexture(canvas), transparent: true, depthTest: false }));
        const height = entity.textHeight ?? entity.height ?? 2.5;
        label.scale.set(height * canvas.width / canvas.height, height, 1); label.position.copy(point(entity.startPoint ?? entity.position ?? { x: 0, y: 0 }));
        label.center.set(0, 0); group.add(label);
      } else if (entity.type === 'POINT' && entity.position) {
        const p = point(entity.position); line([p.clone().add(new Vector3(-0.1, 0, 0)), p.clone().add(new Vector3(0.1, 0, 0))], entity, group);
        line([p.clone().add(new Vector3(0, -0.1, 0)), p.clone().add(new Vector3(0, 0.1, 0))], entity, group);
      } else if (entity.type === 'DIMENSION' && entity.block && drawing.blocks[entity.block]) {
        append(drawing.blocks[entity.block]!.entities, group, depth + 1);
      } else if (entity.type === 'INSERT') {
        const block = drawing.blocks[entity.name ?? ''];
        if (!block) throw new Error('DXF 引用的图块不存在');
        const part = new Group(); part.name = entity.name ?? '图块';
        const content = new Group();
        content.position.copy(point(block.position ?? { x: 0, y: 0 })).multiplyScalar(-1);
        append(block.entities, content, depth + 1); part.add(content);
        part.position.copy(point(entity.position ?? { x: 0, y: 0 }));
        part.scale.set(entity.xScale ?? 1, entity.yScale ?? 1, entity.zScale ?? 1);
        part.rotation.z = (entity.rotation ?? 0) * Math.PI / 180; group.add(part);
      } else if (entity.type === 'LINE') line(vertices.map(point), entity, group);
      else if (entity.type === 'LWPOLYLINE' || entity.type === 'POLYLINE') {
        const points: Vector3[] = [];
        const length = vertices.length + (entity.shape ? 1 : 0);
        for (let i = 0; i < length; i++) {
          const a = vertices[i % vertices.length]!;
          points.push(point(a));
          if (a.bulge && i < length - 1) {
            const b = vertices[(i + 1) % vertices.length]!;
            const chord = new Vector2(b.x - a.x, b.y - a.y); const distance = chord.length();
            if (distance) {
              const mid = new Vector2((a.x + b.x) / 2, (a.y + b.y) / 2);
              const offset = distance * (1 - a.bulge ** 2) / (4 * a.bulge);
              const center = mid.add(new Vector2(-chord.y, chord.x).normalize().multiplyScalar(offset));
              const start = Math.atan2(a.y - center.y, a.x - center.x); const sweep = 4 * Math.atan(a.bulge);
              const radius = Math.hypot(a.x - center.x, a.y - center.y);
              for (let j = 1; j < 24; j++) points.push(new Vector3(center.x + radius * Math.cos(start + sweep * j / 24), center.y + radius * Math.sin(start + sweep * j / 24), a.z ?? 0));
            }
          }
        }
        line(points, entity, group);
      } else if (entity.type === 'CIRCLE' || entity.type === 'ARC') {
        const center = entity.center!; const start = entity.type === 'CIRCLE' ? 0 : entity.startAngle ?? 0;
        let end = entity.type === 'CIRCLE' ? Math.PI * 2 : entity.endAngle ?? Math.PI * 2;
        if (end <= start) end += Math.PI * 2;
        const curve = new EllipseCurve(center.x, center.y, entity.radius!, entity.radius!, start, end, false, 0);
        line(curve.getPoints(96).map((p) => new Vector3(p.x, p.y, center.z ?? 0)), entity, group);
      } else if (entity.type === 'ELLIPSE' && entity.center && entity.majorAxisEndPoint) {
        const axis = entity.majorAxisEndPoint; const radius = Math.hypot(axis.x, axis.y);
        const curve = new EllipseCurve(entity.center.x, entity.center.y, radius, radius * (entity.axisRatio ?? 1), entity.startAngle ?? 0, entity.endAngle ?? Math.PI * 2, false, Math.atan2(axis.y, axis.x));
        line(curve.getPoints(96).map((p) => new Vector3(p.x, p.y, entity.center!.z ?? 0)), entity, group);
      } else if (entity.type === 'SPLINE' && entity.controlPoints?.length && entity.knotValues?.length) {
        const curve = new NURBSCurve(entity.degreeOfSplineCurve ?? 3, entity.knotValues, entity.controlPoints.map((p, i) => new Vector4(p.x, p.y, p.z ?? 0, entity.weights?.[i] ?? 1)));
        line(curve.getPoints(128), entity, group);
      } else if ((entity.type === '3DFACE' || entity.type === 'SOLID') && vertices.length >= 3) {
        const indices = [0, 1, 2, ...(vertices.length > 3 ? [0, 2, 3] : [])];
        const geometry = new BufferGeometry();
        geometry.setAttribute('position', new Float32BufferAttribute(indices.flatMap((i) => point(vertices[i]!).toArray()), 3)); geometry.computeVertexNormals();
        group.add(new Mesh(geometry, new MeshStandardMaterial({ color: entity.color ?? 0x94a3b8, side: DoubleSide })));
      } else unsupported.add(entity.type);
    }
  }
  // Keep explicit blocks intact; spread plain drawing entities in bounded groups.
  for (const [index, entity] of drawing.entities.entries()) {
    if (entity.type === 'INSERT') { append([entity], root); continue; }
    const batch = Math.floor(index / batchSize);
    const group = plainGroups[batch] ?? new Group();
    if (!plainGroups[batch]) { group.name = `图形 ${batch + 1}`; plainGroups[batch] = group; root.add(group); }
    append([entity], group);
  }
  for (const group of plainGroups) if (group && !group.children.length) root.remove(group);
  if (!root.children.length) throw new Error('DXF 不含当前可预览的线、曲线、面或图块');
  if (unsupported.size) root.userData.previewWarning = `未显示的 DXF 实体：${[...unsupported].join('、')}`;
  return root;
}
