/* HollVPN — поведение лендинга.
 *
 * Всё, что нужно менять при запуске — бот, ссылки и цены — собрано
 * в CONFIG наверху. Ниже правки не требуются.
 */
(function () {
  'use strict';

  var CONFIG = {
    bot:      'hollvpn_bot',            // https://t.me/<bot>
    support:  'hollvpn_support',
    channel:  'hollvpn_status',
    checkout: '/checkout',              // страница оплаты на сайте
    currency: '₽',

    plans: [
      {
        id: 'start', name: 'Старт', sub: 'Одному человеку',
        month: 199, year: 119, devices: 5,
        features: [
          'Все 16 локаций',
          'Безлимитная скорость',
          'VLESS + Reality, AmneziaWG, Shadowsocks',
          'Раздельное туннелирование',
          'Поддержка 24/7 в Telegram'
        ],
        absent: ['Отдельные профили для семьи']
      },
      {
        id: 'pro', name: 'Про', sub: 'Самый частый выбор', featured: true,
        month: 349, year: 209, devices: 10,
        features: [
          'Всё из «Старта»',
          'Приоритетные серверы с меньшей загрузкой',
          'Выделенный IP по запросу',
          'Ранний доступ к новым локациям',
          'Ответ поддержки вне очереди'
        ],
        absent: ['Отдельные профили для семьи']
      },
      {
        id: 'family', name: 'Семейный', sub: 'До пяти профилей',
        month: 599, year: 359, devices: 25,
        features: [
          'Всё из «Про»',
          '5 отдельных профилей с своими ключами',
          'Каждый профиль отзывается отдельно',
          'Общая оплата, раздельный доступ',
          'Помощь с настройкой роутера'
        ],
        absent: []
      }
    ]
  };

  var $  = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;

  function fmt(n) {
    // Неразрывный пробел между разрядами: цена не переносится по строке.
    return String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
  }

  /* ------------------------------------------------------------- ссылки -- */

  function tgLink(utm) {
    return 'https://t.me/' + CONFIG.bot + (utm ? '?start=' + encodeURIComponent(utm) : '');
  }

  function wireLinks(scope) {
    $$('[data-tg]', scope).forEach(function (a) {
      a.href = tgLink(a.getAttribute('data-utm') || 'site');
      a.rel = 'noopener';
    });
    $$('[data-tg-support]', scope).forEach(function (a) {
      a.href = 'https://t.me/' + CONFIG.support; a.rel = 'noopener';
    });
    $$('[data-tg-channel]', scope).forEach(function (a) {
      a.href = 'https://t.me/' + CONFIG.channel; a.rel = 'noopener';
    });
  }

  /* --------------------------------------------------------------- тема -- */

  function initTheme() {
    var btn = $('#themeToggle');
    if (!btn) return;
    function sync() {
      var dark = document.documentElement.getAttribute('data-theme') !== 'light';
      var use = $('use', btn);
      if (use) use.setAttribute('href', dark ? '#i-moon' : '#i-sun');
      btn.setAttribute('aria-label', dark ? 'Включить светлую тему' : 'Включить тёмную тему');
    }
    btn.addEventListener('click', function () {
      var next = document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
      document.documentElement.setAttribute('data-theme', next);
      try { localStorage.setItem('hollvpn-theme', next); } catch (e) {}
      sync();
      document.dispatchEvent(new CustomEvent('hollvpn:theme', { detail: next }));
    });
    sync();
  }

  /* ------------------------------------------------------------- шапка -- */

  function initHeader() {
    var header = $('#header'), nav = $('#nav'), burger = $('#burger');

    var onScroll = function () {
      header.classList.toggle('is-stuck', window.scrollY > 8);
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();

    if (burger && nav) {
      burger.addEventListener('click', function () {
        var open = nav.classList.toggle('is-open');
        burger.setAttribute('aria-expanded', String(open));
      });
      nav.addEventListener('click', function (e) {
        if (e.target.tagName === 'A') {
          nav.classList.remove('is-open');
          burger.setAttribute('aria-expanded', 'false');
        }
      });
    }

    // Подсветка текущего раздела в навигации.
    var links = $$('#nav a[href^="#"]');
    var targets = links.map(function (a) { return $(a.getAttribute('href')); }).filter(Boolean);
    if (!targets.length || !window.IntersectionObserver) return;

    var spy = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (!en.isIntersecting) return;
        links.forEach(function (a) {
          a.classList.toggle('is-current', a.getAttribute('href') === '#' + en.target.id);
        });
      });
    }, { rootMargin: '-45% 0px -50% 0px' });
    targets.forEach(function (t) { spy.observe(t); });
  }

  /* --------------------------------------------------------- анимации -- */

  function initReveal() {
    var items = $$('.reveal');
    if (!window.IntersectionObserver || reduced) {
      items.forEach(function (el) { el.classList.add('is-in'); });
      return;
    }
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (!en.isIntersecting) return;
        en.target.classList.add('is-in');
        io.unobserve(en.target);
      });
    }, { rootMargin: '0px 0px -8% 0px', threshold: 0.05 });
    items.forEach(function (el) { io.observe(el); });
  }

  function initCounters() {
    var els = $$('[data-count-to]');
    if (!els.length) return;
    if (reduced || !window.IntersectionObserver) return;

    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (!en.isIntersecting) return;
        var el = en.target;
        io.unobserve(el);
        var to = parseFloat(el.getAttribute('data-count-to'));
        var dec = parseInt(el.getAttribute('data-decimals') || '0', 10);
        var t0 = performance.now(), dur = 1100;
        (function tick(now) {
          var p = Math.min(1, (now - t0) / dur);
          var eased = 1 - Math.pow(1 - p, 3);
          el.textContent = (to * eased).toFixed(dec);
          if (p < 1) requestAnimationFrame(tick);
        })(t0);
      });
    }, { threshold: 0.6 });
    els.forEach(function (el) { io.observe(el); });
  }

  /* Наклон карточки вслед за курсором. Слушатель один на документ:
     полсотни отдельных обработчиков на движение мыши стоили бы дороже. */
  function initTilt() {
    if (reduced || matchMedia('(hover: none)').matches) return;

    document.addEventListener('pointermove', function (e) {
      var tilt = e.target.closest ? e.target.closest('.tilt') : null;
      if (!tilt) return;
      var card = tilt.firstElementChild;
      if (!card) return;
      var r = tilt.getBoundingClientRect();
      var px = (e.clientX - r.left) / r.width;
      var py = (e.clientY - r.top) / r.height;
      var dx = px - 0.5, dy = py - 0.5;
      var deg = Math.min(7, Math.hypot(dx, dy) * 14);
      card.style.setProperty('--rx', String(dx));
      card.style.setProperty('--ry', String(-dy));
      card.style.setProperty('--deg', deg.toFixed(2) + 'deg');
      card.style.setProperty('--mx', (px * 100).toFixed(1) + '%');
      card.style.setProperty('--my', (py * 100).toFixed(1) + '%');
    }, { passive: true });

    document.addEventListener('pointerleave', function (e) {
      var tilt = e.target.closest ? e.target.closest('.tilt') : null;
      if (!tilt) return;
      var card = tilt.firstElementChild;
      if (card) card.style.setProperty('--deg', '0deg');
    }, true);
  }

  /* ------------------------------------------------------ география -- */

  /* Приблизительные координаты посетителя по часовому поясу. Точность нужна
     не выше «какой континент», поэтому этого достаточно, а запрос к сервису
     геолокации на сайте про приватность был бы странным. */
  var TZ = {
    'Europe/Moscow': [55.75, 37.62], 'Europe/Kaliningrad': [54.7, 20.5],
    'Europe/Samara': [53.2, 50.15], 'Asia/Yekaterinburg': [56.84, 60.6],
    'Asia/Omsk': [54.99, 73.37], 'Asia/Novosibirsk': [55.03, 82.92],
    'Asia/Krasnoyarsk': [56.01, 92.87], 'Asia/Irkutsk': [52.29, 104.3],
    'Asia/Vladivostok': [43.12, 131.89], 'Europe/Kyiv': [50.45, 30.52],
    'Europe/Kiev': [50.45, 30.52], 'Europe/Minsk': [53.9, 27.57],
    'Asia/Almaty': [43.24, 76.89], 'Asia/Tashkent': [41.3, 69.24],
    'Asia/Tbilisi': [41.7, 44.8], 'Asia/Yerevan': [40.18, 44.51],
    'Asia/Baku': [40.4, 49.87], 'Europe/Istanbul': [41.01, 28.98],
    'Europe/Berlin': [52.52, 13.4], 'Europe/London': [51.51, -0.13],
    'Europe/Warsaw': [52.23, 21.01], 'Europe/Belgrade': [44.79, 20.45],
    'Asia/Dubai': [25.2, 55.27], 'Asia/Bangkok': [13.75, 100.5],
    'America/New_York': [40.71, -74.01], 'America/Los_Angeles': [34.05, -118.24]
  };

  function here() {
    var tz = '';
    try { tz = Intl.DateTimeFormat().resolvedOptions().timeZone || ''; } catch (e) {}
    if (TZ[tz]) return TZ[tz];
    // Запасной вариант: долгота из смещения UTC, широта — средняя по России.
    var offset = -new Date().getTimezoneOffset() / 60;
    return [52, Math.max(-180, Math.min(180, offset * 15))];
  }

  function distanceKm(a, b) {
    var R = 6371, rad = Math.PI / 180;
    var dLat = (b[0] - a[0]) * rad, dLon = (b[1] - a[1]) * rad;
    var s = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
            Math.cos(a[0] * rad) * Math.cos(b[0] * rad) *
            Math.sin(dLon / 2) * Math.sin(dLon / 2);
    return 2 * R * Math.atan2(Math.sqrt(s), Math.sqrt(1 - s));
  }

  /* Свет в оптоволокне идёт примерно 200 км/мс, маршрут никогда не прямой,
     плюс задержка на оборудовании. Оценка, а не замер, — так и подписано. */
  function estimateRtt(from, to) {
    var km = distanceKm(from, to);
    return Math.round(8 + (km / 100) * 1.45);
  }

  /* ------------------------------------------------- глобус и серверы -- */

  function initGlobeAndServers() {
    var canvas = $('#globe'), stage = $('#globeStage'), list = $('#serverScroll');
    var locations = (window.HollGlobe && window.HollGlobe.LOCATIONS) || [];
    if (!locations.length) return;

    var origin = here();
    // Оценка задержки и сортировка «ближайшие сверху» — то, что человек
    // на этой странице действительно хочет знать.
    locations.forEach(function (l) { l.rtt = estimateRtt(origin, [l.lat, l.lon]); });
    var sorted = locations.slice().sort(function (a, b) { return a.rtt - b.rtt; });

    // A dark navy sphere on a paper-white page reads as a hole, so the globe
    // gets its own palette per theme.
    var LIGHT_GLOBE = {
      deep: '#cfe3f4', rim: '#5f9ecd', dot: '#0a4f68',
      arc: '#0e7490', mark: '#0c4a6e', atmo: '#38bdf8',
      additive: false, dotScale: 1.3
    };
    function globeTheme() {
      return document.documentElement.getAttribute('data-theme') === 'light'
        ? LIGHT_GLOBE : {};
    }

    var globe = null;
    if (canvas && window.HollGlobe) {
      try {
        globe = window.HollGlobe.init(canvas, globeTheme());
      } catch (e) {
        globe = null;
      }
    }
    if (globe) {
      document.addEventListener('hollvpn:theme', function () {
        globe.setColors(globeTheme());
      });
    }
    if (!globe && stage) {
      // Нет WebGL — вместо пустого места осмысленная заглушка.
      if (canvas) canvas.hidden = true;
      var fb = document.createElement('div');
      fb.className = 'globe-fallback';
      fb.textContent = '16 серверов в Европе, США и Азии';
      stage.appendChild(fb);
    }

    var readout = $('#globeReadout'), roCity = $('#roCity'), roMeta = $('#roMeta');

    function select(loc, row) {
      $$('.server-row', list).forEach(function (r) { r.classList.remove('is-active'); });
      if (row) row.classList.add('is-active');
      if (globe) globe.focus(loc);
      if (readout) {
        readout.hidden = false;
        roCity.textContent = loc.city;
        roMeta.textContent = '≈ ' + loc.rtt + ' мс · загрузка ' + Math.round(loc.load * 100) + '%';
      }
    }

    if (!list) return;
    sorted.forEach(function (loc, i) {
      var row = document.createElement('button');
      row.type = 'button';
      row.className = 'server-row';
      row.setAttribute('role', 'listitem');

      var loadClass = loc.load > 0.66 ? 'high' : (loc.load > 0.4 ? 'mid' : '');
      row.innerHTML =
        '<span class="name">' +
          '<span class="flag">' + loc.id.toUpperCase() + '</span>' +
          '<span><span class="city">' + loc.city + '</span> ' +
          '<span class="country">' + loc.country + '</span></span>' +
        '</span>' +
        '<span class="ping' + (loc.rtt > 120 ? ' is-far' : '') + '">≈ ' + loc.rtt + ' мс</span>' +
        '<span class="loadbar"><i class="' + loadClass + '" style="width:' +
          Math.round(loc.load * 100) + '%"></i></span>';

      row.addEventListener('click', function () { select(loc, row); });
      list.appendChild(row);
      if (i === 0) select(loc, row);
    });

    var foot = document.createElement('div');
    foot.className = 'server-foot';
    foot.innerHTML = '<span><b>' + sorted.length + '</b> локаций — список прокручивается</span>' +
                     '<span>ближайшая: <b>' + sorted[0].city + '</b></span>';
    list.parentNode.appendChild(foot);
  }

  /* ------------------------------------------------------------ тарифы -- */

  var period = 'year';

  function planCard(p) {
    var price = p[period];
    var save = Math.round((1 - p.year / p.month) * 100);
    var note = period === 'year'
      ? '<s>' + fmt(p.month) + ' ' + CONFIG.currency + '</s> — <b>выгода ' + save +
        '%</b>, ' + fmt(p.year * 12) + ' ' + CONFIG.currency + ' за год'
      : 'списание раз в месяц, отменить можно в любой момент';

    var feats = p.features.map(function (f) {
      return '<li><svg aria-hidden="true"><use href="#i-check"/></svg>' + f + '</li>';
    }).join('');
    var absent = (p.absent || []).map(function (f) {
      return '<li class="muted"><svg aria-hidden="true"><use href="#i-close-x"/></svg>' + f + '</li>';
    }).join('');

    return '' +
      '<article class="card plan' + (p.featured ? ' plan--featured' : '') + '" data-plan="' + p.id + '">' +
        (p.featured ? '<span class="plan-tag">Популярный</span>' : '') +
        '<h3>' + p.name + '</h3>' +
        '<div class="plan-sub">' + p.sub + ' · до ' + p.devices + ' устройств</div>' +
        '<div class="price"><span class="amount">' + fmt(price) + '</span>' +
          '<span class="per">' + CONFIG.currency + ' / мес</span></div>' +
        '<div class="price-note">' + note + '</div>' +
        '<ul>' + feats + absent + '</ul>' +
        '<div class="plan-foot">' +
          '<a class="btn ' + (p.featured ? 'btn--primary' : 'btn--ghost') + ' btn--block" ' +
             'data-tg data-utm="plan_' + p.id + '_' + period + '" href="#">' +
            '<svg aria-hidden="true"><use href="#i-tg"/></svg>Оформить в Telegram</a>' +
          '<div class="plan-alt">или <a href="' + CONFIG.checkout + '?plan=' + p.id +
            '&period=' + period + '">оплатить на сайте</a></div>' +
        '</div>' +
      '</article>';
  }

  function renderPlans() {
    var host = $('#plans');
    if (!host) return;
    host.innerHTML = CONFIG.plans.map(planCard).join('');
    wireLinks(host);

    var hint = $('#saveHint');
    if (hint) {
      var best = Math.max.apply(null, CONFIG.plans.map(function (p) {
        return Math.round((1 - p.year / p.month) * 100);
      }));
      hint.textContent = period === 'year'
        ? 'Экономия до ' + best + '% по сравнению с помесячной оплатой'
        : 'На годовой оплате те же тарифы дешевле до ' + best + '%';
    }
  }

  function initPricing() {
    var seg = $$('[data-period]');
    if (!seg.length) return;
    seg.forEach(function (btn) {
      btn.addEventListener('click', function () {
        period = btn.getAttribute('data-period');
        seg.forEach(function (b) {
          b.setAttribute('aria-selected', String(b === btn));
        });
        renderPlans();
        updateCalc();
      });
    });
    renderPlans();
  }

  /* -------------------------------------------------------------- квиз -- */

  var QUIZ = [
    {
      q: 'Сколько устройств нужно подключить?',
      hint: 'Считайте телефоны, компьютеры, планшеты и телевизор.',
      options: [
        { label: 'Одно-два — только себе', v: { devices: 2 } },
        { label: 'Три-семь — я и близкие', v: { devices: 7 } },
        { label: 'Восемь и больше — вся семья', v: { devices: 20 } }
      ]
    },
    {
      q: 'Что важнее всего?',
      hint: 'Можно выбрать главное — остальное есть на всех тарифах.',
      options: [
        { label: 'Чтобы просто работало и не блокировалось', v: { need: 'access' } },
        { label: 'Скорость: стриминг, торренты, игры', v: { need: 'speed' } },
        { label: 'Приватность и минимум следов', v: { need: 'privacy' } }
      ]
    },
    {
      q: 'На какой срок берёте?',
      hint: 'Годовая оплата дешевле, но начать можно и с пробного периода.',
      options: [
        { label: 'Сначала попробую бесплатно', v: { term: 'trial' } },
        { label: 'На месяц, посмотрю по ходу', v: { term: 'month' } },
        { label: 'Сразу на год, чтобы дешевле', v: { term: 'year' } }
      ]
    }
  ];

  function recommend(a) {
    var plan = CONFIG.plans[0];
    if (a.devices > 10) plan = CONFIG.plans[2];
    else if (a.devices > 2 || a.need === 'speed') plan = CONFIG.plans[1];

    var term = a.term === 'year' ? 'year' : 'month';
    var reasons = [];
    reasons.push('Устройств хватит: тариф даёт до ' + plan.devices + ', вам нужно около ' + a.devices + '.');
    if (a.need === 'speed') reasons.push('Для стриминга и игр берите ближайшие локации — Хельсинки или Варшаву.');
    if (a.need === 'privacy') reasons.push('Включите Kill Switch и проверьте утечки — обе инструкции есть в справочнике.');
    if (a.need === 'access') reasons.push('Оставьте протокол VLESS + Reality: он выдаётся по умолчанию и не определяется фильтрами.');
    if (a.term === 'trial') reasons.push('Начните с трёх бесплатных дней — карта не нужна, тариф выберете потом.');
    if (a.term === 'year') reasons.push('Годовая оплата экономит ' +
      Math.round((1 - plan.year / plan.month) * 100) + '% — это ' +
      fmt(plan.month * 12 - plan.year * 12) + ' ' + CONFIG.currency + ' за год.');
    return { plan: plan, term: term, reasons: reasons, trial: a.term === 'trial' };
  }

  function initQuiz() {
    var body = $('#quizBody'), bar = $('#quizBar');
    if (!body) return;
    var step = 0, answers = {};

    function renderStep() {
      if (step >= QUIZ.length) return renderResult();
      var q = QUIZ[step];
      bar.style.width = ((step / QUIZ.length) * 100) + '%';
      body.innerHTML =
        '<span class="eyebrow" style="margin-bottom:14px">Подбор тарифа</span>' +
        '<div class="quiz-q">' + q.q + '</div>' +
        '<div class="quiz-hint">' + q.hint + '</div>' +
        '<div class="quiz-options">' + q.options.map(function (o, i) {
          return '<button class="quiz-opt" type="button" data-i="' + i + '">' +
                 '<span class="o-key">' + (i + 1) + '</span>' + o.label + '</button>';
        }).join('') + '</div>' +
        '<div class="quiz-steps">Шаг ' + (step + 1) + ' из ' + QUIZ.length +
          (step > 0 ? ' · <a href="#" data-back>назад</a>' : '') + '</div>';

      $$('.quiz-opt', body).forEach(function (btn) {
        btn.addEventListener('click', function () {
          Object.assign(answers, q.options[+btn.getAttribute('data-i')].v);
          step++;
          renderStep();
        });
      });
      var back = $('[data-back]', body);
      if (back) back.addEventListener('click', function (e) {
        e.preventDefault(); step--; renderStep();
      });
    }

    function renderResult() {
      bar.style.width = '100%';
      var r = recommend(answers);
      var price = r.plan[r.term];
      body.innerHTML =
        '<span class="eyebrow" style="margin-bottom:14px">Рекомендация</span>' +
        '<div class="quiz-result">' +
          '<div class="r-plan">' + r.plan.name +
            ' <span class="r-price">' + fmt(price) + ' ' + CONFIG.currency + '/мес</span></div>' +
          '<ul>' + r.reasons.map(function (x) { return '<li>' + x + '</li>'; }).join('') + '</ul>' +
          '<div class="stack gap-8">' +
            '<a class="btn btn--primary btn--block" data-tg data-utm="quiz_' + r.plan.id + '" href="#">' +
              '<svg aria-hidden="true"><use href="#i-tg"/></svg>' +
              (r.trial ? 'Начать бесплатно' : 'Оформить «' + r.plan.name + '»') + '</a>' +
            '<button class="btn btn--ghost btn--block" type="button" data-restart>Пройти заново</button>' +
          '</div>' +
        '</div>';
      wireLinks(body);
      $('[data-restart]', body).addEventListener('click', function () {
        step = 0; answers = {}; renderStep();
      });
    }

    renderStep();
  }

  /* ------------------------------------------------------ калькулятор -- */

  function updateCalc() {
    var price = $('#calcPrice'), devices = $('#calcDevices');
    if (!price || !devices) return;

    var cur = +price.value, need = +devices.value;
    var plan = CONFIG.plans.filter(function (p) { return p.devices >= need; })[0] ||
               CONFIG.plans[CONFIG.plans.length - 1];
    var ours = plan[period];

    $('#calcPriceOut').textContent = fmt(cur);
    $('#calcDevicesOut').textContent = need;
    $('#calcOurs').textContent = fmt(ours) + ' ' + CONFIG.currency;

    var save = (cur - ours) * 12;
    var out = $('#calcSave'), box = out.closest('.o');
    if (save > 0) {
      out.textContent = fmt(save) + ' ' + CONFIG.currency;
      box.classList.add('win');
      box.querySelector('.k').textContent = 'Экономия за год';
    } else {
      // Честнее показать «дороже», чем нарисовать отрицательную экономию.
      out.textContent = fmt(-save) + ' ' + CONFIG.currency;
      box.classList.remove('win');
      box.querySelector('.k').textContent = save === 0 ? 'Разницы нет' : 'Дороже за год';
    }
  }

  function paintRange(el) {
    var span = (el.max - el.min) || 1;
    el.style.setProperty('--fill', ((el.value - el.min) / span * 100).toFixed(1) + '%');
  }

  function initCalc() {
    ['#calcPrice', '#calcDevices'].forEach(function (sel) {
      var el = $(sel);
      if (!el) return;
      paintRange(el);
      el.addEventListener('input', function () { paintRange(el); updateCalc(); });
    });
    updateCalc();
  }

  /* --------------------------------------------------------------- QR -- */

  function initQR() {
    var canvas = $('#qr');
    if (!canvas || !window.HollQR) return;
    var link = tgLink('qr');

    function paint() {
      var light = getComputedStyle(document.documentElement)
        .getPropertyValue('--bg-3').trim() || '#ffffff';
      var dark = document.documentElement.getAttribute('data-theme') === 'light'
        ? '#08131F' : '#06121e';
      try {
        window.HollQR.toCanvas(canvas, link, { size: 148, dark: dark, light: '#ffffff' });
      } catch (e) {
        canvas.hidden = true;
      }
      void light;
    }
    paint();
    document.addEventListener('hollvpn:theme', paint);

    $$('[data-copy-tg]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var label = btn.innerHTML;
        var done = function () {
          btn.textContent = 'Ссылка скопирована';
          setTimeout(function () { btn.innerHTML = label; }, 1800);
        };
        if (navigator.clipboard) navigator.clipboard.writeText(link).then(done, done);
        else done();
      });
    });
  }

  /* ------------------------------------------------------- утечки -- */

  function initLeak() {
    var btn = $('#leakRun'), grid = $('#leakGrid');
    if (!btn || !grid || !window.HollLeak) return;

    btn.addEventListener('click', function () {
      var res = window.HollLeak.run();
      var render = function (items) {
        grid.innerHTML = items.map(function (it) {
          return '<div class="leak-item' + (it.exposed ? ' is-exposed' : '') + '">' +
                 '<div class="k">' + it.k + '</div>' +
                 '<div class="v">' + String(it.v) + '</div></div>';
        }).join('');
      };
      render(res.items);
      btn.textContent = 'Проверить ещё раз';

      res.webrtc.then(function (w) {
        var items = res.items.slice();
        items[items.length - 1] = {
          k: 'Локальный IP (WebRTC)', v: w.value, exposed: w.exposed
        };
        render(items);
      });
    });
  }

  /* ------------------------------------------------- командная палитра -- */

  function buildIndex() {
    var idx = [];

    $$('main section[id]').forEach(function (s) {
      var h = s.querySelector('h1, h2');
      if (!h) return;
      var p = s.querySelector('.lede');
      idx.push({
        kind: 'Раздел', icon: 'i-arrow',
        title: h.textContent.trim(),
        desc: p ? p.textContent.trim().slice(0, 90) : '',
        href: '#' + s.id
      });
    });

    (window.HollKB ? window.HollKB.categories : []).forEach(function (c) {
      c.articles.forEach(function (a) {
        idx.push({
          kind: 'Справочник', icon: 'i-book',
          title: a.title, desc: a.summary,
          href: 'guide.html#' + a.id
        });
      });
    });

    ((window.HollGlobe && window.HollGlobe.LOCATIONS) || []).forEach(function (l) {
      idx.push({
        kind: 'Локация', icon: 'i-globe',
        title: l.city + ', ' + l.country,
        desc: 'Сервер HollVPN' + (l.rtt ? ' · ≈ ' + l.rtt + ' мс' : ''),
        href: '#servers'
      });
    });

    return idx;
  }

  function initPalette() {
    var back = $('#palette'), input = $('#paletteInput'), out = $('#paletteResults');
    if (!back) return;
    var index = [], results = [], cursor = 0, lastFocus = null;

    function esc(s) { return s.replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }

    function mark(text, q) {
      var safe = esc(text);
      if (!q) return safe;
      var i = safe.toLowerCase().indexOf(q.toLowerCase());
      if (i < 0) return safe;
      return safe.slice(0, i) + '<mark>' + safe.slice(i, i + q.length) + '</mark>' +
             safe.slice(i + q.length);
    }

    function score(item, q) {
      var t = item.title.toLowerCase(), d = (item.desc || '').toLowerCase();
      if (t.startsWith(q)) return 0;
      if (t.indexOf(q) >= 0) return 1;
      if (d.indexOf(q) >= 0) return 2;
      return -1;
    }

    function render() {
      var q = input.value.trim().toLowerCase();
      results = !q ? index.slice(0, 8) : index
        .map(function (it) { return { it: it, s: score(it, q) }; })
        .filter(function (x) { return x.s >= 0; })
        .sort(function (a, b) { return a.s - b.s; })
        .slice(0, 12)
        .map(function (x) { return x.it; });

      cursor = 0;
      if (!results.length) {
        out.innerHTML = '<div class="palette-empty">Ничего не нашлось. ' +
          'Попробуйте «iPhone», «оплата» или «скорость».</div>';
        return;
      }

      var groups = {}, order = [];
      results.forEach(function (r) {
        if (!groups[r.kind]) { groups[r.kind] = []; order.push(r.kind); }
        groups[r.kind].push(r);
      });

      var n = -1;
      out.innerHTML = order.map(function (kind) {
        return '<div class="palette-group">' + kind + '</div>' +
          groups[kind].map(function (r) {
            n++;
            return '<button class="palette-item" type="button" role="option" data-n="' + n +
              '" aria-selected="' + (n === 0) + '">' +
              '<span class="p-ico"><svg aria-hidden="true"><use href="#' + r.icon + '"/></svg></span>' +
              '<span><span class="p-title">' + mark(r.title, q) + '</span>' +
              (r.desc ? '<span class="p-desc">' + mark(r.desc, q) + '</span>' : '') + '</span>' +
              '</button>';
          }).join('');
      }).join('');

      // Порядок кнопок в DOM совпадает с порядком в results — иначе
      // стрелки выбирали бы не то, что подсвечено.
      results = order.reduce(function (acc, k) { return acc.concat(groups[k]); }, []);

      $$('.palette-item', out).forEach(function (el) {
        el.addEventListener('click', function () { go(+el.getAttribute('data-n')); });
        el.addEventListener('mousemove', function () { move(+el.getAttribute('data-n')); });
      });
    }

    function move(n) {
      cursor = Math.max(0, Math.min(results.length - 1, n));
      $$('.palette-item', out).forEach(function (el, i) {
        el.setAttribute('aria-selected', String(i === cursor));
        if (i === cursor) el.scrollIntoView({ block: 'nearest' });
      });
    }

    function go(n) {
      var r = results[n];
      if (!r) return;
      close();
      location.href = r.href;
    }

    function open() {
      index = buildIndex();
      lastFocus = document.activeElement;
      back.hidden = false;
      document.body.style.overflow = 'hidden';
      input.value = '';
      render();
      input.focus();
    }

    function close() {
      back.hidden = true;
      document.body.style.overflow = '';
      if (lastFocus && lastFocus.focus) lastFocus.focus();
    }

    $$('[data-palette-open]').forEach(function (b) { b.addEventListener('click', open); });

    document.addEventListener('keydown', function (e) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        back.hidden ? open() : close();
        return;
      }
      // «/» — привычный шорткат поиска, но не когда человек печатает.
      if (e.key === '/' && back.hidden && !/^(INPUT|TEXTAREA)$/.test(document.activeElement.tagName)) {
        e.preventDefault(); open(); return;
      }
      if (back.hidden) return;
      if (e.key === 'Escape') { e.preventDefault(); close(); }
      else if (e.key === 'ArrowDown') { e.preventDefault(); move(cursor + 1); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); move(cursor - 1); }
      else if (e.key === 'Enter') { e.preventDefault(); go(cursor); }
    });

    input.addEventListener('input', render);
    back.addEventListener('click', function (e) { if (e.target === back) close(); });
  }

  /* ---------------------------------------------------------- запуск -- */

  function init() {
    wireLinks(document);
    initTheme();
    initHeader();
    initReveal();
    initCounters();
    initTilt();
    initGlobeAndServers();
    initPricing();
    initQuiz();
    initCalc();
    initQR();
    initLeak();
    initPalette();

    var y = $('#year');
    if (y) y.textContent = String(new Date().getFullYear());

    // На узких экранах поле поиска прячется, но иконка должна остаться.
    var icon = $('#searchIconBtn');
    if (icon && matchMedia('(max-width: 860px)').matches) icon.style.display = '';
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  window.HollApp = { CONFIG: CONFIG, tgLink: tgLink, estimateRtt: estimateRtt, here: here };
})();
