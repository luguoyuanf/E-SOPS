import type { VbenFormSchema } from '#/adapter/form';

import { computed, ref } from 'vue';
import { useUserStore } from '@vben/stores';
import { getCurrentUserApi, listTenantsApi } from '#/api';
import { $t } from '#/locales';
import { tenantOwnershipLabel } from '#/adapter/tenant-ownership';

type TenantRow = { tenant_id?: null | string; tenant_name?: null | string };

/** Root queries default to all tenants; mutations retain the verified JWT tenant. */
export function useTenantReadScope() {
  const userStore = useUserStore();
  const isRoot = computed(() => userStore.userInfo?.roles?.includes('super') ?? false);
  const currentTenantId = ref<string>();
  const tenants = ref<Array<{ code: string; id: string; name: string }>>([]);
  const ready = (async () => {
    const knownTenantId = userStore.userInfo?.tenantId;
    currentTenantId.value = typeof knownTenantId === 'string'
      ? knownTenantId : (await getCurrentUserApi()).tenant_id ?? undefined;
    if (!isRoot.value) return;
    let page = 1;
    while (true) {
      const result = await listTenantsApi({ page, page_size: 500 });
      tenants.value.push(...result.items);
      if (!result.items.length || tenants.value.length >= result.total) break;
      page++;
    }
  })();
  function canMutate(value: unknown) {
    const row = value as TenantRow;
    return !isRoot.value || (!!currentTenantId.value && row.tenant_id === currentTenantId.value);
  }
  function tenantName(value: unknown) {
    return tenantOwnershipLabel(value, 'tenant', tenants.value, {
      platform: $t('system.tenantScope.platform'),
      unknown: $t('system.tenantScope.unknown'),
    });
  }
  function filterSchema(): VbenFormSchema[] {
    return isRoot.value ? [{
      component: 'ApiSelect',
      componentProps: {
        allowClear: true,
        api: async () => { await ready; return tenants.value; },
        labelField: 'name',
        valueField: 'id',
        showSearch: true,
        optionFilterProp: 'label',
        placeholder: $t('system.tenantScope.all'),
      },
      fieldName: 'tenant_id',
      label: $t('system.tenantScope.tenant'),
    }] : [];
  }
  return { canMutate, currentTenantId, filterSchema, isRoot, ready, tenantName, tenants };
}
