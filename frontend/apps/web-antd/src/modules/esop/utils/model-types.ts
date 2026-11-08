export interface StepMesh {
  name?: string;
  color?: number[];
  attributes: { position: { array: number[] }; normal?: { array: number[] } };
  index: { array: number[] };
}
export interface StepNode { name?: string; meshes: number[]; children: StepNode[]; }
export interface StepResult { success: boolean; root: StepNode; meshes: StepMesh[]; }
export const MODEL_MAX_BYTES = 50 * 1024 * 1024;
export const MODEL_MAX_TRIANGLES = 2_000_000;
export const MODEL_MAX_PARTS = 2000;

export function modelExtension(name: string): string {
  return name.split('.').pop()?.toLowerCase() ?? '';
}

/** Only resources explicitly supplied by this operation may leave the browser. */
export function resolveModelResource(uri: string, resources: Record<string, string>): string {
  if (/^data:/i.test(uri)) {
    if (uri.length > MODEL_MAX_BYTES * 1.4) throw new Error('模型内嵌资源过大');
    return uri;
  }
  let path: string;
  try { path = decodeURIComponent(uri).replaceAll('\\', '/'); }
  catch { throw new Error('模型资源名称无效'); }
  if (/^[a-z][a-z\d+.-]*:/i.test(path) || path.startsWith('/') || path.split('/').includes('..')) {
    throw new Error('模型引用了未授权的外部资源，请将配套文件上传到同一工序');
  }
  path = path.replace(/^\.\//, '');
  const value = resources[path] ?? resources[path.split('/').pop() ?? ''];
  if (!value) throw new Error(`缺少模型配套文件或存在同名附件：${path}`);
  return value;
}
