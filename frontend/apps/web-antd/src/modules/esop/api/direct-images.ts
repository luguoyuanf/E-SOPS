import { message } from 'ant-design-vue';
import { imageContentType, imageDigests } from '../utils/image-digests';
export { imageContentType } from '../utils/image-digests';

import { requestClient } from '#/api/request';
import type { OperationAttachment } from './esop';

interface UploadPolicy {
  ticket: string;
  url: string;
  method: 'POST';
  fields: Record<string, string>;
}

function uploadToOss(policy: UploadPolicy, file: File, onProgress?: (percent: number) => void, signal?: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    if (signal?.aborted) { reject(new DOMException('已取消上传', 'AbortError')); return; }
    const form = new FormData();
    for (const [key, value] of Object.entries(policy.fields)) form.append(key, value);
    form.append('file', file);
    const xhr = new XMLHttpRequest();
    const abort = () => xhr.abort();
    const done = () => signal?.removeEventListener('abort', abort);
    xhr.open(policy.method, policy.url);
    xhr.timeout = 300_000;
    // A separate XHR intentionally has no application token, cookies or API interceptors.
    xhr.withCredentials = false;
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress?.(Math.min(100, Math.round(event.loaded * 100 / event.total)));
    };
    xhr.onload = () => {
      done();
      if (xhr.status >= 200 && xhr.status < 300) resolve();
      else {
        message.error('OSS 上传未成功，请重试；持续失败请检查存储授权和跨域配置');
        reject(new Error('OSS 上传未成功'));
      }
    };
    xhr.onerror = xhr.ontimeout = () => {
      done();
      message.error('OSS 上传连接失败或超时，请检查网络后重试');
      reject(new Error('OSS 上传连接失败或超时'));
    };
    xhr.onabort = () => { done(); reject(new DOMException('已取消上传', 'AbortError')); };
    signal?.addEventListener('abort', abort, { once: true });
    xhr.send(form);
  });
}

export async function uploadImageDirect(file: File, operationId?: string, onProgress?: (percent: number) => void, signal?: AbortSignal) {
  const path = operationId ? `/esop/operations/${operationId}/files/direct-upload` : '/esop/operations/files/direct-upload';
  const digests = await imageDigests(file);
  if (signal?.aborted) throw new DOMException('已取消上传', 'AbortError');
  const policy = await requestClient.post<UploadPolicy>(path, {
    name: file.name, content_type: imageContentType(file.name), size: file.size, ...digests,
  });
  try {
    await uploadToOss(policy, file, onProgress, signal);
    if (signal?.aborted) throw new DOMException('已取消上传', 'AbortError');
    return await requestClient.post<OperationAttachment>(`${path}/complete`, { ticket: policy.ticket });
  } catch (error) {
    try { await requestClient.post(`${path}/abort`, { ticket: policy.ticket }); }
    catch { /* The signed staging prefix also has a bounded lifecycle. */ }
    throw error;
  }
}
