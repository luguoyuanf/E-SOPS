import { describe, expect, it } from 'vitest';
import { googleBindingNeedsLocalhost, validGoogleBindingMfa } from './google-binding';

describe('Google binding verification', () => {
  it('requires the configured localhost origin instead of copying a session', () => {
    expect(googleBindingNeedsLocalhost('127.0.0.1')).toBe(true);
    expect(googleBindingNeedsLocalhost('localhost')).toBe(false);
    expect(googleBindingNeedsLocalhost('esops.cc')).toBe(false);
  });
  it('requires a six-digit MFA code only when MFA is enabled', () => {
    expect(validGoogleBindingMfa(false, '')).toBe(true);
    expect(validGoogleBindingMfa(true, '123456')).toBe(true);
    for (const invalid of ['', '12345', '1234567', '12345a', '123 456']) {
      expect(validGoogleBindingMfa(true, invalid)).toBe(false);
    }
  });
});
