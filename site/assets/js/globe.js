/* HollVPN globe — dependency-free WebGL.
 *
 * A privacy product that pulls 600 KB of third-party JavaScript to draw its
 * hero is telling on itself, so this renders on raw WebGL 1 instead: a dark
 * sphere, a dot matrix of coastlines, glowing exit nodes, and great-circle
 * arcs with packets running along them. ~12 KB, no network calls.
 */
(function (root) {
  'use strict';

  /* ---------------------------------------------------------------- mat4 --
   * Column-major, same convention as OpenGL. Only the handful of operations
   * the scene actually needs. */

  function ident() {
    return new Float32Array([1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1]);
  }

  function perspective(fovy, aspect, near, far) {
    var f = 1 / Math.tan(fovy / 2), nf = 1 / (near - far);
    return new Float32Array([
      f / aspect, 0, 0, 0,
      0, f, 0, 0,
      0, 0, (far + near) * nf, -1,
      0, 0, 2 * far * near * nf, 0
    ]);
  }

  function mul(a, b) {
    var o = new Float32Array(16);
    for (var c = 0; c < 4; c++) {
      for (var r = 0; r < 4; r++) {
        var s = 0;
        for (var k = 0; k < 4; k++) s += a[k * 4 + r] * b[c * 4 + k];
        o[c * 4 + r] = s;
      }
    }
    return o;
  }

  function translation(x, y, z) {
    var m = ident(); m[12] = x; m[13] = y; m[14] = z; return m;
  }

  function rotY(rad) {
    var c = Math.cos(rad), s = Math.sin(rad), m = ident();
    m[0] = c; m[2] = -s; m[8] = s; m[10] = c; return m;
  }

  function rotX(rad) {
    var c = Math.cos(rad), s = Math.sin(rad), m = ident();
    m[5] = c; m[6] = s; m[9] = -s; m[10] = c; return m;
  }

  /* ------------------------------------------------------------- geodesy -- */

  function toVec(lonDeg, latDeg, radius) {
    var lon = lonDeg * Math.PI / 180, lat = latDeg * Math.PI / 180;
    var cl = Math.cos(lat);
    return [radius * cl * Math.sin(lon), radius * Math.sin(lat), radius * cl * Math.cos(lon)];
  }

  /* Spherical linear interpolation between two points on the unit sphere,
   * which is what makes an arc follow a great circle rather than cutting a
   * chord through the planet. */
  function slerp(a, b, t) {
    var d = a[0]*b[0] + a[1]*b[1] + a[2]*b[2];
    d = Math.max(-1, Math.min(1, d));
    var o = Math.acos(d);
    if (o < 1e-6) return a.slice();
    var so = Math.sin(o), f1 = Math.sin((1 - t) * o) / so, f2 = Math.sin(t * o) / so;
    return [a[0]*f1 + b[0]*f2, a[1]*f1 + b[1]*f2, a[2]*f1 + b[2]*f2];
  }

  /* --------------------------------------------------------------- exits -- */

  var LOCATIONS = [
    { id:'nl', city:'Амстердам',    country:'Нидерланды',      lat:52.37,  lon:4.90,    load:0.34, hub:true },
    { id:'de', city:'Франкфурт',    country:'Германия',        lat:50.11,  lon:8.68,    load:0.41, hub:true },
    { id:'fi', city:'Хельсинки',    country:'Финляндия',       lat:60.17,  lon:24.94,   load:0.22, hub:true },
    { id:'se', city:'Стокгольм',    country:'Швеция',          lat:59.33,  lon:18.07,   load:0.28 },
    { id:'pl', city:'Варшава',      country:'Польша',          lat:52.23,  lon:21.01,   load:0.37 },
    { id:'gb', city:'Лондон',       country:'Великобритания',  lat:51.51,  lon:-0.13,   load:0.45 },
    { id:'fr', city:'Париж',        country:'Франция',         lat:48.86,  lon:2.35,    load:0.31 },
    { id:'ch', city:'Цюрих',        country:'Швейцария',       lat:47.38,  lon:8.54,    load:0.19 },
    { id:'tr', city:'Стамбул',      country:'Турция',          lat:41.01,  lon:28.98,   load:0.52 },
    { id:'am', city:'Ереван',       country:'Армения',         lat:40.18,  lon:44.51,   load:0.26 },
    { id:'kz', city:'Алматы',       country:'Казахстан',       lat:43.24,  lon:76.89,   load:0.30 },
    { id:'ae', city:'Дубай',        country:'ОАЭ',             lat:25.20,  lon:55.27,   load:0.38 },
    { id:'us', city:'Нью-Йорк',     country:'США',             lat:40.71,  lon:-74.01,  load:0.47, hub:true },
    { id:'la', city:'Лос-Анджелес', country:'США',             lat:34.05,  lon:-118.24, load:0.35 },
    { id:'jp', city:'Токио',        country:'Япония',          lat:35.68,  lon:139.69,  load:0.29 },
    { id:'sg', city:'Сингапур',     country:'Сингапур',        lat:1.35,   lon:103.82,  load:0.33 }
  ];

  /* -------------------------------------------------------------- shaders -- */

  var VS_SPHERE = [
    'attribute vec3 aPos;',
    'uniform mat4 uProj, uView, uModel;',
    'varying vec3 vNormal; varying vec3 vWorld;',
    'void main(){',
    '  vNormal = normalize(mat3(uModel) * aPos);',
    '  vec4 w = uModel * vec4(aPos,1.0);',
    '  vWorld = w.xyz;',
    '  gl_Position = uProj * uView * w;',
    '}'
  ].join('\n');

  var FS_SPHERE = [
    'precision mediump float;',
    'varying vec3 vNormal; varying vec3 vWorld;',
    'uniform vec3 uCam, uDeep, uRim, uLightDir;',
    'void main(){',
    '  vec3 n = normalize(vNormal);',
    '  vec3 v = normalize(uCam - vWorld);',
    '  float fres = pow(1.0 - max(dot(n, v), 0.0), 2.5);',
    // A soft terminator keeps the sphere from reading as a flat disc.
    '  float lambert = max(dot(n, normalize(uLightDir)), 0.0);',
    '  vec3 col = uDeep * (0.55 + 0.45 * lambert) + uRim * fres * 0.9;',
    '  gl_FragColor = vec4(col, 1.0);',
    '}'
  ].join('\n');

  var VS_DOTS = [
    'attribute vec3 aPos; attribute float aSeed;',
    'uniform mat4 uProj, uView, uModel;',
    'uniform vec3 uCam; uniform float uPix, uTime;',
    'varying float vFade; varying float vTw;',
    'void main(){',
    '  vec4 w = uModel * vec4(aPos,1.0);',
    '  vec3 n = normalize(mat3(uModel) * aPos);',
    '  vec3 v = normalize(uCam - w.xyz);',
    '  float facing = dot(n, v);',
    // Dots near the silhouette shrink and dim, which reads as curvature.
    '  vFade = smoothstep(0.02, 0.35, facing);',
    '  vTw = 0.75 + 0.25 * sin(uTime * 1.6 + aSeed * 6.283);',
    '  vec4 p = uProj * uView * w;',
    '  gl_PointSize = uPix * (1.0 + 0.35 * facing) * (0.55 + 0.45 * vFade);',
    '  gl_Position = p;',
    '}'
  ].join('\n');

  var FS_DOTS = [
    'precision mediump float;',
    'varying float vFade; varying float vTw;',
    'uniform vec3 uColor;',
    'void main(){',
    '  vec2 d = gl_PointCoord - vec2(0.5);',
    '  float r = dot(d, d);',
    '  if (r > 0.25) discard;',
    '  float a = smoothstep(0.25, 0.04, r) * vFade * vTw;',
    '  gl_FragColor = vec4(uColor, a);',
    '}'
  ].join('\n');

  var VS_ARC = [
    'attribute vec3 aPos; attribute float aT; attribute float aPhase;',
    'uniform mat4 uProj, uView, uModel; uniform float uTime;',
    'varying float vGlow;',
    'void main(){',
    '  vec4 w = uModel * vec4(aPos,1.0);',
    // One packet per arc, wrapping; brightness falls off behind the head.
    '  float head = fract(uTime * 0.19 + aPhase);',
    '  float d = head - aT;',
    '  if (d < 0.0) d += 1.0;',
    '  vGlow = exp(-d * 11.0) + 0.14;',
    '  gl_Position = uProj * uView * w;',
    '}'
  ].join('\n');

  var FS_ARC = [
    'precision mediump float;',
    'varying float vGlow;',
    'uniform vec3 uColor; uniform float uAlpha;',
    'void main(){ gl_FragColor = vec4(uColor * vGlow, clamp(vGlow,0.0,1.0) * uAlpha); }'
  ].join('\n');

  var VS_MARK = [
    'attribute vec3 aPos; attribute float aSeed;',
    'uniform mat4 uProj, uView, uModel; uniform vec3 uCam;',
    'uniform float uPix, uTime;',
    'varying float vFade; varying float vPulse;',
    'void main(){',
    '  vec4 w = uModel * vec4(aPos,1.0);',
    '  vec3 n = normalize(mat3(uModel) * aPos);',
    '  float facing = dot(n, normalize(uCam - w.xyz));',
    '  vFade = smoothstep(-0.05, 0.25, facing);',
    '  vPulse = 0.5 + 0.5 * sin(uTime * 2.2 + aSeed * 6.283);',
    '  gl_PointSize = uPix * (1.25 + 0.5 * vPulse);',
    '  gl_Position = uProj * uView * w;',
    '}'
  ].join('\n');

  var FS_MARK = [
    'precision mediump float;',
    'varying float vFade; varying float vPulse;',
    'uniform vec3 uColor;',
    'void main(){',
    '  vec2 d = gl_PointCoord - vec2(0.5);',
    '  float r = length(d);',
    '  if (r > 0.5) discard;',
    '  float core = smoothstep(0.16, 0.03, r);',
    '  float ring = smoothstep(0.5, 0.2, r) * 0.35 * (0.4 + vPulse);',
    '  gl_FragColor = vec4(uColor, (core + ring) * vFade);',
    '}'
  ].join('\n');

  var VS_ATMO = [
    'attribute vec3 aPos;',
    'uniform mat4 uProj, uView, uModel; uniform vec3 uCam;',
    'varying vec3 vNormal; varying vec3 vWorld;',
    'void main(){',
    '  vNormal = normalize(mat3(uModel) * aPos);',
    '  vec4 w = uModel * vec4(aPos,1.0);',
    '  vWorld = w.xyz;',
    '  gl_Position = uProj * uView * w;',
    '}'
  ].join('\n');

  var FS_ATMO = [
    'precision mediump float;',
    'varying vec3 vNormal; varying vec3 vWorld;',
    'uniform vec3 uCam, uColor; uniform float uAlpha;',
    'void main(){',
    '  vec3 n = normalize(vNormal);',
    '  vec3 v = normalize(uCam - vWorld);',
    '  float fres = pow(1.0 - abs(dot(n, v)), 3.0);',
    '  gl_FragColor = vec4(uColor * fres, fres * uAlpha);',
    '}'
  ].join('\n');

  /* ------------------------------------------------------------ gl helpers -- */

  function compile(gl, type, src) {
    var sh = gl.createShader(type);
    gl.shaderSource(sh, src);
    gl.compileShader(sh);
    if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
      throw new Error('shader: ' + gl.getShaderInfoLog(sh));
    }
    return sh;
  }

  function program(gl, vs, fs) {
    var p = gl.createProgram();
    gl.attachShader(p, compile(gl, gl.VERTEX_SHADER, vs));
    gl.attachShader(p, compile(gl, gl.FRAGMENT_SHADER, fs));
    gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) {
      throw new Error('link: ' + gl.getProgramInfoLog(p));
    }
    // Cache locations so the draw loop never touches the string API.
    var loc = {}, i, n;
    n = gl.getProgramParameter(p, gl.ACTIVE_UNIFORMS);
    for (i = 0; i < n; i++) {
      var u = gl.getActiveUniform(p, i).name.replace(/\[0\]$/, '');
      loc[u] = gl.getUniformLocation(p, u);
    }
    n = gl.getProgramParameter(p, gl.ACTIVE_ATTRIBUTES);
    for (i = 0; i < n; i++) {
      var a = gl.getActiveAttrib(p, i).name;
      loc[a] = gl.getAttribLocation(p, a);
    }
    p.loc = loc;
    return p;
  }

  function buffer(gl, data, type) {
    var b = gl.createBuffer();
    var target = type || gl.ARRAY_BUFFER;
    gl.bindBuffer(target, b);
    gl.bufferData(target, data, gl.STATIC_DRAW);
    return b;
  }

  function bindAttr(gl, prog, name, buf, size) {
    var l = prog.loc[name];
    if (l === undefined || l < 0) return;
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.enableVertexAttribArray(l);
    gl.vertexAttribPointer(l, size, gl.FLOAT, false, 0, 0);
  }

  function hexToRgb(hex) {
    var h = hex.replace('#', '');
    if (h.length === 3) h = h[0]+h[0]+h[1]+h[1]+h[2]+h[2];
    var n = parseInt(h, 16);
    return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
  }

  /* ----------------------------------------------------------- geometry -- */

  function sphereMesh(rings, sectors, radius) {
    var pos = [], idx = [], r, s;
    for (r = 0; r <= rings; r++) {
      var phi = Math.PI * r / rings;
      for (s = 0; s <= sectors; s++) {
        var theta = 2 * Math.PI * s / sectors;
        pos.push(
          radius * Math.sin(phi) * Math.sin(theta),
          radius * Math.cos(phi),
          radius * Math.sin(phi) * Math.cos(theta)
        );
      }
    }
    for (r = 0; r < rings; r++) {
      for (s = 0; s < sectors; s++) {
        var a = r * (sectors + 1) + s, b = a + sectors + 1;
        idx.push(a, b, a + 1, b, b + 1, a + 1);
      }
    }
    return { pos: new Float32Array(pos), idx: new Uint16Array(idx), count: idx.length };
  }

  /* Coastline dots on an equal-area-ish grid: longitude steps widen toward the
   * poles so the dots stay evenly spaced instead of bunching up. */
  function landDots(step, radius) {
    var world = root.HollWorld, pos = [], seed = [];
    if (!world) return { pos: new Float32Array(0), seed: new Float32Array(0), count: 0 };
    for (var lat = -84; lat <= 84; lat += step) {
      var cos = Math.cos(lat * Math.PI / 180);
      if (cos < 0.06) continue;
      var lonStep = step / cos;
      for (var lon = -180; lon < 180; lon += lonStep) {
        if (!world.isLand(lon, lat)) continue;
        var v = toVec(lon, lat, radius);
        pos.push(v[0], v[1], v[2]);
        seed.push(Math.random());
      }
    }
    return {
      pos: new Float32Array(pos),
      seed: new Float32Array(seed),
      count: pos.length / 3
    };
  }

  function arcGeometry(pairs, segments) {
    var pos = [], ts = [], phase = [], counts = [];
    for (var i = 0; i < pairs.length; i++) {
      var a = toVec(pairs[i][0].lon, pairs[i][0].lat, 1);
      var b = toVec(pairs[i][1].lon, pairs[i][1].lat, 1);
      var dot = Math.max(-1, Math.min(1, a[0]*b[0] + a[1]*b[1] + a[2]*b[2]));
      // Longer hops arch higher, so distant routes stay clear of the surface.
      var lift = 0.10 + 0.30 * (Math.acos(dot) / Math.PI);
      var ph = Math.random();
      for (var s = 0; s <= segments; s++) {
        var t = s / segments;
        var p = slerp(a, b, t);
        var scale = 1 + lift * Math.sin(Math.PI * t);
        pos.push(p[0] * scale, p[1] * scale, p[2] * scale);
        ts.push(t);
        phase.push(ph);
      }
      counts.push(segments + 1);
    }
    return {
      pos: new Float32Array(pos),
      t: new Float32Array(ts),
      phase: new Float32Array(phase),
      counts: counts
    };
  }

  /* ---------------------------------------------------------------- main -- */

  function init(canvas, opts) {
    opts = opts || {};
    var gl = canvas.getContext('webgl', {
      alpha: true, antialias: true, premultipliedAlpha: false,
      powerPreference: 'low-power'
    }) || canvas.getContext('experimental-webgl');
    if (!gl) return null;

    var DEFAULTS = {
      deep: '#0a1830', rim: '#245f9e', dot: '#4A9BFF',
      arc: '#8AC5FF', mark: '#E2EFFF', atmo: '#3B8EF5',
      additive: true, dotScale: 1
    };
    var colors = {}, additive = true, dotScale = 1;

    /* Additive blending makes arcs glow where they cross on a dark ground, but
       on a light one it washes them straight out to white — so the blend mode
       travels with the palette. */
    function setColors(next) {
      var c = Object.assign({}, DEFAULTS, opts, next || {});
      additive = c.additive !== false;
      dotScale = c.dotScale || 1;
      ['deep', 'rim', 'dot', 'arc', 'mark', 'atmo'].forEach(function (k) {
        colors[k] = hexToRgb(c[k]);
      });
    }
    setColors();

    var progSphere = program(gl, VS_SPHERE, FS_SPHERE);
    var progDots   = program(gl, VS_DOTS,   FS_DOTS);
    var progArc    = program(gl, VS_ARC,    FS_ARC);
    var progMark   = program(gl, VS_MARK,   FS_MARK);
    var progAtmo   = program(gl, VS_ATMO,   FS_ATMO);

    var sphere = sphereMesh(48, 64, 1.0);
    var bufSpherePos = buffer(gl, sphere.pos);
    var bufSphereIdx = buffer(gl, sphere.idx, gl.ELEMENT_ARRAY_BUFFER);

    var atmo = sphereMesh(32, 48, 1.16);
    var bufAtmoPos = buffer(gl, atmo.pos);
    var bufAtmoIdx = buffer(gl, atmo.idx, gl.ELEMENT_ARRAY_BUFFER);

    var dots = landDots(opts.dotStep || 1.5, 1.004);
    var bufDotPos = buffer(gl, dots.pos);
    var bufDotSeed = buffer(gl, dots.seed);

    // Routes fan out from the European hubs, which is where most traffic for
    // this audience actually exits.
    var hubs = LOCATIONS.filter(function (l) { return l.hub; });
    var pairs = [];
    LOCATIONS.forEach(function (l, i) {
      if (l.hub) return;
      pairs.push([hubs[i % hubs.length], l]);
    });
    pairs.push([hubs[0], hubs[2]], [hubs[1], hubs[3 % hubs.length]], [hubs[0], hubs[1]]);
    var arcs = arcGeometry(pairs, 64);
    var bufArcPos = buffer(gl, arcs.pos);
    var bufArcT = buffer(gl, arcs.t);
    var bufArcPhase = buffer(gl, arcs.phase);

    var markPos = [], markSeed = [];
    LOCATIONS.forEach(function (l) {
      var v = toVec(l.lon, l.lat, 1.012);
      markPos.push(v[0], v[1], v[2]);
      markSeed.push(Math.random());
    });
    var bufMarkPos = buffer(gl, new Float32Array(markPos));
    var bufMarkSeed = buffer(gl, new Float32Array(markSeed));

    var state = {
      yaw: -0.6, pitch: -0.32, targetYaw: -0.6, targetPitch: -0.32,
      spin: 0.055, dragging: false, vx: 0, lastX: 0, lastY: 0,
      dpr: 1, w: 0, h: 0, running: false, raf: 0, t0: performance.now()
    };

    var reduced = root.matchMedia &&
      root.matchMedia('(prefers-reduced-motion: reduce)').matches;

    function resize() {
      var dpr = Math.min(root.devicePixelRatio || 1, 2);
      var w = canvas.clientWidth, h = canvas.clientHeight;
      if (!w || !h) return false;
      if (state.w === w && state.h === h && state.dpr === dpr) return false;
      state.w = w; state.h = h; state.dpr = dpr;
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      gl.viewport(0, 0, canvas.width, canvas.height);
      return true;
    }

    var camZ = 5.2;
    var camera = [0, 0, camZ];

    function draw(now) {
      var time = (now - state.t0) / 1000;

      if (!state.dragging) {
        state.targetYaw += state.spin * 0.016;
        state.targetYaw += state.vx;
        state.vx *= 0.94;
      }
      state.yaw += (state.targetYaw - state.yaw) * 0.09;
      state.pitch += (state.targetPitch - state.pitch) * 0.09;

      var proj = perspective(Math.PI / 6, canvas.width / canvas.height, 0.1, 40);
      var view = translation(0, 0, -camZ);
      var model = mul(rotX(state.pitch), rotY(state.yaw));
      var pix = state.dpr;

      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
      gl.enable(gl.DEPTH_TEST);
      gl.depthFunc(gl.LEQUAL);
      gl.enable(gl.BLEND);
      gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);

      // 1. Opaque sphere. Also the depth mask that hides the far-side dots
      //    and the far half of every arc, with no sorting on our side.
      gl.useProgram(progSphere);
      gl.depthMask(true);
      gl.uniformMatrix4fv(progSphere.loc.uProj, false, proj);
      gl.uniformMatrix4fv(progSphere.loc.uView, false, view);
      gl.uniformMatrix4fv(progSphere.loc.uModel, false, model);
      gl.uniform3fv(progSphere.loc.uCam, camera);
      gl.uniform3fv(progSphere.loc.uDeep, colors.deep);
      gl.uniform3fv(progSphere.loc.uRim, colors.rim);
      gl.uniform3fv(progSphere.loc.uLightDir, [0.55, 0.42, 0.72]);
      bindAttr(gl, progSphere, 'aPos', bufSpherePos, 3);
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, bufSphereIdx);
      gl.drawElements(gl.TRIANGLES, sphere.count, gl.UNSIGNED_SHORT, 0);

      // 2. Coastlines.
      gl.useProgram(progDots);
      gl.depthMask(false);
      gl.uniformMatrix4fv(progDots.loc.uProj, false, proj);
      gl.uniformMatrix4fv(progDots.loc.uView, false, view);
      gl.uniformMatrix4fv(progDots.loc.uModel, false, model);
      gl.uniform3fv(progDots.loc.uCam, camera);
      gl.uniform3fv(progDots.loc.uColor, colors.dot);
      gl.uniform1f(progDots.loc.uPix, 1.9 * pix * dotScale);
      gl.uniform1f(progDots.loc.uTime, time);
      bindAttr(gl, progDots, 'aPos', bufDotPos, 3);
      bindAttr(gl, progDots, 'aSeed', bufDotSeed, 1);
      gl.drawArrays(gl.POINTS, 0, dots.count);

      // 3. Routes, additive so crossings brighten.
      gl.useProgram(progArc);
      gl.blendFunc(gl.SRC_ALPHA, additive ? gl.ONE : gl.ONE_MINUS_SRC_ALPHA);
      gl.uniformMatrix4fv(progArc.loc.uProj, false, proj);
      gl.uniformMatrix4fv(progArc.loc.uView, false, view);
      gl.uniformMatrix4fv(progArc.loc.uModel, false, model);
      gl.uniform3fv(progArc.loc.uColor, colors.arc);
      gl.uniform1f(progArc.loc.uAlpha, additive ? 0.85 : 0.95);
      gl.uniform1f(progArc.loc.uTime, time);
      bindAttr(gl, progArc, 'aPos', bufArcPos, 3);
      bindAttr(gl, progArc, 'aT', bufArcT, 1);
      bindAttr(gl, progArc, 'aPhase', bufArcPhase, 1);
      var off = 0;
      for (var i = 0; i < arcs.counts.length; i++) {
        gl.drawArrays(gl.LINE_STRIP, off, arcs.counts[i]);
        off += arcs.counts[i];
      }

      // 4. Exit nodes.
      gl.useProgram(progMark);
      gl.uniformMatrix4fv(progMark.loc.uProj, false, proj);
      gl.uniformMatrix4fv(progMark.loc.uView, false, view);
      gl.uniformMatrix4fv(progMark.loc.uModel, false, model);
      gl.uniform3fv(progMark.loc.uCam, camera);
      gl.uniform3fv(progMark.loc.uColor, colors.mark);
      gl.uniform1f(progMark.loc.uPix, 7 * pix);
      gl.uniform1f(progMark.loc.uTime, time);
      bindAttr(gl, progMark, 'aPos', bufMarkPos, 3);
      bindAttr(gl, progMark, 'aSeed', bufMarkSeed, 1);
      gl.drawArrays(gl.POINTS, 0, LOCATIONS.length);

      // 5. Atmosphere last, depth-free, so the halo survives the silhouette.
      gl.useProgram(progAtmo);
      gl.disable(gl.DEPTH_TEST);
      gl.uniformMatrix4fv(progAtmo.loc.uProj, false, proj);
      gl.uniformMatrix4fv(progAtmo.loc.uView, false, view);
      gl.uniformMatrix4fv(progAtmo.loc.uModel, false, model);
      gl.uniform3fv(progAtmo.loc.uCam, camera);
      gl.uniform3fv(progAtmo.loc.uColor, colors.atmo);
      gl.uniform1f(progAtmo.loc.uAlpha, additive ? 0.55 : 0.32);
      bindAttr(gl, progAtmo, 'aPos', bufAtmoPos, 3);
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, bufAtmoIdx);
      gl.drawElements(gl.TRIANGLES, atmo.count, gl.UNSIGNED_SHORT, 0);

      gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    }

    function frame(now) {
      resize();
      draw(now);
      if (state.running) state.raf = requestAnimationFrame(frame);
    }

    function start() {
      if (state.running || reduced) return;
      state.running = true;
      state.raf = requestAnimationFrame(frame);
    }

    function stop() {
      state.running = false;
      cancelAnimationFrame(state.raf);
    }

    /* Drag to spin. Vertical drag is clamped so the globe can never flip past
     * the poles and leave the user upside down. */
    function onDown(e) {
      state.dragging = true;
      state.lastX = e.clientX; state.lastY = e.clientY; state.vx = 0;
      canvas.setPointerCapture && canvas.setPointerCapture(e.pointerId);
      canvas.classList.add('is-grabbing');
    }
    function onMove(e) {
      if (!state.dragging) return;
      var dx = (e.clientX - state.lastX) / Math.max(state.w, 1);
      var dy = (e.clientY - state.lastY) / Math.max(state.h, 1);
      state.lastX = e.clientX; state.lastY = e.clientY;
      state.targetYaw += dx * 3.2;
      state.targetPitch = Math.max(-0.9, Math.min(0.9, state.targetPitch + dy * 2.2));
      state.vx = dx * 0.35;
      if (!state.running && !reduced) start();
    }
    function onUp(e) {
      state.dragging = false;
      canvas.releasePointerCapture && e.pointerId != null &&
        canvas.releasePointerCapture(e.pointerId);
      canvas.classList.remove('is-grabbing');
      if (reduced) { resize(); draw(performance.now()); }
    }

    canvas.addEventListener('pointerdown', onDown);
    root.addEventListener('pointermove', onMove);
    root.addEventListener('pointerup', onUp);
    root.addEventListener('pointercancel', onUp);

    // Off-screen and background tabs cost nothing.
    if (root.IntersectionObserver) {
      new IntersectionObserver(function (entries) {
        entries[0].isIntersecting ? start() : stop();
      }, { threshold: 0.01 }).observe(canvas);
    } else {
      start();
    }
    document.addEventListener('visibilitychange', function () {
      document.hidden ? stop() : start();
    });

    resize();
    draw(performance.now());
    if (!reduced) start();

    return {
      start: start, stop: stop, locations: LOCATIONS,
      setColors: function (next) {
        setColors(next);
        if (!state.running) { resize(); draw(performance.now()); }
      },
      focus: function (loc) {
        state.targetYaw = -loc.lon * Math.PI / 180;
        state.targetPitch = loc.lat * Math.PI / 180 * 0.75;
        state.vx = 0;
        if (reduced) {
          // Reduced motion still gets the answer, just without the journey.
          state.yaw = state.targetYaw; state.pitch = state.targetPitch;
          resize(); draw(performance.now());
        }
      }
    };
  }

  root.HollGlobe = { init: init, LOCATIONS: LOCATIONS, toVec: toVec };
})(typeof window !== 'undefined' ? window : globalThis);
