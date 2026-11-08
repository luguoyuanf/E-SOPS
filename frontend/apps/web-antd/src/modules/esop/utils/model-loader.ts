import { Box3, BufferGeometry, Color, DoubleSide, Float32BufferAttribute, Group, LoadingManager, Mesh, MeshStandardMaterial, Object3D, Vector3 } from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { MTLLoader } from 'three/addons/loaders/MTLLoader.js';
import { OBJLoader } from 'three/addons/loaders/OBJLoader.js';
import { STLLoader } from 'three/addons/loaders/STLLoader.js';

import { parseDxfModel } from './model-dxf';
import { MODEL_MAX_BYTES, MODEL_MAX_PARTS, MODEL_MAX_TRIANGLES, modelExtension, resolveModelResource } from './model-types';
import type { StepNode, StepResult } from './model-types';

export async function fetchModelBytes(url: string, signal?: AbortSignal): Promise<ArrayBuffer> {
  const response = await fetch(url, { signal, credentials: 'omit' });
  if (!response.ok) throw new Error('模型或配套文件读取失败，请刷新预览链接后重试');
  if (Number(response.headers.get('content-length')) > MODEL_MAX_BYTES) throw new Error('模型文件过大');
  const reader = response.body?.getReader();
  if (!reader) throw new Error('浏览器不支持模型文件读取');
  const chunks: Uint8Array[] = []; let length = 0;
  try {
    while (true) {
      const { done, value } = await reader.read(); if (done) break;
      length += value.length;
      if (length > MODEL_MAX_BYTES) throw new Error('模型文件过大');
      chunks.push(value);
    }
  } catch (error) { await reader.cancel(); throw error; }
  const bytes = new Uint8Array(length); let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
  return bytes.buffer;
}

export function stepResultToModel(result: StepResult): Group {
  if (!result.success || !result.meshes?.length) throw new Error('STEP 文件没有可显示的模型');
  function node(source: StepNode): Group {
    const group = new Group(); group.name = source.name ?? '部件';
    for (const i of source.meshes ?? []) {
      const mesh = result.meshes[i]; if (!mesh) throw new Error('STEP 部件数据不完整');
      const geometry = new BufferGeometry();
      geometry.setAttribute('position', new Float32BufferAttribute(mesh.attributes.position.array, 3));
      if (mesh.attributes.normal) geometry.setAttribute('normal', new Float32BufferAttribute(mesh.attributes.normal.array, 3));
      geometry.setIndex(mesh.index.array); if (!mesh.attributes.normal) geometry.computeVertexNormals();
      const color = mesh.color?.length === 3 ? new Color().setRGB(mesh.color[0]!, mesh.color[1]!, mesh.color[2]!) : new Color(0x94a3b8);
      const object = new Mesh(geometry, new MeshStandardMaterial({ color, metalness: 0.15, roughness: 0.65, side: DoubleSide })); object.name = mesh.name ?? group.name; group.add(object);
    }
    for (const child of source.children ?? []) group.add(node(child));
    return group;
  }
  return node(result.root);
}

function parseStep(bytes: ArrayBuffer, signal?: AbortSignal): Promise<Group> {
  return new Promise((resolve, reject) => {
    const worker = new Worker(new URL('./step-import.worker.ts', import.meta.url), { type: 'module' });
    const finish = () => { clearTimeout(timer); signal?.removeEventListener('abort', abort); worker.terminate(); };
    const abort = () => { finish(); reject(new DOMException('Aborted', 'AbortError')); };
    const timer = setTimeout(() => { finish(); reject(new Error('STEP 解析超时，请精简模型后重试')); }, 90_000);
    worker.onmessage = ({ data }: MessageEvent<{ result?: StepResult; error?: string }>) => {
      finish();
      try { data.result ? resolve(stepResultToModel(data.result)) : reject(new Error(data.error || 'STEP 解析失败')); }
      catch (error) { reject(error); }
    };
    worker.onerror = () => { finish(); reject(new Error('STEP 解析组件加载失败，请刷新后重试')); };
    signal?.addEventListener('abort', abort, { once: true });
    if (signal?.aborted) { abort(); return; }
    worker.postMessage(bytes, [bytes]);
  });
}

export async function loadModelData(bytes: ArrayBuffer, name: string, resources: Record<string, string> = {}, signal?: AbortSignal): Promise<Object3D> {
  if (!bytes.byteLength || bytes.byteLength > MODEL_MAX_BYTES) throw new Error('模型为空或超过预览大小限制');
  const extension = modelExtension(name); const text = () => new TextDecoder().decode(bytes);
  let model: Object3D;
  if (extension === 'stp' || extension === 'step') model = await parseStep(bytes, signal);
  else if (extension === 'dxf') model = parseDxfModel(text());
  else if (extension === 'stl') {
    const view = new DataView(bytes);
    if (!new TextDecoder().decode(bytes.slice(0, 80)).trimStart().startsWith('solid')) {
      if (bytes.byteLength < 84 || view.getUint32(80, true) > MODEL_MAX_TRIANGLES || 84 + view.getUint32(80, true) * 50 > bytes.byteLength) throw new Error('STL 文件不完整或过于复杂');
    }
    const geometry = new STLLoader().parse(bytes); geometry.computeVertexNormals();
    const group = new Group(); group.add(new Mesh(geometry, new MeshStandardMaterial({ color: 0x94a3b8, side: DoubleSide }))); model = group;
  } else if (extension === 'obj') {
    const manager = new LoadingManager(); manager.setURLModifier((uri) => resolveModelResource(uri, resources));
    const loader = new OBJLoader(manager); const content = text();
    const mtl = /^\s*mtllib\s+(.+)$/m.exec(content)?.[1]?.trim();
    if (mtl) {
      const data = await fetchModelBytes(resolveModelResource(mtl, resources), signal);
      const materials = new MTLLoader(manager).parse(new TextDecoder().decode(data), ''); materials.preload(); loader.setMaterials(materials);
    }
    model = loader.parse(content);
  } else if (extension === 'glb' || extension === 'gltf') {
    const manager = new LoadingManager();
    const json = extension === 'gltf' ? JSON.parse(text()) : glbJson(bytes);
    function validateUris(value: unknown) {
      if (!value || typeof value !== 'object') return;
      for (const [key, item] of Object.entries(value)) {
        if (key === 'uri' && typeof item === 'string') resolveModelResource(item, resources);
        else validateUris(item);
      }
    }
    validateUris(json);
    // Explicit source URIs were validated above; blob URLs here are generated internally by GLTFLoader.
    manager.setURLModifier((uri) => uri.startsWith('blob:') ? uri : resolveModelResource(uri, resources));
    model = (await new GLTFLoader(manager).parseAsync(extension === 'gltf' ? text() : bytes, '')).scene;
  } else throw new Error('不支持的模型格式');
  if (signal?.aborted) { disposeModel(model); throw new DOMException('Aborted', 'AbortError'); }
  let triangles = 0; let meshes = 0;
  model.traverse((object) => {
    const geometry = (object as Mesh).geometry;
    if (geometry) {
      const position = geometry.getAttribute('position');
      if (position) {
        const values = position.array;
        for (let i = 0; i < values.length; i++) if (!Number.isFinite(values[i])) throw new Error('模型包含无效坐标');
      }
      meshes++; triangles += (geometry.index?.count ?? geometry.getAttribute('position')?.count ?? 0) / 3; }
  });
  if (!meshes || new Box3().setFromObject(model).isEmpty()) { disposeModel(model); throw new Error('文件没有可显示的模型数据'); }
  if (meshes > MODEL_MAX_PARTS || triangles > MODEL_MAX_TRIANGLES) { disposeModel(model); throw new Error('模型过于复杂，请精简后预览'); }
  return model;
}

function glbJson(data: ArrayBuffer): { buffers?: { uri?: string }[]; images?: { uri?: string }[] } {
  const view = new DataView(data);
  if (data.byteLength < 20 || view.getUint32(0, true) !== 0x46546c67) throw new Error('GLB 文件格式不正确');
  const length = view.getUint32(12, true);
  if (length > data.byteLength - 20) throw new Error('GLB 文件不完整');
  return JSON.parse(new TextDecoder().decode(new Uint8Array(data, 20, length)));
}

export function disposeModel(model: Object3D) {
  model.traverse((object) => {
    const mesh = object as Mesh; mesh.geometry?.dispose();
    for (const material of mesh.material ? Array.isArray(mesh.material) ? mesh.material : [mesh.material] : []) {
      for (const value of Object.values(material)) if (value?.isTexture) { value.dispose(); value.source?.data?.close?.(); }
      material.dispose();
    }
  });
}

export function explosionParts(model: Object3D): { object: Object3D; origin: Vector3; direction: Vector3 }[] {
  let branch = model;
  while (branch.children.length === 1 && branch.children[0]!.children.length) branch = branch.children[0]!;
  const parts = branch.children.filter((child) => !child.userData.excludeFromExplosion && !new Box3().setFromObject(child).isEmpty());
  if (parts.length < 2) return [];
  const center = new Box3().setFromObject(branch).getCenter(new Vector3());
  const size = new Box3().setFromObject(branch).getSize(new Vector3()).length();
  return parts.map((object, index) => {
    const partCenter = new Box3().setFromObject(object).getCenter(new Vector3());
    const direction = partCenter.sub(center);
    if (direction.lengthSq() < 1e-10) direction.set(Math.cos(index * 2 * Math.PI / parts.length), Math.sin(index * 2 * Math.PI / parts.length), 0.3);
    direction.normalize().multiplyScalar(size * 0.65);
    // Convert a world displacement through the parent transform without moving geometry vertices.
    const local = object.parent!.worldToLocal(center.clone().add(direction)).sub(object.parent!.worldToLocal(center.clone()));
    return { object, origin: object.position.clone(), direction: local };
  });
}
