import { buildManifest } from './build-manifest';

import type { BuildManifest } from '../api/core/modules';

type RuntimeManifest = BuildManifest;

function runtimeContract(manifest: RuntimeManifest | typeof buildManifest): string {
  return JSON.stringify([
    manifest.schema_version,
    manifest.edition,
    manifest.platform_contract_version,
    manifest.platform_version,
    Array.isArray(manifest.modules) ? manifest.modules.map((module) => [
      module?.code,
      module?.version,
      module?.migration_namespace,
      module?.migration_heads,
      module?.openapi_sha256,
    ]) : null,
  ]);
}

export class ManifestMismatchError extends Error {
  readonly serverDigest: string;

  constructor(serverDigest: string) {
    super(
      `Edition manifest mismatch: frontend=${buildManifest.manifest_digest}, server=${serverDigest}`,
    );
    this.name = 'ManifestMismatchError';
    this.serverDigest = serverDigest;
  }
}

export function assertManifestCompatibility(manifest: RuntimeManifest): void {
  // Build provenance changes on documentation commits too; runtime contracts
  // must match, while source_revision and its artifact digest may differ.
  if (runtimeContract(manifest) !== runtimeContract(buildManifest)) {
    throw new ManifestMismatchError(manifest.manifest_digest);
  }
}
