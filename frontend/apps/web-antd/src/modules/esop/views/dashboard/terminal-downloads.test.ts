import type { HardwareModel, OtaPackage } from '../../api/ota';

import { describe, expect, it } from 'vitest';

import { publishedTerminalDownloads, terminalPlatformForPackage } from './terminal-downloads';

describe('terminal download options', () => {
  it.each([
    ['station.apk', 'armeabi-v7a', 'android32'],
    ['station.apk', 'arm64-v8a', 'android64'],
    ['station.exe', 'windows-x86_64', 'windows64'],
    ['station.deb', 'ubuntu-arm64', 'ubuntuArm64'],
    ['station.AppImage', 'aarch64', 'ubuntuArm64'],
  ] as const)('classifies %s for %s', (file, abi, expected) => {
    expect(terminalPlatformForPackage(file, abi)).toBe(expected);
  });

  it('does not offer unsupported Windows x86 packages', () => {
    expect(terminalPlatformForPackage('station.exe', 'win32-x86')).toBeUndefined();
  });

  it('does not offer drafts, unknown ABIs or inaccessible packages', () => {
    const models = [{ id: 'a', abi: 'arm64-v8a' }] as HardwareModel[];
    const packages = [
      { id: 'draft', hardware_model_id: 'a', file_name: 'station.apk', status: 'draft', created_at: '2026-11-01' },
      { id: 'published', hardware_model_id: 'a', file_name: 'station.apk', status: 'published', created_at: '2026-10-31' },
      { id: 'other', hardware_model_id: 'b', file_name: 'station.exe', status: 'published', created_at: '2026-11-01' },
    ] as OtaPackage[];
    const available = publishedTerminalDownloads(packages, models);
    expect(available.get('android64')?.id).toBe('published');
    expect(available.has('windows64')).toBe(false);
  });
});
