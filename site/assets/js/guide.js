/* Справочник: навигация, маршрутизация по хэшу, фильтр и копирование команд.
 *
 * Статьи берутся из HollKB, страница одна — переход между статьями меняет
 * только хэш, поэтому ссылка на конкретную инструкцию всегда работает
 * и её можно отправить в поддержку.
 */
(function () {
  'use strict';

  var $  = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };

  var KB = window.HollKB;
  if (!KB) return;

  // Плоский список в порядке отображения — по нему работают «назад/вперёд».
  var FLAT = [];
  KB.categories.forEach(function (c) {
    c.articles.forEach(function (a) { FLAT.push({ cat: c, article: a }); });
  });

  var nav = $('#kbNav'), host = $('#kbArticle'),
      crumbs = $('#kbCrumbs'), nextPrev = $('#kbNextPrev');

  /* ------------------------------------------------------------ навигация */

  function buildNav() {
    nav.innerHTML = KB.categories.map(function (c) {
      return '<div class="kb-cat" data-cat="' + c.id + '">' +
        '<h4><svg aria-hidden="true"><use href="#' + c.icon + '"/></svg>' + c.title + '</h4>' +
        '<ul>' + c.articles.map(function (a) {
          return '<li data-title="' + a.title.toLowerCase() + ' ' + a.summary.toLowerCase() + '">' +
            '<a href="#' + a.id + '" data-id="' + a.id + '">' + a.title + '</a></li>';
        }).join('') + '</ul></div>';
    }).join('');
  }

  function markCurrent(id) {
    $$('a[data-id]', nav).forEach(function (a) {
      var on = a.getAttribute('data-id') === id;
      a.classList.toggle('is-current', on);
      if (on) a.setAttribute('aria-current', 'page');
      else a.removeAttribute('aria-current');
    });
  }

  /* -------------------------------------------------------------- статья */

  function copyButtons(scope) {
    $$('pre[data-copy]', scope).forEach(function (pre) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'copy-btn';
      btn.innerHTML = '<svg aria-hidden="true"><use href="#i-copy"/></svg>Копировать';
      btn.addEventListener('click', function () {
        var text = pre.querySelector('code').innerText;
        var done = function (ok) {
          btn.classList.toggle('is-done', ok);
          btn.innerHTML = ok
            ? '<svg aria-hidden="true"><use href="#i-check"/></svg>Скопировано'
            : 'Не удалось';
          setTimeout(function () {
            btn.classList.remove('is-done');
            btn.innerHTML = '<svg aria-hidden="true"><use href="#i-copy"/></svg>Копировать';
          }, 1800);
        };
        if (navigator.clipboard) {
          navigator.clipboard.writeText(text).then(function () { done(true); },
                                                   function () { done(false); });
        } else {
          done(false);
        }
      });
      pre.appendChild(btn);
    });
  }

  function render(id) {
    var i = FLAT.findIndex(function (e) { return e.article.id === id; });
    if (i < 0) i = 0;
    var entry = FLAT[i], a = entry.article, c = entry.cat;

    crumbs.innerHTML =
      '<a href="index.html">Главная</a><span aria-hidden="true">/</span>' +
      '<a href="guide.html">Справочник</a><span aria-hidden="true">/</span>' +
      '<span>' + c.title + '</span>';

    host.innerHTML = '<h1>' + a.title + '</h1>' +
                     '<p class="kb-summary">' + a.summary + '</p>' + a.body;
    copyButtons(host);

    var prev = FLAT[i - 1], next = FLAT[i + 1];
    nextPrev.innerHTML =
      (prev ? '<a href="#' + prev.article.id + '"><span class="d">Назад</span>' +
              '<span class="t">' + prev.article.title + '</span></a>'
            : '<a class="is-blank" aria-hidden="true" tabindex="-1"><span class="d">—</span><span class="t">—</span></a>') +
      (next ? '<a class="next" href="#' + next.article.id + '"><span class="d">Дальше</span>' +
              '<span class="t">' + next.article.title + '</span></a>'
            : '<a class="next is-blank" aria-hidden="true" tabindex="-1"><span class="d">—</span><span class="t">—</span></a>');

    markCurrent(a.id);
    document.title = a.title + ' — справочник HollVPN';

    var desc = document.querySelector('meta[name="description"]');
    if (desc) desc.setAttribute('content', a.summary);
  }

  /* -------------------------------------------------------------- фильтр */

  function initFilter() {
    var input = $('#kbSearch');
    if (!input) return;

    input.addEventListener('input', function () {
      var q = input.value.trim().toLowerCase();
      var shown = 0;

      $$('.kb-cat', nav).forEach(function (cat) {
        var visible = 0;
        $$('li', cat).forEach(function (li) {
          var hit = !q || li.getAttribute('data-title').indexOf(q) >= 0;
          li.classList.toggle('is-hidden', !hit);
          if (hit) visible++;
        });
        cat.classList.toggle('is-hidden', visible === 0);
        shown += visible;
      });

      var empty = $('.kb-empty-nav', nav);
      if (!shown) {
        if (!empty) {
          empty = document.createElement('p');
          empty.className = 'kb-empty-nav';
          empty.textContent = 'Ничего не нашлось. Попробуйте «роутер», «оплата» или «скорость».';
          nav.appendChild(empty);
        }
      } else if (empty) {
        empty.remove();
      }
    });

    // Esc очищает фильтр, не закрывая страницу.
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && input.value) {
        e.stopPropagation();
        input.value = '';
        input.dispatchEvent(new Event('input'));
      }
    });
  }

  /* ------------------------------------------------------ мобильный список */

  function initToggle() {
    var side = $('#guideSide'), btn = $('#kbToggle');
    if (!side || !btn) return;

    btn.addEventListener('click', function () {
      var open = side.classList.toggle('is-open');
      btn.setAttribute('aria-expanded', String(open));
    });

    // Выбрал статью — список сворачивается, чтобы сразу был виден текст.
    nav.addEventListener('click', function (e) {
      if (e.target.closest('a') && matchMedia('(max-width: 940px)').matches) {
        side.classList.remove('is-open');
        btn.setAttribute('aria-expanded', 'false');
      }
    });
  }

  /* ------------------------------------------------------------- запуск */

  function route() {
    var id = location.hash.replace(/^#/, '');
    render(id);
  }

  function init() {
    buildNav();
    initFilter();
    initToggle();
    route();

    window.addEventListener('hashchange', function () {
      route();
      // Свежая статья начинается сверху, а не там, где кончилась прошлая.
      var main = $('#guideMain');
      if (main) {
        var y = main.getBoundingClientRect().top + window.scrollY - 90;
        window.scrollTo({ top: Math.max(0, y), behavior: 'smooth' });
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
