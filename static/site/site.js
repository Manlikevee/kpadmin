(function () {
  var root = document.documentElement;
  var ICONS = {
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5L19 19M19 5l-1.5 1.5M6.5 17.5L5 19"/>',
    moon: '<path d="M20 14.5A8 8 0 019.5 4 8 8 0 1020 14.5z"/>',
    menu: '<path d="M4 7h16M4 12h16M4 17h16"/>', x: '<path d="M6 6l12 12M18 6L6 18"/>',
    check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>', left: '<path d="M15 5l-7 7 7 7"/>', right: '<path d="M9 5l7 7-7 7"/>'
  };
  function ic(n) { return '<svg class="i" viewBox="0 0 24 24">' + ICONS[n] + '</svg>' }

  /* ---------- theme (key shared with the admin portal) ---------- */
  function isDark() { var t = root.getAttribute('data-theme'); return t ? t === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches }
  var tb = document.getElementById('theme');
  function paint() { if (!tb) return; tb.innerHTML = ic(isDark() ? 'sun' : 'moon'); tb.setAttribute('aria-label', isDark() ? 'Switch to light mode' : 'Switch to dark mode') }
  if (tb) tb.onclick = function () { var n = isDark() ? 'light' : 'dark'; root.setAttribute('data-theme', n); try { localStorage.setItem('kp-theme', n) } catch (e) { } paint() };
  paint();

  /* ---------- mobile menu ---------- */
  var bg = document.getElementById('burger'), dr = document.getElementById('drawer');
  if (bg && dr) {
    bg.innerHTML = ic('menu');
    bg.onclick = function () { var o = dr.classList.toggle('open'); bg.innerHTML = ic(o ? 'x' : 'menu'); bg.setAttribute('aria-expanded', o); document.body.style.overflow = o ? 'hidden' : '' };
  }

  /* ---------- toast ---------- */
  function toast(m) { var t = document.createElement('div'); t.className = 'toast'; t.setAttribute('role', 'status'); t.innerHTML = ic('check') + '<span></span>'; t.querySelector('span').textContent = m; document.body.appendChild(t); setTimeout(function () { t.remove() }, 3200) }

  /* ---------- demo forms ---------- */
  document.querySelectorAll('form[data-demo]').forEach(function (f) {
    f.addEventListener('submit', function (e) { e.preventDefault(); toast(f.dataset.demo); f.reset(); var a = f.querySelector('.amt'); if (a && window.kpGiveReset) window.kpGiveReset() });
  });

  /* ---------- year ---------- */
  document.querySelectorAll('[data-year]').forEach(function (y) { y.textContent = new Date().getFullYear() });

  /* ---------- countdown to next Sunday 9:00 (visitor's local time) ---------- */
  var cd = document.getElementById('cd');
  if (cd) {
    var label = document.getElementById('cdDate');
    var nextSun = function () { var n = new Date(), d = new Date(n); d.setHours(9, 0, 0, 0); d.setDate(n.getDate() + ((7 - n.getDay()) % 7)); if (d <= n) d.setDate(d.getDate() + 7); return d };
    var target = nextSun();
    if (label) label.textContent = target.toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' }) + ' · 9:00 AM';
    var tick = function () {
      var s = Math.max(0, Math.floor((target - new Date()) / 1000)); if (s === 0) target = nextSun();
      var v = [Math.floor(s / 86400), Math.floor(s % 86400 / 3600), Math.floor(s % 3600 / 60), s % 60];
      cd.querySelectorAll('strong').forEach(function (el, i) { el.textContent = String(v[i]).padStart(2, '0') });
    };
    tick(); setInterval(tick, 1000);
  }

  /* ---------- filters + search: .fchip[data-f] and items [data-c] inside [data-list] ---------- */
  document.querySelectorAll('[data-filters]').forEach(function (grp) {
    var list = document.querySelector(grp.dataset.filters), q = grp.querySelector('input'), cur = 'all';
    var empty = list.parentNode.querySelector('.empty');
    function run() {
      var term = q ? q.value.toLowerCase().trim() : '', n = 0;
      list.querySelectorAll('[data-c]').forEach(function (it) {
        var ok = (cur === 'all' || it.dataset.c.split(' ').indexOf(cur) > -1) && (!term || it.textContent.toLowerCase().indexOf(term) > -1);
        it.hidden = !ok; if (ok) n++;
      });
      if (empty) empty.hidden = n > 0;
    }
    grp.addEventListener('click', function (e) { var b = e.target.closest('.fchip'); if (!b) return; grp.querySelectorAll('.fchip').forEach(function (x) { x.classList.toggle('on', x === b) }); cur = b.dataset.f; run() });
    if (q) q.addEventListener('input', run);
  });

  /* ---------- gallery lightbox ---------- */
  var gal = document.getElementById('gal');
  if (gal) {
    var lb = null, idx = 0;
    var vis = function () { return [].slice.call(gal.querySelectorAll('.gi')).filter(function (g) { return !g.hidden }) };
    var show = function () {
      var items = vis(), g = items[(idx + items.length) % items.length]; idx = items.indexOf(g);
      var art = g.querySelector('.art').cloneNode(true); art.style.cssText = g.querySelector('.art').style.cssText; art.style.aspectRatio = '';
      var fig = lb.querySelector('figure'); fig.innerHTML = ''; fig.appendChild(art);
      var c = document.createElement('figcaption'); c.innerHTML = '<b></b><span></span>'; c.firstChild.textContent = g.dataset.t; c.lastChild.textContent = g.dataset.d; fig.appendChild(c);
    };
    var open = function (g) {
      idx = vis().indexOf(g);
      lb = document.createElement('div'); lb.className = 'lb'; lb.setAttribute('role', 'dialog'); lb.setAttribute('aria-label', 'Photo viewer');
      lb.innerHTML = '<button class="x" aria-label="Close">' + ic('x') + '</button><button class="pv" aria-label="Previous">' + ic('left') + '</button><button class="nx" aria-label="Next">' + ic('right') + '</button><figure></figure>';
      document.body.appendChild(lb); document.body.style.overflow = 'hidden'; show();
      lb.addEventListener('click', function (e) { if (e.target.closest('.x') || e.target === lb) close(); else if (e.target.closest('.pv')) { idx--; show() } else if (e.target.closest('.nx')) { idx++; show() } });
    };
    var close = function () { if (lb) { lb.remove(); lb = null; document.body.style.overflow = '' } };
    gal.addEventListener('click', function (e) { var g = e.target.closest('.gi'); if (g) open(g) });
    document.addEventListener('keydown', function (e) { if (!lb) return; if (e.key === 'Escape') close(); if (e.key === 'ArrowLeft') { idx--; show() } if (e.key === 'ArrowRight') { idx++; show() } });
  }
  /* real photos: any .art[data-img] gets its image */
  document.querySelectorAll('.art[data-img]').forEach(function (a) { a.style.backgroundImage = 'url(' + a.dataset.img + ')' });

  /* ---------- church locator ---------- */
  var mapbox = document.getElementById('mapbox');
  if (mapbox) {
    var pins = [].slice.call(mapbox.querySelectorAll('.pin')), cards = [].slice.call(document.querySelectorAll('.lc'));
    var det = document.getElementById('detail');
    var sel = function (i) {
      pins.forEach(function (p, k) { p.classList.toggle('on', k === i) }); cards.forEach(function (c, k) { c.classList.toggle('on', k === i) });
      var c = cards[i]; if (!c) return;
      det.querySelector('h3').textContent = c.dataset.n; det.querySelector('.ad').textContent = c.dataset.a; det.querySelector('.tm').textContent = c.dataset.t;
      det.querySelector('.dir').href = 'https://www.google.com/maps/search/?api=1&query=' + encodeURIComponent(c.dataset.a);
      det.querySelector('.tel').href = 'tel:' + c.dataset.p.replace(/\s/g, ''); det.hidden = false;
    };
    cards.forEach(function (c, i) { c.onclick = function () { sel(i) } }); pins.forEach(function (p, i) { p.onclick = function () { sel(i) } });
    var s = document.getElementById('locq');
    if (s) s.oninput = function () {
      var v = s.value.toLowerCase(), n = 0;
      cards.forEach(function (c, i) { var ok = c.textContent.toLowerCase().indexOf(v) > -1 || c.dataset.a.toLowerCase().indexOf(v) > -1; c.hidden = !ok; pins[i].hidden = !ok; if (ok) n++ });
      document.getElementById('locEmpty').hidden = n > 0;
    };
    sel(0);
  }

  /* ---------- giving ---------- */
  var give = document.getElementById('give');
  if (give) {
    var presets = { USD: [10, 25, 50, 100], GBP: [10, 25, 50, 100], EUR: [10, 25, 50, 100], NGN: [5000, 10000, 25000, 50000], GHS: [50, 100, 250, 500] };
    var sym = { USD: '$', GBP: '£', EUR: '€', NGN: '₦', GHS: 'GH₵' };
    var amt = 50, freq = 'One time', cur = give.querySelector('#cur'), box = give.querySelector('.amts'), custom = give.querySelector('#custom');
    var fmt = function (n) { return (sym[cur.value] || '') + Number(n).toLocaleString('en-GB') };
    var sum = function () { document.querySelector('#sumAmt').textContent = amt ? fmt(amt) : '—'; document.querySelector('#sumFreq').textContent = freq; document.querySelector('#sumFund').textContent = give.querySelector('#fund').value };
    var draw = function () { var p = presets[cur.value]; box.innerHTML = p.map(function (v, i) { return '<button type="button" class="amt' + (v === amt ? ' on' : '') + '" data-v="' + v + '">' + fmt(v) + '</button>' }).join(''); sum() };
    window.kpGiveReset = function () { amt = presets[cur.value][1]; custom.value = ''; draw() };
    box.addEventListener('click', function (e) { var b = e.target.closest('.amt'); if (!b) return; amt = +b.dataset.v; custom.value = ''; draw() });
    custom.oninput = function () { amt = +custom.value || 0; box.querySelectorAll('.amt').forEach(function (b) { b.classList.remove('on') }); sum() };
    cur.onchange = function () { amt = presets[cur.value][1]; custom.value = ''; draw() };
    give.querySelector('#fund').onchange = sum;
    give.querySelectorAll('.seg button').forEach(function (b) { b.onclick = function () { give.querySelectorAll('.seg button').forEach(function (x) { x.classList.toggle('on', x === b) }); freq = b.dataset.v; sum() } });
    amt = presets[cur.value][1]; draw();
  }
})();

/* live banner: re-check every 2 minutes so it appears/disappears without a reload */
(function () {
  var b = document.getElementById('liveBanner'); if (!b || !window.fetch) return;
  function poll() {
    fetch('/sermons/live-status/', { headers: { Accept: 'application/json' } }).then(function (r) { return r.json() }).then(function (d) {
      if (d.live) { b.hidden = false; b.classList.remove('soon'); b.querySelector('.wrap').innerHTML = '<span class="live-dot"></span><b>LIVE NOW</b><span class="lt"></span><a class="btn btn-p btn-s" target="_blank" rel="noopener">Watch live</a>'; b.querySelector('.lt').textContent = d.live.title; b.querySelector('a').href = d.live.watch_url }
      else if (!d.upcoming) { b.hidden = true }
    }).catch(function () { });
  }
  setInterval(poll, 120000);
  var w = document.getElementById('liveWhen'); if (w) { var t = new Date(w.getAttribute('datetime')); if (!isNaN(t)) w.textContent = t.toLocaleString([], { weekday: 'short', hour: 'numeric', minute: '2-digit', day: 'numeric', month: 'short' }) }
})();
