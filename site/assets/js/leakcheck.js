/* What a website learns about you before you click anything.
 *
 * Every value below is read from the browser itself — no request leaves the
 * page, which is the point: a privacy product that shipped its privacy demo
 * to a third-party API would be making the opposite argument. Anything that
 * meaningfully narrows down who you are is flagged as exposed.
 */
(function (root) {
  'use strict';

  function safe(fn, fallback) {
    try {
      var v = fn();
      return (v === undefined || v === null || v === '') ? (fallback || '—') : v;
    } catch (e) { return fallback || 'недоступно'; }
  }

  /* FNV-1a — short, fast, and good enough to show that two visits produce the
   * same number. Not a security hash and not presented as one. */
  function hash(str) {
    var h = 0x811c9dc5;
    for (var i = 0; i < str.length; i++) {
      h ^= str.charCodeAt(i);
      h = (h + (h << 1) + (h << 4) + (h << 7) + (h << 8) + (h << 24)) >>> 0;
    }
    return ('00000000' + h.toString(16)).slice(-8);
  }

  function gpu() {
    var c = document.createElement('canvas');
    var gl = c.getContext('webgl') || c.getContext('experimental-webgl');
    if (!gl) return null;
    var ext = gl.getExtension('WEBGL_debug_renderer_info');
    if (!ext) return gl.getParameter(gl.RENDERER);
    return gl.getParameter(ext.UNMASKED_RENDERER_WEBGL);
  }

  /* The canvas fingerprint: identical hardware plus identical fonts render
   * these shapes identically, and the result is stable across visits. */
  function canvasPrint() {
    var c = document.createElement('canvas');
    c.width = 240; c.height = 60;
    var ctx = c.getContext('2d');
    ctx.textBaseline = 'top';
    ctx.font = '15px "Arial"';
    ctx.fillStyle = '#f60';
    ctx.fillRect(120, 5, 62, 20);
    ctx.fillStyle = '#069';
    ctx.fillText('HollVPN ☁ fingerprint', 2, 15);
    ctx.fillStyle = 'rgba(102,204,0,0.7)';
    ctx.fillText('HollVPN ☁ fingerprint', 4, 22);
    return hash(c.toDataURL());
  }

  function osName() {
    var d = navigator.userAgentData;
    if (d && d.platform) return d.platform;
    var ua = navigator.userAgent;
    if (/Windows NT 10/.test(ua)) return 'Windows 10 или 11';
    if (/Windows/.test(ua)) return 'Windows';
    if (/iPhone|iPad|iPod/.test(ua)) return 'iOS / iPadOS';
    if (/Android/.test(ua)) return 'Android';
    if (/Mac OS X/.test(ua)) return 'macOS';
    if (/Linux/.test(ua)) return 'Linux';
    return 'неизвестна';
  }

  function browserName() {
    var ua = navigator.userAgent;
    var m = /(Firefox|Edg|OPR|YaBrowser|Chrome|Safari)\/([\d.]+)/.exec(ua);
    if (!m) return 'неизвестен';
    var names = { Edg: 'Edge', OPR: 'Opera', YaBrowser: 'Яндекс.Браузер' };
    return (names[m[1]] || m[1]) + ' ' + m[2].split('.')[0];
  }

  /* Host ICE candidates, gathered without a STUN server so nothing is
   * contacted. Modern browsers answer with an mDNS hostname instead of the
   * real address — that is the good outcome, and it is reported as such. */
  function webrtc() {
    return new Promise(function (resolve) {
      var RTC = root.RTCPeerConnection || root.webkitRTCPeerConnection;
      if (!RTC) return resolve({ value: 'WebRTC отключён', exposed: false });

      var pc, done = false, found = [];
      var finish = function () {
        if (done) return;
        done = true;
        try { pc.close(); } catch (e) {}
        if (!found.length) return resolve({ value: 'адрес не раскрыт', exposed: false });
        var real = found.filter(function (a) { return !/\.local$/i.test(a); });
        if (!real.length) {
          resolve({ value: 'скрыт браузером (mDNS)', exposed: false });
        } else {
          resolve({ value: real[0], exposed: true });
        }
      };

      try {
        pc = new RTC({ iceServers: [] });
        pc.createDataChannel('x');
        pc.onicecandidate = function (e) {
          if (!e.candidate) return finish();
          var m = /candidate:\S+ \d+ \S+ \d+ (\S+)/.exec(e.candidate.candidate);
          if (m && found.indexOf(m[1]) === -1) found.push(m[1]);
        };
        pc.createOffer().then(function (o) { return pc.setLocalDescription(o); })
          .catch(finish);
        setTimeout(finish, 1200);
      } catch (e) {
        resolve({ value: 'недоступно', exposed: false });
      }
    });
  }

  function run() {
    var tz = safe(function () { return Intl.DateTimeFormat().resolvedOptions().timeZone; });
    var offset = -new Date().getTimezoneOffset() / 60;
    var langs = safe(function () { return (navigator.languages || [navigator.language]).join(', '); });
    var renderer = safe(gpu, 'скрыт браузером');

    var items = [
      { k: 'Часовой пояс',      v: tz + ' (UTC' + (offset >= 0 ? '+' : '') + offset + ')', exposed: true },
      { k: 'Языки',             v: langs, exposed: true },
      { k: 'Операционная система', v: osName(), exposed: true },
      { k: 'Браузер',           v: browserName(), exposed: true },
      { k: 'Экран',             v: safe(function () {
          return screen.width + '×' + screen.height + ' @' + (root.devicePixelRatio || 1) +
                 'x, ' + screen.colorDepth + ' бит'; }), exposed: true },
      { k: 'Видеокарта',        v: renderer, exposed: renderer !== 'скрыт браузером' },
      { k: 'Ядер процессора',   v: safe(function () { return String(navigator.hardwareConcurrency); }, 'скрыто') },
      { k: 'Оперативная память', v: safe(function () {
          return navigator.deviceMemory ? navigator.deviceMemory + ' ГБ и больше' : null; }, 'скрыта') },
      { k: 'Сенсорный ввод',    v: (navigator.maxTouchPoints || 0) > 0
          ? 'да, до ' + navigator.maxTouchPoints + ' касаний' : 'нет' },
      { k: 'Отпечаток canvas',  v: safe(canvasPrint, 'заблокирован'), exposed: true },
      { k: 'Do Not Track',      v: (navigator.doNotTrack === '1' ? 'включён' : 'не включён'),
        exposed: navigator.doNotTrack !== '1' },
      { k: 'Cookie',            v: navigator.cookieEnabled ? 'разрешены' : 'запрещены' },
      { k: 'Локальный IP (WebRTC)', v: 'проверяем…', pending: true }
    ];

    return { items: items, webrtc: webrtc() };
  }

  root.HollLeak = { run: run, hash: hash };
})(typeof window !== 'undefined' ? window : globalThis);
