/* ============================================================
   Coffee Cloud · B 端客户后台（纯工具模块，无 DOM 依赖）
   金额：整数分；数量：十进制字符串；日期：YYYY-MM-DD 或 UTC ISO。
   该文件同时供 Node 纯逻辑测试（tests/merchant-ui-*.test.mjs）使用。
   ============================================================ */

export const UNKNOWN_AMOUNT_LABEL = '待补全';
export const DEFAULT_TIMEZONE = 'Asia/Shanghai';

/** 空值判断：null / undefined / 空白字符串。 */
export function isBlank(value) {
  if (value === null || value === undefined) return true;
  if (typeof value === 'string' && value.trim() === '') return true;
  return false;
}

/** 金额（分）→ 展示字符串；null/undefined 一律显示“待补全”，绝不按 0 处理。 */
export function fmtMoney(minor, { placeholder = UNKNOWN_AMOUNT_LABEL } = {}) {
  if (minor === null || minor === undefined) return placeholder;
  const n = Number(minor);
  if (!Number.isFinite(n)) return placeholder;
  const sign = n < 0 ? '-' : '';
  const abs = Math.abs(Math.round(n));
  const yuan = Math.floor(abs / 100);
  const cents = String(abs % 100).padStart(2, '0');
  return `${sign}¥${yuan.toLocaleString('en-US')}.${cents}`;
}

/** 图表纵轴等紧凑金额格式：¥1.2万 / ¥980。 */
export function fmtMoneyCompact(minor) {
  if (minor === null || minor === undefined || !Number.isFinite(Number(minor))) return '—';
  const abs = Math.abs(Number(minor));
  const sign = Number(minor) < 0 ? '-' : '';
  if (abs >= 100000000) return `${sign}¥${(abs / 100000000).toFixed(1)}亿`;
  if (abs >= 1000000) return `${sign}¥${(abs / 1000000).toFixed(1)}万`;
  if (abs >= 100000) return `${sign}¥${Math.round(abs / 100) / 10}k`;
  return `${sign}¥${Math.round(abs / 100)}`;
}

/**
 * 元字符串 → 分整数。严格校验：非负、最多两位小数、不允许 NaN / 空串 / 千分位 / 科学计数法。
 * 返回 {ok:true, minor} 或 {ok:false, reason}。
 */
export function parseYuanToMinor(text) {
  if (typeof text !== 'string') return { ok: false, reason: '请输入金额' };
  const t = text.trim();
  if (t === '') return { ok: false, reason: '请输入金额' };
  if (!/^\d+(\.\d{1,2})?$/.test(t)) {
    return { ok: false, reason: '金额必须是非负数字，最多两位小数，例如 12.50' };
  }
  const [intPart, decPart = ''] = t.split('.');
  const cents = (decPart + '00').slice(0, 2);
  return { ok: true, minor: Number(intPart) * 100 + Number(cents) };
}

/**
 * 数量输入 → 规范化十进制字符串。
 * 默认非负；allowNegative 时允许前导负号（用于盘点差额）。
 */
export function parseQuantity(text, { allowNegative = false } = {}) {
  if (typeof text !== 'string') return { ok: false, reason: '请输入数量' };
  const t = text.trim();
  if (t === '') return { ok: false, reason: '请输入数量' };
  const pattern = allowNegative ? /^-?\d+(\.\d+)?$/ : /^\d+(\.\d+)?$/;
  if (!pattern.test(t)) {
    return { ok: false, reason: allowNegative ? '数量必须是数字（盘点差额可带负号）' : '数量必须是非负数字' };
  }
  const negative = t.startsWith('-');
  const body = negative ? t.slice(1) : t;
  const [intPart, decPart = ''] = body.split('.');
  const intNorm = intPart.replace(/^0+(?=\d)/, '');
  const decNorm = decPart.replace(/0+$/, '');
  const normalized = `${negative ? '-' : ''}${intNorm}${decNorm ? '.' + decNorm : ''}`;
  return { ok: true, value: normalized };
}

/** 数量展示：按精度补齐或裁剪小数位；null → 待补全。 */
export function fmtQty(value, precision = 2) {
  if (value === null || value === undefined || value === '') return UNKNOWN_AMOUNT_LABEL;
  const n = Number(value);
  if (!Number.isFinite(n)) return UNKNOWN_AMOUNT_LABEL;
  return n.toFixed(Math.max(0, Math.min(6, Number(precision) || 0)));
}

/* ---------------- 日期与组织时区 ---------------- */

const isoDatePattern = /^\d{4}-\d{2}-\d{2}$/;

function assertIsoDate(dateStr, name = 'date') {
  if (!isoDatePattern.test(String(dateStr || ''))) {
    throw new Error(`invalid ${name}: ${dateStr}`);
  }
}

/** UTC ISO / Date → 组织时区展示 “2026-08-31 14:05”。 */
export function fmtDateTime(iso, timeZone = DEFAULT_TIMEZONE) {
  if (!iso) return '—';
  const d = iso instanceof Date ? iso : new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  try {
    return new Intl.DateTimeFormat('zh-CN', {
      timeZone, year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', hour12: false,
    }).format(d);
  } catch (_) {
    return d.toISOString().replace('T', ' ').slice(0, 16);
  }
}

/** UTC ISO → 组织时区日期 “2026-08-31”。 */
export function fmtDate(iso, timeZone = DEFAULT_TIMEZONE) {
  if (!iso) return '—';
  const d = iso instanceof Date ? iso : new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  try {
    return new Intl.DateTimeFormat('en-CA', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit' }).format(d);
  } catch (_) {
    return d.toISOString().slice(0, 10);
  }
}

/** 组织时区“今天”的 YYYY-MM-DD。 */
export function todayInTz(timeZone = DEFAULT_TIMEZONE) {
  try {
    return new Intl.DateTimeFormat('en-CA', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
  } catch (_) {
    return new Date().toISOString().slice(0, 10);
  }
}

/** YYYY-MM-DD 加减天数（纯日期算术，按 UTC，不涉时区跳变）。 */
export function addDays(dateStr, days) {
  assertIsoDate(dateStr, 'dateStr');
  const n = Number(days);
  if (!Number.isInteger(n)) throw new Error(`invalid days: ${days}`);
  const base = Date.parse(`${dateStr}T00:00:00Z`);
  const next = new Date(base + n * 86400000);
  return next.toISOString().slice(0, 10);
}

/** YYYY-MM-DD 所在月第一天。 */
export function monthStart(dateStr) {
  assertIsoDate(dateStr, 'dateStr');
  return `${dateStr.slice(0, 7)}-01`;
}

/** YYYY-MM-DD 所在年第一天。 */
export function yearStart(dateStr) {
  assertIsoDate(dateStr, 'dateStr');
  return `${dateStr.slice(0, 4)}-01-01`;
}

/** 界面“结束日期（含当日）” → API 右边界 to（不含当日）。 */
export function inclusiveEndToExclusive(endInclusive) {
  return addDays(endInclusive, 1);
}

/** API period.to（不含当日）→ 界面展示的含当日结束日期。 */
export function exclusiveEndToInclusive(toExclusive) {
  return addDays(toExclusive, -1);
}

/**
 * 日期快捷项：today / last7 / thisMonth / thisYear。
 * 返回 {from, to}（两端均含当日，用于界面展示）。
 */
export function rangeShortcut(kind, today) {
  const t = today || todayInTz();
  assertIsoDate(t, 'today');
  switch (kind) {
    case 'today':
      return { from: t, to: t };
    case 'last7':
      return { from: addDays(t, -6), to: t };
    case 'thisMonth':
      return { from: monthStart(t), to: t };
    case 'thisYear':
      return { from: yearStart(t), to: t };
    default:
      throw new Error(`unknown shortcut: ${kind}`);
  }
}

/** 校验界面日期区间（含当日，from ≤ to）。 */
export function isValidRange(from, to) {
  return isoDatePattern.test(String(from || '')) && isoDatePattern.test(String(to || '')) && from <= to;
}

/** 把日期序列按 DAY/MONTH/YEAR 归并的 key。 */
export function grainKey(dateStr, grain) {
  assertIsoDate(dateStr, 'dateStr');
  if (grain === 'MONTH') return dateStr.slice(0, 7);
  if (grain === 'YEAR') return dateStr.slice(0, 4);
  return dateStr;
}

/* ---------------- CSV ---------------- */

/** CSV 单元格转义：包含逗号/引号/换行时加引号并双写引号，防公式注入加前导空格场景由服务器负责，这里保证语法正确。 */
export function csvEscape(field) {
  const raw = field === null || field === undefined ? '' : String(field);
  if (/[",\r\n]/.test(raw)) {
    return `"${raw.replace(/"/g, '""')}"`;
  }
  return raw;
}

/** 构建 CSV 文本（BOM 由调用方决定是否附加）。 */
export function buildCsv(header, rows) {
  const lines = [header.map(csvEscape).join(',')];
  for (const row of rows) lines.push(row.map(csvEscape).join(','));
  return lines.join('\r\n');
}

/* ---------------- 数值辅助 ---------------- */

/** 百分比：分子/分母均为数值；任一缺失返回 null（缺口，不显示 0%）。 */
export function percent(part, total, { digits = 1 } = {}) {
  if (part === null || part === undefined || total === null || total === undefined) return null;
  const p = Number(part); const t = Number(total);
  if (!Number.isFinite(p) || !Number.isFinite(t) || t <= 0) return null;
  return `${((p / t) * 100).toFixed(digits)}%`;
}

/** 求和金额列表（取字段 key）：返回 {sum, hasUnknown, count}。null 记为未知，不按 0 参与展示。 */
export function sumMinor(items, key) {
  let sum = 0; let hasUnknown = false; let count = 0;
  for (const item of Array.isArray(items) ? items : []) {
    const v = item ? item[key] : undefined;
    if ((typeof v !== 'number' && typeof v !== 'string') || isBlank(v)) { hasUnknown = true; continue; }
    const n = Number(v);
    if (Number.isSafeInteger(n)) { sum += n; count += 1; }
    else { hasUnknown = true; }
  }
  return { sum, hasUnknown, count };
}

/** 适合纵轴的“整齐”刻度：返回 [0, step, 2*step, ...]。 */
export function niceTicks(maxValue, count = 4) {
  const max = Number(maxValue);
  if (!Number.isFinite(max) || max <= 0) return [0, 1, 2, 3, 4];
  const rough = max / count;
  const pow = Math.pow(10, Math.floor(Math.log10(rough)));
  const candidates = [1, 2, 2.5, 5, 10].map(m => m * pow);
  let step = candidates[0];
  for (const c of candidates) { if (c >= rough) { step = c; break; } }
  const ticks = [];
  for (let v = 0; v < max + step * 0.5; v += step) ticks.push(Math.round(v * 100) / 100);
  if (ticks[ticks.length - 1] < max) ticks.push(ticks[ticks.length - 1] + step);
  return ticks;
}

/** 邮箱格式粗校验（前端提示用，最终以后端为准）。 */
export function looksLikeEmail(text) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(String(text || '').trim());
}

/* ---------------- 用户名模式（USERNAME 注册/登录） ---------------- */

/** 与服务端约定一致的默认用户名规则：3–32 位，字母开头，后续小写字母/数字/点/下划线/连字符。 */
export const DEFAULT_USERNAME_PATTERN = '^[a-z][a-z0-9_.-]{2,31}$';

/** 用户名规范化：trim + lowercase（不区分大小写，提交前统一）。 */
export function normalizeUsername(raw) {
  return String(raw ?? '').trim().toLowerCase();
}

/**
 * 校验用户名（先规范化再匹配）。返回 {ok:true, value} 或 {ok:false, reason, value}。
 * pattern 缺省或非法时回退到 DEFAULT_USERNAME_PATTERN，绝不放行空值。
 */
export function validateUsername(raw, pattern) {
  const value = normalizeUsername(raw);
  if (!value) return { ok: false, reason: '请输入用户名', value };
  let re;
  try {
    re = new RegExp(typeof pattern === 'string' && pattern ? pattern : DEFAULT_USERNAME_PATTERN);
  } catch (_) {
    re = new RegExp(DEFAULT_USERNAME_PATTERN);
  }
  if (!re.test(value)) {
    return {
      ok: false,
      reason: '用户名需 3–32 个字符：以字母开头，后续可用小写字母、数字、点、下划线或连字符（不区分大小写，提交前会转为小写）',
      value,
    };
  }
  return { ok: true, value };
}

/**
 * 新密码长度校验：默认 15–128 个字符（配置可覆盖）。
 * 返回 {ok:true} 或 {ok:false, reason}。
 */
export function validateNewPassword(password, { passwordMinLength = 15, passwordMaxLength = 128 } = {}) {
  const min = Number(passwordMinLength) > 0 ? Math.floor(Number(passwordMinLength)) : 15;
  const max = Number(passwordMaxLength) >= min ? Math.floor(Number(passwordMaxLength)) : 128;
  const value = String(password ?? '');
  if (value.length < min || value.length > max) {
    return { ok: false, reason: `密码长度需 ${min}–${max} 个字符` };
  }
  return { ok: true };
}

/** 金额输入的浏览器 inputmode 提示值。 */
export const MONEY_INPUT_PATTERN = '\\d+(\\.\\d{1,2})?';
