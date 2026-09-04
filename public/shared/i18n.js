(function attachCoffeeI18n(global) {
  'use strict';

  const KNOWN_LOCALES = Object.freeze({
    'zh-CN': { nativeName: '简体中文', intlFallback: 'zh-CN' },
    'zh-TW': { nativeName: '繁體中文', intlFallback: 'zh-TW' },
    'en-US': { nativeName: 'English', intlFallback: 'en-US' },
    'ko-KR': { nativeName: '한국어', intlFallback: 'ko-KR' },
    'ko-KP': { nativeName: '조선말', intlFallback: 'ko-KR' },
    'ja-JP': { nativeName: '日本語', intlFallback: 'ja-JP' },
    'th-TH': { nativeName: 'ไทย', intlFallback: 'th-TH' },
    'es-ES': { nativeName: 'Español', intlFallback: 'es-ES' },
    'de-DE': { nativeName: 'Deutsch', intlFallback: 'de-DE' },
    'fr-FR': { nativeName: 'Français', intlFallback: 'fr-FR' },
    'ru-RU': { nativeName: 'Русский', intlFallback: 'ru-RU' },
  });

  const DEFAULT_LOCALE = 'zh-CN';
  const DEFAULT_STORAGE_KEY = 'coffee-cloud.locale';
  const catalogs = new Map();
  const listeners = new Set();
  let locale = DEFAULT_LOCALE;
  let fallbackLocale = DEFAULT_LOCALE;
  let storageKey = DEFAULT_STORAGE_KEY;
  let enabledLocales = ['zh-CN', 'en-US'];

  function canonicalLocale(value) {
    const raw = String(value || '').trim().replace(/_/g, '-');
    if (!raw) return null;
    const lower = raw.toLowerCase();
    if (lower === 'zh-tw' || lower === 'zh-hk' || lower === 'zh-mo' || lower === 'zh-hant') return 'zh-TW';
    if (lower === 'zh-cn' || lower === 'zh-sg' || lower === 'zh-hans' || lower === 'zh') return 'zh-CN';
    if (lower === 'ko-kp') return 'ko-KP';
    if (lower === 'ko' || lower.startsWith('ko-')) return 'ko-KR';
    if (lower === 'en' || lower.startsWith('en-')) return 'en-US';
    if (lower === 'ja' || lower.startsWith('ja-')) return 'ja-JP';
    if (lower === 'th' || lower.startsWith('th-')) return 'th-TH';
    if (lower === 'es' || lower.startsWith('es-')) return 'es-ES';
    if (lower === 'de' || lower.startsWith('de-')) return 'de-DE';
    if (lower === 'fr' || lower.startsWith('fr-')) return 'fr-FR';
    if (lower === 'ru' || lower.startsWith('ru-')) return 'ru-RU';
    return Object.keys(KNOWN_LOCALES).find(item => item.toLowerCase() === lower) || null;
  }

  function safeStorageGet(key) {
    try { return global.localStorage?.getItem(key) || null; } catch (_) { return null; }
  }

  function safeStorageSet(key, value) {
    try { global.localStorage?.setItem(key, value); } catch (_) { /* Private storage may be unavailable. */ }
  }

  function normalizeEnabled(values) {
    const result = [];
    for (const value of values || []) {
      const normalized = canonicalLocale(value);
      if (normalized && !result.includes(normalized)) result.push(normalized);
    }
    return result.length ? result : [DEFAULT_LOCALE];
  }

  function resolveLocale(candidates, supported = enabledLocales, defaultValue = fallbackLocale) {
    const allow = new Set(normalizeEnabled(supported));
    for (const candidate of candidates || []) {
      const normalized = canonicalLocale(candidate);
      if (normalized && allow.has(normalized)) return normalized;
    }
    const fallback = canonicalLocale(defaultValue);
    return fallback && allow.has(fallback) ? fallback : [...allow][0];
  }

  function registerCatalog(targetLocale, messages) {
    const normalized = canonicalLocale(targetLocale);
    if (!normalized) throw new Error(`Unsupported locale: ${targetLocale}`);
    const previous = catalogs.get(normalized) || {};
    catalogs.set(normalized, Object.freeze({ ...previous, ...(messages || {}) }));
  }

  function lookup(targetLocale, key) {
    return catalogs.get(targetLocale)?.[key];
  }

  function interpolate(template, params) {
    return String(template).replace(/\{([A-Za-z][\w]*)\}/g, (match, key) => (
      Object.prototype.hasOwnProperty.call(params, key) ? String(params[key]) : match
    ));
  }

  function renderMessage(message, params, targetLocale) {
    if (message && typeof message === 'object' && message.plural) {
      const amount = Number(params[message.plural]);
      const category = new Intl.PluralRules(intlLocale(targetLocale)).select(amount);
      const template = message[category] ?? message.other;
      return interpolate(template ?? '', params);
    }
    return interpolate(message ?? '', params);
  }

  function t(key, params = {}, options = {}) {
    const requested = options.locale ? canonicalLocale(options.locale) : locale;
    let message = lookup(requested, key);
    if (message === undefined) message = lookup(fallbackLocale, key);
    if (message === undefined && fallbackLocale !== DEFAULT_LOCALE) message = lookup(DEFAULT_LOCALE, key);
    if (message === undefined) return options.defaultValue ?? key;
    return renderMessage(message, params, requested || fallbackLocale);
  }

  function intlLocale(targetLocale = locale) {
    const normalized = canonicalLocale(targetLocale) || fallbackLocale;
    return KNOWN_LOCALES[normalized]?.intlFallback || fallbackLocale;
  }

  function applyDocumentLanguage() {
    if (global.document?.documentElement) global.document.documentElement.lang = locale;
  }

  function translateDocument(root = global.document) {
    if (!root?.querySelectorAll) return;
    const nodes = [];
    if (root.matches?.('[data-i18n]')) nodes.push(root);
    nodes.push(...root.querySelectorAll('[data-i18n]'));
    for (const node of nodes) node.textContent = t(node.dataset.i18n);
    const attributes = ['placeholder', 'title', 'aria-label'];
    for (const attribute of attributes) {
      const dataName = `i18n${attribute.split('-').map(part => part[0].toUpperCase() + part.slice(1)).join('')}`;
      const selector = `[data-${dataName.replace(/[A-Z]/g, letter => `-${letter.toLowerCase()}`)}]`;
      const attrNodes = [];
      if (root.matches?.(selector)) attrNodes.push(root);
      attrNodes.push(...root.querySelectorAll(selector));
      for (const node of attrNodes) node.setAttribute(attribute, t(node.dataset[dataName]));
    }
  }

  function setLocale(nextLocale, { persist = true, translate = true } = {}) {
    const normalized = resolveLocale([nextLocale], enabledLocales, fallbackLocale);
    if (!enabledLocales.includes(normalized)) return locale;
    const changed = normalized !== locale;
    locale = normalized;
    if (persist) safeStorageSet(storageKey, locale);
    applyDocumentLanguage();
    if (translate) translateDocument();
    if (changed) for (const listener of listeners) listener(locale);
    return locale;
  }

  function configure(options = {}) {
    storageKey = options.storageKey || DEFAULT_STORAGE_KEY;
    enabledLocales = normalizeEnabled(options.enabledLocales || enabledLocales);
    fallbackLocale = resolveLocale([options.fallbackLocale], enabledLocales, DEFAULT_LOCALE);
    const browserLocales = options.browserLocales || global.navigator?.languages || [global.navigator?.language];
    locale = resolveLocale([
      options.initialLocale,
      safeStorageGet(storageKey),
      ...browserLocales,
    ], enabledLocales, fallbackLocale);
    applyDocumentLanguage();
    if (options.translate !== false) translateDocument();
    return locale;
  }

  function onChange(listener) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  }

  function formatNumber(value, options = {}) {
    if (value === null || value === undefined || value === '') return options.placeholder ?? '—';
    const number = Number(value);
    if (!Number.isFinite(number)) return options.placeholder ?? '—';
    return new Intl.NumberFormat(intlLocale(), options).format(number);
  }

  function currencyFractionDigits(currency) {
    try {
      return new Intl.NumberFormat(intlLocale(), { style: 'currency', currency }).resolvedOptions().maximumFractionDigits;
    } catch (_) { return 2; }
  }

  function formatMoney(amountMinor, currency = 'CNY', options = {}) {
    if (amountMinor === null || amountMinor === undefined || !Number.isFinite(Number(amountMinor))) {
      return options.placeholder ?? '—';
    }
    const digits = currencyFractionDigits(currency);
    return new Intl.NumberFormat(intlLocale(), {
      style: 'currency', currency, currencyDisplay: options.currencyDisplay || 'symbol',
      minimumFractionDigits: digits, maximumFractionDigits: digits,
    }).format(Number(amountMinor) / (10 ** digits));
  }

  function formatDateTime(value, options = {}) {
    if (!value) return options.placeholder ?? '—';
    const date = value instanceof Date ? value : new Date(value);
    if (Number.isNaN(date.getTime())) return options.placeholder ?? String(value);
    const { placeholder: _placeholder, ...intlOptions } = options;
    return new Intl.DateTimeFormat(intlLocale(), {
      calendar: 'gregory', hour12: false,
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit',
      ...intlOptions,
    }).format(date);
  }

  function formatRelativeTime(value, now = Date.now()) {
    if (!value) return t('common.time.never', {}, { defaultValue: '—' });
    const timestamp = value instanceof Date ? value.getTime() : new Date(value).getTime();
    if (!Number.isFinite(timestamp)) return '—';
    const seconds = Math.round((timestamp - now) / 1000);
    let amount = seconds;
    let unit = 'second';
    if (Math.abs(seconds) >= 86400) { amount = Math.round(seconds / 86400); unit = 'day'; }
    else if (Math.abs(seconds) >= 3600) { amount = Math.round(seconds / 3600); unit = 'hour'; }
    else if (Math.abs(seconds) >= 60) { amount = Math.round(seconds / 60); unit = 'minute'; }
    return new Intl.RelativeTimeFormat(intlLocale(), { numeric: 'auto' }).format(amount, unit);
  }

  global.CoffeeI18n = Object.freeze({
    KNOWN_LOCALES, DEFAULT_LOCALE, canonicalLocale, resolveLocale, registerCatalog,
    configure, setLocale, getLocale: () => locale, getEnabledLocales: () => [...enabledLocales],
    t, translateDocument, onChange, formatNumber, formatMoney, formatDateTime, formatRelativeTime,
  });
})(globalThis);
