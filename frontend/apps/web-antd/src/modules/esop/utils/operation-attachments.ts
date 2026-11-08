import type { OperationAttachment } from '../api/esop';

export const attachmentCategories = [
  { key: 'image', label: '图片' },
  { key: 'pdf', label: 'PDF' },
  { key: 'word', label: 'Word' },
  { key: 'excel', label: 'Excel' },
  { key: 'ppt', label: 'PPT' },
  { key: 'video', label: '视频' },
  { key: 'cad', label: 'CAD' },
  { key: 'model3d', label: '3D 模型' },
  { key: 'model_resource', label: '模型资源' },
] as const;
export type AttachmentCategory = typeof attachmentCategories[number]['key'];
export interface AttachmentPage { id: string; type: string; }

export function groupOperationAttachments(files: OperationAttachment[]) {
  const groups: Record<AttachmentCategory, OperationAttachment[]> = { image: [], pdf: [], word: [], excel: [], ppt: [], video: [], cad: [], model3d: [], model_resource: [] };
  for (const file of files) {
    if (Object.hasOwn(groups, file.kind)) groups[file.kind as AttachmentCategory].push(file);
  }
  return groups;
}

export function operationAttachmentPages(file: OperationAttachment | undefined): AttachmentPage[] {
  if (!file) return [];
  if (['cad', 'model3d', 'model_resource'].includes(file.kind)) return [{ id: file.file_id, type: 'application/x-esop-model' }];
  if (file.kind === 'video') return [{ id: file.file_id, type: file.content_type || 'video/mp4' }];
  if (file.display_pages?.length) return file.display_pages.map((id) => ({ id, type: 'image/png' }));
  if (file.display_file_id) return [{ id: file.display_file_id, type: file.display_content_type || 'application/pdf' }];
  if (file.kind === 'image' || file.kind === 'pdf') return [{ id: file.file_id, type: file.content_type || (file.kind === 'pdf' ? 'application/pdf' : 'image/png') }];
  return [];
}

export function boundPreviewIndex(index: number, count: number) {
  return Math.max(0, Math.min(index, Math.max(count - 1, 0)));
}
