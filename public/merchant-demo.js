/* ============================================================
   Coffee Cloud · B 端客户后台 · 显式演示适配器（仅 ?demo=1 启用）
   - 不是支付网关，也不是业务系统实现；数据只存在当前页面内存，
     刷新即清空；不发送任何 merchant / admin API 请求。
   - 与真实适配器导出同名同形方法，业务视图不区分两套流程。
   - 数据由确定性 fixture / 公式生成：同一日期每次计算结果一致，
     不随机波动；缺成本不补零。
   ============================================================ */

import { MerchantError } from './merchant-api.js';
import { addDays, grainKey, monthStart, todayInTz } from './merchant-format.js';

export const DEMO_ROLES = ['OWNER', 'OPERATOR', 'FINANCE'];

const ALL_PERMISSIONS = [
  'dashboard.read', 'devices.read', 'devices.manage', 'devices.claim', 'devices.transfer',
  'commands.execute', 'stores.read', 'stores.manage', 'orders.read', 'refunds.manage',
  'prices.read', 'prices.manage', 'inventory.read', 'inventory.manage', 'costs.read',
  'costs.manage', 'reports.read', 'reports.export', 'members.read', 'members.manage',
  'payments.read', 'payments.manage', 'tenant.manage', 'audit.read',
];

const ROLE_PERMISSIONS = {
  OWNER: ALL_PERMISSIONS,
  FINANCE: ['dashboard.read', 'devices.read', 'stores.read', 'orders.read', 'prices.read',
    'inventory.read', 'costs.read', 'reports.read', 'reports.export', 'payments.read'],
  OPERATOR: ['dashboard.read', 'devices.read', 'devices.manage', 'commands.execute',
    'stores.read', 'orders.read', 'inventory.read', 'inventory.manage', 'prices.read'],
};

function err(status, code, message, options) { return new MerchantError(status, code, message, options); }

function hashString(text) {
  let h = 2166136261;
  for (const ch of String(text)) {
    h ^= ch.charCodeAt(0);
    h = Math.imul(h, 16777619) >>> 0;
  }
  return h;
}

function clone(value) {
  if (typeof structuredClone === 'function') return structuredClone(value);
  return JSON.parse(JSON.stringify(value));
}

/* ---------------- 确定性经营事实（同日期结果恒定） ---------------- */

function dayFact(dateStr, scale) {
  const h = hashString(`fact:${dateStr}`);
  const wd = new Date(`${dateStr}T00:00:00Z`).getUTCDay();
  const workday = wd >= 1 && wd <= 5;
  const cups = Math.max(2, Math.round(((workday ? 18 : 9) + (h % 7) - 3) * scale));
  const received = cups * 1580 + (h % 5) * 120;
  const refunded = h % 13 === 5 ? Math.round(received * 0.06) : 0;
  const recognized = Math.round(received * 0.97) - refunded;
  const missingCost = h % 11 === 3;
  const material = missingCost ? null : Math.round(received * (0.30 + (h % 6) / 100));
  const waste = material === null ? null : Math.round(material * 0.04);
  const fee = Math.round(received * 0.006) + 30;
  const opex = 1200 + (h % 4) * 260;
  const deliveredCups = cups - (h % 17 === 2 ? 1 : 0);
  const profit = material === null || waste === null ? null : recognized - material - waste - fee - opex;
  return {
    receivedMinor: received, refundedMinor: refunded, netCashMinor: received - refunded,
    recognizedRevenueMinor: recognized, materialCostMinor: material, wasteCostMinor: waste,
    paymentFeeMinor: fee, operatingExpenseMinor: opex, estimatedProfitMinor: profit,
    deliveredCupCount: deliveredCups,
  };
}

const MONEY_KEYS = ['receivedMinor', 'refundedMinor', 'netCashMinor', 'recognizedRevenueMinor',
  'materialCostMinor', 'wasteCostMinor', 'paymentFeeMinor', 'operatingExpenseMinor', 'estimatedProfitMinor'];

function emptyFact() {
  const fact = { deliveredCupCount: 0 };
  for (const key of MONEY_KEYS) fact[key] = 0;
  return fact;
}

function addFact(target, fact) {
  /* 任一侧未知 → 合计记为未知（null），绝不按 0 参与展示 */
  target.deliveredCupCount += fact.deliveredCupCount || 0;
  for (const key of MONEY_KEYS) {
    const unknown = target[key] === null || target[key] === undefined || fact[key] === null || fact[key] === undefined;
    target[key] = unknown ? null : target[key] + fact[key];
  }
}

function iterateDates(from, toExclusive) {
  const out = [];
  for (let d = from; d < toExclusive; d = addDays(d, 1)) out.push(d);
  return out;
}

/* ---------------- 内存数据库 ---------------- */

function buildDb() {
  const db = {
    tenants: {
      't-morning': { id: 't-morning', name: '晨光咖啡', timezone: 'Asia/Shanghai', version: 4, factor: 1 },
      't-harbor': { id: 't-harbor', name: '临港商务中心', timezone: 'Asia/Shanghai', version: 2, factor: 0.55 },
    },
    stores: [
      { id: 'st-101', tenantId: 't-morning', name: '中环广场店', address: '湖滨路 88 号中环广场 B1-12', status: 'ACTIVE', version: 2 },
      { id: 'st-102', tenantId: 't-morning', name: '滨江创意园店', address: '江畔路 6 号创意园 3 栋大厅', status: 'ACTIVE', version: 1 },
      { id: 'st-201', tenantId: 't-harbor', name: '高铁站候车厅店', address: '临港高铁站二层候车厅 A 区', status: 'ACTIVE', version: 1 },
      { id: 'st-202', tenantId: 't-harbor', name: '写字楼大堂店', address: '海港大道 1 号 A 座大堂', status: 'ACTIVE', version: 3 },
    ],
    devices: [],
    materials: [
      { id: 'mt-beans', tenantId: 't-morning', name: '咖啡豆·意式拼配', unit: 'g', unitPrecision: 0, status: 'ACTIVE', averageUnitCostMinor: 850 },
      { id: 'mt-milk', tenantId: 't-morning', name: '鲜牛奶', unit: 'ml', unitPrecision: 0, status: 'ACTIVE', averageUnitCostMinor: 12 },
      { id: 'mt-cup', tenantId: 't-morning', name: '纸杯·中杯', unit: '个', unitPrecision: 0, status: 'ACTIVE', averageUnitCostMinor: 45 },
      { id: 'mt-syrup', tenantId: 't-morning', name: '香草糖浆', unit: 'ml', unitPrecision: 0, status: 'ACTIVE', averageUnitCostMinor: null },
      { id: 'mt-beans-h', tenantId: 't-harbor', name: '咖啡豆·深烘', unit: 'g', unitPrecision: 0, status: 'ACTIVE', averageUnitCostMinor: 910 },
      { id: 'mt-milk-h', tenantId: 't-harbor', name: '常温奶', unit: 'ml', unitPrecision: 0, status: 'ACTIVE', averageUnitCostMinor: 10 },
      { id: 'mt-cup-h', tenantId: 't-harbor', name: '纸杯·大杯', unit: '个', unitPrecision: 0, status: 'ACTIVE', averageUnitCostMinor: 52 },
    ],
    inventory: {},   // `${storeId}|${deviceId}` → {materialId: onHand}; reserved 单列
    orders: [],
    purchases: [],
    movements: [],
    expenses: [],
    members: [
      { id: 'mb-1', tenantId: 't-morning', displayName: '演示用户', email: 'owner@demo.local', role: 'OWNER', status: 'ACTIVE', storeScope: { mode: 'ALL', storeIds: [] }, version: 3 },
      { id: 'mb-2', tenantId: 't-morning', displayName: '王财务', email: 'finance@demo.local', role: 'FINANCE', status: 'ACTIVE', storeScope: { mode: 'ALL', storeIds: [] }, version: 1 },
      { id: 'mb-3', tenantId: 't-morning', displayName: '李运维', email: 'ops@demo.local', role: 'OPERATOR', status: 'ACTIVE', storeScope: { mode: 'SELECTED', storeIds: ['st-101'] }, version: 2 },
      { id: 'mb-4', tenantId: 't-morning', displayName: '陈离岗', email: 'former@demo.local', role: 'OPERATOR', status: 'SUSPENDED', storeScope: { mode: 'SELECTED', storeIds: ['st-102'] }, version: 4 },
      { id: 'mb-5', tenantId: 't-harbor', displayName: '演示用户', email: 'owner@demo.local', role: 'FINANCE', status: 'ACTIVE', storeScope: { mode: 'ALL', storeIds: [] }, version: 1 },
      { id: 'mb-6', tenantId: 't-harbor', displayName: '赵经理', email: 'manager@demo.local', role: 'OWNER', status: 'ACTIVE', storeScope: { mode: 'ALL', storeIds: [] }, version: 1 },
    ],
    invitations: [
      { id: 'inv-1', tenantId: 't-morning', email: 'new-finance@demo.local', role: 'FINANCE', status: 'PENDING', deliveryStatus: 'QUEUED', expiresAt: null, version: 1 },
    ],
    paymentAccounts: [
      { id: 'pa-1', tenantId: 't-morning', label: '支付宝·正式账户', provider: 'alipay', environment: 'LIVE', appIdMasked: '20****03', merchantIdMasked: '2088****77', status: 'ACTIVE', isDefault: true, version: 2, configuredAt: '2026-08-02T03:20:00Z', checks: [{ name: '密钥格式', status: 'PASS', message: '私钥可解析' }, { name: '签名自检', status: 'PASS', message: '网关验签通过' }] },
      { id: 'pa-2', tenantId: 't-morning', label: '沙箱联调账户', provider: 'alipay', environment: 'SANDBOX', appIdMasked: '90****11', merchantIdMasked: '2088****22', status: 'ACTIVE', isDefault: false, version: 1, configuredAt: '2026-08-12T06:00:00Z', checks: [{ name: '密钥格式', status: 'PASS', message: '私钥可解析' }, { name: '签名自检', status: 'FAIL', message: '公钥与商户不匹配' }] },
      { id: 'pa-3', tenantId: 't-morning', label: '模拟渠道账户', provider: 'alipay_mock', environment: 'MOCK', appIdMasked: 'mo****01', merchantIdMasked: 'mock-****01', status: 'ACTIVE', isDefault: false, version: 1, configuredAt: '2026-08-15T02:00:00Z', checks: [{ name: '密钥格式', status: 'PASS', message: '演示密钥' }] },
      { id: 'pa-4', tenantId: 't-harbor', label: '支付宝·正式账户', provider: 'alipay', environment: 'LIVE', appIdMasked: '20****66', merchantIdMasked: '2088****31', status: 'ACTIVE', isDefault: true, version: 1, configuredAt: '2026-08-05T08:00:00Z', checks: [{ name: '密钥格式', status: 'PASS', message: '私钥可解析' }, { name: '签名自检', status: 'PASS', message: '网关验签通过' }] },
    ],
    transfers: [],
    prices: [],
    audit: [],
    commandStates: {},
  };

  const today = todayInTz('Asia/Shanghai');

  /* 设备 8 台：在线 / 离线 / 停用 / 未激活 */
  const deviceDefs = [
    { id: 'dv-1', tenantId: 't-morning', deviceId: 'CC-BOT-0101', name: '中环广场·1号机', serialNumber: 'SN-A0101', storeId: 'st-101', lifecycle: 'ACTIVE', online: true, lastSeenAgoMin: 1, ownershipVersion: 1, version: 2 },
    { id: 'dv-2', tenantId: 't-morning', deviceId: 'CC-BOT-0102', name: '中环广场·2号机', serialNumber: 'SN-A0102', storeId: 'st-101', lifecycle: 'ACTIVE', online: true, lastSeenAgoMin: 3, ownershipVersion: 1, version: 1 },
    { id: 'dv-3', tenantId: 't-morning', deviceId: 'CC-BOT-0103', name: '中环广场·3号机', serialNumber: 'SN-A0103', storeId: 'st-101', lifecycle: 'SUSPENDED', online: false, lastSeenAgoMin: 4320, ownershipVersion: 2, version: 5 },
    { id: 'dv-4', tenantId: 't-morning', deviceId: 'CC-BOT-0201', name: '滨江·大堂机', serialNumber: 'SN-B0201', storeId: 'st-102', lifecycle: 'ACTIVE', online: true, lastSeenAgoMin: 2, ownershipVersion: 1, version: 1 },
    { id: 'dv-5', tenantId: 't-morning', deviceId: 'CC-BOT-0202', name: '滨江·露台机', serialNumber: 'SN-B0202', storeId: 'st-102', lifecycle: 'PENDING_ACTIVATION', online: false, lastSeenAgoMin: null, ownershipVersion: 1, version: 1 },
    { id: 'dv-6', tenantId: 't-morning', deviceId: 'CC-BOT-0203', name: '滨江·会议室机', serialNumber: 'SN-B0203', storeId: 'st-102', lifecycle: 'ACTIVE', online: false, lastSeenAgoMin: 2880, ownershipVersion: 3, version: 3 },
    { id: 'dv-7', tenantId: 't-harbor', deviceId: 'CC-BOT-0301', name: '高铁站·A口机', serialNumber: 'SN-C0301', storeId: 'st-201', lifecycle: 'ACTIVE', online: true, lastSeenAgoMin: 1, ownershipVersion: 1, version: 2 },
    { id: 'dv-8', tenantId: 't-harbor', deviceId: 'CC-BOT-0401', name: '写字楼·1F机', serialNumber: 'SN-D0401', storeId: 'st-202', lifecycle: 'ARCHIVED', online: false, lastSeenAgoMin: 44640, ownershipVersion: 2, version: 4 },
  ];
  for (const def of deviceDefs) {
    const device = { ...def, lastSeenAt: def.lastSeenAgoMin === null ? null : new Date(Date.now() - def.lastSeenAgoMin * 60000).toISOString() };
    db.devices.push(device);
  }

  /* 库存初始量 */
  for (const device of db.devices) {
    const key = `${device.storeId}|${device.id}`;
    const h = hashString(key);
    db.inventory[key] = {
      'mt-beans': 4200 + (h % 900), 'mt-milk': 6400 + (h % 1200), 'mt-cup': 260 + (h % 80), 'mt-syrup': 900 + (h % 300),
      'mt-beans-h': 3000 + (h % 500), 'mt-milk-h': 5000 + (h % 800), 'mt-cup-h': 200 + (h % 60),
      reserved: { 'mt-cup': device.online ? 2 : 0 },
    };
    if (device.id === 'dv-2') db.inventory[key]['mt-milk'] = 380;      // 低库存告警示例
    if (device.id === 'dv-6') db.inventory[key]['mt-cup'] = 18;        // 危急示例
  }

  /* 价格 */
  const menu = [
    { sku: 'LATTE-M', name: '拿铁（中杯）', priceMinor: 1500 },
    { sku: 'AMERICANO-M', name: '美式（中杯）', priceMinor: 1200 },
    { sku: 'FLATWHITE-M', name: '澳白（中杯）', priceMinor: 1600 },
    { sku: 'MATCHA-L', name: '抹茶拿铁（大杯）', priceMinor: 1800 },
  ];
  for (const store of db.stores) {
    menu.forEach((item, index) => {
      db.prices.push({
        id: `pr-${store.id}-${index}`, tenantId: store.tenantId, sku: item.sku, name: item.name,
        storeId: store.id, deviceId: null, priceMinor: item.priceMinor,
        effectiveAt: `${addDays(today, -60)}T00:00:00Z`, version: 1,
      });
    });
  }
  db.prices.push({
    id: 'pr-plan-1', tenantId: 't-morning', sku: 'LATTE-M', name: '拿铁（中杯）',
    storeId: 'st-101', deviceId: null, priceMinor: 1600,
    effectiveAt: `${addDays(today, 7)}T00:00:00Z`, version: 1,
  });

  /* 订单（近 30 天，确定性状态混合） */
  for (const tenantId of Object.keys(db.tenants)) {
    const tenantDevices = db.devices.filter(d => d.tenantId === tenantId);
    let n = 0;
    for (let back = 29; back >= 0; back -= 1) {
      const date = addDays(today, -back);
      const h = hashString(`order:${tenantId}:${date}`);
      const count = 1 + (h % 3);
      for (let i = 0; i < count; i += 1) {
        n += 1;
        const device = tenantDevices[(h + i) % tenantDevices.length];
        const store = db.stores.find(s => s.id === device.storeId);
        const pick = menu[(h + i * 3) % menu.length];
        const quantity = 1 + ((h + i) % 2);
        const totalMinor = pick.priceMinor * quantity;
        const mix = n % 12;
        const createdAt = `${date}T${String(9 + (h % 9)).padStart(2, '0')}:${String((h * 7 + i * 13) % 60).padStart(2, '0')}:00Z`;
        let paymentStatus = 'PAID';
        let productionStatus = 'DELIVERED';
        let refundedMinor = 0;
        let environment = 'LIVE';
        if (mix === 7) productionStatus = 'MAKING';
        if (mix === 8) productionStatus = 'HOLD';
        if (mix === 9) { paymentStatus = 'PARTIALLY_REFUNDED'; refundedMinor = 100; }
        if (mix === 10) { paymentStatus = 'REFUNDED'; refundedMinor = totalMinor; }
        if (mix === 11) environment = 'TEST';
        const order = {
          id: `o-${tenantId}-${n}`,
          tenantId,
          orderNo: `CC${date.replace(/-/g, '')}${String(n).padStart(4, '0')}`,
          createdAt, paidAt: createdAt, deliveredAt: productionStatus === 'DELIVERED' ? createdAt : null,
          storeIdSnapshot: store.id, storeNameSnapshot: store.name,
          deviceId: device.id, deviceNameSnapshot: device.name,
          items: [{ name: pick.name, sku: pick.sku, quantity, unitPriceMinor: pick.priceMinor }],
          totalMinor, receivedMinor: totalMinor, refundedMinor,
          paymentStatus, productionStatus, environment,
        };
        order.allowedActions = (paymentStatus === 'PAID' || paymentStatus === 'PARTIALLY_REFUNDED') ? ['REFUND'] : [];
        order.costSummary = {
          status: n % 13 === 7 ? 'MISSING' : 'COMPLETE',
          materialCostMinor: n % 13 === 7 ? null : Math.round(totalMinor * 0.31),
        };
        db.orders.push(order);
      }
    }
  }

  /* 采购 / 费用 / 出入库 / 转让 fixture */
  db.purchases.push(
    {
      id: 'pu-1', tenantId: 't-morning', storeId: 'st-101', purchasedOn: addDays(today, -19), supplier: '云豆供应链',
      note: '月度主料补货', status: 'POSTED', version: 2,
      lines: [
        { materialId: 'mt-beans', materialName: '咖啡豆·意式拼配', quantity: '10', unit: 'kg', totalCostMinor: 120000 },
        { materialId: 'mt-milk', materialName: '鲜牛奶', quantity: '40', unit: 'L', totalCostMinor: 9600 },
      ],
    },
    {
      id: 'pu-2', tenantId: 't-morning', storeId: 'st-102', purchasedOn: addDays(today, -3), supplier: '鑫达包材',
      note: '纸杯补货（草稿）', status: 'DRAFT', version: 1,
      lines: [{ materialId: 'mt-cup', materialName: '纸杯·中杯', quantity: '2000', unit: '个', totalCostMinor: 4600 }],
    },
    {
      id: 'pu-3', tenantId: 't-harbor', storeId: 'st-201', purchasedOn: addDays(today, -12), supplier: '港口批发',
      note: '', status: 'POSTED', version: 1,
      lines: [{ materialId: 'mt-beans-h', materialName: '咖啡豆·深烘', quantity: '6', unit: 'kg', totalCostMinor: 78000 }],
    },
  );
  db.expenses.push(
    { id: 'ex-1', tenantId: 't-morning', category: 'RENT', amountMinor: 450000, storeId: 'st-101', deviceId: null, occurredOn: monthStart(today), allocationStart: null, allocationEnd: null, allocationMethod: 'ONCE', status: 'POSTED', note: '8 月铺位租金', version: 2 },
    { id: 'ex-2', tenantId: 't-morning', category: 'LABOR', amountMinor: 1240000, storeId: null, deviceId: null, occurredOn: monthStart(today), allocationStart: monthStart(today), allocationEnd: today, allocationMethod: 'DAILY_EQUAL', status: 'POSTED', note: '门店人员成本按日均摊', version: 1 },
    { id: 'ex-3', tenantId: 't-morning', category: 'MAINTENANCE', amountMinor: 18000, storeId: 'st-102', deviceId: 'dv-6', occurredOn: addDays(today, -6), allocationStart: null, allocationEnd: null, allocationMethod: 'ONCE', status: 'DRAFT', note: '滨江会议室机维修', version: 1 },
    { id: 'ex-4', tenantId: 't-harbor', category: 'UTILITIES', amountMinor: 96000, storeId: 'st-201', deviceId: null, occurredOn: monthStart(today), allocationStart: null, allocationEnd: null, allocationMethod: 'ONCE', status: 'POSTED', note: '候车厅电费', version: 1 },
  );
  db.movements.push(
    { id: 'mv-1', tenantId: 't-morning', type: 'RESTOCK', materialId: 'mt-beans', materialName: '咖啡豆·意式拼配', quantity: '10000', unit: 'g', sourceStoreId: null, sourceDeviceId: null, targetStoreId: 'st-101', targetDeviceId: 'dv-1', reason: '采购 pu-1 入库', createdAt: `${addDays(today, -19)}T05:00:00Z`, eventId: 'evt-mv-1' },
    { id: 'mv-2', tenantId: 't-morning', type: 'WASTE', materialId: 'mt-milk', materialName: '鲜牛奶', quantity: '500', unit: 'ml', sourceStoreId: 'st-101', sourceDeviceId: 'dv-1', targetStoreId: null, targetDeviceId: null, reason: '过期报废', createdAt: `${addDays(today, -8)}T06:30:00Z`, eventId: 'evt-mv-2' },
    { id: 'mv-3', tenantId: 't-morning', type: 'ADJUSTMENT', materialId: 'mt-cup', materialName: '纸杯·中杯', quantity: '-12', unit: '个', sourceStoreId: 'st-101', sourceDeviceId: 'dv-2', targetStoreId: null, targetDeviceId: null, reason: '盘点差异', createdAt: `${addDays(today, -2)}T09:10:00Z`, eventId: 'evt-mv-3' },
  );
  db.transfers.push(
    {
      id: 'tr-1', tenantId: 't-morning', deviceId: 'dv-6', deviceName: '滨江·会议室机', direction: 'IN',
      counterpartName: '远航餐饮（原组织）', status: 'PENDING_RECIPIENT', blockingReasons: [], version: 1,
      createdAt: `${addDays(today, -1)}T04:00:00Z`, reason: '设备随场地转让',
    },
    {
      id: 'tr-2', tenantId: 't-morning', deviceId: 'dv-1', deviceName: '中环广场·1号机', direction: 'OUT',
      counterpartName: '合作方连锁（目标组织）', status: 'BLOCKED', blockingReasons: ['存在在途生产任务', '存在处理中的退款'], version: 1,
      createdAt: `${addDays(today, -4)}T02:00:00Z`, reason: '调拨到合作门店',
    },
  );

  /* 审计 fixture */
  const auditSeed = [
    ['owner@demo.local', 'device.lifecycle.update', 'device', 'CC-BOT-0103 · 暂停', 4],
    ['finance@demo.local', 'report.export', 'report', '月度经营报表 CSV', 6],
    ['owner@demo.local', 'member.update', 'member', '李运维 · 门店范围调整', 9],
    ['ops@demo.local', 'inventory.movement.create', 'inventory', '纸杯盘点差额 −12', 12],
    ['owner@demo.local', 'payment_account.set_default', 'payment_account', '支付宝·正式账户', 15],
    ['owner@demo.local', 'device.transfer.request', 'transfer', '滨江·会议室机', 18],
    ['owner@demo.local', 'order.refund.create', 'order', 'CC202608xx0007 · 部分退款', 22],
  ];
  for (const [actor, action, resourceType, resourceLabel, back] of auditSeed) {
    db.audit.push({
      id: `au-${db.audit.length + 1}`, tenantId: 't-morning', createdAt: `${addDays(today, -back)}T08:00:00Z`,
      actorName: actor, action, resourceType, resourceLabel, outcome: 'SUCCESS', requestId: `req-demo-${db.audit.length + 1}`,
    });
  }

  return db;
}

/* ============================================================
   演示适配器
   ============================================================ */

export function createDemoAdapter() {
  let db = buildDb();
  let session = null;          // { membershipId, user }
  let faults = { empty: false, forbidden: false, network: false, slow: false };
  let emailUnavailable = false;
  let seq = 500;
  const uid = prefix => `${prefix}-${(seq += 1)}`;

  const tz = () => (session && db.tenants[currentTenantId()] ? db.tenants[currentTenantId()].timezone : 'Asia/Shanghai');
  function currentTenantId() {
    if (!session) throw err(401, 'UNAUTHORIZED', '未登录或会话已过期');
    const membership = session.memberships.find(m => m.id === session.membershipId);
    if (!membership) throw err(401, 'UNAUTHORIZED', '会话已失效');
    return membership.tenantId;
  }

  async function gate({ read = false } = {}) {
    if (faults.slow) await new Promise(resolve => setTimeout(resolve, 1300));
    if (faults.network) throw err(0, 'NETWORK', '演示：模拟网络失败');
    if (read && faults.forbidden) throw err(403, 'FORBIDDEN', '演示：模拟无权限（403）');
  }

  /* 列表读取统一入口：empty 故障返回空列表 */
  async function listGate() {
    await gate({ read: true });
    return faults.empty;
  }
  function emptyResult() { return { items: [], nextCursor: null, total: 0 }; }

  function sessionPayload() {
    const membership = session.memberships.find(m => m.id === session.membershipId);
    const tenant = db.tenants[membership.tenantId];
    const stores = db.stores.filter(s => s.tenantId === tenant.id);
    const scope = membership.role === 'OPERATOR'
      ? { mode: 'SELECTED', storeIds: [stores[0] ? stores[0].id : ''] }
      : { mode: 'ALL', storeIds: [] };
    return {
      user: { ...session.user },
      tenant: { id: tenant.id, name: tenant.name, timezone: tenant.timezone, environment: 'LIVE' },
      memberships: session.memberships.map(m => ({ ...m })),
      permissions: ROLE_PERMISSIONS[membership.role] || [],
      storeScope: scope,
      csrfToken: 'demo-csrf-token-in-memory',
      demoRole: membership.role,
    };
  }

  function requireSession() {
    if (!session) throw err(401, 'UNAUTHORIZED', '未登录或会话已过期');
    return sessionPayload();
  }

  function audit(action, resourceType, resourceLabel) {
    db.audit.unshift({
      id: uid('au'), tenantId: currentTenantId(), createdAt: new Date().toISOString(),
      actorName: session ? session.user.email : 'anonymous', action, resourceType, resourceLabel,
      outcome: 'SUCCESS', requestId: uid('req'),
    });
  }

  function versionConflict() { return err(409, 'VERSION_CONFLICT', '数据已被其他成员修改，请重新读取后再提交'); }

  function deviceSummary(device) {
    const store = db.stores.find(s => s.id === device.storeId);
    return {
      id: device.id, deviceId: device.deviceId, name: device.name, serialNumber: device.serialNumber,
      storeId: device.storeId, storeName: store ? store.name : null, lifecycle: device.lifecycle,
      online: device.online, lastSeenAt: device.lastSeenAt, ownershipVersion: device.ownershipVersion,
      version: device.version,
    };
  }

  function allowedActionsOf(device) {
    const base = ['RENAME', 'REASSIGN'];
    if (device.lifecycle === 'ACTIVE') {
      base.push('SUSPEND', 'ARCHIVE', 'REQUEST_TRANSFER', 'REQUEST_UNBIND');
      if (device.online) base.push('COMMAND_RELOAD_CONFIG', 'COMMAND_SYNC_CONFIG', 'COMMAND_CLEAN', 'COMMAND_RESTART_APP');
    } else if (device.lifecycle === 'SUSPENDED') {
      base.push('RESUME', 'ARCHIVE', 'REQUEST_UNBIND');
    } else if (device.lifecycle === 'PENDING_ACTIVATION') {
      base.push('ARCHIVE');
    }
    return base;
  }

  function deviceAlerts(device) {
    const alerts = [];
    if (device.online && device.id === 'dv-2') alerts.push({ id: 'al-milk', severity: 'WARNING', title: '鲜牛奶余量偏低', description: '预计不足 1 天用量，请尽快补货。', deviceId: device.deviceId });
    if (!device.online && device.lifecycle === 'ACTIVE') alerts.push({ id: 'al-off', severity: 'ERROR', title: '设备离线', description: `${device.name} 已超过 24 小时未上报心跳。`, deviceId: device.deviceId });
    if (device.lifecycle === 'SUSPENDED') alerts.push({ id: 'al-susp', severity: 'INFO', title: '设备已停用', description: '已暂停派发新制作任务。', deviceId: device.deviceId });
    return alerts;
  }

  function orderDetailBody(order) {
    const payments = [{
      id: `pay-${order.id}`, provider: order.environment === 'TEST' ? 'alipay_mock' : 'alipay',
      accountLabel: order.environment === 'TEST' ? '模拟渠道账户（演示）' : '支付宝·正式账户（演示）',
      environment: order.environment === 'TEST' ? 'MOCK' : 'LIVE', status: order.receivedMinor > 0 ? 'SUCCESS' : 'PENDING',
      amountMinor: order.receivedMinor,
    }];
    const refunds = [];
    if (order.paymentStatus === 'REFUNDED' || order.paymentStatus === 'PARTIALLY_REFUNDED') {
      refunds.push({ id: `rf-${order.id}-1`, amountMinor: order.refundedMinor, status: 'SUCCESS', reason: '演示退款', createdAt: order.createdAt });
    }
    if (order.paymentStatus === 'REFUNDING') {
      refunds.push({ id: `rf-${order.id}-p`, amountMinor: order.pendingRefundMinor || 100, status: 'PENDING', reason: '演示处理中退款', createdAt: order.createdAt });
    }
    const timeline = [
      { at: order.createdAt, label: '订单创建' },
      order.paidAt ? { at: order.paidAt, label: '支付成功' } : null,
      order.deliveredAt ? { at: order.deliveredAt, label: '制作交付确认' } : null,
      refunds.length ? { at: refunds[refunds.length - 1].createdAt, label: `退款 ${refunds[refunds.length - 1].status === 'SUCCESS' ? '成功' : '申请中'}` } : null,
    ].filter(Boolean);
    return { ...clone(order), payments, refunds, timeline, allowedActions: [...order.allowedActions] };
  }

  function scopeFactor(storeId) { return storeId ? 0.5 : 1; }

  function reportRows({ from, to, grain, storeId, environment }) {
    const tenantId = currentTenantId();
    const tenant = db.tenants[tenantId];
    const envFactor = environment === 'TEST' ? 0.12 : 1;
    const groups = new Map();
    for (const date of iterateDates(from, to)) {
      const fact = dayFact(date, tenant.factor * scopeFactor(storeId) * envFactor);
      const key = grainKey(date, grain);
      if (!groups.has(key)) groups.set(key, emptyFact());
      addFact(groups.get(key), fact);
    }
    const rows = Array.from(groups.entries()).sort((a, b) => (a[0] < b[0] ? -1 : 1)).map(([period, fact]) => ({
      period, ...fact,
      completeness: fact.materialCostMinor === null ? { status: 'INCOMPLETE', missing: ['material_cost'] } : { status: 'COMPLETE', missing: [] },
    }));
    return rows;
  }

  function totalsOf(rows) {
    const totals = emptyFact();
    for (const row of rows) addFact(totals, row);
    const hasUnknown = rows.some(r => r.materialCostMinor === null);
    return { totals, completeness: { status: hasUnknown ? 'INCOMPLETE' : 'COMPLETE', missing: hasUnknown ? ['material_cost'] : [] } };
  }

  /* ---------------- 适配器 ---------------- */

  const adapter = {
    kind: 'demo',

    abortAll() { /* 内存适配器无在途请求；由应用层 epoch 屏蔽旧响应 */ },
    clearSession() { session = null; },

    /* ---- 认证与会话 ---- */
    /* 与真实适配器同形：演示维持 EMAIL 注册 + 邮件可用，兼容既有测试。 */
    async authConfig() {
      return {
        registrationMode: 'EMAIL',
        passwordMinLength: 15,
        passwordMaxLength: 128,
        usernamePattern: '^[a-z][a-z0-9_.-]{2,31}$',
        mailEnabled: true,
        limitedRelease: true,
      };
    },
    async register(body) {
      await gate();
      if (!body.email || !body.password || !body.tenantName) throw err(422, 'VALIDATION_ERROR', '请完整填写注册信息');
      return { status: 'VERIFICATION_PENDING', demoHint: '演示模式可直接使用任意邮箱登录' };
    },
    async verifyEmail(body) {
      await gate();
      if (body.token !== 'demo-verify-token') throw err(404, 'TOKEN_INVALID', '验证链接无效或已使用');
      return { status: 'VERIFIED' };
    },
    async login(body) {
      await gate();
      if (!body.email || !body.password || body.password.length < 6) {
        throw err(401, 'BAD_CREDENTIALS', '邮箱或密码不正确');
      }
      session = {
        membershipId: 'mb-demo-1',
        user: { id: 'u-demo', email: body.email, displayName: '演示用户' },
        memberships: [
          { id: 'mb-demo-1', tenantId: 't-morning', tenantName: '晨光咖啡（演示）', role: 'OWNER' },
          { id: 'mb-demo-2', tenantId: 't-harbor', tenantName: '临港商务中心（演示）', role: 'FINANCE' },
        ],
      };
      audit('auth.login', 'session', '登录成功');
      return sessionPayload();
    },
    async forgotPassword(body) {
      await gate();
      void body;
      return { status: 'ACCEPTED' };
    },
    async resetPassword(body) {
      await gate();
      if (body.token !== 'demo-reset-token') throw err(404, 'TOKEN_INVALID', '重置链接无效或已使用');
      if (!body.password || body.password.length < 8) throw err(422, 'WEAK_PASSWORD', '密码至少 8 位');
      return { status: 'UPDATED' };
    },
    async acceptInvitation(body) {
      await gate();
      if (body.token !== 'demo-invite-token') throw err(404, 'TOKEN_INVALID', '邀请链接无效或已过期');
      return { status: 'ACCEPTED' };
    },
    async logout() { await gate(); session = null; return { status: 'SIGNED_OUT' }; },
    async revokeOtherSessions() { await gate(); return { revokedCount: 2 }; },
    async reauthenticate(body) {
      await gate();
      if (!body.password || body.password.length < 6) throw err(401, 'BAD_CREDENTIALS', '密码不正确');
      return { validUntil: new Date(Date.now() + 5 * 60000).toISOString() };
    },
    async getSession() { await gate({ read: true }); return requireSession(); },
    async switchTenant(membershipId) {
      await gate();
      if (!session || !session.memberships.some(m => m.id === membershipId)) {
        throw err(403, 'NOT_A_MEMBER', '当前账号不是该组织的成员');
      }
      session.membershipId = membershipId;
      return sessionPayload();
    },

    /* ---- 总览 ---- */
    async dashboard(params = {}) {
      await gate({ read: true });
      requireSession();
      const tenantId = currentTenantId();
      if (faults.empty) {
        return { period: params, environment: params.environment || 'LIVE', metrics: null, completeness: { status: 'COMPLETE', missing: [] }, trend: [], alerts: [], recentOrders: [] };
      }
      const tenant = db.tenants[tenantId];
      const envFactor = params.environment === 'TEST' ? 0.12 : 1;
      const agg = emptyFact();
      const trend = [];
      for (const date of iterateDates(params.from, params.to)) {
        const fact = dayFact(date, tenant.factor * scopeFactor(params.storeId) * envFactor);
        addFact(agg, fact);
        trend.push({ date, receivedMinor: fact.receivedMinor, estimatedProfitMinor: fact.estimatedProfitMinor });
      }
      const devices = db.devices.filter(d => d.tenantId === tenantId);
      const alerts = devices.flatMap(deviceAlerts);
      const orders = db.orders
        .filter(o => o.tenantId === tenantId && (!params.storeId || o.storeIdSnapshot === params.storeId))
        .filter(o => !params.environment || o.environment === params.environment)
        .slice(0, 8)
        .map(o => ({ id: o.id, orderNo: o.orderNo, createdAt: o.createdAt, storeNameSnapshot: o.storeNameSnapshot, deviceNameSnapshot: o.deviceNameSnapshot, totalMinor: o.totalMinor, paymentStatus: o.paymentStatus, productionStatus: o.productionStatus, environment: o.environment }));
      return {
        period: { from: params.from, to: params.to, timezone: tenant.timezone },
        environment: params.environment || 'LIVE',
        metrics: {
          deviceCount: devices.length,
          onlineCount: devices.filter(d => d.online).length,
          paidOrderCount: db.orders.filter(o => o.tenantId === tenantId && o.receivedMinor > 0).length,
          deliveredCupCount: agg.deliveredCupCount,
          ...(sessionPayload().permissions.includes('costs.read') ? agg : {}),
        },
        completeness: { status: trend.some(t => t.estimatedProfitMinor === null) ? 'INCOMPLETE' : 'COMPLETE', missing: trend.some(t => t.estimatedProfitMinor === null) ? ['material_cost'] : [] },
        trend: sessionPayload().permissions.includes('costs.read') ? trend : [],
        alerts,
        recentOrders: orders,
      };
    },

    /* ---- 设备 ---- */
    async listDevices(params = {}) {
      if (await listGate()) return emptyResult();
      requireSession();
      let items = db.devices.filter(d => d.tenantId === currentTenantId()).map(deviceSummary);
      if (params.storeId) items = items.filter(d => d.storeId === params.storeId);
      if (params.status) items = items.filter(d => d.lifecycle === params.status);
      if (params.q) {
        const q = String(params.q).toLowerCase();
        items = items.filter(d => [d.name, d.deviceId, d.serialNumber, d.storeName].join(' ').toLowerCase().includes(q));
      }
      return { items, nextCursor: null, total: items.length };
    },
    async getDevice(id) {
      await gate({ read: true });
      requireSession();
      const device = db.devices.find(d => d.id === id && d.tenantId === currentTenantId());
      if (!device) throw err(404, 'NOT_FOUND', '设备不存在或没有访问权限');
      const inv = db.inventory[`${device.storeId}|${device.id}`] || {};
      const materialIds = Object.keys(inv).filter(k => k !== 'reserved');
      const capabilities = [
        { id: 'rc-latte', name: '拿铁（中杯）', version: 3, estimatedSeconds: 150 },
        { id: 'rc-americano', name: '美式（中杯）', version: 2, estimatedSeconds: 110 },
        { id: 'rc-flatwhite', name: '澳白（中杯）', version: 1, estimatedSeconds: 160 },
      ];
      const inventory = materialIds.map(materialId => {
        const material = db.materials.find(m => m.id === materialId) || { name: materialId, unit: '' };
        const onHand = Number(inv[materialId] || 0);
        const reserved = Number((inv.reserved && inv.reserved[materialId]) || 0);
        const capacity = materialId.includes('beans') ? 10000 : materialId.includes('milk') ? 8000 : 300;
        const ratio = onHand / capacity;
        return {
          materialId, name: material.name, unit: material.unit, onHandQuantity: String(onHand),
          reservedQuantity: String(reserved), availableQuantity: String(onHand - reserved),
          status: ratio < 0.08 ? 'CRITICAL' : ratio < 0.25 ? 'LOW' : 'OK',
        };
      });
      const currentJob = device.online && device.id === 'dv-1'
        ? { id: 'job-demo-1', status: 'MAKING', productName: '拿铁（中杯）', startedAt: new Date(Date.now() - 90000).toISOString() }
        : null;
      return { ...deviceSummary(device), capabilities, inventory, currentJob, alerts: deviceAlerts(device), allowedActions: allowedActionsOf(device) };
    },
    async claimDevice(body, idempotencyKey) {
      await gate();
      requireSession();
      void idempotencyKey;
      if (body.claimCode !== 'CLAIM-DEMO-OK') throw err(404, 'CLAIM_INVALID', '认领码不存在或已被使用');
      const store = db.stores.find(s => s.id === body.storeId && s.tenantId === currentTenantId());
      if (!store) throw err(404, 'STORE_NOT_FOUND', '门店不存在或没有访问权限');
      const device = {
        id: uid('dv'), tenantId: currentTenantId(), deviceId: `CC-BOT-9${String(seq).slice(-3)}`,
        name: body.name || '新认领设备', serialNumber: `SN-${String(seq)}`, storeId: store.id,
        lifecycle: 'ACTIVE', online: false, lastSeenAt: null, ownershipVersion: 1, version: 1,
      };
      db.devices.push(device);
      db.inventory[`${device.storeId}|${device.id}`] = { 'mt-beans': 5000, 'mt-milk': 6000, 'mt-cup': 200, reserved: {} };
      audit('device.claim', 'device', `${device.deviceId} · ${device.name}`);
      return deviceSummary(device);
    },
    async updateDevice(id, body) {
      await gate();
      requireSession();
      const device = db.devices.find(d => d.id === id && d.tenantId === currentTenantId());
      if (!device) throw err(404, 'NOT_FOUND', '设备不存在或没有访问权限');
      if (Number(body.version) !== device.version) throw versionConflict();
      if (body.name !== undefined) device.name = body.name;
      if (body.storeId !== undefined) {
        const store = db.stores.find(s => s.id === body.storeId && s.tenantId === currentTenantId());
        if (!store) throw err(404, 'STORE_NOT_FOUND', '门店不存在或没有访问权限');
        device.storeId = store.id;
      }
      device.version += 1;
      audit('device.update', 'device', `${device.deviceId} · ${device.name}`);
      return deviceSummary(device);
    },
    async deviceLifecycle(id, body) {
      await gate();
      requireSession();
      const device = db.devices.find(d => d.id === id && d.tenantId === currentTenantId());
      if (!device) throw err(404, 'NOT_FOUND', '设备不存在或没有访问权限');
      if (Number(body.version) !== device.version) throw versionConflict();
      const map = { SUSPEND: 'SUSPENDED', RESUME: 'ACTIVE', ARCHIVE: 'ARCHIVED' };
      if (!map[body.action]) throw err(422, 'BAD_ACTION', '不支持的生命周期操作');
      if (device.lifecycle === 'ARCHIVED') throw err(409, 'LIFECYCLE_LOCKED', '已归档设备不能变更生命周期');
      device.lifecycle = map[body.action];
      if (body.action !== 'RESUME') device.online = false;
      device.version += 1;
      audit('device.lifecycle.update', 'device', `${device.deviceId} · ${body.action}`);
      return deviceSummary(device);
    },
    async sendDeviceCommand(id, body, idempotencyKey) {
      await gate();
      requireSession();
      const device = db.devices.find(d => d.id === id && d.tenantId === currentTenantId());
      if (!device) throw err(404, 'NOT_FOUND', '设备不存在或没有访问权限');
      if (!allowedActionsOf(device).includes(`COMMAND_${body.command}`)) {
        throw err(403, 'COMMAND_NOT_ALLOWED', '当前状态下不允许执行该命令');
      }
      const commandId = uid('cmd');
      db.commandStates[commandId] = { polls: 0, command: body.command, need: body.command === 'RESTART_APP' ? 3 : 2 };
      audit('device.command.create', 'command', `${device.deviceId} · ${body.command}`);
      return { id: commandId, status: 'PENDING' };
    },
    async getDeviceCommand(id, commandId) {
      await gate({ read: true });
      requireSession();
      const state = db.commandStates[commandId];
      if (!state) throw err(404, 'NOT_FOUND', '命令不存在或没有访问权限');
      state.polls += 1;
      if (state.polls < state.need) return { id: commandId, status: 'EXECUTING', resultMessage: null };
      return { id: commandId, status: 'SUCCEEDED', resultMessage: `命令 ${state.command} 已在设备端执行完成（演示）` };
    },
    async createUnbindRequest(id, body) {
      await gate();
      requireSession();
      const device = db.devices.find(d => d.id === id && d.tenantId === currentTenantId());
      if (!device) throw err(404, 'NOT_FOUND', '设备不存在或没有访问权限');
      if (Number(body.ownershipVersion) !== device.ownershipVersion) throw versionConflict();
      audit('device.unbind.request', 'device', `${device.deviceId}`);
      return { id: uid('ub'), status: 'PENDING_APPROVAL' };
    },
    async createTransferRequest(id, body, idempotencyKey) {
      await gate();
      requireSession();
      void idempotencyKey;
      const device = db.devices.find(d => d.id === id && d.tenantId === currentTenantId());
      if (!device) throw err(404, 'NOT_FOUND', '设备不存在或没有访问权限');
      if (Number(body.ownershipVersion) !== device.ownershipVersion) throw versionConflict();
      if (!body.targetTenantReference) throw err(422, 'VALIDATION_ERROR', '请填写目标组织');
      const blocking = [];
      if (device.id === 'dv-1') blocking.push('存在在途生产任务', '存在处理中的退款');
      if (blocking.length) {
        const transfer = { id: uid('tr'), tenantId: currentTenantId(), deviceId: device.id, deviceName: device.name, direction: 'OUT', counterpartName: body.targetTenantReference, status: 'BLOCKED', blockingReasons: blocking, version: 1, createdAt: new Date().toISOString(), reason: body.reason || '' };
        db.transfers.push(transfer);
        audit('device.transfer.request', 'transfer', `${device.name} · 阻断`);
        return { id: transfer.id, status: 'BLOCKED', blockingReasons: blocking };
      }
      const transfer = { id: uid('tr'), tenantId: currentTenantId(), deviceId: device.id, deviceName: device.name, direction: 'OUT', counterpartName: body.targetTenantReference, status: 'PENDING_PLATFORM', blockingReasons: [], version: 1, createdAt: new Date().toISOString(), reason: body.reason || '' };
      db.transfers.push(transfer);
      audit('device.transfer.request', 'transfer', `${device.name}`);
      return { id: transfer.id, status: 'PENDING_PLATFORM', blockingReasons: [] };
    },
    async listTransfers() {
      if (await listGate()) return emptyResult();
      requireSession();
      return { items: db.transfers.filter(t => t.tenantId === currentTenantId()).map(t => ({ ...t })), nextCursor: null, total: db.transfers.length };
    },
    async acceptTransfer(id, body) {
      await gate();
      requireSession();
      const transfer = db.transfers.find(t => t.id === id && t.tenantId === currentTenantId());
      if (!transfer) throw err(404, 'NOT_FOUND', '转让记录不存在或没有访问权限');
      if (Number(body.version) !== transfer.version) throw versionConflict();
      if (transfer.status !== 'PENDING_RECIPIENT') throw err(409, 'BAD_STATE', '当前状态不能接受转让');
      transfer.status = 'COMPLETED';
      transfer.version += 1;
      audit('device.transfer.accept', 'transfer', `${transfer.deviceName}`);
      return { ...transfer };
    },
    async cancelTransfer(id, body) {
      await gate();
      requireSession();
      const transfer = db.transfers.find(t => t.id === id && t.tenantId === currentTenantId());
      if (!transfer) throw err(404, 'NOT_FOUND', '转让记录不存在或没有访问权限');
      if (Number(body.version) !== transfer.version) throw versionConflict();
      if (transfer.status === 'COMPLETED') throw err(409, 'BAD_STATE', '已完成的转让不能取消');
      transfer.status = 'CANCELLED';
      transfer.version += 1;
      audit('device.transfer.cancel', 'transfer', `${transfer.deviceName}`);
      return { ...transfer };
    },

    /* ---- 门店与价格 ---- */
    async listStores() {
      if (await listGate()) return emptyResult();
      requireSession();
      const items = db.stores.filter(s => s.tenantId === currentTenantId()).map(s => ({
        ...s, deviceCount: db.devices.filter(d => d.storeId === s.id && d.tenantId === s.tenantId).length,
      }));
      return { items, nextCursor: null, total: items.length };
    },
    async createStore(body) {
      await gate();
      requireSession();
      if (!body.name) throw err(422, 'VALIDATION_ERROR', '请填写门店名称');
      const store = { id: uid('st'), tenantId: currentTenantId(), name: body.name, address: body.address || '', status: 'ACTIVE', version: 1 };
      db.stores.push(store);
      audit('store.create', 'store', store.name);
      return { ...store, deviceCount: 0 };
    },
    async updateStore(id, body) {
      await gate();
      requireSession();
      const store = db.stores.find(s => s.id === id && s.tenantId === currentTenantId());
      if (!store) throw err(404, 'NOT_FOUND', '门店不存在或没有访问权限');
      if (Number(body.version) !== store.version) throw versionConflict();
      if (body.status === 'ARCHIVED') {
        const devices = db.devices.filter(d => d.storeId === store.id && d.tenantId === store.tenantId);
        if (devices.length) throw err(409, 'STORE_HAS_DEVICES', '该门店仍有设备，请先转移或归档设备后再归档门店');
      }
      if (body.name !== undefined) store.name = body.name;
      if (body.address !== undefined) store.address = body.address;
      if (body.status !== undefined) store.status = body.status;
      store.version += 1;
      audit('store.update', 'store', store.name);
      return { ...store, deviceCount: db.devices.filter(d => d.storeId === store.id).length };
    },
    async listPrices(params = {}) {
      if (await listGate()) return emptyResult();
      requireSession();
      let items = db.prices.filter(p => p.tenantId === currentTenantId());
      if (params.storeId) items = items.filter(p => p.storeId === params.storeId);
      if (params.deviceId) items = items.filter(p => p.deviceId === params.deviceId);
      return { items: clone(items), nextCursor: null, total: items.length };
    },
    async createPrice(body) {
      await gate();
      requireSession();
      if (!body.sku || !Number.isFinite(Number(body.priceMinor)) || Number(body.priceMinor) < 0) {
        throw err(422, 'VALIDATION_ERROR', '请填写商品与正确的售价');
      }
      const price = {
        id: uid('pr'), tenantId: currentTenantId(), sku: body.sku, name: body.name || body.sku,
        storeId: body.storeId || null, deviceId: body.deviceId || null, priceMinor: Number(body.priceMinor),
        effectiveAt: body.effectiveAt || new Date().toISOString(), version: 1,
      };
      db.prices.push(price);
      audit('price.create', 'price', `${price.sku}`);
      return { ...price };
    },

    /* ---- 订单与退款 ---- */
    async listOrders(params = {}) {
      if (await listGate()) return emptyResult();
      requireSession();
      let items = db.orders.filter(o => o.tenantId === currentTenantId());
      if (params.storeId) items = items.filter(o => o.storeIdSnapshot === params.storeId);
      if (params.deviceId) items = items.filter(o => o.deviceId === params.deviceId);
      if (params.status) items = items.filter(o => o.productionStatus === params.status || o.paymentStatus === params.status);
      if (params.environment) items = items.filter(o => o.environment === params.environment);
      if (params.from) items = items.filter(o => o.createdAt.slice(0, 10) >= params.from);
      if (params.to) items = items.filter(o => o.createdAt.slice(0, 10) < params.to);
      const sorted = items.slice().sort((a, b) => (a.createdAt < b.createdAt ? 1 : -1));
      const size = 20;
      const startIndex = params.cursor ? Number(atob(String(params.cursor))) || 0 : 0;
      const page = sorted.slice(startIndex, startIndex + size);
      const nextCursor = startIndex + size < sorted.length ? btoa(String(startIndex + size)) : null;
      return { items: clone(page), nextCursor, total: sorted.length };
    },
    async getOrder(id) {
      await gate({ read: true });
      requireSession();
      const order = db.orders.find(o => o.id === id && o.tenantId === currentTenantId());
      if (!order) throw err(404, 'NOT_FOUND', '订单不存在或没有访问权限');
      return orderDetailBody(order);
    },
    async createRefund(id, body, idempotencyKey) {
      await gate();
      requireSession();
      void idempotencyKey;
      const order = db.orders.find(o => o.id === id && o.tenantId === currentTenantId());
      if (!order) throw err(404, 'NOT_FOUND', '订单不存在或没有访问权限');
      if (!order.allowedActions.includes('REFUND')) throw err(403, 'REFUND_NOT_ALLOWED', '该订单当前不允许发起退款');
      const max = order.receivedMinor - order.refundedMinor;
      const amount = Number(body.amountMinor);
      if (!Number.isFinite(amount) || amount <= 0) throw err(422, 'VALIDATION_ERROR', '请填写正确的退款金额', { fields: { amountMinor: '退款金额必须大于 0' } });
      if (amount > max) throw err(422, 'VALIDATION_ERROR', `退款金额不能超过可退上限 ${max} 分`, { fields: { amountMinor: '超过可退上限' } });
      const refundId = uid('rf');
      order.refundsPending = order.refundsPending || [];
      order.refundsPending.push({ id: refundId, amountMinor: amount, reason: body.reason || '' });
      order.pendingRefundMinor = amount;
      order.paymentStatus = 'REFUNDING';
      order.allowedActions = [];
      audit('order.refund.create', 'order', `${order.orderNo} · ${amount} 分`);
      return { id: refundId, status: 'PENDING', amountMinor: amount };
    },

    /* ---- 物料 / 采购 / 库存 ---- */
    async listMaterials() {
      if (await listGate()) return emptyResult();
      requireSession();
      return { items: clone(db.materials.filter(m => m.tenantId === currentTenantId())), nextCursor: null };
    },
    async createMaterial(body) {
      await gate();
      requireSession();
      if (!body.name || !body.unit) throw err(422, 'VALIDATION_ERROR', '请填写物料名称与单位');
      const material = { id: uid('mt'), tenantId: currentTenantId(), name: body.name, unit: body.unit, unitPrecision: Number(body.unitPrecision) || 0, status: 'ACTIVE', averageUnitCostMinor: null };
      db.materials.push(material);
      audit('material.create', 'material', material.name);
      return { ...material };
    },
    async listPurchases(params = {}) {
      if (await listGate()) return emptyResult();
      requireSession();
      let items = db.purchases.filter(p => p.tenantId === currentTenantId());
      if (params.storeId) items = items.filter(p => p.storeId === params.storeId);
      if (params.from) items = items.filter(p => p.purchasedOn >= params.from);
      if (params.to) items = items.filter(p => p.purchasedOn < params.to);
      return { items: clone(items.slice().sort((a, b) => (a.purchasedOn < b.purchasedOn ? 1 : -1))), nextCursor: null };
    },
    async createPurchase(body, idempotencyKey) {
      await gate();
      requireSession();
      void idempotencyKey;
      if (!body.lines || !body.lines.length) throw err(422, 'VALIDATION_ERROR', '请至少填写一行采购明细');
      const purchase = { id: uid('pu'), tenantId: currentTenantId(), storeId: body.storeId, purchasedOn: body.purchasedOn, supplier: body.supplier || '', note: body.note || '', status: 'DRAFT', version: 1, lines: body.lines.map(l => ({ ...l })) };
      db.purchases.push(purchase);
      audit('purchase.create', 'purchase', `${purchase.purchasedOn} · ${purchase.supplier || '无供应商'}`);
      return clone(purchase);
    },
    async updatePurchase(id, body) {
      await gate();
      requireSession();
      const purchase = db.purchases.find(p => p.id === id && p.tenantId === currentTenantId());
      if (!purchase) throw err(404, 'NOT_FOUND', '采购单不存在或没有访问权限');
      if (purchase.status !== 'DRAFT') throw err(409, 'NOT_DRAFT', '已入账采购单不能直接修改，请通过后续调整更正');
      if (Number(body.version) !== purchase.version) throw versionConflict();
      for (const key of ['storeId', 'purchasedOn', 'supplier', 'note']) if (body[key] !== undefined) purchase[key] = body[key];
      if (body.lines) purchase.lines = body.lines.map(l => ({ ...l }));
      purchase.version += 1;
      audit('purchase.update', 'purchase', purchase.id);
      return clone(purchase);
    },
    async postPurchase(id, body) {
      await gate();
      requireSession();
      const purchase = db.purchases.find(p => p.id === id && p.tenantId === currentTenantId());
      if (!purchase) throw err(404, 'NOT_FOUND', '采购单不存在或没有访问权限');
      if (Number(body.version) !== purchase.version) throw versionConflict();
      if (purchase.status !== 'DRAFT') throw err(409, 'ALREADY_POSTED', '该采购单已入账');
      purchase.status = 'POSTED';
      purchase.version += 1;
      audit('purchase.post', 'purchase', purchase.id);
      return clone(purchase);
    },
    async getInventory(params = {}) {
      if (await listGate()) return emptyResult();
      requireSession();
      const tenantId = currentTenantId();
      const rows = [];
      for (const device of db.devices.filter(d => d.tenantId === tenantId)) {
        if (params.storeId && device.storeId !== params.storeId) continue;
        if (params.deviceId && device.id !== params.deviceId) continue;
        const inv = db.inventory[`${device.storeId}|${device.id}`] || {};
        for (const materialId of Object.keys(inv).filter(k => k !== 'reserved')) {
          const material = db.materials.find(m => m.id === materialId && m.tenantId === tenantId);
          if (!material) continue;
          const onHand = Number(inv[materialId] || 0);
          const reserved = Number((inv.reserved && inv.reserved[materialId]) || 0);
          rows.push({
            materialId, name: material.name, unit: material.unit,
            onHandQuantity: String(onHand), reservedQuantity: String(reserved), availableQuantity: String(onHand - reserved),
            costStatus: material.averageUnitCostMinor === null ? 'MISSING_COST' : 'OK',
            storeId: device.storeId, deviceId: device.id, deviceName: device.name,
          });
        }
      }
      return { items: rows, nextCursor: null };
    },
    async listMovements(params = {}) {
      if (await listGate()) return emptyResult();
      requireSession();
      let items = db.movements.filter(m => m.tenantId === currentTenantId());
      if (params.type) items = items.filter(m => m.type === params.type);
      if (params.storeId) items = items.filter(m => m.sourceStoreId === params.storeId || m.targetStoreId === params.storeId);
      return { items: clone(items.slice().sort((a, b) => (a.createdAt < b.createdAt ? 1 : -1))), nextCursor: null };
    },
    async createMovement(body, idempotencyKey) {
      await gate();
      requireSession();
      void idempotencyKey;
      const tenantId = currentTenantId();
      const types = ['RESTOCK', 'WASTE', 'ADJUSTMENT', 'TRANSFER'];
      if (!types.includes(body.type)) throw err(422, 'VALIDATION_ERROR', '请选择正确的类型');
      const quantity = String(body.quantity || '');
      if (!/^-?\d+(\.\d+)?$/.test(quantity)) throw err(422, 'VALIDATION_ERROR', '数量格式不正确');
      const negative = quantity.startsWith('-');
      if (body.type !== 'ADJUSTMENT' && negative) throw err(422, 'VALIDATION_ERROR', `${body.type} 数量必须为正数`);
      const material = db.materials.find(m => m.id === body.materialId && m.tenantId === tenantId);
      if (!material) throw err(404, 'NOT_FOUND', '物料不存在或没有访问权限');
      const movement = { id: uid('mv'), tenantId, type: body.type, materialId: material.id, materialName: material.name, quantity, unit: material.unit, sourceStoreId: body.sourceStoreId || null, sourceDeviceId: body.sourceDeviceId || null, targetStoreId: body.targetStoreId || null, targetDeviceId: body.targetDeviceId || null, reason: body.reason || '', createdAt: new Date().toISOString(), eventId: uid('evt') };
      const applyTo = (storeId, deviceId, delta) => {
        const key = `${storeId}|${deviceId}`;
        db.inventory[key] = db.inventory[key] || { reserved: {} };
        db.inventory[key][material.id] = Number(db.inventory[key][material.id] || 0) + delta;
      };
      const num = Number(quantity);
      if (body.type === 'RESTOCK') applyTo(body.targetStoreId, body.targetDeviceId, num);
      if (body.type === 'WASTE') applyTo(body.sourceStoreId, body.sourceDeviceId, -num);
      if (body.type === 'ADJUSTMENT') applyTo(body.sourceStoreId, body.sourceDeviceId, num);
      if (body.type === 'TRANSFER') { applyTo(body.sourceStoreId, body.sourceDeviceId, -num); applyTo(body.targetStoreId, body.targetDeviceId, num); }
      db.movements.push(movement);
      audit('inventory.movement.create', 'inventory', `${material.name} · ${quantity}`);
      return clone(movement);
    },

    /* ---- 运营费用 ---- */
    async listExpenses(params = {}) {
      if (await listGate()) return emptyResult();
      requireSession();
      let items = db.expenses.filter(e => e.tenantId === currentTenantId());
      if (params.storeId) items = items.filter(e => e.storeId === params.storeId);
      if (params.from) items = items.filter(e => e.occurredOn >= params.from);
      if (params.to) items = items.filter(e => e.occurredOn < params.to);
      return { items: clone(items.slice().sort((a, b) => (a.occurredOn < b.occurredOn ? 1 : -1))), nextCursor: null };
    },
    async createExpense(body, idempotencyKey) {
      await gate();
      requireSession();
      void idempotencyKey;
      if (!Number.isFinite(Number(body.amountMinor)) || Number(body.amountMinor) <= 0) throw err(422, 'VALIDATION_ERROR', '请填写正确的费用金额');
      if (body.allocationMethod === 'DAILY_EQUAL' && !(body.allocationStart && body.allocationEnd)) {
        throw err(422, 'VALIDATION_ERROR', '按日均摊需要填写分摊区间');
      }
      const expense = { id: uid('ex'), tenantId: currentTenantId(), category: body.category, amountMinor: Number(body.amountMinor), storeId: body.storeId || null, deviceId: body.deviceId || null, occurredOn: body.occurredOn, allocationStart: body.allocationStart || null, allocationEnd: body.allocationEnd || null, allocationMethod: body.allocationMethod || 'ONCE', status: 'DRAFT', note: body.note || '', version: 1 };
      db.expenses.push(expense);
      audit('expense.create', 'expense', `${expense.category}`);
      return clone(expense);
    },
    async postExpense(id, body) {
      await gate();
      requireSession();
      const expense = db.expenses.find(e => e.id === id && e.tenantId === currentTenantId());
      if (!expense) throw err(404, 'NOT_FOUND', '费用不存在或没有访问权限');
      if (Number(body.version) !== expense.version) throw versionConflict();
      if (expense.status !== 'DRAFT') throw err(409, 'ALREADY_POSTED', '该费用已入账');
      expense.status = 'POSTED';
      expense.version += 1;
      audit('expense.post', 'expense', expense.id);
      return clone(expense);
    },
    async reverseExpense(id, body) {
      await gate();
      requireSession();
      const expense = db.expenses.find(e => e.id === id && e.tenantId === currentTenantId());
      if (!expense) throw err(404, 'NOT_FOUND', '费用不存在或没有访问权限');
      if (expense.status !== 'POSTED') throw err(409, 'BAD_STATE', '只有已入账费用可以冲正');
      expense.status = 'REVERSED';
      expense.version += 1;
      expense.reversalReason = body.reason || '';
      audit('expense.reverse', 'expense', expense.id);
      return clone(expense);
    },

    /* ---- 报表 ---- */
    async operatingReport(params = {}) {
      await gate({ read: true });
      requireSession();
      const tenant = db.tenants[currentTenantId()];
      const rows = reportRows(params);
      const { totals, completeness } = totalsOf(rows);
      return {
        period: { from: params.from, to: params.to, timezone: tenant.timezone },
        grain: params.grain, environment: params.environment || 'LIVE', rows, totals, completeness,
      };
    },
    async operatingCsv(params = {}) {
      const report = await adapter.operatingReport(params);
      const header = ['period', 'receivedMinor', 'refundedMinor', 'netCashMinor', 'recognizedRevenueMinor',
        'materialCostMinor', 'wasteCostMinor', 'paymentFeeMinor', 'operatingExpenseMinor', 'estimatedProfitMinor', 'deliveredCupCount'];
      const rows = report.rows.map(r => header.map(key => (r[key] === null || r[key] === undefined ? '' : String(r[key]))));
      const text = ['# 界面演示数据 · 非真实经营数据', header.join(','), ...rows.map(r => r.join(','))].join('\r\n');
      const blob = new Blob([`\ufeff${text}`], { type: 'text/csv;charset=utf-8' });
      return { blob, filename: `demo-operating-${params.grain}-${params.from}_${params.to}.csv` };
    },

    /* ---- 成员与邀请 ---- */
    async listMembers() {
      if (await listGate()) return emptyResult();
      requireSession();
      const tenantId = currentTenantId();
      const demoEmail = session.user.email;
      return { items: clone(db.members.filter(m => m.tenantId === tenantId).map(m => ({ ...m, email: m.displayName === '演示用户' ? demoEmail : m.email }))), nextCursor: null };
    },
    async updateMember(id, body) {
      await gate();
      requireSession();
      const member = db.members.find(m => m.id === id && m.tenantId === currentTenantId());
      if (!member) throw err(404, 'NOT_FOUND', '成员不存在或没有访问权限');
      if (Number(body.version) !== member.version) throw versionConflict();
      const tenantId = currentTenantId();
      const ownerCount = db.members.filter(m => m.tenantId === tenantId && m.role === 'OWNER' && m.status === 'ACTIVE').length;
      const losingOwner = member.role === 'OWNER' && member.status === 'ACTIVE'
        && ((body.role && body.role !== 'OWNER') || (body.status && body.status !== 'ACTIVE'));
      if (losingOwner && ownerCount <= 1) throw err(409, 'LAST_OWNER', '最后一位 OWNER 不能被停用或降级');
      if (body.role !== undefined) member.role = body.role;
      if (body.status !== undefined) member.status = body.status;
      if (body.storeScope !== undefined) member.storeScope = body.storeScope;
      member.version += 1;
      audit('member.update', 'member', member.email || member.displayName);
      return clone(member);
    },
    async listInvitations() {
      if (await listGate()) return emptyResult();
      requireSession();
      const items = db.invitations.filter(i => i.tenantId === currentTenantId()).map(i => ({ ...i, expiresAt: i.expiresAt || new Date(Date.now() + 7 * 86400000).toISOString() }));
      return { items, nextCursor: null };
    },
    async createInvitation(body, idempotencyKey) {
      await gate();
      requireSession();
      void idempotencyKey;
      if (!body.email) throw err(422, 'VALIDATION_ERROR', '请填写被邀请人邮箱');
      const invitation = { id: uid('inv'), tenantId: currentTenantId(), email: body.email, role: body.role || 'OPERATOR', status: 'PENDING', deliveryStatus: emailUnavailable ? 'UNAVAILABLE' : 'QUEUED', expiresAt: new Date(Date.now() + 7 * 86400000).toISOString(), version: 1, storeScope: body.storeScope || null };
      db.invitations.push(invitation);
      audit('invitation.create', 'invitation', invitation.email);
      return clone(invitation);
    },
    async revokeInvitation(id) {
      await gate();
      requireSession();
      const invitation = db.invitations.find(i => i.id === id && i.tenantId === currentTenantId());
      if (!invitation) throw err(404, 'NOT_FOUND', '邀请不存在或没有访问权限');
      if (invitation.status !== 'PENDING') throw err(409, 'BAD_STATE', '该邀请已结束');
      invitation.status = 'REVOKED';
      audit('invitation.revoke', 'invitation', invitation.email);
      return clone(invitation);
    },

    /* ---- 收款账户 ---- */
    async listPaymentAccounts() {
      if (await listGate()) return emptyResult();
      requireSession();
      return { items: clone(db.paymentAccounts.filter(a => a.tenantId === currentTenantId())), nextCursor: null };
    },
    async createPaymentAccount(body, idempotencyKey) {
      await gate();
      requireSession();
      void idempotencyKey;
      if (!body.label || !body.appId || !body.merchantId || !body.appPrivateKey) throw err(422, 'VALIDATION_ERROR', '请完整填写账户信息与密钥');
      const mask = value => `${String(value).slice(0, 2)}****${String(value).slice(-2)}`;
      const account = {
        id: uid('pa'), tenantId: currentTenantId(), label: body.label, provider: body.provider,
        environment: body.environment, appIdMasked: mask(body.appId), merchantIdMasked: mask(body.merchantId),
        status: 'ACTIVE', isDefault: false, version: 1, configuredAt: new Date().toISOString(),
        checks: [{ name: '密钥格式', status: 'PASS', message: '私钥已加密保存（演示）' }],
      };
      db.paymentAccounts.push(account);
      audit('payment_account.create', 'payment_account', account.label);
      return clone(account);
    },
    async validatePaymentAccount(id, body) {
      await gate();
      requireSession();
      const account = db.paymentAccounts.find(a => a.id === id && a.tenantId === currentTenantId());
      if (!account) throw err(404, 'NOT_FOUND', '账户不存在或没有访问权限');
      if (Number(body.version) !== account.version) throw versionConflict();
      const checks = clone(account.checks).map(c => ({ ...c }));
      checks.push({ name: '渠道连通', status: 'PASS', message: '渠道握手成功（演示）' });
      account.lastValidation = { at: new Date().toISOString(), status: 'PASS' };
      return { status: 'PASS', checks };
    },
    async setDefaultPaymentAccount(id, body) {
      await gate();
      requireSession();
      const account = db.paymentAccounts.find(a => a.id === id && a.tenantId === currentTenantId());
      if (!account) throw err(404, 'NOT_FOUND', '账户不存在或没有访问权限');
      if (Number(body.version) !== account.version) throw versionConflict();
      if (account.status !== 'ACTIVE') throw err(409, 'NOT_ACTIVE', '只有启用中的账户可以设为默认');
      const hasFail = (account.checks || []).some(c => c.status === 'FAIL');
      if (hasFail) throw err(409, 'VALIDATION_REQUIRED', '校验未通过的账户不能设为默认收款账户');
      for (const a of db.paymentAccounts.filter(x => x.tenantId === currentTenantId())) a.isDefault = false;
      account.isDefault = true;
      account.version += 1;
      audit('payment_account.set_default', 'payment_account', account.label);
      return clone(account);
    },
    async disablePaymentAccount(id, body) {
      await gate();
      requireSession();
      const account = db.paymentAccounts.find(a => a.id === id && a.tenantId === currentTenantId());
      if (!account) throw err(404, 'NOT_FOUND', '账户不存在或没有访问权限');
      if (Number(body.version) !== account.version) throw versionConflict();
      if (account.isDefault) throw err(409, 'IS_DEFAULT', '默认收款账户不能直接停用，请先切换默认账户');
      account.status = 'DISABLED';
      account.version += 1;
      audit('payment_account.disable', 'payment_account', account.label);
      return clone(account);
    },

    /* ---- 组织与审计 ---- */
    async getTenant() {
      await gate({ read: true });
      requireSession();
      const tenant = db.tenants[currentTenantId()];
      return clone(tenant);
    },
    async updateTenant(body) {
      await gate();
      requireSession();
      const tenant = db.tenants[currentTenantId()];
      if (Number(body.version) !== tenant.version) throw versionConflict();
      if (body.timezone !== undefined && body.timezone !== tenant.timezone) {
        throw err(409, 'TIMEZONE_LOCKED', '组织已产生交易记录，时区变更可能影响既有账期，已被服务器拒绝；报表账期始终按组织时区计算。');
      }
      if (body.name !== undefined) tenant.name = body.name;
      tenant.version += 1;
      audit('tenant.update', 'tenant', tenant.name);
      return clone(tenant);
    },
    async listAudit(params = {}) {
      if (await listGate()) return emptyResult();
      requireSession();
      let items = db.audit.filter(a => a.tenantId === currentTenantId());
      if (params.action) items = items.filter(a => a.action.includes(String(params.action)));
      if (params.from) items = items.filter(a => a.createdAt.slice(0, 10) >= params.from);
      if (params.to) items = items.filter(a => a.createdAt.slice(0, 10) < params.to);
      return { items: clone(items), nextCursor: null };
    },

    /* ---- 演示专属工具（仅 ?demo=1 时由页面调用） ---- */
    demoFaults() { return { ...faults }; },
    demoToggleFault(name) {
      if (!(name in faults)) return { ...faults };
      faults[name] = !faults[name];
      return { ...faults };
    },
    demoSetRole(role) {
      if (!ROLE_PERMISSIONS[role]) throw err(422, 'BAD_ROLE', '未知角色');
      const membership = session.memberships.find(m => m.id === session.membershipId);
      membership.role = role;
      return sessionPayload();
    },
    demoToggleEmailUnavailable() {
      emailUnavailable = !emailUnavailable;
      return emailUnavailable;
    },
    demoAdvanceRefunds() {
      let count = 0;
      for (const order of db.orders) {
        const pending = order.refundsPending || [];
        if (!pending.length) continue;
        for (const refund of pending) {
          order.refundedMinor += refund.amountMinor;
          count += 1;
        }
        order.paymentStatus = order.refundedMinor >= order.receivedMinor ? 'REFUNDED' : 'PARTIALLY_REFUNDED';
        order.allowedActions = order.paymentStatus === 'PARTIALLY_REFUNDED' ? ['REFUND'] : [];
        order.refundsPending = [];
      }
      return { advanced: count };
    },
    demoReset() {
      db = buildDb();
      if (session) return sessionPayload();
      return null;
    },
    demoHints() {
      return {
        claimCode: 'CLAIM-DEMO-OK',
        verifyToken: 'demo-verify-token',
        resetToken: 'demo-reset-token',
        inviteToken: 'demo-invite-token',
        loginHint: '任意邮箱 + 至少 6 位密码即可登录演示',
      };
    },
  };

  return adapter;
}
