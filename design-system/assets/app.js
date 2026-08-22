/* Scaler Cortex Interviewer — prototype behaviour.
   Everything here is presentation. All data is synthetic and labelled as such. */

/* ---------------------------------------------------------------------------
   Posterior ridge — a real Beta density, drawn from real α and β.
   This is the one chart in the system, and it exists because a single
   percentage cannot tell an unasked Topic from a failed one.
   Wide and flat = unknown.  Narrow = known.
   ------------------------------------------------------------------------ */
function betaDensity(a, b, n) {
  // unnormalised pdf in log space, then exponentiated relative to its own max
  const xs = [], ls = [];
  for (let i = 0; i <= n; i++) {
    const x = Math.min(Math.max(i / n, 1e-6), 1 - 1e-6);
    xs.push(x);
    ls.push((a - 1) * Math.log(x) + (b - 1) * Math.log(1 - x));
  }
  const max = Math.max(...ls);
  return { xs, ys: ls.map(l => Math.exp(l - max)) };
}

/* central credible interval, by numeric integration of the same density */
function credibleInterval(a, b, mass) {
  const n = 2000, { xs, ys } = betaDensity(a, b, n);
  let total = 0;
  const cum = ys.map(y => (total += y));
  const lo = (1 - mass) / 2, hi = 1 - lo;
  const at = p => {
    const target = p * total;
    for (let i = 0; i < cum.length; i++) if (cum[i] >= target) return xs[i];
    return 1;
  };
  return [at(lo), at(hi)];
}

/* Evidence Floor bands.

   CONTEXT.md is explicit that these are "read off the posterior as a credible
   interval, not chosen by hand" — so the boundary between Untested, a hedged
   reading and a firm one is the WIDTH of the 80% interval, not a count of
   answers. A wide interval means we do not know, however many questions
   produced it; a narrow one means we do, and the mean is worth reporting.

   The two widths below are the only constants, and they are properties of how
   sure a reading has to be before it is shown — not of how much evidence it
   took to get there. */
const BAND_UNKNOWN = 0.70;  // interval at least this wide: say nothing
const BAND_FIRM    = 0.40;  // interval narrower than this: say it plainly
const CI_MASS      = 0.80;

function readTopic(a, b) {
  const evidence = a + b - 2;              // prior is α = β = 1
  const [lo, hi] = credibleInterval(a, b, CI_MASS);
  const width = hi - lo;

  // Below the floor the tracker says Untested and nothing more. There is
  // deliberately no branch here that returns a number in that case.
  if (width >= BAND_UNKNOWN) {
    return { band: 'untested', label: 'Untested', mastery: null, lo, hi, width, evidence };
  }
  const mean = a / (a + b);
  const firm = width < BAND_FIRM;
  const weak = hi < 0.6;
  return {
    band: firm ? (weak ? 'firm-weak' : 'firm-strong') : 'hedged',
    label: firm ? (weak ? 'Looks weak' : 'Looks solid') : 'Early signal',
    mastery: mean, lo, hi, width, evidence, firm
  };
}

function ridgePath(a, b, W, H) {
  const PAD = 1;
  const { xs, ys } = betaDensity(a, b, 120);
  const px = x => PAD + x * (W - PAD * 2);
  const py = y => H - 2 - y * (H - 10);
  const line = xs.map((x, i) => `${i ? 'L' : 'M'}${px(x).toFixed(2)},${py(ys[i]).toFixed(2)}`).join('');
  return { line, area: `${line}L${px(1)},${H}L${px(0)},${H}Z`, px };
}

/* Where a ridge names the posterior it came from, animate the update itself:
   the prior deforms into the posterior over one authored moment. The curve is
   the argument — one answer visibly narrows what we know — so showing the two
   states as a static diff throws away the only thing the chart is for. */
function animateRidge(el, from, to, W, H, paint) {
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (reduce) { paint(to.a, to.b); return; }
  const DUR = 900, t0 = performance.now();
  const ease = t => 1 - Math.pow(1 - t, 3);       // exponential-ish ease-out
  (function step(now) {
    const t = Math.min(1, (now - t0) / DUR), k = ease(t);
    paint(from.a + (to.a - from.a) * k, from.b + (to.b - from.b) * k);
    if (t < 1) requestAnimationFrame(step);
  })(t0);
}

function renderRidge(el) {
  const a = parseFloat(el.dataset.alpha), b = parseFloat(el.dataset.beta);
  const W = 260, H = el.dataset.h ? +el.dataset.h : 64;

  // The band is read from the FINAL posterior, so a mid-tween frame never
  // flashes a reading the Topic does not actually have.
  const r = readTopic(a, b);
  const untested = r.band === 'untested';
  const stroke = untested ? '#8195b0'
    : r.band === 'firm-weak' ? '#c00219'
    : r.band === 'firm-strong' ? '#1c7a50' : '#7d5400';
  const fill = untested ? 'rgba(129,149,176,.18)'
    : r.band === 'firm-weak' ? 'rgba(192,2,25,.12)'
    : r.band === 'firm-strong' ? 'rgba(28,122,80,.14)' : 'rgba(125,84,0,.12)';

  const label = untested
    ? 'Untested — no reading'
    : `Posterior density, centre ${(a / (a + b) * 100).toFixed(0)} percent, ` +
      `80 percent interval ${(r.lo * 100).toFixed(0)} to ${(r.hi * 100).toFixed(0)} percent`;

  el.innerHTML =
    `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${label}">
       <line x1="1" y1="${H - 2}" x2="${W - 1}" y2="${H - 2}" stroke="#d7dee8" stroke-width="1"/>
       <path class="ridge__area" fill="${fill}"/>
       <path class="ridge__line" fill="none" stroke="${stroke}" stroke-width="1.75"
             stroke-linejoin="round" ${untested ? 'stroke-dasharray="3 3"' : ''}/>
       <line class="ridge__mean" y1="${H - 2}" y2="8" stroke="${stroke}"
             stroke-width="1.5" stroke-dasharray="2 2" ${untested ? 'opacity="0"' : ''}/>
     </svg>`;

  const areaEl = el.querySelector('.ridge__area');
  const lineEl = el.querySelector('.ridge__line');
  const meanEl = el.querySelector('.ridge__mean');

  const paint = (pa, pb) => {
    const { line, area, px } = ridgePath(pa, pb, W, H);
    areaEl.setAttribute('d', area);
    lineEl.setAttribute('d', line);
    const m = px(pa / (pa + pb)).toFixed(2);
    meanEl.setAttribute('x1', m); meanEl.setAttribute('x2', m);
  };

  const fa = el.dataset.fromAlpha, fb = el.dataset.fromBeta;
  if (fa !== undefined && fb !== undefined) {
    paint(parseFloat(fa), parseFloat(fb));
    const run = () => animateRidge(el, { a: parseFloat(fa), b: parseFloat(fb) },
                                   { a, b }, W, H, paint);
    if ('IntersectionObserver' in window) {
      const io = new IntersectionObserver(es => {
        if (es.some(e => e.isIntersecting)) { io.disconnect(); run(); }
      }, { threshold: .5 });
      io.observe(el);
    } else run();
  } else {
    paint(a, b);
  }
}

/* ---------------------------------------------------------------------------
   Overlays
   ------------------------------------------------------------------------ */
let lastFocused = null;

function openOverlay(id) {
  const o = document.getElementById(id);
  if (!o) return;
  lastFocused = document.activeElement;
  o.dataset.open = 'true';
  document.body.style.overflow = 'hidden';
  // These dialogs claim aria-modal, so the rest of the page must actually
  // leave the tab order rather than merely sitting behind a scrim.
  document.querySelectorAll('.app').forEach(el => el.inert = true);
  const f = o.querySelector('[data-autofocus]') || o.querySelector('button');
  if (f) f.focus();
}

function closeOverlay(id) {
  const o = id ? document.getElementById(id) : document.querySelector('.overlay[data-open="true"]');
  if (!o) return;
  o.dataset.open = 'false';
  document.body.style.overflow = '';
  document.querySelectorAll('.app').forEach(el => el.inert = false);
  if (lastFocused && lastFocused.focus) lastFocused.focus();
  lastFocused = null;
}

/* ---------------------------------------------------------------------------
   Boot
   ------------------------------------------------------------------------ */
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.ridge').forEach(renderRidge);

  document.querySelectorAll('[data-open-overlay]').forEach(b =>
    b.addEventListener('click', () => openOverlay(b.dataset.openOverlay)));
  document.querySelectorAll('[data-close-overlay]').forEach(b =>
    b.addEventListener('click', () => closeOverlay(b.dataset.closeOverlay || null)));
  document.querySelectorAll('.overlay').forEach(o =>
    o.addEventListener('mousedown', e => { if (e.target === o) closeOverlay(o.id); }));
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeOverlay(); });

  /* multi-select option rows (Modules) */
  document.querySelectorAll('[data-toggle]').forEach(el =>
    el.addEventListener('click', () => {
      el.dataset.on = el.dataset.on === 'true' ? 'false' : 'true';
      const form = el.closest('[data-scope-form]');
      if (form) updateScope(form);
    }));

  /* single-select rows (Provider, duration) */
  document.querySelectorAll('[data-radio-group]').forEach(group => {
    group.querySelectorAll('[data-radio]').forEach(el =>
      el.addEventListener('click', () => {
        group.querySelectorAll('[data-radio]').forEach(o => {
          o.dataset.on = 'false'; o.setAttribute('aria-pressed', 'false');
        });
        el.dataset.on = 'true'; el.setAttribute('aria-pressed', 'true');
        const form = el.closest('[data-scope-form]');
        if (form) updateScope(form);
      }));
  });

  document.querySelectorAll('[data-scope-form]').forEach(updateScope);

  /* composer: the Answer Turn is a submit event, and must be keyboard-reachable */
  document.querySelectorAll('.composer__field').forEach(f => {
    f.addEventListener('keydown', e => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
        e.preventDefault();
        const btn = f.closest('.composer')?.querySelector('[data-submit-turn]');
        btn?.click();
      }
    });
  });
});

/* Session scope summary. Topic counts are real — from the scraped Corpus. */
function updateScope(form) {
  const on = [...form.querySelectorAll('[data-toggle][data-on="true"]')];
  const topics = on.reduce((n, el) => n + (+el.dataset.topics || 0), 0);
  const mods = on.length;
  const out = form.querySelector('[data-scope-out]');
  if (out) {
    out.textContent = mods === 0
      ? 'No Modules chosen'
      : `${mods} Module${mods > 1 ? 's' : ''} · ${topics} Topic${topics > 1 ? 's' : ''} in scope`;
  }
  const start = form.querySelector('[data-start]');
  if (start) {
    const ok = mods > 0;
    start.toggleAttribute('disabled', !ok);
    start.setAttribute('aria-disabled', String(!ok));
  }
  const gt = form.querySelector('[data-groundtruth-out]');
  if (gt) {
    const pairs = on.reduce((n, el) => n + (+el.dataset.gt || 0), 0);
    gt.textContent = pairs > 0
      ? `${pairs} Assignment/Answer Key pairs in scope — those questions grade at full weight.`
      : 'No Answer Keys in scope. Questions grade from Topic text, at reduced weight.';
  }
}
