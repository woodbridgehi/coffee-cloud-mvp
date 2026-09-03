/* Coffee Cloud — 内联 SVG 图标库（viewBox 24 / stroke 1.5 / 圆端点）
   用法：<i data-cc-icon="dashboard" data-size="20"></i> 或 ccIcon('name', 20) */
(function (global) {
  'use strict';
  var P = {
    'dashboard': '<rect x="3" y="3" width="7.5" height="7.5" rx="1.5"/><rect x="13.5" y="3" width="7.5" height="7.5" rx="1.5"/><rect x="3" y="13.5" width="7.5" height="7.5" rx="1.5"/><rect x="13.5" y="13.5" width="7.5" height="7.5" rx="1.5"/>',
    'orders': '<path d="M6 3h12a1 1 0 0 1 1 1v17l-3-2-2.5 2L11 19l-2.5 2L6 19l-2 2V4a1 1 0 0 1 1-1Z"/><path d="M8 8h8M8 12h6"/>',
    'report': '<path d="M4 20V10M10 20V4M16 20v-8M22 20H2"/>',
    'device': '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M5 9h14M9 13h6M12 13v4"/><path d="M9 3V2h6v1"/>',
    'store': '<path d="M4 10 5.5 4h13L20 10"/><path d="M4 10a2.5 2.5 0 0 0 5 0 2.5 2.5 0 0 0 5 0 2.5 2.5 0 0 0 5 0"/><path d="M5 12v8h14v-8"/><path d="M9 20v-5h6v5"/>',
    'transfer': '<path d="M8 7h13m0 0-3.5-3.5M21 7l-3.5 3.5"/><path d="M16 17H3m0 0 3.5-3.5M3 17l3.5 3.5"/>',
    'price': '<path d="M3 11V4a1 1 0 0 1 1-1h7l10 10-8 8L3 11Z"/><circle cx="8" cy="8" r="1.5"/>',
    'material': '<path d="M21 8.5 12 3 3 8.5v7L12 21l9-5.5v-7Z"/><path d="M3 8.5 12 14l9-5.5M12 14v7"/>',
    'inventory': '<path d="m12 2 9 5-9 5-9-5 9-5Z"/><path d="m3 12 9 5 9-5"/><path d="m3 17 9 5 9-5"/>',
    'movement': '<path d="M7 3v18M3 7l4-4 4 4"/><path d="M17 21V3m4 4-4-4-4 4"/>',
    'expense': '<rect x="3" y="6" width="18" height="13" rx="2"/><path d="M3 10h18"/><path d="M7 15h4"/>',
    'members': '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><path d="M16 5a3.5 3.5 0 0 1 0 7M15.5 14.5a6.5 6.5 0 0 1 6 5.5"/>',
    'invite': '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>',
    'account': '<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20"/><path d="M6 15h4"/>',
    'settings': '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1 1.55V21a2 2 0 1 1-4 0v-.09a1.7 1.7 0 0 0-1-1.55 1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.7 1.7 0 0 0 .34-1.87 1.7 1.7 0 0 0-1.55-1H3a2 2 0 1 1 0-4h.09a1.7 1.7 0 0 0 1.55-1 1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.7 1.7 0 0 0 1.87.34h.09a1.7 1.7 0 0 0 1-1.55V3a2 2 0 1 1 4 0v.09a1.7 1.7 0 0 0 1 1.55 1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.7 1.7 0 0 0-.34 1.87v.09a1.7 1.7 0 0 0 1.55 1H21a2 2 0 1 1 0 4h-.09a1.7 1.7 0 0 0-1.55 1Z"/>',
    'audit': '<path d="M12 3 4 6v5c0 5 3.4 8.6 8 10 4.6-1.4 8-5 8-10V6l-8-3Z"/><path d="m9 12 2 2 4-4"/>',
    'demo': '<path d="M10 3h4M11 3v5.5L5.5 18a2 2 0 0 0 1.8 3h9.4a2 2 0 0 0 1.8-3L13 8.5V3"/><path d="M8 15h8"/>',
    'search': '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>',
    'chev-down': '<path d="m6 9 6 6 6-6"/>',
    'chev-right': '<path d="m9 6 6 6-6 6"/>',
    'chev-left': '<path d="m15 6-6 6 6 6"/>',
    'close': '<path d="M18 6 6 18M6 6l12 12"/>',
    'check': '<path d="m5 12 5 5L20 7"/>',
    'copy': '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
    'refresh': '<path d="M21 12a9 9 0 1 1-2.64-6.36"/><path d="M21 3v6h-6"/>',
    'plus': '<path d="M12 5v14M5 12h14"/>',
    'alert-triangle': '<path d="M10.3 4.1 2.9 17a2 2 0 0 0 1.7 3h14.8a2 2 0 0 0 1.7-3L13.7 4.1a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4M12 17h.01"/>',
    'alert-circle': '<circle cx="12" cy="12" r="9"/><path d="M12 8v4M12 16h.01"/>',
    'info': '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
    'clock': '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    'brand-symbol': '<rect x="5.5" y="4" width="9" height="13.5" rx="2.5" stroke="currentColor" stroke-width="1.6" fill="none"/><path d="M14.5 9a2.5 2.5 0 0 1 0 4.5" stroke="currentColor" stroke-width="1.6"/><path d="M8 8.5h4" stroke="#B78A52" stroke-width="1.8" stroke-linecap="round"/>',
    'coffee': '<path d="M17 8h1.5a2.5 2.5 0 0 1 0 5H17"/><path d="M4 8h13v6a5 5 0 0 1-5 5H9a5 5 0 0 1-5-5V8Z"/><path d="M8 3c0 1-1 1.5-1 2.5S8 7 8 7M12 3c0 1-1 1.5-1 2.5S12 7 12 7"/>',
    'logout': '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5M21 12H9"/>',
    'user': '<circle cx="12" cy="8" r="4"/><path d="M5 21a7 7 0 0 1 14 0"/>',
    'menu': '<path d="M4 6h16M4 12h16M4 18h16"/>',
    'filter': '<path d="M3 5h18l-7 8v5.5L10 21v-8L3 5Z"/>',
    'download': '<path d="M12 3v12m0 0 4-4m-4 4-4-4"/><path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/>',
    'external': '<path d="M14 4h6v6"/><path d="M20 4 11 13"/><path d="M19 14v5a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h5"/>',
    'edit': '<path d="M12 4H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-6"/><path d="M17.5 3.5a2.1 2.1 0 0 1 3 3L11 16l-4 1 1-4 9.5-9.5Z"/>',
    'lock': '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    'eye': '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>',
    'eye-off': '<path d="M3 3l18 18"/><path d="M10.6 5.1A9.8 9.8 0 0 1 12 5c6.5 0 10 7 10 7a17.4 17.4 0 0 1-3.2 4"/><path d="M6.6 6.6A16.7 16.7 0 0 0 2 12s3.5 7 10 7a9.7 9.7 0 0 0 4.3-1"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/>',
    'key': '<circle cx="8" cy="15" r="4.5"/><path d="m11.5 11.5 8-8M17 4l3 3M14 7l3 3"/>',
    'power': '<path d="M12 3v9"/><path d="M18.4 6.6a9 9 0 1 1-12.8 0"/>',
    'shield': '<path d="M12 3 4 6v5c0 5 3.4 8.6 8 10 4.6-1.4 8-5 8-10V6l-8-3Z"/>',
    'bell': '<path d="M6 9a6 6 0 0 1 12 0c0 5 2 6 2 6H4s2-1 2-6"/><path d="M10.3 20a2 2 0 0 0 3.4 0"/>',
    'mail': '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>',
    'trash': '<path d="M4 7h16M10 11v6M14 11v6"/><path d="M6 7l1 13a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-13"/><path d="M9 7V4h6v3"/>',
    'wifi-off': '<path d="m2 2 20 20"/><path d="M8.8 16.9a5 5 0 0 1 6.4 0"/><path d="M5 13a10 10 0 0 1 3-2"/><path d="M19 13a10 10 0 0 0-5.6-2.7"/><path d="M2 8.8A15 15 0 0 1 7 6.3M22 8.8a15 15 0 0 0-8.3-2.8"/><circle cx="12" cy="20" r="0.5"/>',
    'history': '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l3 2"/>',
    'play': '<path d="M7 4.5 19 12 7 19.5v-15Z"/>',
    'package': '<path d="M21 8.5 12 3 3 8.5v7L12 21l9-5.5v-7Z"/><path d="M3 8.5 12 14l9-5.5M12 14v7"/>',
    'building': '<rect x="4" y="3" width="16" height="18" rx="1"/><path d="M9 21v-4h6v4"/><path d="M8 7h2M8 11h2M14 7h2M14 11h2"/>',
    'sparkle': '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M5.6 5.6l2.8 2.8M15.6 15.6l2.8 2.8M18.4 5.6l-2.8 2.8M8.4 15.6l-2.8 2.8"/>',
    'cmd': '<path d="M6 3a3 3 0 1 1 3 3v12a3 3 0 1 1-3-3h12a3 3 0 1 1-3 3V6a3 3 0 1 1 3 3H6Z"/>'
  };

  function ccIcon(name, size, cls) {
    var d = P[name];
    if (!d) return '';
    size = size || 20;
    return '<svg width="' + size + '" height="' + size + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"' + (cls ? ' class="' + cls + '"' : '') + '>' + d + '</svg>';
  }

  function paint(root) {
    (root || document).querySelectorAll('i[data-cc-icon]').forEach(function (el) {
      var html = ccIcon(el.getAttribute('data-cc-icon'), parseInt(el.getAttribute('data-size') || '20', 10));
      if (html) { el.outerHTML = html; }
    });
  }

  global.ccIcon = ccIcon;
  global.ccPaintIcons = paint;
  document.addEventListener('DOMContentLoaded', function () { paint(); });
})(window);
