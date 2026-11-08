import { watch } from 'vue';

import { i18n } from '@vben/locales';

// Bridges fixed legacy UI copy while pages migrate to explicit $t keys.
// Exact phrases only; editable fields and business values in table cells stay untouched.
type TranslationMap = Record<string, string>;
type Tracked = { last: string; source: string };

const localeFiles = import.meta.glob<TranslationMap>('./ui-copy/*.json', {
  import: 'default',
});
const trackedText = new WeakMap<Text, Tracked>();
const trackedAttributes = new WeakMap<Element, Map<string, Tracked>>();
const attributes = ['alt', 'aria-label', 'placeholder', 'title'];
const excluded = 'script, style, noscript, svg, textarea, option, [role="tree"], .ant-tree, .ant-select-selection-item, [contenteditable], [data-no-translate]';

let translations: TranslationMap = {};
let language = 'zh-CN';
let revision = 0;

function eligible(node: Node): boolean {
  if (window.location.pathname.includes('/web-terminal')) return false;
  const element = node.nodeType === Node.ELEMENT_NODE
    ? node as Element
    : node.parentElement;
  if (!element || element.closest(excluded)) return false;
  if (element.closest('tbody, .vxe-table--body')) {
    return Boolean(element.closest('button, [role="button"], .ant-tag'));
  }
  return true;
}

function translateText(node: Text) {
  if (!eligible(node)) return;
  const current = node.nodeValue ?? '';
  const previous = trackedText.get(node);
  const source = previous?.last === current ? previous.source : current;
  const trimmed = source.trim();
  if (!trimmed || !/[\u3400-\u9fff]/u.test(trimmed)) {
    trackedText.delete(node);
    return;
  }
  const selectedCount = /^已选 (\d+) 项$/u.exec(trimmed);
  const translated = language === 'zh-CN'
    ? trimmed
    : selectedCount
      ? translations['已选 {count} 项']?.replace('{count}', selectedCount[1] ?? '0')
      : translations[trimmed];
  if (!translated) return;
  const leading = source.slice(0, source.indexOf(trimmed));
  const trailing = source.slice(source.indexOf(trimmed) + trimmed.length);
  const next = `${leading}${translated}${trailing}`;
  trackedText.set(node, { last: next, source });
  if (current !== next) node.nodeValue = next;
}

function translateAttributes(element: Element) {
  if (!eligible(element)) return;
  let tracked = trackedAttributes.get(element);
  if (!tracked) {
    tracked = new Map();
    trackedAttributes.set(element, tracked);
  }
  for (const name of attributes) {
    const current = element.getAttribute(name);
    if (current === null) continue;
    const previous = tracked.get(name);
    const source = previous?.last === current ? previous.source : current;
    if (!/[\u3400-\u9fff]/u.test(source)) {
      tracked.delete(name);
      continue;
    }
    const next = language === 'zh-CN' ? source : translations[source];
    if (!next) continue;
    tracked.set(name, { last: next, source });
    if (current !== next) element.setAttribute(name, next);
  }
}

function translateTree(node: Node) {
  if (window.location.pathname.includes('/web-terminal')) return;
  if (node.nodeType === Node.TEXT_NODE) {
    translateText(node as Text);
    return;
  }
  if (node.nodeType !== Node.ELEMENT_NODE) return;
  const element = node as Element;
  if (element.closest(excluded)) return;
  if (eligible(element)) translateAttributes(element);
  for (const child of element.childNodes) translateTree(child);
}

function installUiCopyTranslation() {
  const observer = new MutationObserver((changes) => {
    for (const change of changes) {
      if (change.type === 'characterData') translateTree(change.target);
      if (change.type === 'attributes') translateAttributes(change.target as Element);
      if (change.type === 'childList') {
        for (const node of change.addedNodes) translateTree(node);
      }
    }
  });
  observer.observe(document.body, {
    attributeFilter: attributes,
    attributes: true,
    characterData: true,
    childList: true,
    subtree: true,
  });
  watch(() => i18n.global.locale.value, async (locale) => {
    const currentRevision = ++revision;
    const code = locale === 'zh-TW' ? 'zh-TW' : locale.split('-')[0];
    const module = localeFiles[`./ui-copy/${code}.json`];
    const nextTranslations = module ? await module() : {};
    if (currentRevision !== revision) return;
    language = locale;
    translations = nextTranslations;
    translateTree(document.body);
  }, { immediate: true });
}

export { installUiCopyTranslation };
