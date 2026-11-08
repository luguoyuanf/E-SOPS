<script lang="ts" setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';

import { Select } from 'ant-design-vue';

import { preloadErpSelectOptions } from './erp-select-options';

const props = withDefaults(
  defineProps<{
    allowClear?: boolean;
    cacheKey?: string;
    class?: string;
    disabled?: boolean;
    formatOption: (record: any) => { label: string; value: string };
    load: (keyword: string) => Promise<any[]>;
    mode?: 'multiple' | 'tags';
    placeholder?: string;
    selectedOptions?: Array<{ label: string; value: string }>;
    value?: string | string[];
  }>(),
  { allowClear: false, cacheKey: '', class: undefined, disabled: false, mode: undefined, placeholder: undefined, selectedOptions: () => [], value: undefined },
);

const emit = defineEmits<{
  change: [value: string | string[] | undefined];
  'update:value': [value: string | string[] | undefined];
}>();

const loading = ref(false);
const options = ref<Array<{ label: string; value: string }>>([]);
const knownOptions = new Map<string, { label: string; value: string }>();
const displayedOptions = computed(() => {
  const known = new Map(props.selectedOptions.map((option) => [option.value, option]));
  const selectedValues = Array.isArray(props.value) ? props.value : [props.value];
  for (const value of selectedValues) {
    if (value && knownOptions.has(value)) known.set(value, knownOptions.get(value)!);
  }
  for (const option of options.value) known.set(option.value, option);
  return [...known.values()];
});
let searchTimer: number | undefined;
let requestId = 0;

const selectValue = computed({
  get: () => props.value,
  set: (value) => {
    emit('update:value', value);
    emit('change', value);
  },
});

async function loadOptions(keyword = '') {
  const currentRequest = ++requestId;
  loading.value = true;
  try {
    const records = keyword ? await props.load(keyword) : await preloadErpSelectOptions(props.load, props.cacheKey);
    if (currentRequest !== requestId) return;
    // Make options visible only after the loading state settles; otherwise an
    // option can unmount between pointer down and the Select's click handler.
    loading.value = false;
    options.value = records.map(props.formatOption);
    for (const option of options.value) knownOptions.set(option.value, option);
  } catch {
    if (currentRequest === requestId) loading.value = false;
  }
}

function search(keyword: string) {
  if (searchTimer) window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(() => void loadOptions(keyword), 250);
}

function dropdownVisibleChange(open: boolean) {
  if (!open) void loadOptions();
}

onMounted(() => void loadOptions());
watch(() => props.cacheKey, () => void loadOptions());

onBeforeUnmount(() => {
  if (searchTimer) window.clearTimeout(searchTimer);
});
</script>

<template>
  <Select
    v-model:value="selectValue"
    :allow-clear="allowClear"
    :class="$props.class"
    :disabled="disabled"
    :filter-option="false"
    :loading="loading"
    :mode="mode"
    :options="displayedOptions"
    :placeholder="placeholder"
    show-search
    @dropdown-visible-change="dropdownVisibleChange"
    @search="search"
  />
</template>
