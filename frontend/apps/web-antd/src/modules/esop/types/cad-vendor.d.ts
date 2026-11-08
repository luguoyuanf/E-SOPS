declare module 'occt-import-js' {
  const initialize: (options?: { locateFile?: (file: string) => string }) => Promise<{
    ReadStepFile: (data: Uint8Array, options: null | Record<string, unknown>) => unknown;
  }>;
  export default initialize;
}
