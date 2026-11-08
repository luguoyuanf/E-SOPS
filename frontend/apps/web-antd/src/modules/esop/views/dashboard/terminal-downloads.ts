import type { HardwareModel, OtaPackage } from '../../api/ota';

export type TerminalPlatform = 'android32' | 'android64' | 'windows64' | 'ubuntuArm64';

export const terminalPlatforms: { key: TerminalPlatform; label: string; detail: string }[] = [
  { key: 'android32', label: 'Android APK 32 位', detail: 'ARM32 · armeabi-v7a' },
  { key: 'android64', label: 'Android APK 64 位', detail: 'ARM64 · arm64-v8a' },
  { key: 'windows64', label: 'Windows 64 位', detail: 'x64 · ZIP / EXE' },
  { key: 'ubuntuArm64', label: 'Ubuntu ARM64', detail: 'ARM64 · DEB / AppImage' },
];

export function terminalPlatformForPackage(fileName: string, abi: string): TerminalPlatform | undefined {
  const file = fileName.toLowerCase();
  const architecture = abi.toLowerCase().replaceAll(/[-_\s]/g, '');
  if (file.endsWith('.apk')) {
    if (architecture.includes('armeabiv7a') || architecture.includes('armv7')) return 'android32';
    if (architecture.includes('arm64v8a') || architecture.includes('aarch64')) return 'android64';
  }
  if (file.endsWith('.exe')) {
    if (architecture.includes('x8664') || architecture.includes('amd64') || architecture.includes('win64')) return 'windows64';
  }
  if (file.endsWith('.deb') || file.endsWith('.appimage')) {
    if (architecture.includes('arm64') || architecture.includes('aarch64')) return 'ubuntuArm64';
  }
  return undefined;
}

export function publishedTerminalDownloads(packages: OtaPackage[], models: HardwareModel[]) {
  const modelById = new Map(models.map((model) => [model.id, model]));
  const available = new Map<TerminalPlatform, OtaPackage>();
  for (const row of [...packages].filter((item) => item.status === 'published')
    .sort((a, b) => (b.published_at || b.created_at).localeCompare(a.published_at || a.created_at))) {
    const platform = terminalPlatformForPackage(row.file_name, modelById.get(row.hardware_model_id)?.abi || '');
    if (platform && !available.has(platform)) available.set(platform, row);
  }
  return available;
}
