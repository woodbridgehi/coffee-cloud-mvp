/* ============================================================
   Coffee Cloud · 设备运营台（纯展示模块，无 DOM 依赖）
   从 admin.js 抽出的格式化函数，供页面与 Node 回归测试
   （tests/admin-format.test.mjs）共用。
   数据正确性约定：
   - 金额（分）为 null / undefined / 非数值时返回「—」，
     绝不把未知金额渲染成 ¥0.00；
   - 金额用整数算术换算，避免浮点误差；
   - 百分比缺失返回「—」，不显示 0%。
   ============================================================ */

export const UNKNOWN_LABEL = '—';

function numeric(value) {
  return typeof value === 'number' || (typeof value === 'string' && value.trim() !== '');
}

/** 金额（分）→ 展示字符串；未知返回「—」。 */
export function fmtMoney(minor, currency) {
  if (!numeric(minor)) return UNKNOWN_LABEL;
  const n = Number(minor);
  if (!Number.isSafeInteger(n)) return UNKNOWN_LABEL;
  const sign = n < 0 ? '-' : '';
  const abs = Math.abs(n);
  const body = `${Math.floor(abs / 100)}.${String(abs % 100).padStart(2, '0')}`;
  return currency === 'CNY' || !currency ? `${sign}¥${body}` : `${sign}${body} ${currency}`;
}

/** UTC ISO / Date → 本地展示「MM-DD HH:mm:ss」。 */
export function fmtTime(value) {
  if (!value) return '—';
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString('zh-CN', {
    hour12: false, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit',
  });
}

/** 相对时间；now 可注入便于测试。 */
export function fmtAgo(value, now = Date.now()) {
  if (!value) return '从未';
  const ms = now - new Date(value).getTime();
  if (!Number.isFinite(ms)) return '—';
  const sec = Math.round(ms / 1000);
  if (sec < 0) return fmtTime(value);
  if (sec < 60) return `${sec} 秒前`;
  if (sec < 3600) return `${Math.round(sec / 60)} 分钟前`;
  if (sec < 86400) return `${Math.round(sec / 3600)} 小时前`;
  return `${Math.round(sec / 86400)} 天前`;
}

/** 比率（0–1）→ 百分比；缺失返回「—」。 */
export function fmtPercent(rate) {
  if (!numeric(rate)) return UNKNOWN_LABEL;
  const n = Number(rate);
  if (!Number.isFinite(n)) return UNKNOWN_LABEL;
  return `${(n * 100).toFixed(1)}%`;
}
