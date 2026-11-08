import type { Object3D, PerspectiveCamera, Scene } from 'three';

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createApp, defineComponent, h, nextTick } from 'vue';
import { BoxGeometry, Group, Mesh, MeshStandardMaterial, Vector3 } from 'three';
import ModelAttachmentViewer from './model-attachment-viewer.vue';

const state = vi.hoisted(() => ({ camera: undefined as PerspectiveCamera | undefined, scene: undefined as Scene | undefined, warn: vi.fn(), nextFrame: undefined as FrameRequestCallback | undefined }));
vi.mock('ant-design-vue', () => ({
  Button: defineComponent({ setup: (_, { slots, attrs }) => () => h('button', attrs, slots.default?.()) }),
  Spin: defineComponent({ setup: () => () => h('div') }), message: { warning: state.warn },
}));
vi.mock('three', async (original) => {
  const library = await original<typeof import('three')>();
  return { ...library, WebGLRenderer: class {
    domElement = document.createElement('canvas');
    setPixelRatio() {} setSize() {} dispose() {} forceContextLoss() {}
    render(scene: Scene, camera: PerspectiveCamera) { state.scene = scene; state.camera = camera; scene.updateMatrixWorld(true); camera.updateMatrixWorld(true); }
  } };
});
vi.mock('three/addons/controls/OrbitControls.js', () => ({ OrbitControls: class {
  target = new Vector3(); constructor(private camera: PerspectiveCamera) {}
  addEventListener() {} removeEventListener() {} dispose() {}
  update() { this.camera.lookAt(this.target); this.camera.updateMatrixWorld(true); }
} }));
vi.mock('../utils/model-loader', async (original) => {
  const library = await original<typeof import('../utils/model-loader')>();
  return { ...library, loadModelData: vi.fn(async () => {
    const model = new Group();
    for (const x of [-2, 2]) { const mesh = new Mesh(new BoxGeometry(), new MeshStandardMaterial()); mesh.position.x = x; model.add(mesh); }
    return model;
  }) };
});
let unmount: () => void;
let root: HTMLDivElement;
const flush = async () => { await new Promise((resolve) => setTimeout(resolve, 0)); await nextTick(); };
function button(name: string) { return [...root.querySelectorAll('button')].find((item) => item.textContent === name)!; }
function parts(): Object3D[] { return state.scene!.children.find((child) => child.type === 'Group')!.children; }
beforeEach(async () => {
  state.warn.mockClear(); state.camera = undefined; state.nextFrame = undefined;
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} });
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => { state.nextFrame = callback; return 1; });
  vi.stubGlobal('cancelAnimationFrame', () => {});
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ x: 0, y: 0, top: 0, bottom: 300, left: 0, right: 600, width: 600, height: 300, toJSON: () => ({}) });
  root = document.createElement('div'); document.body.append(root);
  const app = createApp(ModelAttachmentViewer, { active: true, fileName: 'assembly.obj', data: new ArrayBuffer(1) }); app.mount(root); unmount = () => app.unmount(); await flush();
});
afterEach(() => { unmount(); root.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('model camera fitting and nonblocking fullscreen', () => {
  it('fits explicit expansion and frames the complete playback range only when playback starts', async () => {
    const closedDistance = state.camera!.position.length(); button('展开').click(); await flush();
    expect(state.camera!.position.length()).toBeGreaterThan(closedDistance);
    button('复位').click(); await flush(); const closedPositions = parts().map((part) => part.position.clone());
    button('自动播放').click(); await flush();
    expect(state.camera!.position.length()).toBeGreaterThan(closedDistance);
    expect(parts().map((part) => part.position.toArray())).toEqual(closedPositions.map((p) => p.toArray()));
    state.camera!.position.set(30, 40, 50); const userView = state.camera!.position.clone();
    state.nextFrame!(16); state.nextFrame!(32); state.nextFrame!(48);
    expect(state.camera!.position.toArray()).toEqual(userView.toArray());
    expect(parts()[0]!.position.distanceTo(closedPositions[0]!)).toBeGreaterThan(0);
  });
  it('keeps the loaded model usable when the browser rejects native fullscreen', async () => {
    const viewer = root.firstElementChild as HTMLElement;
    Object.defineProperty(viewer, 'requestFullscreen', { value: vi.fn().mockRejectedValue(new Error('not active tab')) });
    button('全屏').click(); await flush();
    expect(state.warn).toHaveBeenCalledWith('当前浏览器暂不能进入全屏，可继续在预览窗口查看');
    expect(root.querySelector('[role=alert]')).toBeNull(); expect(root.querySelector('canvas')).not.toBeNull();
    expect(button('展开').disabled).toBe(false);
  });
});
