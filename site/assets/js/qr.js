/* Minimal QR encoder — byte mode, ECC level M, versions 1-6.
 *
 * A QR pointing at the Telegram bot is the shortest path from a desktop
 * visitor to a phone, and pulling a library for it would mean a third-party
 * script on a privacy site. Versions 1-6 hold 106 bytes at level M, which is
 * several times what a t.me link needs, and stop below version 7 so the
 * version-information blocks never come into play.
 */
(function (root) {
  'use strict';

  /* ------------------------------------------------------- GF(256) ------ */

  var EXP = new Uint8Array(512), LOG = new Uint8Array(256);
  (function () {
    var x = 1;
    for (var i = 0; i < 255; i++) {
      EXP[i] = x; LOG[x] = i;
      x <<= 1;
      if (x & 0x100) x ^= 0x11D;      // primitive polynomial for QR
    }
    for (i = 255; i < 512; i++) EXP[i] = EXP[i - 255];
  })();

  function gmul(a, b) {
    if (a === 0 || b === 0) return 0;
    return EXP[LOG[a] + LOG[b]];
  }

  /* Generator polynomial for n error-correction codewords:
   * g(x) = (x - a^0)(x - a^1)...(x - a^(n-1)) */
  function rsGenerator(n) {
    var g = [1];
    for (var i = 0; i < n; i++) {
      var next = new Array(g.length + 1).fill(0);
      for (var j = 0; j < g.length; j++) {
        next[j] ^= g[j];                      // x * g(x)
        next[j + 1] ^= gmul(g[j], EXP[i]);    // a^i * g(x)
      }
      g = next;
    }
    return g;
  }

  function rsEncode(data, ecLen) {
    var gen = rsGenerator(ecLen);
    var rem = new Array(ecLen).fill(0);
    for (var i = 0; i < data.length; i++) {
      var factor = data[i] ^ rem[0];
      rem.shift(); rem.push(0);
      for (var j = 0; j < ecLen; j++) rem[j] ^= gmul(gen[j + 1], factor);
    }
    return rem;
  }

  /* ------------------------------------------------------- version tables --
   * [total codewords, EC codewords per block, block count] at level M.
   * Every version here has a single block group, which keeps interleaving
   * to one loop. */
  var SPEC = {
    1: [26,  10, 1],
    2: [44,  16, 1],
    3: [70,  26, 1],
    4: [100, 18, 2],
    5: [134, 24, 2],
    6: [172, 16, 4]
  };
  var ALIGN = { 1: [], 2: [6,18], 3: [6,22], 4: [6,26], 5: [6,30], 6: [6,34] };

  function dataCapacity(v) {
    var s = SPEC[v];
    return s[0] - s[1] * s[2];
  }

  /* ------------------------------------------------------------ encoding -- */

  function utf8Bytes(str) {
    var out = [], i, c;
    for (i = 0; i < str.length; i++) {
      c = str.charCodeAt(i);
      if (c < 0x80) out.push(c);
      else if (c < 0x800) out.push(0xC0 | (c >> 6), 0x80 | (c & 63));
      else if (c >= 0xD800 && c <= 0xDBFF && i + 1 < str.length) {
        var cp = 0x10000 + ((c - 0xD800) << 10) + (str.charCodeAt(++i) - 0xDC00);
        out.push(0xF0 | (cp >> 18), 0x80 | ((cp >> 12) & 63),
                 0x80 | ((cp >> 6) & 63), 0x80 | (cp & 63));
      } else out.push(0xE0 | (c >> 12), 0x80 | ((c >> 6) & 63), 0x80 | (c & 63));
    }
    return out;
  }

  function buildData(bytes, version) {
    var cap = dataCapacity(version), bits = [];
    function push(val, len) {
      for (var i = len - 1; i >= 0; i--) bits.push((val >> i) & 1);
    }
    push(0b0100, 4);            // byte mode
    push(bytes.length, 8);      // count indicator: 8 bits for versions 1-9
    for (var i = 0; i < bytes.length; i++) push(bytes[i], 8);

    var capBits = cap * 8;
    for (i = 0; i < 4 && bits.length < capBits; i++) bits.push(0);  // terminator
    while (bits.length % 8) bits.push(0);

    var words = [];
    for (i = 0; i < bits.length; i += 8) {
      words.push(bits.slice(i, i + 8).reduce(function (a, b) { return (a << 1) | b; }, 0));
    }
    // Alternating pad bytes, as the spec prescribes.
    var pad = [0xEC, 0x11], p = 0;
    while (words.length < cap) words.push(pad[p++ % 2]);
    return words;
  }

  function interleave(words, version) {
    var spec = SPEC[version], ecLen = spec[1], nBlocks = spec[2];
    var per = words.length / nBlocks, blocks = [], ecs = [], i, j;
    for (i = 0; i < nBlocks; i++) {
      var b = words.slice(i * per, (i + 1) * per);
      blocks.push(b);
      ecs.push(rsEncode(b, ecLen));
    }
    var out = [];
    for (j = 0; j < per; j++) for (i = 0; i < nBlocks; i++) out.push(blocks[i][j]);
    for (j = 0; j < ecLen; j++) for (i = 0; i < nBlocks; i++) out.push(ecs[i][j]);
    return out;
  }

  /* -------------------------------------------------------------- matrix -- */

  function makeMatrix(version) {
    var size = version * 4 + 17;
    var m = [], reserved = [], i, j;
    for (i = 0; i < size; i++) {
      m.push(new Array(size).fill(0));
      reserved.push(new Array(size).fill(false));
    }

    function finder(r, c) {
      for (var dr = -1; dr <= 7; dr++) {
        for (var dc = -1; dc <= 7; dc++) {
          var rr = r + dr, cc = c + dc;
          if (rr < 0 || rr >= size || cc < 0 || cc >= size) continue;
          var inRing = (dr >= 0 && dr <= 6 && dc >= 0 && dc <= 6) &&
            (dr === 0 || dr === 6 || dc === 0 || dc === 6 ||
             (dr >= 2 && dr <= 4 && dc >= 2 && dc <= 4));
          m[rr][cc] = inRing ? 1 : 0;
          reserved[rr][cc] = true;
        }
      }
    }
    finder(0, 0); finder(0, size - 7); finder(size - 7, 0);

    // Timing patterns.
    for (i = 8; i < size - 8; i++) {
      m[6][i] = m[i][6] = (i % 2 === 0) ? 1 : 0;
      reserved[6][i] = reserved[i][6] = true;
    }

    // Alignment patterns, skipping the three finder corners.
    var pos = ALIGN[version];
    for (i = 0; i < pos.length; i++) {
      for (j = 0; j < pos.length; j++) {
        var r = pos[i], c = pos[j];
        if ((r < 8 && c < 8) || (r < 8 && c > size - 9) || (r > size - 9 && c < 8)) continue;
        for (var dr = -2; dr <= 2; dr++) {
          for (var dc = -2; dc <= 2; dc++) {
            var a = Math.max(Math.abs(dr), Math.abs(dc));
            m[r + dr][c + dc] = (a === 1) ? 0 : 1;
            reserved[r + dr][c + dc] = true;
          }
        }
      }
    }

    // Format information areas, plus the always-dark module.
    for (i = 0; i <= 8; i++) {
      if (i !== 6) { reserved[8][i] = true; reserved[i][8] = true; }
    }
    for (i = 0; i < 8; i++) {
      reserved[8][size - 1 - i] = true;
      reserved[size - 1 - i][8] = true;
    }
    m[size - 8][8] = 1;
    reserved[size - 8][8] = true;

    return { size: size, m: m, reserved: reserved };
  }

  function placeData(grid, codewords) {
    var size = grid.size, m = grid.m, reserved = grid.reserved;
    var bitIdx = 0, total = codewords.length * 8;
    var row = size - 1, dir = -1;
    for (var col = size - 1; col > 0; col -= 2) {
      if (col === 6) col--;                       // the vertical timing column
      for (;;) {
        for (var c = 0; c < 2; c++) {
          var cc = col - c;
          if (!reserved[row][cc]) {
            var bit = 0;
            if (bitIdx < total) {
              bit = (codewords[bitIdx >> 3] >> (7 - (bitIdx & 7))) & 1;
              bitIdx++;
            }
            m[row][cc] = bit;
          }
        }
        row += dir;
        if (row < 0 || row >= size) { row -= dir; dir = -dir; break; }
      }
    }
  }

  var MASKS = [
    function (i, j) { return (i + j) % 2 === 0; },
    function (i)    { return i % 2 === 0; },
    function (i, j) { return j % 3 === 0; },
    function (i, j) { return (i + j) % 3 === 0; },
    function (i, j) { return (Math.floor(i / 2) + Math.floor(j / 3)) % 2 === 0; },
    function (i, j) { return (i * j) % 2 + (i * j) % 3 === 0; },
    function (i, j) { return ((i * j) % 2 + (i * j) % 3) % 2 === 0; },
    function (i, j) { return ((i + j) % 2 + (i * j) % 3) % 2 === 0; }
  ];

  function formatBits(mask) {
    var fmt = (0 << 3) | mask;                    // 00 = level M
    var d = fmt << 10;
    for (var i = 4; i >= 0; i--) {
      if ((d >>> (i + 10)) & 1) d ^= 0x537 << i;  // BCH(15,5)
    }
    return ((fmt << 10) | d) ^ 0x5412;
  }

  function writeFormat(m, size, mask) {
    var bits = formatBits(mask);
    function bit(i) { return (bits >> i) & 1; }
    for (var i = 0; i <= 5; i++) m[i][8] = bit(i);
    m[7][8] = bit(6); m[8][8] = bit(7); m[8][7] = bit(8);
    for (i = 9; i <= 14; i++) m[8][14 - i] = bit(i);
    for (i = 0; i <= 7; i++) m[8][size - 1 - i] = bit(i);
    for (i = 8; i <= 14; i++) m[size - 15 + i][8] = bit(i);
    m[size - 8][8] = 1;
  }

  /* The four penalty rules from the spec; the mask with the lowest total wins,
   * which is what keeps the code readable to a phone camera at an angle. */
  function penalty(m, size) {
    var score = 0, i, j, run, dark = 0;

    function scanLine(get) {
      run = 1;
      var prev = get(0);
      for (var k = 1; k < size; k++) {
        var cur = get(k);
        if (cur === prev) { run++; }
        else { if (run >= 5) score += 3 + (run - 5); run = 1; prev = cur; }
      }
      if (run >= 5) score += 3 + (run - 5);
    }
    for (i = 0; i < size; i++) {
      scanLine((function (r) { return function (k) { return m[r][k]; }; })(i));
      scanLine((function (c) { return function (k) { return m[k][c]; }; })(i));
    }

    for (i = 0; i < size - 1; i++) {
      for (j = 0; j < size - 1; j++) {
        var v = m[i][j];
        if (v === m[i][j+1] && v === m[i+1][j] && v === m[i+1][j+1]) score += 3;
      }
    }

    var P1 = [1,0,1,1,1,0,1,0,0,0,0], P2 = [0,0,0,0,1,0,1,1,1,0,1];
    function matches(get, at, pat) {
      for (var k = 0; k < pat.length; k++) if (get(at + k) !== pat[k]) return false;
      return true;
    }
    for (i = 0; i < size; i++) {
      for (j = 0; j <= size - 11; j++) {
        var rowGet = (function (r) { return function (k) { return m[r][k]; }; })(i);
        var colGet = (function (c) { return function (k) { return m[k][c]; }; })(i);
        if (matches(rowGet, j, P1) || matches(rowGet, j, P2)) score += 40;
        if (matches(colGet, j, P1) || matches(colGet, j, P2)) score += 40;
      }
    }

    for (i = 0; i < size; i++) for (j = 0; j < size; j++) dark += m[i][j];
    var pct = dark * 100 / (size * size);
    score += Math.floor(Math.abs(pct - 50) / 5) * 10;
    return score;
  }

  function encode(text, opts) {
    opts = opts || {};
    var bytes = utf8Bytes(text), version = 0;
    for (var v = 1; v <= 6; v++) {
      // 2 codewords go to the mode indicator and character count.
      if (bytes.length + 2 <= dataCapacity(v)) { version = v; break; }
    }
    if (!version) throw new Error('QR: строка слишком длинная (максимум ~106 байт)');

    var codewords = interleave(buildData(bytes, version), version);
    var base = makeMatrix(version);
    placeData(base, codewords);

    var best = null, bestScore = Infinity, chosen = 0;
    var first = opts.mask == null ? 0 : opts.mask;
    var last  = opts.mask == null ? 7 : opts.mask;
    for (var mask = first; mask <= last; mask++) {
      var m = base.m.map(function (r) { return r.slice(); });
      for (var i = 0; i < base.size; i++) {
        for (var j = 0; j < base.size; j++) {
          if (!base.reserved[i][j] && MASKS[mask](i, j)) m[i][j] ^= 1;
        }
      }
      writeFormat(m, base.size, mask);
      var s = penalty(m, base.size);
      if (s < bestScore) { bestScore = s; best = m; chosen = mask; }
    }
    return { size: base.size, modules: best, version: version, mask: chosen };
  }

  /* Renders at whole-pixel module size so the code stays crisp; the canvas is
   * resized to fit rather than scaled by CSS. */
  function toCanvas(canvas, text, opts) {
    opts = opts || {};
    var qr = encode(text);
    var quiet = opts.quiet == null ? 2 : opts.quiet;
    var target = opts.size || canvas.width || 148;
    var scale = Math.max(1, Math.floor(target / (qr.size + quiet * 2)));
    var px = (qr.size + quiet * 2) * scale;

    canvas.width = px; canvas.height = px;
    canvas.style.width = target + 'px';
    canvas.style.height = target + 'px';

    var ctx = canvas.getContext('2d');
    ctx.fillStyle = opts.light || '#ffffff';
    ctx.fillRect(0, 0, px, px);
    ctx.fillStyle = opts.dark || '#06121e';
    for (var i = 0; i < qr.size; i++) {
      for (var j = 0; j < qr.size; j++) {
        if (qr.modules[i][j]) {
          ctx.fillRect((j + quiet) * scale, (i + quiet) * scale, scale, scale);
        }
      }
    }
    return qr;
  }

  root.HollQR = { encode: encode, toCanvas: toCanvas };
})(typeof window !== 'undefined' ? window : globalThis);

if (typeof module !== 'undefined' && module.exports) {
  module.exports = (typeof window !== 'undefined' ? window : globalThis).HollQR;
}
