import { Blob } from 'node:buffer';
import { webcrypto } from 'node:crypto';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { imageContentType, imageDigests } from './image-digests';

afterEach(() => vi.unstubAllGlobals());
describe('OSS image request integrity', () => {
  it('sends standard Base64 MD5 and hex SHA256 for the exact file bytes', async () => {
    vi.stubGlobal('crypto', webcrypto);
    expect(await imageDigests(new Blob(['abc']) as unknown as globalThis.Blob)).toEqual({
      md5: 'kAFQmDzST7DWlj99KOF/cg==',
      sha256: 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad',
    });
    expect(imageContentType('IMAGE.JPEG')).toBe('image/jpeg');
    expect(imageContentType('document.svg')).toBeUndefined();
  });
});
