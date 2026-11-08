import type { Operation } from '../api/esop';

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createApp, defineComponent, h, nextTick } from 'vue';
import OperationAttachmentsPreview from './operation-attachments-preview.vue';
import ProductSopPreview from './product-sop-preview.vue';

const { getFile } = vi.hoisted(() => ({ getFile: vi.fn() }));
vi.mock('../api/product-sops', () => ({ getProductSopFileAccess: getFile }));
vi.mock('ant-design-vue', () => {
  const Wrapper = defineComponent({ inheritAttrs: false, setup: (_, { slots, attrs }) => () => h('div', attrs, slots.default?.()) });
  return {
    Modal: Wrapper, Spin: Wrapper, Empty: Wrapper,
    Select: defineComponent({ props: ['value', 'options'], emits: ['update:value'], setup: (props, { attrs, emit }) => () => h('select', { ...attrs, value: props.value, onChange: (event: Event) => emit('update:value', (event.target as HTMLSelectElement).value) }, props.options?.map((item: { value: string; label: string }) => h('option', { value: item.value }, item.label))) }),
    Tree: defineComponent({ props: ['treeData'], emits: ['select'], setup: (props, { emit }) => () => h('div', { role: 'tree' }, props.treeData.map((node: { key: string; title: string }) => h('button', { onClick: () => emit('select', [node.key]) }, node.title))) }),
    Button: defineComponent({ setup: (_, { slots, attrs }) => () => h('button', attrs, slots.default?.()) }),
  };
});

vi.mock('./model-attachment-viewer.vue', () => ({ __esModule: true, default: defineComponent({ setup: (_, { attrs }) => () => h('div', attrs) }) }));

const operation: Operation = {
  id: 'operation', product_id: 'product', code: 'STEP', name: '装配', sort_order: 0,
  attachments: [
    { file_id: 'image-original', name: '照片.png', kind: 'image', content_type: 'image/png', size: 10 },
    { file_id: 'word-one', name: '同名文档.docx', kind: 'word', content_type: 'application/octet-stream', size: 10, display_file_id: 'word-pdf', display_pages: ['word-page-one', 'word-page-two'] },
    { file_id: 'word-two', name: '同名文档.docx', kind: 'word', content_type: 'application/octet-stream', size: 10, display_pages: ['second-document-page'] },
    { file_id: 'video-original', name: '视频.mp4', kind: 'video', content_type: 'video/mp4', size: 10 },
  ],
};
let unmount: () => void;
let root: HTMLElement;
async function flush() { await new Promise((resolve) => setTimeout(resolve, 0)); await nextTick(); }
function mount(component: typeof OperationAttachmentsPreview | typeof ProductSopPreview, operations = [operation], extra: Record<string, unknown> = {}) {
  root = document.createElement('div'); document.body.append(root);
  const app = createApp(component, { open: true, productId: 'product', title: '冻结版本预览', operations, versionId: 'frozen-version', ...extra });
  app.mount(root); unmount = () => app.unmount();
}
function button(label: string) { return [...root.querySelectorAll<HTMLButtonElement>('button')].find((item) => item.textContent === label)!; }

beforeEach(() => {
  getFile.mockReset().mockImplementation((_product: string, id: string) => Promise.resolve({ url: `https://private-oss.example/${id}`, expires_at: '2026-10-27T23:59:59Z' }));
  vi.stubGlobal('URL', class extends URL { static override createObjectURL() { return 'https://private-oss.example/image-original'; } static override revokeObjectURL() {} });
});
afterEach(() => { unmount?.(); root?.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('附件弹窗首开与独立切换', () => {
  it('图片和文档页可缩放，切页还原并限制缩放范围', async () => {
    mount(OperationAttachmentsPreview); await flush();
    button('放大').click(); await flush();
    expect(root.querySelector<HTMLElement>('.attachment-zoom-content')?.style.width).toBe('125%');
    button('还原').click(); await flush();
    expect(root.querySelector<HTMLElement>('.attachment-zoom-content')?.style.width).toBe('100%');
    for (let i = 0; i < 12; i++) { button('放大').click(); await flush(); }
    expect(button('放大').disabled).toBe(true);
    expect(root.querySelector<HTMLElement>('.attachment-zoom-content')?.style.width).toBe('300%');
    button('Word').click(); await flush();
    expect(root.querySelector<HTMLElement>('.attachment-zoom-content')?.style.width).toBe('100%');
    for (let i = 0; i < 5; i++) { button('缩小').click(); await flush(); }
    expect(button('缩小').disabled).toBe(true);
    expect(root.querySelector<HTMLElement>('.attachment-zoom-content')?.style.width).toBe('50%');
    button('下一页').click(); await flush();
    expect(root.querySelector<HTMLElement>('.attachment-zoom-content')?.style.width).toBe('100%');
    button('视频').click(); await flush();
    expect(root.querySelector('[aria-label="预览缩放"]')).toBeNull();
  });
  it('PDF缩放使用浏览器PDF查看器参数', async () => {
    getFile.mockResolvedValue({ url: 'about:blank', expires_at: '2026-10-27T23:59:59Z' });
    mount(OperationAttachmentsPreview, [{ ...operation, attachments: [
      { file_id: 'pdf', name: '指导书.pdf', kind: 'pdf', content_type: 'application/pdf', size: 10 },
    ] }]); await flush();
    button('放大').click(); await flush();
    expect(root.querySelector('iframe')?.src).toContain('#zoom=125');
  });
  it('首次以 open=true 挂载即加载冻结版本，只显示有附件的分类', async () => {
    mount(OperationAttachmentsPreview); await flush();
    expect(getFile).toHaveBeenCalledWith('product', 'image-original', 'frozen-version');
    expect(root.querySelector('img')?.getAttribute('src')).toBe('https://private-oss.example/image-original');
    expect([...root.querySelectorAll('[role=tab]')].map((tab) => tab.textContent)).toEqual(['图片', 'Word', '视频']);
  });
  it('编辑附件指定文件定位同类索引并通过编辑器resolver读取未保存文件', async () => {
    const resolveFile = vi.fn(async (id: string) => ({ url: `https://private-oss.example/editor-${id}`, expires_at: '2026-10-27T23:59:59Z' }));
    mount(OperationAttachmentsPreview, [operation], { initialFileId: 'word-two', resolveFile }); await flush();
    expect(root.querySelector('[role=tab][aria-selected=true]')?.textContent).toBe('Word');
    expect(root.textContent).toContain('附件 2 / 2');
    expect(resolveFile).toHaveBeenCalledWith('second-document-page');
    expect(getFile).not.toHaveBeenCalled();
    expect(root.querySelector('img')?.src).toBe('https://private-oss.example/editor-second-document-page');
  });
  it('模型和同工序配套文件全部使用传入resolver', async () => {
    const modelOperation: Operation = { ...operation, attachments: [
      { file_id: 'model', name: 'assembly.gltf', kind: 'model3d', content_type: 'model/gltf+json', size: 10 },
      { file_id: 'buffer', name: 'assembly.bin', kind: 'model_resource', content_type: 'application/octet-stream', size: 10 },
      operation.attachments[0]!,
    ] };
    const resolveFile = vi.fn(async (id: string) => ({ url: `https://private-oss.example/${id}`, expires_at: '2026-10-27T23:59:59Z' }));
    mount(OperationAttachmentsPreview, [modelOperation], { initialFileId: 'model', resolveFile }); await flush();
    expect(resolveFile.mock.calls.map(([id]) => id)).toEqual(expect.arrayContaining(['model', 'buffer', 'image-original']));
    expect(getFile).not.toHaveBeenCalled();
  });
  it('模型与配套资源同时请求访问地址，重复打开复用有效地址', async () => {
    const pending = new Map<string, (value: { url: string; expires_at: string }) => void>();
    const resolveFile = vi.fn((id: string) => new Promise<{ url: string; expires_at: string }>((resolve) => pending.set(id, resolve)));
    const modelOperation: Operation = { ...operation, attachments: [
      { file_id: 'model', name: 'assembly.gltf', kind: 'model3d', content_type: 'model/gltf+json', size: 10 },
      { file_id: 'buffer', name: 'assembly.bin', kind: 'model_resource', content_type: 'application/octet-stream', size: 10 },
      operation.attachments[0]!,
    ] };
    mount(OperationAttachmentsPreview, [modelOperation], { initialFileId: 'model', resolveFile }); await flush();
    expect(resolveFile.mock.calls.map(([id]) => id)).toEqual(expect.arrayContaining(['model', 'buffer', 'image-original']));
    for (const [id, resolve] of pending) resolve({ url: `https://private-oss.example/${id}`, expires_at: new Date(Date.now() + 120_000).toISOString() });
    await flush();
    button('图片').click(); await flush();
    button('3D 模型').click(); await flush();
    expect(resolveFile).toHaveBeenCalledTimes(3);
  });
  it('模型资源标签只显示说明，不请求无需显示的原文件地址', async () => {
    const resolveFile = vi.fn(async (id: string) => ({ url: `https://private-oss.example/${id}`, expires_at: new Date(Date.now() + 120_000).toISOString() }));
    const modelOperation: Operation = { ...operation, attachments: [
      { file_id: 'buffer', name: 'assembly.bin', kind: 'model_resource', content_type: 'application/octet-stream', size: 10 },
    ] };
    mount(OperationAttachmentsPreview, [modelOperation], { resolveFile }); await flush();
    expect(root.textContent).toContain('此文件为模型配套资源');
    expect(resolveFile).not.toHaveBeenCalled();
  });
  it('不把无关的同名图片当作模型错误，也不随意选择一个同名资源', async () => {
    const modelOperation = { ...operation, attachments: [
      operation.attachments[0]!, { ...operation.attachments[0]!, file_id: 'same-name-other-id' },
      { file_id: 'model', name: 'assembly.stp', kind: 'model3d', content_type: 'application/step', size: 10 },
    ] };
    mount(OperationAttachmentsPreview, [modelOperation], { initialFileId: 'model' }); await flush();
    expect(getFile).toHaveBeenCalledWith('product', 'model', 'frozen-version');
    expect(root.textContent).not.toContain('附件预览加载失败');
    expect(getFile).not.toHaveBeenCalledWith('product', 'same-name-other-id', 'frozen-version');
  });
  it('所有入口传递统一横竖比例和产品的四个分辨率预设', async () => {
    mount(ProductSopPreview); await flush();
    const panel = root.querySelector<HTMLElement>('[role=tabpanel]')!;
    expect(panel.style.getPropertyValue('--terminal-screen-aspect')).toBe('16 / 9');
    expect(panel.style.getPropertyValue('--terminal-screen-native-width')).toBe('1920px');
    const presets = root.querySelector<HTMLSelectElement>('[aria-label="终端分辨率与方向"]')!;
    expect([...presets.options].map((item) => item.value)).toEqual(['1920x1080', '1280x720', '1080x1920', '720x1280']);
    presets.value = '1080x1920'; presets.dispatchEvent(new Event('change')); await flush();
    expect(panel.style.getPropertyValue('--terminal-screen-aspect')).toBe('9 / 16');
    expect(panel.style.getPropertyValue('--terminal-screen-native-width')).toBe('1080px');
    expect(root.querySelector('img')?.className).toContain('object-contain');
  });
  it('切同名附件重置文档页，空类别不出现在切换栏', async () => {
    mount(OperationAttachmentsPreview); await flush();
    button('Word').click(); await flush();
    expect(getFile).toHaveBeenLastCalledWith('product', 'word-page-one', 'frozen-version');
    button('下一页').click(); await flush();
    expect(getFile).toHaveBeenLastCalledWith('product', 'word-page-two', 'frozen-version');
    button('下一附件').click(); await flush();
    expect(getFile).toHaveBeenLastCalledWith('product', 'second-document-page', 'frozen-version');
    expect(root.textContent).toContain('附件 2 / 2');
    expect(root.textContent).toContain('文档页 1 / 1');
    expect(button('PDF')).toBeUndefined();
    expect([...root.querySelectorAll('[role=tab]')].map((tab) => tab.textContent)).toEqual(['图片', 'Word', '视频']);
  });
  it('视频不自动播放，切出视频类暂停已有视频', async () => {
    const pause = vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {});
    mount(OperationAttachmentsPreview); await flush();
    button('视频').click(); await flush();
    expect(root.querySelector('video')?.autoplay).toBe(false);
    button('图片').click(); await flush();
    expect(pause).toHaveBeenCalled();
  });
  it('整产品预览首次动态挂载也立即显示第一工序媒体', async () => {
    mount(ProductSopPreview); await flush();
    expect(getFile).toHaveBeenCalledWith('product', 'image-original', 'frozen-version');
    expect(root.querySelector('img')?.getAttribute('src')).toBe('https://private-oss.example/image-original');
  });
  it('整产品工序树切换共用分类区，自动选首个有内容的类别且保留冻结版本', async () => {
    mount(ProductSopPreview, [operation, { ...operation, id: 'other', name: '包装', attachments: [operation.attachments[1]!] }]); await flush();
    button('2. 包装').click(); await flush();
    expect(getFile).toHaveBeenLastCalledWith('product', 'word-page-one', 'frozen-version');
    expect(root.querySelector('[role=tab][aria-selected=true]')?.textContent).toBe('Word');
    expect(root.textContent).not.toContain('image-original');
    expect([...root.querySelectorAll('[role=tab]')].map((tab) => tab.textContent)).toEqual(['Word']);
  });
  it('没有附件时隐藏分类栏，并显示工序级空状态', async () => {
    mount(OperationAttachmentsPreview, [{ ...operation, attachments: [] }]); await flush();
    expect(root.querySelector('[role=tablist]')).toBeNull();
    expect(root.textContent).toContain('当前工序暂无附件');
    expect(getFile).not.toHaveBeenCalled();
  });
  it('左右键只在有附件的分类间循环', async () => {
    mount(OperationAttachmentsPreview); await flush();
    const selected = root.querySelector<HTMLElement>('[role=tab][aria-selected=true]')!;
    selected.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true })); await flush();
    expect(root.querySelector('[role=tab][aria-selected=true]')?.textContent).toBe('视频');
  });
  it('审核预览只列变更工序并保留完整版本中的原序号和变更类型', async () => {
    mount(ProductSopPreview, [operation], { operationPositions: { operation: 4 }, operationLabels: { operation: '修改' } }); await flush();
    expect(button('4. 装配 · 修改')).toBeTruthy();
    expect(root.textContent).toContain('1 道');
  });
  it('两个入口弹窗层级高于审核抽屉，关闭时发出同一取消事件', async () => {
    mount(OperationAttachmentsPreview); await flush();
    expect(root.firstElementChild?.getAttribute('z-index')).toBe('3200');
    button('关闭').click(); await flush();
    expect(root.querySelector('img')?.getAttribute('src')).toBeUndefined();
  });

  it('再次点击已选分类不会清空已经加载的预览', async () => {
    mount(OperationAttachmentsPreview); await flush();
    button('图片').click(); await flush();
    expect(root.querySelector('img')?.getAttribute('src')).toBe('https://private-oss.example/image-original');
  });

});
