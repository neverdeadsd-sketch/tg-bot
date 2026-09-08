/* Страница оплаты.
 *
 * Два состояния на одной странице: оформление и результат. После оплаты
 * ЮKassa возвращает пользователя сюда же с ?order=…, и страница опрашивает
 * статус — потому что подписка выдаётся по вебхуку, а не по возврату
 * браузера: пользователь может закрыть вкладку, и это не должно ничего сломать.
 */
(function () {
  'use strict';

  var $ = function (s) { return document.querySelector(s); };
  var CONFIG = (window.HollApp && window.HollApp.CONFIG) || {};
  var API = CONFIG.checkoutApi || '/api';

  function fmt(n) { return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ' '); }

  function plural(n, one, few, many) {
    var a = n % 100, b = n % 10;
    if (a > 4 && a < 21) return many;
    if (b === 1) return one;
    if (b > 1 && b < 5) return few;
    return many;
  }
  function days(n) { return n + ' ' + plural(n, 'день', 'дня', 'дней'); }

  function termByDays(d) {
    var terms = (CONFIG.subscription && CONFIG.subscription.terms) || [];
    for (var i = 0; i < terms.length; i++) if (terms[i].days === d) return terms[i];
    return null;
  }

  /* ------------------------------------------------------------ результат -- */

  var ICON = {
    ok:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>',
    wait: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="9" opacity=".25"/><path d="M12 3a9 9 0 019 9"/></svg>',
    warn: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 8v5M12 17h.01M10.3 3.9 2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/></svg>',
    tg:   '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M21.9 4.3l-3.1 14.6c-.2 1-.9 1.3-1.7.8l-4.7-3.5-2.3 2.2c-.3.3-.5.5-1 .5l.3-4.9 8.9-8c.4-.3-.1-.5-.6-.2L6.7 12.6 2 11.1c-1-.3-1-1 .2-1.5l18.4-7.1c.9-.3 1.6.2 1.3 1.8z"/></svg>'
  };

  function showResult(kind, title, text, actions) {
    $('#stepForm').hidden = true;
    $('#stepResult').hidden = false;
    $('#coStatus').className = 'co-status is-' + kind;
    $('#coStatus').innerHTML =
      '<div class="co-status-icon">' + (ICON[kind] || '') + '</div>' +
      '<h1>' + title + '</h1>' +
      '<p>' + text + '</p>' +
      (actions || '');
    if (window.HollApp) {
      // Проставить ссылки на бота в только что вставленной разметке.
      var a = $('#coStatus').querySelectorAll('[data-tg]');
      for (var i = 0; i < a.length; i++) {
        a[i].href = window.HollApp.tgLink(a[i].getAttribute('data-utm') || 'checkout');
        a[i].rel = 'noopener';
      }
    }
  }

  var botButton =
    '<a class="btn btn--primary btn--lg" data-tg data-utm="checkout_done" href="#">' +
    '<svg aria-hidden="true"><use href="#i-tg"/></svg>Открыть бота</a>';

  /* Опрос статуса: подписку выдаёт вебхук, поэтому в момент возврата она
     может быть ещё не выдана. Ждём разумное время, потом честно говорим,
     что оплата прошла и выдача задерживается, — но денег это не касается. */
  function pollOrder(orderId) {
    var tries = 0, maxTries = 20;

    showResult('wait', 'Проверяем оплату…',
      'Это занимает несколько секунд. Не закрывайте страницу.');

    (function tick() {
      tries++;
      fetch(API + '/payment/' + encodeURIComponent(orderId), { cache: 'no-store' })
        .then(function (r) {
          if (r.status === 404) throw new Error('not-found');
          return r.json();
        })
        .then(function (o) {
          if (o.delivered) {
            var sum = fmt(o.amount.split('.')[0]);
            // При ручной выдаче обещать активную подписку нельзя: заявка
            // ушла, но выдаёт её человек, и это может занять минуты.
            if (o.delivery_mode === 'manual') {
              return showResult('ok', 'Оплата прошла',
                'Платёж на ' + sum + ' ₽ принят, подписка на ' + days(o.days) +
                ' оформляется на ' + o.telegram + '. Обычно это занимает ' +
                'несколько минут — ссылка придёт в бот. Если не пришла в течение ' +
                'часа, напишите в поддержку и назовите номер заказа <code>' +
                orderId + '</code>.', botButton);
            }
            return showResult('ok', 'Подписка активна',
              'Оплата на ' + sum + ' ₽ прошла, доступ на ' + days(o.days) +
              ' выдан на ' + o.telegram + '. Ссылка-подписка ждёт вас в боте.',
              botButton);
          }
          if (o.needs_attention) {
            return showResult('warn', 'Оплата прошла, выдача задерживается',
              'Деньги списаны, но подписка ещё не выдана автоматически. ' +
              'Напишите в поддержку и назовите номер заказа <code>' + orderId +
              '</code> — выдадим вручную.',
              '<a class="btn btn--primary btn--lg" data-tg-support href="#">Написать в поддержку</a>');
          }
          if (o.status === 'canceled') {
            return showResult('warn', 'Платёж отменён',
              'Деньги не списаны. Можно попробовать ещё раз или оплатить в боте.',
              '<a class="btn btn--ghost btn--lg" href="index.html#pricing">Вернуться к тарифам</a>');
          }
          if (tries >= maxTries) {
            return showResult('wait', 'Оплата ещё обрабатывается',
              'Банк подтверждает платёж дольше обычного. Подписка появится в боте ' +
              'автоматически, как только оплата пройдёт. Номер заказа: <code>' +
              orderId + '</code>.', botButton);
          }
          setTimeout(tick, 1500);
        })
        .catch(function (e) {
          if (e.message === 'not-found') {
            return showResult('warn', 'Заказ не найден',
              'Возможно, ссылка устарела. Оформите подписку заново или напишите в поддержку.',
              '<a class="btn btn--ghost btn--lg" href="index.html#pricing">К тарифам</a>');
          }
          if (tries >= maxTries) {
            return showResult('warn', 'Не удалось проверить статус',
              'Это проблема связи, а не оплаты. Откройте бота — если оплата прошла, ' +
              'подписка уже там.', botButton);
          }
          setTimeout(tick, 2000);
        });
    })();
  }

  /* ---------------------------------------------------------- оформление -- */

  function initForm(term) {
    $('#stepForm').hidden = false;
    $('#coTerm').textContent = term.label + ' · ' + days(term.days);
    $('#coPrice').textContent = fmt(term.price) + ' ₽';

    var per = Math.round(term.price / (term.days / 30));
    $('#coPer').textContent = term.days > 30
      ? fmt(per) + ' ₽ в месяц при оплате за ' + days(term.days)
      : 'Оплата за один месяц';

    var form = $('#coForm'), input = $('#coTelegram'),
        btn = $('#coSubmit'), label = $('#coSubmitLabel'), err = $('#coError');

    label.textContent = 'Оплатить ' + fmt(term.price) + ' ₽';

    function fail(message) {
      err.textContent = message;
      err.hidden = false;
      btn.disabled = false;
      label.textContent = 'Оплатить ' + fmt(term.price) + ' ₽';
    }

    form.addEventListener('submit', function (e) {
      e.preventDefault();
      err.hidden = true;

      var tg = input.value.trim().replace(/^@/, '');
      if (!/^[A-Za-z0-9_]{5,32}$/.test(tg)) {
        input.focus();
        return fail('Имя пользователя Telegram: латиница, цифры и подчёркивание, от 5 до 32 символов.');
      }

      btn.disabled = true;
      label.textContent = 'Создаём платёж…';

      fetch(API + '/checkout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ days: term.days, telegram: tg })
      })
        .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
        .then(function (res) {
          if (!res.ok || !res.j.confirmation_url) {
            return fail(res.j.error || 'Не удалось создать платёж. Попробуйте оплатить в боте.');
          }
          location.href = res.j.confirmation_url;
        })
        .catch(function () {
          fail('Не удалось связаться с сервером оплаты. Попробуйте оплатить в боте.');
        });
    });
  }

  /* --------------------------------------------------------------- старт -- */

  function init() {
    var y = $('#year');
    if (y) y.textContent = String(new Date().getFullYear());

    var params = new URLSearchParams(location.search);
    var orderId = params.get('order');

    /* Оплаты на сайте может не быть: сервис из checkout/ не поднят, и
     * CONFIG.checkoutApi пуст. Тогда форма бессмысленна — она бы просто
     * не дозвонилась. Отправляем туда, где деньги действительно принимают.
     * Проверка идёт первой: с ?order=… сюда возвращает ЮKassa, но без API
     * спросить статус заказа всё равно не у кого. */
    if (!CONFIG.checkoutApi) {
      var d0 = Number(params.get('days'));
      var utm = termByDays(d0) ? 'sub_' + d0 + 'd' : 'checkout';
      return showResult('tg', 'Оплата — в боте',
        'Подписка оформляется в Telegram: там же выбор срока, оплата ' +
        'и выдача доступа сразу после неё.',
        '<a class="btn btn--primary btn--lg" data-tg data-utm="' + utm + '" href="#">' +
        '<svg aria-hidden="true"><use href="#i-tg"/></svg>Открыть бота</a>' +
        '<a class="btn btn--ghost btn--lg" href="index.html#pricing">К тарифам</a>');
    }

    if (orderId) return pollOrder(orderId);

    var d = Number(params.get('days'));
    var term = termByDays(d);
    if (!term) {
      return showResult('warn', 'Срок не выбран',
        'Выберите срок подписки на странице тарифов.',
        '<a class="btn btn--primary btn--lg" href="index.html#pricing">К тарифам</a>');
    }
    initForm(term);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
