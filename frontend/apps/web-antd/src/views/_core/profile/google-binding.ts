export function googleBindingNeedsLocalhost(hostname: string): boolean {
  return hostname === '127.0.0.1';
}

export function validGoogleBindingMfa(required: boolean, code: string): boolean {
  return !required || /^\d{6}$/.test(code);
}
