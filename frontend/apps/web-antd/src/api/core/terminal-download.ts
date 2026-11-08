export type TerminalArchitecture = 'arm32' | 'arm64' | 'ubuntuArm64';

export async function downloadOfficialTerminal(
  architecture: TerminalArchitecture,
  _version: string | undefined,
  captchaVerification: string,
) {
  const response = await fetch(`/api/v1/homepage/download-links/${architecture}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ captchaVerification }),
    signal: AbortSignal.timeout(15_000),
    cache: 'no-store',
  });
  if (!response.ok) throw new Error('Download failed');
  const result = await response.json();
  const { url } = result.data || result;
  const target = new URL(url);
  if (target.protocol !== 'https:') throw new Error('Invalid download URL');
  const link = document.createElement('a');
  link.href = url;
  link.referrerPolicy = 'origin';
  document.body.append(link);
  link.click();
  link.remove();
}
