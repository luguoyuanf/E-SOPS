import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';

import { describe, expect, it, vi } from 'vitest';
import { Box3, BoxGeometry, Group, Mesh, MeshStandardMaterial, Vector3 } from 'three';

import { disposeModel, explosionParts, loadModelData, stepResultToModel } from './model-loader';
import { parseDxfModel } from './model-dxf';
import { resolveModelResource } from './model-types';
import type { StepResult } from './model-types';

const bytes = (text: string) => new TextEncoder().encode(text).buffer;
const obj = 'o first\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\no second\nv 2 0 0\nv 3 0 0\nv 2 1 0\nf 4 5 6';
const positions = new Float32Array([0, 0, 0, 1, 0, 0, 0, 1, 0]);
const gltf = () => ({
  asset: { version: '2.0' }, scene: 0, scenes: [{ nodes: [0, 1] }],
  nodes: [{ mesh: 0, translation: [-1, 0, 0] }, { mesh: 0, translation: [1, 0, 0] }],
  meshes: [{ primitives: [{ attributes: { POSITION: 0 } }] }],
  buffers: [{ uri: 'assembly.bin', byteLength: positions.byteLength }],
  bufferViews: [{ buffer: 0, byteOffset: 0, byteLength: positions.byteLength }],
  accessors: [{ bufferView: 0, componentType: 5126, count: 3, type: 'VEC3', min: [0, 0, 0], max: [1, 1, 0] }],
});
function makeGlb() {
  const json = gltf(); delete (json.buffers[0] as { uri?: string }).uri;
  let text = JSON.stringify(json); while (text.length % 4) text += ' ';
  const output = new ArrayBuffer(12 + 8 + text.length + 8 + positions.byteLength);
  const view = new DataView(output); view.setUint32(0, 0x46546c67, true); view.setUint32(4, 2, true); view.setUint32(8, output.byteLength, true);
  view.setUint32(12, text.length, true); view.setUint32(16, 0x4e4f534a, true); new Uint8Array(output, 20, text.length).set(new TextEncoder().encode(text));
  view.setUint32(20 + text.length, positions.byteLength, true); view.setUint32(24 + text.length, 0x004e4942, true); new Uint8Array(output, 28 + text.length).set(new Uint8Array(positions.buffer)); return output;
}

describe('CAD and model parsing', () => {
  it('loads OBJ parts and STL geometry without a rendering server', async () => {
    const model = await loadModelData(bytes(obj), 'assembly.obj'); expect(explosionParts(model)).toHaveLength(2); disposeModel(model);
    const stl = 'solid test\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\nendloop\nendfacet\nendsolid test';
    const single = await loadModelData(bytes(stl), 'part.stl'); expect(explosionParts(single)).toHaveLength(0); expect(new Box3().setFromObject(single).isEmpty()).toBe(false); disposeModel(single);
  });
  it('loads GLB embedded geometry and GLTF operation-scoped companion buffers', async () => {
    const glb = await loadModelData(makeGlb(), 'assembly.glb'); expect(explosionParts(glb)).toHaveLength(2); disposeModel(glb);
    const fetcher = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(positions.buffer));
    try {
      const model = await loadModelData(bytes(JSON.stringify(gltf())), 'assembly.gltf', { 'assembly.bin': 'https://private.example/short-signed-resource' });
      expect(fetcher.mock.calls[0]?.[0]).toEqual(expect.objectContaining({ url: 'https://private.example/short-signed-resource' }));
      expect(explosionParts(model)).toHaveLength(2); disposeModel(model);
    } finally { fetcher.mockRestore(); }
  });
  it('rejects missing, traversal and arbitrary external resources before fetching', async () => {
    for (const uri of ['https://outside.example/x.bin', '../secret.bin', '%2e%2e/secret.bin', 'file:///tmp/model.bin', 'blob:untrusted']) {
      expect(() => resolveModelResource(uri, {})).toThrow('未授权');
    }
    await expect(loadModelData(bytes(JSON.stringify(gltf())), 'assembly.gltf')).rejects.toThrow('缺少模型配套文件');
    expect(resolveModelResource('textures/color.png', { 'color.png': 'https://oss.example/authorized' })).toBe('https://oss.example/authorized');
  });
  it('does not deform vertices when expanding and closing independent parts', () => {
    const model = new Group();
    for (const x of [-2, 2]) { const part = new Mesh(new BoxGeometry(), new MeshStandardMaterial()); part.position.x = x; model.add(part); }
    model.updateMatrixWorld(true); const parts = explosionParts(model); const position = [...(parts[0]!.object as Mesh).geometry.getAttribute('position').array];
    for (const part of parts) part.object.position.copy(part.origin).add(part.direction);
    expect(parts[0]!.object.position.distanceTo(parts[0]!.origin)).toBeGreaterThan(0);
    expect([...(parts[0]!.object as Mesh).geometry.getAttribute('position').array]).toEqual(position);
    for (const part of parts) part.object.position.copy(part.origin);
    expect(parts.map((p) => p.object.position.x)).toEqual([-2, 2]); disposeModel(model);
  });
  it('parses DXF blocks, circular arcs and 3D faces and rejects ACIS solids explicitly', () => {
    const pairs: (number | string)[][] = [[0, 'SECTION'], [2, 'BLOCKS'], [0, 'BLOCK'], [2, 'PART'], [70, 0], [10, 0], [20, 0], [30, 0], [0, '3DFACE'], [10, 0], [20, 0], [30, 0], [11, 1], [21, 0], [31, 0], [12, 0], [22, 1], [32, 1], [13, 0], [23, 1], [33, 1], [0, 'ENDBLK'], [0, 'ENDSEC'], [0, 'SECTION'], [2, 'ENTITIES'], [0, 'INSERT'], [2, 'PART'], [10, -2], [20, 0], [30, 0], [0, 'INSERT'], [2, 'PART'], [10, 2], [20, 0], [30, 0], [0, 'ARC'], [10, 0], [20, 0], [30, 0], [40, 2], [50, 0], [51, 180], [0, 'ENDSEC'], [0, 'EOF']];
    const model = parseDxfModel(`${pairs.flat().join('\n')}\n`); model.updateMatrixWorld(true);
    expect(explosionParts(model)).toHaveLength(3); expect(new Box3().setFromObject(model).getSize(new Vector3()).x).toBeGreaterThan(4); disposeModel(model);
    expect(() => parseDxfModel('0\n3DSOLID\n')).toThrow('ACIS');
  });
  it('keeps plain DXF lines in separate bounded groups so the terminal can expand them', () => {
    const dxf = '0\nSECTION\n2\nENTITIES\n0\nLINE\n10\n0\n20\n0\n11\n1\n21\n0\n0\nLINE\n10\n3\n20\n0\n11\n4\n21\n0\n0\nENDSEC\n0\nEOF\n';
    const model = parseDxfModel(dxf); model.updateMatrixWorld(true);
    expect(explosionParts(model)).toHaveLength(2);
    disposeModel(model);
  });
  it('imports actual STEP single-part and assembly test assets through the installed WASM parser', async () => {
    const require = createRequire(import.meta.url); const root = dirname(dirname(require.resolve('occt-import-js')));
    const initialize = require('occt-import-js') as (options: { wasmBinary: Buffer }) => Promise<{ ReadStepFile: (data: Uint8Array, options: null) => StepResult }>;
    const parser = await initialize({ wasmBinary: readFileSync(join(root, 'dist/occt-import-js.wasm')) });
    const cube = stepResultToModel(parser.ReadStepFile(readFileSync(join(root, 'test/testfiles/simple-basic-cube/cube.stp')), null));
    expect(explosionParts(cube)).toHaveLength(0); disposeModel(cube);
    const assembly = stepResultToModel(parser.ReadStepFile(readFileSync(join(root, 'test/testfiles/cax-if/as1-oc-214.stp')), null));
    expect(explosionParts(assembly).length).toBeGreaterThan(1); disposeModel(assembly);
  }, 20_000);
});
