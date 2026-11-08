import CryptoJS from 'crypto-js';

export function imageContentType(name: string) {
  const extension = name.split('.').pop()?.toLowerCase() ?? '';
  return ({ png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', webp: 'image/webp', gif: 'image/gif' } as Record<string, string>)[extension];
}

export async function imageDigests(file: Blob) {
  const data = await file.arrayBuffer();
  const words = CryptoJS.lib.WordArray.create(data);
  return {
    md5: CryptoJS.MD5(words).toString(CryptoJS.enc.Base64),
    sha256: Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', data)), (value) => value.toString(16).padStart(2, '0')).join(''),
  };
}

