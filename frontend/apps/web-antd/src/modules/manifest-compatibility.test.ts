import { describe, expect, it } from 'vitest';
import { buildManifest } from './build-manifest';
import { assertManifestCompatibility, ManifestMismatchError } from './manifest-compatibility';

const current = () => JSON.parse(JSON.stringify(buildManifest));

describe('runtime contract compatibility', () => {
  it('accepts the same contract from a different source commit and artifact digest', () => {
    const remote = { ...current(), source_revision: 'different-commit', manifest_digest: 'sha256:different-build' };
    expect(() => assertManifestCompatibility(remote)).not.toThrow();
  });
  it.each(['schema_version', 'edition', 'platform_contract_version', 'platform_version'])(
    'rejects changed %s even when the artifact digest is unchanged', (field) => {
      const remote = current(); remote[field] = 'changed';
      expect(() => assertManifestCompatibility(remote)).toThrow(ManifestMismatchError);
    },
  );
  it.each(['code', 'version', 'migration_namespace', 'migration_heads', 'openapi_sha256'])(
    'rejects changed module %s', (field) => {
      const remote = current(); remote.modules[0][field] = field === 'migration_heads' ? ['changed'] : 'changed';
      expect(() => assertManifestCompatibility(remote)).toThrow(ManifestMismatchError);
    },
  );
  it('rejects missing or additional modules', () => {
    for (const modules of [undefined, [], [...current().modules, current().modules[0]]]) {
      expect(() => assertManifestCompatibility({ ...current(), modules })).toThrow(ManifestMismatchError);
    }
  });
});
