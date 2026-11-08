import type { StepResult } from './model-types';

import initialize from 'occt-import-js';
import wasmUrl from 'occt-import-js/dist/occt-import-js.wasm?url';

import { MODEL_MAX_BYTES, MODEL_MAX_PARTS, MODEL_MAX_TRIANGLES } from './model-types';

const scope = self as unknown as {
  onmessage: (event: MessageEvent<ArrayBuffer>) => void;
  postMessage: (value: unknown) => void;
};
scope.onmessage = async ({ data }) => {
  try {
    if (data.byteLength > MODEL_MAX_BYTES) throw new Error('模型文件过大');
    const occt = await initialize({ locateFile: () => wasmUrl });
    const result = occt.ReadStepFile(new Uint8Array(data), {
      linearDeflectionType: 'bounding_box_ratio', linearDeflection: 0.002, angularDeflection: 0.5,
    }) as StepResult;
    if (!result.success || !result.meshes.length) throw new Error('STEP 文件无法解析，请检查文件是否完整');
    if (result.meshes.length > MODEL_MAX_PARTS || result.meshes.reduce((sum, mesh) => sum + mesh.index.array.length / 3, 0) > MODEL_MAX_TRIANGLES) {
      throw new Error('模型过于复杂，请精简模型后再预览');
    }
    scope.postMessage({ result });
  } catch (error) {
    scope.postMessage({ error: error instanceof Error && /[\u3400-\u9fff]/u.test(error.message) ? error.message : 'STEP 文件解析失败，请检查文件格式' });
  }
};
