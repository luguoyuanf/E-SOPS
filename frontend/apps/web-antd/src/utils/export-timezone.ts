import { getCurrentTimezone } from '@vben/utils';

export function exportTimezoneHeaders() {
  return { 'X-Export-Timezone': getCurrentTimezone() };
}
