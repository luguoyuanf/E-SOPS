type PublicLanguageData = { translations?: Record<string, string> };
export function translate(text: string, values: Record<string, string | number> = {}) {
  const raw = document.getElementById('public-language-data')?.textContent;
  const data: PublicLanguageData = raw ? JSON.parse(raw) : {};
  let result = data.translations?.[text] || text;
  for (const [key, value] of Object.entries(values)) result = result.replace(`{${key}}`, String(value));
  return result;
}

/** Limit legacy captcha copy adaptation to this standalone public entry. */
export function translateCaptcha(root: HTMLElement) {
  function update() {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node = walker.nextNode();
    while (node) {
      const value = node.textContent || '';
      let localized = translate(value.trim());
      if (/^[\d.]+s 验证通过$/.test(value)) localized = value.replace('验证通过', translate('验证通过'));
      if (localized !== value.trim()) node.textContent = value.replace(value.trim(), localized);
      node = walker.nextNode();
    }
    for (const element of root.querySelectorAll<HTMLElement>('[aria-label], [alt]')) {
      for (const attribute of ['aria-label', 'alt']) {
        const value = element.getAttribute(attribute);
        if (value && translate(value) !== value) element.setAttribute(attribute, translate(value));
      }
    }
  }
  const observer = new MutationObserver(update);
  observer.observe(root, {subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['aria-label','alt']});
  update();
}
