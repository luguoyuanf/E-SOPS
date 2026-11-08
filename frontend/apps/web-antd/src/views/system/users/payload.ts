/** Only the verified platform actor may submit the platform privilege flag. */
export function userPayloadForActor(
  payload: Record<string, unknown>,
  isPlatformActor: boolean,
): Record<string, unknown> {
  const { is_superuser, ...fields } = payload;
  return isPlatformActor ? { ...fields, is_superuser } : fields;
}
