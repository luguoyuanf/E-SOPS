import type { OperationAttachment } from '../api/esop';
import { describe, expect, it } from 'vitest';
import { attachmentCategories, boundPreviewIndex, groupOperationAttachments, operationAttachmentPages } from './operation-attachments';

function file(file_id: string, kind: string, more: Partial<OperationAttachment> = {}): OperationAttachment {
  return { file_id, kind, name: '同名文件', content_type: null, size: 10, ...more };
}
describe('工序附件分类和手动分页', () => {
  it('原六类始终保留并增加模型分类，Office 转换文件仍属于原类别', () => {
    const groups = groupOperationAttachments([file('word', 'word', { display_file_id: 'word-pdf', display_pages: ['word-page'] }), file('pdf', 'pdf')]);
    expect(attachmentCategories.map((item) => item.key)).toEqual(['image', 'pdf', 'word', 'excel', 'ppt', 'video', 'cad', 'model3d', 'model_resource']);
    expect(Object.keys(groups)).toHaveLength(9);
    expect(groups.word.map((item) => item.file_id)).toEqual(['word']);
    expect(groups.pdf.map((item) => item.file_id)).toEqual(['pdf']);
    expect(groups.image).toEqual([]);
  });
  it('同名附件以原文件身份保留，不将替换文件合并或丢失', () => {
    const groups = groupOperationAttachments([file('old', 'image'), file('replacement', 'image')]);
    expect(groups.image.map((item) => item.file_id)).toEqual(['old', 'replacement']);
  });
  it('文档分页与附件身份分开，优先使用该文档的转换图片', () => {
    const document = file('original-word', 'word', { display_file_id: 'converted-pdf', display_pages: ['page-one', 'page-two'] });
    expect(operationAttachmentPages(document)).toEqual([{ id: 'page-one', type: 'image/png' }, { id: 'page-two', type: 'image/png' }]);
    expect(document.file_id).toBe('original-word');
    expect(operationAttachmentPages(file('original-video', 'video', { display_pages: ['unexpected-page'] }))[0]?.id).toBe('original-video');
    expect(operationAttachmentPages(file('unconverted-word', 'word'))).toEqual([]);
  });
  it('空类别和首尾边界不循环跳转', () => {
    expect(boundPreviewIndex(-1, 3)).toBe(0);
    expect(boundPreviewIndex(3, 3)).toBe(2);
    expect(boundPreviewIndex(1, 0)).toBe(0);
    expect(boundPreviewIndex(1, 1)).toBe(0);
  });
});
