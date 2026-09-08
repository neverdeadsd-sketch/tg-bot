/* Проверка источника вебхука.
 *
 * ЮKassa шлёт уведомления с опубликованного набора адресов. Это не главная
 * защита — главная в том, что статус платежа мы перечитываем из API, — но
 * отсекает мусор до того, как он дойдёт до логики.
 */
'use strict';

// https://yookassa.ru/developers/using-api/webhooks — список адресов уведомлений
const ALLOWED = [
  '185.71.76.0/27',
  '185.71.77.0/27',
  '77.75.153.0/25',
  '77.75.156.11/32',
  '77.75.156.35/32',
  '77.75.154.128/25',
  '2a02:5180::/32'
];

function v4ToInt(ip) {
  const p = ip.split('.');
  if (p.length !== 4) return null;
  let n = 0;
  for (const part of p) {
    const b = Number(part);
    if (!Number.isInteger(b) || b < 0 || b > 255 || !/^\d{1,3}$/.test(part)) return null;
    n = (n * 256) + b;
  }
  return n;
}

/* Первые `bits` бит адреса IPv6 в виде строки из шестнадцатеричных групп.
 * Хватает для единственного диапазона /32 в списке. */
function v6Prefix(ip, bits) {
  const groups = expandV6(ip);
  if (!groups) return null;
  const need = Math.ceil(bits / 16);
  return groups.slice(0, need).join(':');
}

function expandV6(ip) {
  if (!ip.includes(':')) return null;
  const halves = ip.split('::');
  if (halves.length > 2) return null;
  const head = halves[0] ? halves[0].split(':') : [];
  const tail = halves.length === 2 && halves[1] ? halves[1].split(':') : [];
  if (halves.length === 1 && head.length !== 8) return null;
  const fill = 8 - head.length - tail.length;
  if (fill < 0) return null;
  const full = [...head, ...Array(halves.length === 2 ? fill : 0).fill('0'), ...tail];
  if (full.length !== 8) return null;
  return full.map(function (g) {
    if (!/^[0-9a-fA-F]{0,4}$/.test(g)) return null;
    return (g || '0').toLowerCase().replace(/^0+(?=.)/, '');
  });
}

function normalise(remote) {
  if (!remote) return '';
  // Node отдаёт IPv4 через IPv6-сокет как ::ffff:1.2.3.4
  const m = /^::ffff:(\d+\.\d+\.\d+\.\d+)$/i.exec(remote);
  return m ? m[1] : remote;
}

function isAllowed(remoteAddress) {
  const ip = normalise(remoteAddress);
  if (!ip) return false;

  for (const cidr of ALLOWED) {
    const [base, bitsRaw] = cidr.split('/');
    const bits = Number(bitsRaw);

    if (base.includes(':')) {
      if (!ip.includes(':')) continue;
      const a = v6Prefix(ip, bits), b = v6Prefix(base, bits);
      if (a !== null && a === b) return true;
      continue;
    }

    const a = v4ToInt(ip), b = v4ToInt(base);
    if (a === null || b === null) continue;
    const mask = bits === 0 ? 0 : (~0 << (32 - bits)) >>> 0;
    if (((a & mask) >>> 0) === ((b & mask) >>> 0)) return true;
  }
  return false;
}

module.exports = { isAllowed, ALLOWED };
