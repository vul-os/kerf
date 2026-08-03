/**
 * kerf site/ gate — renders index.html and docs.html in a real browser and
 * fails on the defects that static inspection cannot see.
 *
 * Why a browser: every bug this catches was invisible in the source. A
 * screenshot stretched to the wrong aspect ratio, both theme variants painted
 * on top of each other, a 1× image served to a 2× screen, an anchor pointing
 * at an id that no longer exists — the HTML reads fine in all four cases. So
 * do the four this pass added: a token at 4.23:1 (needs alpha and inherited
 * opacity flattened against the ground actually painted), two SVG labels
 * overlapping by 20px (needs real CSS pixels, not the nominal user units
 * getBBox reports), a line-clamp painting through its own bottom padding, and
 * a chip positioned to hang outside a box that clips it.
 *
 * Note the touch pass. Every other run here uses a desktop context, where
 * `(hover: none)` never matches — so the one rule these pages write FOR touch
 * was the one the gate had never rendered, and it measured 3.28:1.
 *
 * Each check states what it measured, not just pass/fail, so a green run is
 * evidence rather than an assertion. Run:
 *
 *   cd scripts && npm install        # playwright, once
 *   npm run check:site               # serves site/ itself and grades it
 *   npm run check:site:selftest      # prove the checks can fail
 *
 * Run the self-test whenever you touch this file. Every check here is a claim
 * that it would notice its own defect; the self-test is the only thing that
 * holds it to that, and it has already caught two checks in this file that
 * examined nothing (a legibility scan scoped to a <main> the landing does not
 * have, and a stickiness measurement taken mid-smooth-scroll).
 */

import { chromium } from 'playwright';
import { createServer } from 'http';
import { readFile } from 'fs/promises';
import { existsSync } from 'fs';
import { resolve, dirname, extname, join, normalize } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const SITE = resolve(__dirname, '..', 'site');

const VIEWPORTS = [
  { w: 1600, h: 900, label: 'desktop-wide' },
  { w: 1440, h: 900, label: 'desktop' },
  { w: 1280, h: 800, label: 'laptop' },
  { w: 1024, h: 768, label: 'tablet-landscape' },
  { w: 768,  h: 1024, label: 'tablet' },
  { w: 430,  h: 932, label: 'phone-large' },
  { w: 390,  h: 844, label: 'phone' },
  { w: 360,  h: 780, label: 'phone-small' },
];

const MIME = {
  '.html': 'text/html; charset=utf-8', '.css': 'text/css', '.js': 'text/javascript',
  '.mjs': 'text/javascript', '.json': 'application/json', '.md': 'text/markdown; charset=utf-8',
  '.png': 'image/png', '.jpg': 'image/jpeg', '.svg': 'image/svg+xml',
  '.woff2': 'font/woff2', '.txt': 'text/plain; charset=utf-8',
};

function serve(root) {
  return new Promise(ok => {
    const s = createServer(async (req, res) => {
      const rel = normalize(decodeURIComponent(req.url.split('?')[0])).replace(/^(\.\.[/\\])+/, '');
      let file = join(root, rel);
      if (!extname(file)) file = join(file, 'index.html');
      try {
        const body = await readFile(file);
        res.writeHead(200, { 'content-type': MIME[extname(file)] || 'application/octet-stream' });
        res.end(body);
      } catch {
        res.writeHead(404).end('not found');
      }
    });
    s.listen(0, '127.0.0.1', () => ok(s));
  });
}

// ---------------------------------------------------------------------------
// Findings
// ---------------------------------------------------------------------------
const findings = [];
const notes = [];
const fail = (check, where, detail) => findings.push({ check, where, detail });
const note = (s) => notes.push(s);

// ---------------------------------------------------------------------------
// Per-viewport, per-theme DOM checks
// ---------------------------------------------------------------------------
async function inspect(page, opts = {}) {
  return page.evaluate(async ({ isRouter, isDark }) => {
    const out = { overflow: null, imgs: [], smallText: [], deadAnchors: [], hiddenPairs: [],
                  themedShots: [], lowContrast: [], svgCollisions: [], clampLeaks: [], hangs: [],
                  textRuns: 0 };

    // 1 · page-level horizontal overflow.
    // scrollWidth alone is not enough: html{overflow-x:clip} makes an
    // overflowing child report the clipped width, so measure the children too.
    const de = document.documentElement;
    const bleed = [];
    document.querySelectorAll('body *').forEach(el => {
      const cs = getComputedStyle(el);
      if (cs.position === 'fixed') return;
      const r = el.getBoundingClientRect();
      if (r.width <= 0) return;
      // Deliberate designs that overflow their own scroll container are fine;
      // only flag elements that push the PAGE sideways.
      let p = el.parentElement, contained = false;
      while (p && p !== document.body) {
        const pcs = getComputedStyle(p);
        if (/auto|scroll|hidden|clip/.test(pcs.overflowX)) { contained = true; break; }
        p = p.parentElement;
      }
      if (contained) return;
      // Something parked wholly off-screen left (a skip link at -9999px) adds
      // no horizontal scroll — only content crossing the RIGHT edge does, plus
      // anything straddling the left edge and therefore partly unreachable.
      if (r.right <= 0) return;
      if (r.right > window.innerWidth + 1 || r.left < -1) {
        bleed.push({ tag: el.tagName, cls: String(el.className).slice(0, 50),
                     left: Math.round(r.left), right: Math.round(r.right) });
      }
    });
    out.overflow = { docW: de.scrollWidth, winW: window.innerWidth, bleed: bleed.slice(0, 6) };

    // 2 · every visible raster image at its true aspect ratio, and — on a 2×
    // context — actually resolving to a 2× source when one is offered.
    // naturalWidth is DENSITY-CORRECTED: a candidate picked via a "2x"
    // descriptor reports half its real pixel width, so comparing it against
    // the device pixels needed double-counts the ratio and every retina image
    // looks 2x too soft. Re-load currentSrc bare to get its true pixel size.
    const trueSize = async (url) => await new Promise(res => {
      const probe = new Image();
      probe.onload = () => res([probe.naturalWidth, probe.naturalHeight]);
      probe.onerror = () => res([0, 0]);
      probe.src = url;
    });
    for (const im of document.querySelectorAll('img')) {
      const r = im.getBoundingClientRect();
      if (r.width < 4 || r.height < 4) continue;
      if (!im.naturalWidth || !im.naturalHeight) continue;
      const rendered = r.width / r.height;
      const natural = im.naturalWidth / im.naturalHeight;
      const url = im.currentSrc || im.src;
      const [px, py] = await trueSize(url);
      // Only `fill` (the default) stretches pixels. cover/contain/none crop or
      // letterbox instead, so a box ratio that differs from the source ratio is
      // the intended design, not a defect — flagging it made every deliberately
      // cropped thumbnail look like a bug.
      const fit = getComputedStyle(im).objectFit;
      out.imgs.push({
        file: url.split('/').pop(),
        css: `${Math.round(r.width)}x${Math.round(r.height)}`,
        nat: `${im.naturalWidth}x${im.naturalHeight}`,
        realPx: `${px}x${py}`,
        skewPct: fit === 'fill' ? +(Math.abs(rendered / natural - 1) * 100).toFixed(1) : 0,
        objectFit: fit,
        offersSrcset: !!(im.srcset || im.closest('picture')?.querySelector('source[srcset]')),
        // >1 means the display asks for more pixels than the file has — the
        // exact cause of a soft-looking screenshot.
        upscale: px ? +(r.width * devicePixelRatio / px).toFixed(2) : 0,
      });
    }

    // 3 · legibility floor for real body copy.
    //     Scoped to `body *`, not `main *`: kerf's landing has no <main> at
    //     all — it is thirteen bare <section>s — so the inherited selector
    //     reached nothing but the footer and the whole page's type could have
    //     been 9px without this check noticing. The self-test's
    //     `text-too-small` case is what surfaced that; it reported MISSED.
    const TEXTY = new Set(['P', 'LI', 'DD', 'DT', 'TD', 'TH', 'SPAN', 'B', 'EM', 'STRONG', 'A', 'CODE']);
    document.querySelectorAll('body *').forEach(el => {
      if (!TEXTY.has(el.tagName)) return;
      const own = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim().length > 12);
      if (!own) return;
      const r = el.getBoundingClientRect();
      if (r.width < 4 || r.height < 4) return;
      const cs = getComputedStyle(el);
      if (cs.visibility === 'hidden' || cs.textTransform === 'uppercase') return;  // eyebrows/labels
      const size = parseFloat(cs.fontSize);
      if (size < 12) {
        out.smallText.push({ tag: el.tagName, size,
                             text: el.textContent.trim().slice(0, 40) });
      }
    });

    // 4 · every same-page fragment link resolves.
    // Skipped on the docs viewer: it is a hash ROUTER, so "#sdk" and
    // "#sdk/auth" name a chapter and a section within it, not ids in the
    // current document. checkDocsChapters() validates those against the real
    // route table instead.
    if (!isRouter) {
      document.querySelectorAll('a[href^="#"]').forEach(a => {
        const id = a.getAttribute('href').slice(1);
        if (!id) return;
        if (!document.getElementById(id) && !document.querySelector(`[name="${CSS.escape(id)}"]`)) {
          out.deadAnchors.push({ href: '#' + id, text: a.textContent.trim().slice(0, 30) });
        }
      });
    }

    // 5 · theme-aware screenshots, both mechanisms, decided from the DOM
    // relationship rather than the filename. Filename sniffing does not work:
    // in the ".only-light / .only-dark" model the LIGHT capture is the
    // unmarked one (hero.png beside hero-dark.png), so "no marker in the name"
    // means "the light variant", not "theme-neutral art".
    //
    //   a) paired elements — exactly one of .only-light / .only-dark may paint,
    //      and it must be the one matching the active theme;
    //   b) swapped src — an <img data-light data-dark> must be showing the
    //      attribute for the active theme.
    const painted = e => {
      const r = e.getBoundingClientRect();
      return r.width > 4 && r.height > 4 && getComputedStyle(e).visibility !== 'hidden';
    };
    out.hiddenPairs.push({
      scope: 'document',
      light: [...document.querySelectorAll('.only-light')].filter(painted).length,
      dark:  [...document.querySelectorAll('.only-dark')].filter(painted).length,
    });

    document.querySelectorAll('img[data-light][data-dark]').forEach(im => {
      if (!painted(im)) return;
      const want = new URL(im.getAttribute(isDark ? 'data-dark' : 'data-light'), location.href).href;
      const got  = im.currentSrc || im.src || '';
      if (got && got !== want) {
        out.themedShots.push({ file: got.split('/').pop(), wanted: want.split('/').pop() });
      }
    });

    // 6 · contrast, computed rather than assumed.
    //
    // This is the check the first two passes of this file did not have, and
    // the one the page most needed: thirty distinct runs of body copy on the
    // landing sat between 3.11:1 and 4.23:1 — every section lede, every card
    // blurb, every shell prompt and every code comment — while the gate
    // reported clean. Reading the CSS would not have found it either; the
    // tokens looked plausible and the failures only appear once alpha and
    // inherited `opacity` are flattened against the ground actually painted.
    //
    // Both are flattened here: an ancestor at `opacity:.85` dims the text AND
    // the box behind it, and one of the two real defects this found was
    // exactly that. `seen` collapses identical (element, colour, size) runs so
    // a repeated component reports once instead of forty times.
    {
      const parse = c => { const m = String(c).match(/[\d.]+/g); return m ? [+m[0], +m[1], +m[2], m.length > 3 ? +m[3] : 1] : null; };
      const lin = v => { v /= 255; return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
      const lum = c => 0.2126 * lin(c[0]) + 0.7152 * lin(c[1]) + 0.0722 * lin(c[2]);
      const over = (fg, bg) => { const a = fg[3]; return [fg[0] * a + bg[0] * (1 - a), fg[1] * a + bg[1] * (1 - a), fg[2] * a + bg[2] * (1 - a), 1]; };
      const ratio = (a, b) => { const la = lum(a), lb = lum(b); const hi = Math.max(la, lb), lo = Math.min(la, lb); return (hi + 0.05) / (lo + 0.05); };
      const groundOf = el => {
        const stack = [];
        for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
          const c = parse(getComputedStyle(n).backgroundColor);
          if (c && c[3] > 0) stack.push(c);
          if (c && c[3] >= 1) break;
        }
        // The UA canvas under everything. `color-scheme: dark` paints it dark,
        // and getting this wrong flips every verdict on a transparent page.
        let acc = getComputedStyle(document.documentElement).colorScheme.includes('dark')
          ? [0, 0, 0, 1] : [255, 255, 255, 1];
        for (let i = stack.length - 1; i >= 0; i--) acc = over(stack[i], acc);
        return acc;
      };
      const seen = new Set();
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      for (let t = walker.nextNode(); t; t = walker.nextNode()) {
        const s = t.nodeValue.trim();
        if (!s) continue;
        const el = t.parentElement;
        if (!el || el.closest('svg')) continue;          // illustration ink, graded separately
        const cs = getComputedStyle(el);
        if (cs.display === 'none' || cs.visibility === 'hidden') continue;
        if (!el.offsetParent && cs.position !== 'fixed') continue;
        const r = el.getBoundingClientRect();
        if (r.width < 2 || r.height < 2) continue;
        const raw = parse(cs.color);
        if (!raw) continue;
        let op = 1;
        for (let n = el; n && n.nodeType === 1; n = n.parentElement) op *= parseFloat(getComputedStyle(n).opacity);
        if (op < 0.06) continue;                          // effectively not painted
        out.textRuns++;
        const ground = groundOf(el);
        const fg = over([raw[0], raw[1], raw[2], raw[3] * op], ground);
        const size = parseFloat(cs.fontSize), weight = +cs.fontWeight || 400;
        const large = size >= 24 || (size >= 18.66 && weight >= 700);
        const need = large ? 3 : 4.5;
        const got = ratio(fg, ground);
        if (got >= need) continue;
        const key = el.tagName + '|' + (typeof el.className === 'string' ? el.className : '') + '|' + cs.color + '|' + cs.fontSize + '|' + op.toFixed(2);
        if (seen.has(key)) continue;
        seen.add(key);
        out.lowContrast.push({
          sel: el.tagName.toLowerCase() + (typeof el.className === 'string' && el.className.trim() ? '.' + el.className.trim().split(/\s+/).join('.') : ''),
          text: s.slice(0, 44), color: cs.color, size, weight, need, got: +got.toFixed(2),
          opacity: +op.toFixed(2),
          ground: 'rgb(' + ground.slice(0, 3).map(Math.round).join(',') + ')',
        });
      }
    }

    // 7 · <text> runs inside one inline SVG colliding with each other.
    //
    // Every illustration on this page positions its labels with hand-picked
    // `x` values that assume a monospace advance width. The assumption was
    // wrong by about 20%, so a JSCAD snippet rendered as "export defaultmain"
    // and a Smith-chart readout as "|S11-12.4 dB". Neither is visible in the
    // markup and neither changes any layout metric — only the painted boxes
    // overlap, so only getBoundingClientRect (real CSS pixels, unlike getBBox's
    // nominal user units) can see it.
    for (const svg of document.querySelectorAll('svg')) {
      const items = [...svg.querySelectorAll('text')]
        .filter(t => t.textContent.trim())
        .map(t => ({ t, r: t.getBoundingClientRect() }))
        .filter(o => o.r.width > 0);
      for (let i = 0; i < items.length; i++) {
        for (let j = i + 1; j < items.length; j++) {
          const a = items[i], b = items[j];
          if (Math.abs((a.r.top + a.r.bottom) / 2 - (b.r.top + b.r.bottom) / 2) > 2) continue;
          const ovl = Math.min(a.r.right, b.r.right) - Math.max(a.r.left, b.r.left);
          if (ovl > 0.5) {
            out.svgCollisions.push({
              label: svg.getAttribute('aria-label') || String(svg.getAttribute('class') || '(svg)'),
              a: a.t.textContent.trim().slice(0, 24), b: b.t.textContent.trim().slice(0, 24),
              overlap: +ovl.toFixed(2),
            });
          }
        }
      }
    }

    // 8 · a -webkit-line-clamp that clips at the PADDING box.
    // `overflow:hidden` on a clamped element stops at the padding edge, so any
    // bottom padding is inside the visible window and the ascenders of the
    // first dropped line paint under the ellipsis. Two entries in the docs
    // on-this-page rail did exactly that.
    document.querySelectorAll('body *').forEach(el => {
      const cs = getComputedStyle(el);
      const clamp = cs.webkitLineClamp || cs.getPropertyValue('-webkit-line-clamp');
      if (!clamp || clamp === 'none') return;
      if (el.scrollHeight <= el.clientHeight + 1) return;   // nothing was dropped
      const pb = parseFloat(cs.paddingBottom) || 0;
      if (pb > 0.5) out.clampLeaks.push({
        sel: el.tagName.toLowerCase() + (typeof el.className === 'string' && el.className.trim() ? '.' + el.className.trim().split(/\s+/).join('.') : ''),
        text: el.textContent.trim().slice(0, 40), paddingBottom: pb,
        clientH: el.clientHeight, scrollH: el.scrollHeight,
      });
    });

    // 9 · a LABEL deliberately hung outside its box, inside a clipper.
    // A negative offset says "this is meant to stick out"; an ancestor with
    // overflow != visible says it does not. The hero's two floating chips lost
    // their top 11px and their last three characters to exactly this.
    //
    // Restricted to elements that carry text. A clipped glow, vignette or
    // bleed-gradient is the whole point of `overflow:hidden` — the first draft
    // of this check flagged the hero's own background glow at seven viewports,
    // which is a false positive, not a finding. Losing a character of a label
    // is never intended; losing the tail of a gradient always is.
    document.querySelectorAll('body *').forEach(el => {
      const cs = getComputedStyle(el);
      if (cs.position !== 'absolute') return;
      if (!el.textContent.trim() && !el.querySelector('img')) return;
      const hangs = ['top', 'left', 'right', 'bottom'].some(s => parseFloat(cs[s]) < -0.5);
      if (!hangs) return;
      const r = el.getBoundingClientRect();
      if (r.width < 2 || r.height < 2) return;
      for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
        const pcs = getComputedStyle(p);
        if (pcs.overflow === 'visible') continue;
        const pr = p.getBoundingClientRect();
        const cut = Math.max(pr.top - r.top, pr.left - r.left, r.right - pr.right, r.bottom - pr.bottom);
        if (cut > 0.5) out.hangs.push({
          sel: el.tagName.toLowerCase() + (typeof el.className === 'string' && el.className.trim() ? '.' + el.className.trim().split(/\s+/).join('.') : ''),
          text: el.textContent.trim().slice(0, 30), cutPx: +cut.toFixed(1),
          clipper: p.tagName.toLowerCase() + (typeof p.className === 'string' && p.className.trim() ? '.' + p.className.trim().split(/\s+/).join('.') : ''),
        });
        break;
      }
    });

    return out;
  }, { isRouter: !!opts.isRouter, isDark: !!opts.isDark });
}

async function checkPage(browser, base, path, theme, vp) {
  const ctx = await browser.newContext({
    viewport: { width: vp.w, height: vp.h }, deviceScaleFactor: 2, colorScheme: theme,
  });
  const page = await ctx.newPage();
  const where = `${path} ${vp.label}(${vp.w}) ${theme}`;

  const console404 = [];
  page.on('response', r => { if (r.status() >= 400) console404.push(`${r.status()} ${r.url()}`); });
  page.on('pageerror', e => fail('js-error', where, e.message));

  await page.goto(`${base}/${path}`, { waitUntil: 'networkidle' });
  // reveal-on-scroll gates most of the page; force it so nothing is measured
  // while still at opacity 0 and translated.
  // Reveal-on-scroll gates most of these pages and the class name differs per
  // repo (.rv here, .reveal there). Force every variant: a fast programmatic
  // scroll does not reliably fire an IntersectionObserver, so anything still
  // hidden would be measured at opacity 0 and mid-transform.
  await page.evaluate(() =>
    document.querySelectorAll('.rv, .reveal, [data-reveal]').forEach(e => e.classList.add('in', 'is-in')));
  await page.evaluate(async () => {
    const H = document.body.scrollHeight;
    for (let y = 0; y < H; y += 400) { window.scrollTo(0, y); await new Promise(r => setTimeout(r, 30)); }
    window.scrollTo(0, 0);
  });
  await page.waitForTimeout(500);

  const r = await inspect(page, { isRouter: path === 'docs.html', isDark: theme === 'dark' });

  if (r.overflow.docW > r.overflow.winW + 1) {
    fail('h-overflow', where, `document is ${r.overflow.docW}px wide in a ${r.overflow.winW}px viewport`);
  }
  if (r.overflow.bleed.length) {
    fail('h-overflow', where,
      'elements pushing past the viewport: ' + r.overflow.bleed
        .map(b => `${b.tag}.${b.cls} [${b.left}→${b.right}]`).join('; '));
  }
  r.imgs.forEach(i => {
    if (i.skewPct > 1.5) {
      fail('img-distorted', where,
        `${i.file} drawn ${i.css} from a ${i.nat} source — ${i.skewPct}% off its true aspect ratio`);
    }
    // Vector art has no resolution to be short of — an SVG drawn at any size is
    // exactly as sharp. Only raster sources can be upscaled into softness.
    const isVector = /\.svgx?(\?|#|$)/i.test(i.file);
    if (!isVector && i.offersSrcset && i.upscale > 1.15) {
      fail('img-soft', where,
        `${i.file} drawn ${i.css} at dpr2 from a ${i.realPx} file — upscaled ${i.upscale}×`);
    }
  });
  r.smallText.forEach(t =>
    fail('text-too-small', where, `<${t.tag.toLowerCase()}> at ${t.size}px: “${t.text}”`));
  r.deadAnchors.forEach(a =>
    fail('dead-anchor', where, `${a.href} (“${a.text}”) matches no element on the page`));
  r.themedShots.forEach(s =>
    fail('screenshot-wrong-theme', where,
      `showing ${s.file} in ${theme} mode; the ${theme} variant is ${s.wanted}`));
  r.hiddenPairs.forEach(p => {
    const live = theme === 'dark' ? p.dark : p.light;
    const dead = theme === 'dark' ? p.light : p.dark;
    if (dead > 0) fail('both-themes-visible', where,
      `${p.scope}: ${dead} off-theme image(s) painted alongside ${live} on-theme`);
    if (live === 0 && dead === 0) return;   // page does not use the paired model
    if (live === 0) fail('no-image-visible', where, `${p.scope}: nothing painted for the ${theme} theme`);
  });
  r.lowContrast.forEach(c =>
    fail('text-contrast', where,
      `${c.got}:1 (needs ${c.need}:1) — ${c.color}${c.opacity < 1 ? ` at opacity ${c.opacity}` : ''} ` +
      `on ${c.ground}, ${c.size}px/${c.weight} — ${c.sel} “${c.text}”`));
  r.svgCollisions.forEach(s =>
    fail('svg-text-collides', where,
      `“${s.a}” and “${s.b}” overlap by ${s.overlap}px in the SVG “${s.label}”`));
  r.clampLeaks.forEach(c =>
    fail('clamp-leaks-a-line', where,
      `${c.sel} clamps to ${c.clientH}px of ${c.scrollH}px but keeps ${c.paddingBottom}px of bottom ` +
      `padding inside the clip — the next line paints under the ellipsis (“${c.text}”)`));
  r.hangs.forEach(h =>
    fail('hangs-into-a-clip', where,
      `${h.sel} (“${h.text}”) is positioned to hang outside its box but ${h.clipper} clips ${h.cutPx}px of it`));
  console404.forEach(u => fail('http-error', where, u));

  await ctx.close();
  return r;
}

// ---------------------------------------------------------------------------
// Cross-page anchors: index.html ↔ docs.html
// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------
// The touch pass.
//
// Every other run in this file uses a desktop context, where `(hover: none)`
// never matches — so the one rule on these pages written FOR touch, the
// heading anchor the docs reveal at `opacity:.55` when there is no pointer to
// hover with, was never rendered by the gate at all. It measured 3.28:1 the
// first time anyone actually looked. A control that only exists on phones has
// to be graded on a phone.
// ---------------------------------------------------------------------------
async function checkTouch(browser, base) {
  for (const path of ['index.html', 'docs.html']) {
    const ctx = await browser.newContext({
      viewport: { width: 390, height: 844 }, deviceScaleFactor: 3,
      colorScheme: 'dark', hasTouch: true, isMobile: true,
    });
    const page = await ctx.newPage();
    const where = `${path} touch(390)`;
    await page.goto(`${base}/${path}`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(700);

    // Without this the whole pass is vacuous: if the context stopped
    // emulating touch, every hover-gated rule would sit at opacity 0, be
    // skipped as unpainted, and the pass would report clean having graded
    // nothing that a desktop run did not already cover.
    const touch = await page.evaluate(() => matchMedia('(hover: none)').matches);
    if (!touch) {
      fail('touch-not-emulated', where,
        '(hover: none) does not match in this context — the touch pass proved nothing');
      await ctx.close();
      continue;
    }
    const r = await inspect(page, { isRouter: path === 'docs.html', isDark: true });
    r.lowContrast.forEach(c =>
      fail('text-contrast', where,
        `${c.got}:1 (needs ${c.need}:1) — ${c.color}${c.opacity < 1 ? ` at opacity ${c.opacity}` : ''} ` +
        `on ${c.ground}, ${c.size}px/${c.weight} — ${c.sel} “${c.text}”`));
    r.hangs.forEach(h =>
      fail('hangs-into-a-clip', where,
        `${h.sel} (“${h.text}”) hangs outside its box but ${h.clipper} clips ${h.cutPx}px of it`));
    note(`${where}: (hover:none) active, graded ${r.textRuns} text runs`);
    await ctx.close();
  }
}

async function checkCrossPageAnchors(browser, base) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();

  const idsOf = async (p) => {
    await page.goto(`${base}/${p}`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(400);
    return new Set(await page.evaluate(() => [...document.querySelectorAll('[id]')].map(e => e.id)));
  };
  const linksOf = async (p) => {
    await page.goto(`${base}/${p}`, { waitUntil: 'networkidle' });
    return page.evaluate(() => [...document.querySelectorAll('a[href*=".html#"]')]
      .map(a => ({ href: a.getAttribute('href'), text: a.textContent.trim().slice(0, 30) })));
  };

  const indexIds = await idsOf('index.html');
  const docsIds  = await idsOf('docs.html');
  const ids = { 'index.html': indexIds, 'docs.html': docsIds };

  for (const from of ['index.html', 'docs.html']) {
    for (const l of await linksOf(from)) {
      const [file, frag] = l.href.replace(/^\.\//, '').split('#');
      if (!ids[file]) continue;                       // external or unknown target
      if (file === 'docs.html') continue;             // hash-routed: "#api" is a doc slug, not an id
      if (!ids[file].has(frag)) {
        fail('dead-anchor', `${from} → ${l.href}`,
          `“${l.text}” points at #${frag}, which ${file} does not define`);
      }
    }
  }
  await ctx.close();
}

// ---------------------------------------------------------------------------
// docs.html — the reading surface's own invariants
//
// Everything below is measured in the live page rather than read off the CSS,
// because all four defects here look correct in source:
//
//   · a sticky sidebar whose column is auto-height has no room to slide and
//     scrolls away — the rule says `position:sticky` and does nothing;
//   · a media query adds NO specificity, so a responsive override that reads
//     right silently loses to a later or deeper rule;
//   · a highlighter that failed to load still produces `<pre><code>`;
//   · a footer forbidden by the suite standard is one careless paste away.
//
// docsProbe() is shared with the self-test so the mutations are measured by
// the same code that grades the real page.
// ---------------------------------------------------------------------------
async function docsProbe(page) {
  return page.evaluate(async () => {
    const out = {};

    // 1 · the sidebar column must hold its position while the article scrolls.
    //     Three samples: at rest, one screen down, and well past it. The last
    //     two must agree — a sticky element with no travel is indistinguishable
    //     from a working one until the page is actually long enough to prove it.
    const side = document.querySelector('.side-col');
    out.sticky = null;
    if (side) {
      // The page sets `scroll-behavior: smooth`, so a scrollTo() followed by
      // a couple of animation frames lands somewhere between here and there.
      // Two samples taken mid-flight agree with each other for the wrong
      // reason, and the whole check passes without the page ever having
      // scrolled. Force instant scrolling and then WAIT for the position to
      // actually arrive; `reached` is reported so a green run can be checked.
      const prevRoot = document.documentElement.style.scrollBehavior;
      const prevBody = document.body.style.scrollBehavior;
      document.documentElement.style.scrollBehavior = 'auto';
      document.body.style.scrollBehavior = 'auto';
      const at = async y => {
        window.scrollTo(0, y);
        for (let i = 0; i < 40 && Math.abs(window.scrollY - y) > 1; i++) {
          await new Promise(r => requestAnimationFrame(r));
        }
        await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
        return { top: Math.round(side.getBoundingClientRect().top), reached: Math.round(window.scrollY) };
      };
      const a = await at(0), b = await at(800), c2 = await at(2400);
      const pageH = document.documentElement.scrollHeight;
      window.scrollTo(0, 0);
      await new Promise(r => requestAnimationFrame(r));
      document.documentElement.style.scrollBehavior = prevRoot;
      document.body.style.scrollBehavior = prevBody;
      out.sticky = { t0: a.top, t800: b.top, t2400: c2.top,
                     reached: [a.reached, b.reached, c2.reached], pageH,
                     position: getComputedStyle(side).position,
                     height: Math.round(side.getBoundingClientRect().height) };
    }

    // 2 · the shell is packed left, not floated in a centred column.
    //     Measured on the NAV, not on the grid container: the container is
    //     full-bleed and its left edge reads 0 no matter what the tracks do,
    //     so `justify-content:center` or a fat left padding would leave the
    //     nav swimming in dead space while the container-edge test reported
    //     a healthy 0. What the reader sees is where the nav starts.
    const shell = document.querySelector('.shell');
    out.shell = shell ? {
      left: Math.round(shell.getBoundingClientRect().left),
      navLeft: side ? Math.round(side.getBoundingClientRect().left) : null,
      cols: getComputedStyle(shell).gridTemplateColumns,
      justify: getComputedStyle(shell).justifyContent,
      winW: window.innerWidth,
    } : null;

    // 3 · the on-this-page rail must sit beside the prose it indexes, not a
    //     dead track's width away from it.
    const main = document.querySelector('.main'), railEl = document.querySelector('.rail');
    out.rail = (main && railEl && railEl.getBoundingClientRect().width > 0) ? {
      gap: Math.round(railEl.getBoundingClientRect().left - main.getBoundingClientRect().right),
    } : null;

    // 4 · no footer. Docs pages carry none — asserted, not merely absent.
    out.footers = document.querySelectorAll('footer').length;

    // 5 · code blocks: chip, copy button, and real token markup.
    const c = document.getElementById('content');
    out.doc = null;
    if (c) {
      // Every lookup below is null-guarded on purpose: the self-test breaks
      // this page by DELETING chrome, and a probe that throws on the mutated
      // page cannot grade it.
      const boxes = [...c.querySelectorAll('.code')];
      const chipOf = b => b.querySelector('.lang');
      const isPlain = b => { const l = chipOf(b); return !l || l.classList.contains('plain'); };
      out.doc = {
        err: !!c.querySelector('.err'),
        skeleton: !!c.querySelector('.skeleton'),
        chars: c.textContent.trim().length,
        pres: c.querySelectorAll('pre > code').length,
        boxes: boxes.length,
        chips: c.querySelectorAll('.code .lang').length,
        copies: c.querySelectorAll('.code .copy').length,
        // A block whose fence names a grammar hljs knows must carry token
        // spans. Counting `code.hljs` alone is not enough: the page adds that
        // class to unhighlightable blocks too, so it would pass with the
        // highlighter entirely absent.
        known: boxes.filter(b => !isPlain(b)).length,
        tokenised: boxes.filter(b => !isPlain(b)
                                     && b.querySelectorAll('code [class^="hljs-"]').length > 0).length,
        // Per-block, per-language tally. A block CAN legitimately produce no
        // tokens — `npm install` under the bash grammar colours nothing,
        // because neither word is a builtin, a string or a comment — so
        // "every block must be tokenised" is not a true invariant and was
        // flagging 23 correct blocks. What IS true: a language that appears
        // repeatedly must colour SOMETHING somewhere, or its grammar never
        // registered.
        perLang: boxes.filter(b => !isPlain(b)).map(b => ({
          lang: (chipOf(b) || {}).textContent || '?',
          tokens: b.querySelectorAll('code [class^="hljs-"]').length,
        })),
        registered: (window.hljs && hljs.listLanguages) ? hljs.listLanguages().slice().sort() : null,
        plainChips: boxes.filter(isPlain).map(b => (chipOf(b) || {}).textContent || ''),
        // Hover-only controls do not exist on a phone.
        hiddenCopies: boxes.filter(b => {
          const btn = b.querySelector('.copy');
          if (!btn) return false;                      // absent is code-chrome-missing, not hover-only
          const cs = getComputedStyle(btn);
          return cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity) < 0.15;
        }).length,
        rawFrontMatter: /^\s*title:\s*"/m.test(c.textContent.slice(0, 400)),
      };
    }
    return out;
  });
}

function gradeDocs(r, where) {
  if (r.sticky) {
    const reached = r.sticky.reached || [];
    if (r.sticky.pageH < 3000) {
      note(`${where}: page only ${r.sticky.pageH}px tall — stickiness not provable here`);
    } else if (reached[1] !== 800 || reached[2] !== 2400) {
      // Without this the check is unfalsifiable: if the page never scrolled,
      // every sample is taken at the same offset and they agree trivially.
      fail('sticky-unmeasurable', where,
        `asked for scroll 0/800/2400 but landed at ${reached.join('/')} — nothing was proved`);
    } else if (r.sticky.t800 !== r.sticky.t2400) {
      fail('sidebar-scrolls-away', where,
        `.side-col top: ${r.sticky.t0} at scroll 0, ${r.sticky.t800} at 800, ${r.sticky.t2400} at 2400 ` +
        `(position:${r.sticky.position}) — it is riding the page instead of pinning`);
    } else {
      note(`${where}: sidebar pinned — top ${r.sticky.t0}px at scroll 0, ` +
           `${r.sticky.t800}px at 800, ${r.sticky.t2400}px at 2400 ` +
           `(offsets actually reached: ${reached.join('/')}; column ${r.sticky.height}px tall)`);
    }
  }
  if (r.shell && r.shell.winW >= 1200 && r.shell.winW < 1900) {
    const edge = r.shell.navLeft != null ? r.shell.navLeft : r.shell.left;
    if (edge > 96) {
      fail('shell-not-packed-left', where,
        `the chapter nav starts ${edge}px from the window edge in a ${r.shell.winW}px viewport ` +
        `(.shell at ${r.shell.left}, justify-content:${r.shell.justify}) — ` +
        `it is floating in from the edge with dead space beside it`);
    } else {
      note(`${where}: nav starts ${edge}px from the window edge (tracks ${r.shell.cols})`);
    }
    if (/\b1fr\b/.test(r.shell.cols.replace(/px/g, '')) === false && r.rail && r.rail.gap > 120) {
      fail('rail-adrift', where, `the on-this-page rail sits ${r.rail.gap}px from the prose`);
    }
  }
  if (r.footers > 0) {
    fail('docs-has-footer', where,
      `${r.footers} <footer> element(s) on the docs page — the suite standard forbids all of them`);
  }
}

// The fence census, as a pure decision so the self-test can drive it with
// synthetic tallies instead of re-rendering fifty-eight chapters. Returns
// findings; the caller reports them.
//
// Every floor here is satisfiable on its own by a broken page:
//   · a total-blocks floor holds with every block flat;
//   · a total-tokenised floor holds with one huge JSON file coloured and
//     python dead;
//   · a per-language "at least one token anywhere" floor holds on three
//     blocks out of four hundred — it would have passed nineteen flat `http`
//     blocks sitting beside one coloured one.
//
// The constants are the measured corpus — 382 blocks, 288 naming a grammar,
// 273 carrying tokens, 94 audited and left plain — minus a small edit margin.
// The previous pass set them at 250/220 against a 279/264 corpus, which was
// too slack to be worth much: bash going dark costs exactly 44 blocks and
// lands on 220, which passed.
export function gradeFenceCensus({ totBoxes, totKnown, totTokenised, langTally }) {
  const out = [];
  if (totKnown < 278) {
    out.push({ check: 'highlight-coverage',
      detail: `only ${totKnown} code blocks resolved to a grammar; this corpus labels 288` });
  }
  if (totTokenised < 262) {
    out.push({ check: 'highlight-coverage',
      detail: `only ${totTokenised} of ${totKnown} recognised blocks carry token spans (corpus colours 273)` });
  }
  for (const [lang, e] of langTally) {
    if (e.known >= 3 && e.tokenised === 0) {
      out.push({ check: 'highlight-language-dead',
        detail: `${e.known} \u201c${lang}\u201d block(s) and none coloured — that grammar is not registered` });
    }
    // A language the corpus leans on has to colour MOST of its blocks. The
    // weakest real one is sh at 43/55 = 78%; 0.6 leaves room for a few more
    // `npm install`-shaped blocks that legitimately colour nothing, without
    // leaving room for a grammar that stopped working.
    else if (e.known >= 5 && e.tokenised / e.known < 0.6) {
      out.push({ check: 'highlight-language-thin',
        detail: `only ${e.tokenised} of ${e.known} \u201c${lang}\u201d blocks carry a token span ` +
                `(${Math.round(100 * e.tokenised / e.known)}%) — that grammar is barely firing` });
    }
  }
  // The other direction: labels silently disappearing. Each plain fence is one
  // the audit walked by hand — ASCII trees, tool-name listings, console
  // transcripts, and request lines that hljs's `http` grammar cannot match
  // because it wants an HTTP version on the line. Nine of the ninety-one had a
  // real grammar and were labelled. If this climbs, labels are being lost.
  const totPlain = totBoxes - totKnown;
  if (totPlain > 96) {
    out.push({ check: 'fence-labels-lost',
      detail: `${totPlain} of ${totBoxes} fenced blocks carry no language; the audited corpus leaves 94 plain` });
  }
  return out;
}

async function checkDocsChapters(browser, base) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();

  // Every hash target this site points at must name a published slug.
  await page.goto(`${base}/docs.html`, { waitUntil: 'networkidle' });
  const slugs = await page.evaluate(() => DOCS.map(d => d.slug));
  const slugSet = new Set(slugs);
  const idxCtx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const idx = await idxCtx.newPage();
  await idx.goto(`${base}/index.html`, { waitUntil: 'networkidle' });
  const hrefs = [
    ...await page.evaluate(() => [...document.querySelectorAll('a[href*="docs.html#"]')].map(a => a.getAttribute('href'))),
    ...await idx.evaluate(() => [...document.querySelectorAll('a[href*="docs.html#"]')].map(a => a.getAttribute('href'))),
  ];
  for (const href of hrefs) {
    const slug = href.split('#')[1].split('/')[0];
    if (!slugSet.has(slug)) {
      fail('dead-doc-route', href, `“${slug}” is not one of the ${slugs.length} published doc slugs`);
    }
  }
  await idxCtx.close();

  // Every chapter must render, and every fenced block whose language the
  // bundle knows must come out tokenised.
  let totBoxes = 0, totKnown = 0, totTokenised = 0, registered = null;
  const plainSeen = new Map();
  const langTally = new Map();
  for (const slug of slugs) {
    await page.goto(`${base}/docs.html#${slug}`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(300);
    const r = await docsProbe(page);
    const d = r.doc;
    const where = `docs.html#${slug}`;
    if (!d || d.err || d.skeleton || d.chars < 400) {
      fail('doc-not-rendered', where,
        `err=${d && d.err} skeleton=${d && d.skeleton} textLength=${d && d.chars}`);
      continue;
    }
    if (r.footers > 0) fail('docs-has-footer', where, `${r.footers} <footer> element(s)`);
    if (d.rawFrontMatter) fail('front-matter-leaked', where, 'YAML front matter rendered as prose');
    if (d.boxes !== d.pres) fail('code-block-unwrapped', where, `${d.pres} <pre> but ${d.boxes} .code frames`);
    if (d.chips !== d.boxes || d.copies !== d.boxes) {
      fail('code-chrome-missing', where, `${d.boxes} blocks, ${d.chips} language chips, ${d.copies} copy buttons`);
    }
    if (d.hiddenCopies) {
      fail('control-hover-only', where, `${d.hiddenCopies} copy button(s) are not painted at rest`);
    }
    // The signature of a highlighter that did not run: a chapter full of
    // recognised fences and not one coloured token anywhere in it.
    if (d.known >= 3 && d.tokenised === 0) {
      fail('code-not-highlighted', where,
        `${d.known} block(s) resolved to a grammar and not one produced a token span`);
    }
    d.plainChips.forEach(l => plainSeen.set(l, (plainSeen.get(l) || 0) + 1));
    d.perLang.forEach(b => {
      const e = langTally.get(b.lang) || { known: 0, tokenised: 0 };
      e.known++; if (b.tokens > 0) e.tokenised++;
      langTally.set(b.lang, e);
    });
    if (!registered && d.registered) registered = d.registered;
    totBoxes += d.boxes; totKnown += d.known; totTokenised += d.tokenised;
  }

  note(`docs: ${totBoxes} code blocks across ${slugs.length} chapters; ` +
       `${totKnown} with a known language, ${totTokenised} tokenised`);
  note('docs: per-language coverage — ' +
       [...langTally].sort((a, b) => b[1].known - a[1].known)
         .map(([l, e]) => `${l} ${e.tokenised}/${e.known}`).join(', '));

  gradeFenceCensus({ totBoxes, totKnown, totTokenised, langTally }).forEach(f =>
    fail(f.check, 'docs.html', f.detail));

  // The two grammars kerf layers on itself. If highlight-extras.min.js stops
  // loading, every one of the 67 python blocks silently reverts to flat text
  // and every count above still clears its floor on the strength of JSON.
  for (const need of ['python', 'typescript', 'json', 'bash', 'ini', 'go']) {
    if (registered && !registered.includes(need)) {
      fail('grammar-missing', 'docs.html', `highlight.js has no ${need} grammar registered`);
    }
  }
  if (registered) note(`docs: hljs grammars registered — ${registered.join(' ')}`);

  // Report the split in both directions so neither can drift quietly: how many
  // fences name a grammar, how many were audited and left plain, and — because
  // a ceiling on the total says nothing about WHERE the plain ones are — which
  // chapters hold them.
  if (plainSeen.size) {
    note(`docs: ${totKnown} of ${totBoxes} fences name a grammar; ` +
         `${totBoxes - totKnown} audited and left plain — ` +
         [...plainSeen].map(([l, n]) => `${l || '(none)'}×${n}`).join(', '));
  }

  // Sticky sidebar / left-packed shell, on the longest chapter there is.
  for (const vp of [{ w: 1600, h: 900 }, { w: 1440, h: 900 }, { w: 1280, h: 800 }]) {
    const c2 = await browser.newContext({ viewport: { width: vp.w, height: vp.h } });
    const p2 = await c2.newPage();
    await p2.goto(`${base}/docs.html#api-reference`, { waitUntil: 'networkidle' });
    await p2.waitForTimeout(500);
    gradeDocs(await docsProbe(p2), `docs.html layout(${vp.w})`);
    await c2.close();
  }
  await ctx.close();
}

// ---------------------------------------------------------------------------
// Self-test: break each invariant on purpose and demand the check notices.
// A gate that has quietly stopped failing looks exactly like one that works.
//
// The mutations pick their targets from the page rather than naming selectors,
// so this file is portable across the suite's landing pages, which share no
// class names. A case whose mechanism the page does not use reports "n/a"
// rather than passing silently — an inapplicable check must not read as a
// working one.
// ---------------------------------------------------------------------------
async function selftest(browser, base) {
  const cases = ['img-distorted', 'both-themes-visible', 'text-too-small',
                 'h-overflow', 'screenshot-wrong-theme',
                 'text-contrast', 'svg-text-collides', 'hangs-into-a-clip',
                 'control: unmutated landing grades clean'];
  let allCaught = true;
  for (const name of cases) {
    const ctx = await browser.newContext({
      viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2, colorScheme: 'dark',
    });
    const page = await ctx.newPage();
    await page.goto(`${base}/index.html`, { waitUntil: 'networkidle' });
    await page.evaluate(() => document.querySelectorAll('.rv,.reveal').forEach(e => e.classList.add('in', 'is-in')));
    await page.waitForTimeout(500);

    const applicable = await page.evaluate((which) => {
      const vis = e => { const r = e.getBoundingClientRect(); return r.width > 40 && r.height > 40; };
      if (which === 'img-distorted') {
        // Must be a DECODED image: the check skips anything with no intrinsic
        // size, so mutating a lazy image that has not loaded yet produces a
        // false MISSED rather than a real one.
        const im = [...document.querySelectorAll('img')]
          .filter(e => vis(e) && e.naturalWidth > 0 && e.naturalHeight > 0)
          .sort((a, b) => b.getBoundingClientRect().width - a.getBoundingClientRect().width)[0];
        if (!im) return false;
        // Squash it to a wrong ratio without changing its width. object-fit
        // must be forced to `fill` too: the check deliberately ignores skew
        // under cover/contain (those crop rather than stretch), so on a page
        // whose shots are cropped the mutation would be undetectable BY DESIGN
        // and this case would report a false MISSED.
        im.style.setProperty('object-fit', 'fill', 'important');
        im.style.setProperty('height', Math.round(im.getBoundingClientRect().width * 2) + 'px', 'important');
        im.style.setProperty('aspect-ratio', 'auto', 'important');
        return true;
      }
      if (which === 'text-too-small') {
        const p = [...document.querySelectorAll('main p, .pane p, section p, body p')]
          .find(e => e.textContent.trim().length > 40 && vis(e));
        if (!p) return false;
        p.style.setProperty('font-size', '9px', 'important');
        p.style.setProperty('text-transform', 'none', 'important');
        return true;
      }
      if (which === 'h-overflow') {
        // Straight onto <body>. The scan covers `body *`, and putting the
        // oversized element inside <main> is wrong wherever main is itself a
        // scroll container (envoir's reading pane): the check correctly treats
        // anything inside an overflow container as contained, so the mutation
        // could never be seen and the case reported a false MISSED.
        const host = document.body;
        const d = document.createElement('div');
        d.style.cssText = 'width:3000px;height:20px;background:red';
        host.appendChild(d);
        return true;
      }
      if (which === 'both-themes-visible') {
        if (!document.querySelector('.only-light') || !document.querySelector('.only-dark')) return false;
        document.querySelectorAll('.only-light,.only-dark')
          .forEach(e => e.style.setProperty('display', 'block', 'important'));
        return true;
      }
      if (which === 'text-contrast') {
        // Nudge a real paragraph to a tone that is close enough to the ground
        // to fail AA but nowhere near invisible — 4.0:1 on #0a0b0d. A mutation
        // to grey-on-grey would be caught by any check, including one that
        // only tested "is the text the same colour as the background".
        const p = [...document.querySelectorAll('p, li')]
          .find(e => e.textContent.trim().length > 40 && e.getBoundingClientRect().width > 40);
        if (!p) return false;
        p.style.setProperty('color', '#6e717c', 'important');
        return true;
      }
      if (which === 'svg-text-collides') {
        // Slide one <text> of an inline SVG onto its neighbour. Deliberately a
        // 6-unit nudge, not a total overlap: the real defect was a ~20% advance
        // -width error, which shows up as a few pixels of collision, and a
        // check tuned to "one label exactly on top of another" would miss it.
        for (const svg of document.querySelectorAll('svg')) {
          const texts = [...svg.querySelectorAll('text')]
            .filter(t => t.textContent.trim() && t.getBoundingClientRect().width > 0);
          for (let i = 1; i < texts.length; i++) {
            const a = texts[i - 1].getBoundingClientRect(), b = texts[i].getBoundingClientRect();
            if (Math.abs((a.top + a.bottom) / 2 - (b.top + b.bottom) / 2) > 2) continue;
            if (b.left < a.right) continue;                     // already touching
            const x = parseFloat(texts[i].getAttribute('x'));
            if (!isFinite(x)) continue;
            // The nudge has to be expressed in USER units, and an SVG drawn
            // into a 570px box from a 720-unit viewBox scales them by 0.79 —
            // a flat "move it 6" was smaller than the gap it had to close and
            // this case reported MISSED. getScreenCTM carries the real scale.
            const ctm = texts[i].getScreenCTM();
            const scale = ctm ? Math.abs(ctm.a) || 1 : 1;
            const gapCss = b.left - a.right;
            texts[i].setAttribute('x', String(x - (gapCss + 4) / scale));
            return true;
          }
        }
        return false;
      }
      if (which === 'hangs-into-a-clip') {
        // Put the clip back on the element the two hero chips hang out of.
        const chip = [...document.querySelectorAll('body *')].find(e => {
          const cs = getComputedStyle(e);
          return cs.position === 'absolute' && e.textContent.trim() &&
                 ['top', 'left', 'right', 'bottom'].some(s => parseFloat(cs[s]) < -0.5);
        });
        if (!chip || !chip.parentElement) return false;
        chip.parentElement.style.setProperty('overflow', 'hidden', 'important');
        return true;
      }
      if (which === 'control: unmutated landing grades clean') return true;   // mutate nothing
      if (which === 'screenshot-wrong-theme') {
        const swap = document.querySelectorAll('img[data-light][data-dark]');
        const pair = document.querySelector('.only-light') && document.querySelector('.only-dark');
        if (!swap.length && !pair) return false;
        swap.forEach(im => { im.removeAttribute('srcset'); im.src = im.getAttribute('data-light'); });
        if (pair) {
          document.querySelectorAll('.only-dark').forEach(e => e.style.setProperty('display', 'none', 'important'));
          document.querySelectorAll('.only-light').forEach(e => e.style.setProperty('display', 'block', 'important'));
        }
        return true;
      }
      return false;
    }, name);

    if (!applicable) {
      console.log(`  n/a      ${name} — this page does not use that mechanism`);
      await ctx.close();
      continue;
    }

    await page.waitForTimeout(400);
    const r = await inspect(page, { isDark: true });
    const caught =
      (name === 'img-distorted'       && r.imgs.some(i => i.skewPct > 1.5)) ||
      (name === 'both-themes-visible' && r.hiddenPairs.some(p => p.light > 0 && p.dark > 0)) ||
      (name === 'text-too-small'      && r.smallText.length > 0) ||
      (name === 'h-overflow'          && (r.overflow.docW > r.overflow.winW + 1 || r.overflow.bleed.length > 0)) ||
      (name === 'screenshot-wrong-theme' &&
         (r.themedShots.length > 0 || r.hiddenPairs.some(p => p.light > 0 && p.dark === 0))) ||
      (name === 'text-contrast'      && r.lowContrast.length > 0) ||
      (name === 'svg-text-collides'  && r.svgCollisions.length > 0) ||
      (name === 'hangs-into-a-clip'  && r.hangs.length > 0) ||
      // False-positive control for the three new checks. Without it a probe
      // that reported a defect unconditionally would "catch" every mutation
      // above and read as a perfect gate. It also proves the contrast walk
      // reached something: `textRuns` is the number of runs it actually
      // graded, so a scan scoped to an element the page does not have —
      // exactly how the legibility check went hollow two passes ago — fails
      // here instead of passing silently.
      (name === 'control: unmutated landing grades clean' &&
         r.lowContrast.length === 0 && r.svgCollisions.length === 0 &&
         r.hangs.length === 0 && r.textRuns > 200);
    if (name === 'control: unmutated landing grades clean') {
      console.log(`           (graded ${r.textRuns} text runs, ` +
                  `${r.lowContrast.length} below AA, ${r.svgCollisions.length} svg collisions, ` +
                  `${r.hangs.length} clipped labels)`);
    }
    console.log(`  ${caught ? 'caught  ' : 'MISSED  '} ${name}`);
    if (!caught) allCaught = false;
    await ctx.close();
  }
  // Not `allCaught && …`: a short-circuit would hide every docs case behind
  // the first landing failure, and a gate you cannot see the rest of is a gate
  // you cannot fix.
  const docsOk = await selftestDocs(browser, base);
  return allCaught && docsOk;
}

// The docs-viewer invariants get the same treatment. These are the ones most
// likely to rot silently: three of the four are CSS that reads correct while
// doing nothing, and the fourth is a script that can stop loading without
// changing a byte of markup.
async function selftestDocs(browser, base) {
  const cases = ['sidebar-scrolls-away', 'docs-has-footer', 'code-not-highlighted',
                 'grammar-missing', 'code-chrome-missing', 'control-hover-only',
                 'shell-not-packed-left', 'clamp-leaks-a-line'];
  let allCaught = true;
  for (const name of cases) {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await ctx.newPage();
    // A long chapter: the sticky case cannot be proved on a page that does not
    // scroll, and grading it there would report a false "caught".
    await page.goto(`${base}/docs.html#api-reference`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(700);

    const applicable = await page.evaluate((which) => {
      if (which === 'sidebar-scrolls-away') {
        const s = document.querySelector('.side-col'); if (!s) return false;
        // Exactly the bug this check exists for: the rule is still there, but
        // the element has no travel inside its own box.
        s.style.setProperty('position', 'static', 'important');
        return document.documentElement.scrollHeight > 3000;
      }
      if (which === 'docs-has-footer') {
        const f = document.createElement('footer');
        f.textContent = 'a footer that should not be here';
        document.body.appendChild(f);
        return true;
      }
      if (which === 'code-not-highlighted') {
        // Simulate the highlighter not having run at all: keep every frame
        // and chip, drop every token span. Mutating ONE block would not be a
        // fair test — a single tokenless block is legitimate (`npm install`
        // colours nothing under bash) and the check deliberately tolerates it.
        const boxes = [...document.querySelectorAll('.code')]
          .filter(b => !b.querySelector('.lang').classList.contains('plain'));
        if (boxes.length < 3) return false;
        boxes.forEach(b => { const c = b.querySelector('code'); c.textContent = c.textContent; });
        return true;
      }
      if (which === 'grammar-missing') {
        // The kerf-specific extras bundle failing to load looks exactly like
        // this: core hljs present, python absent, every JSON block still
        // coloured so the totals stay healthy.
        if (!window.hljs || !hljs.listLanguages().includes('python')) return false;
        hljs.unregisterLanguage('python');
        return true;
      }
      if (which === 'code-chrome-missing') {
        const bar = document.querySelector('.code .bar'); if (!bar) return false;
        bar.querySelector('.copy').remove();
        return true;
      }
      if (which === 'control-hover-only') {
        const b = document.querySelector('.code .copy'); if (!b) return false;
        b.style.setProperty('opacity', '0', 'important');
        return true;
      }
      if (which === 'clamp-leaks-a-line') {
        // Put the clamp back on the <a> itself — padding and all — which is
        // exactly the shape the rail had before the clamp moved to an inner
        // span. The entry has to be long enough to actually spill past two
        // lines, or the mutation proves nothing.
        const a = document.querySelector('.rail a');
        if (!a) return false;
        // textContent also unwraps the inner .clamp span — the whole point of
        // the mutation is to put the clamp back on the padded <a>, and leaving
        // the span in place would keep the fix working underneath it and this
        // case would report a false MISSED.
        a.textContent = (a.textContent.trim() + ' — ').repeat(4);
        a.style.setProperty('display', '-webkit-box', 'important');
        a.style.setProperty('-webkit-line-clamp', '2');
        a.style.setProperty('-webkit-box-orient', 'vertical');
        a.style.setProperty('overflow', 'hidden', 'important');
        a.style.setProperty('padding-bottom', '5px', 'important');
        a.style.setProperty('width', '150px', 'important');
        return a.scrollHeight > a.clientHeight + 1;
      }
      if (which === 'shell-not-packed-left') {
        const sh = document.querySelector('.shell'); if (!sh) return false;
        // Deliberately a mutation the OLD container-edge test could not see:
        // the grid container still starts at x=0, only its contents are shoved
        // inward. If this case ever reports MISSED, the check has quietly gone
        // back to measuring the wrapper instead of the nav.
        sh.style.setProperty('padding-left', '300px', 'important');
        return true;
      }
      return false;
    }, name);

    if (!applicable) {
      console.log(`  n/a      ${name} — this page does not use that mechanism`);
      await ctx.close();
      continue;
    }

    const r = await docsProbe(page);
    const d = r.doc || {};
    // The clamp finding comes off the shared inspect() walk, not docsProbe.
    const ins = name === 'clamp-leaks-a-line' ? await inspect(page, { isRouter: true, isDark: true }) : null;
    const caught =
      (name === 'clamp-leaks-a-line'    && ins.clampLeaks.length > 0) ||
      (name === 'sidebar-scrolls-away'  && r.sticky && r.sticky.t800 !== r.sticky.t2400) ||
      (name === 'docs-has-footer'       && r.footers > 0) ||
      (name === 'code-not-highlighted'  && d.known >= 3 && d.tokenised === 0) ||
      (name === 'grammar-missing'       && d.registered && !d.registered.includes('python')) ||
      (name === 'code-chrome-missing'   && (d.chips !== d.boxes || d.copies !== d.boxes)) ||
      (name === 'control-hover-only'    && d.hiddenCopies > 0) ||
      (name === 'shell-not-packed-left' && r.shell && r.shell.navLeft > 96);
    console.log(`  ${caught ? 'caught  ' : 'MISSED  '} ${name}`);
    if (!caught) allCaught = false;
    await ctx.close();
  }

  // False-positive control: the UNMUTATED page must grade clean through the
  // very same probe. Without it a probe that reports a defect unconditionally
  // would "catch" all six mutations and read as a perfect gate.
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  await page.goto(`${base}/docs.html#api-reference`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(700);
  const r = await docsProbe(page);
  const insClean = await inspect(page, { isRouter: true, isDark: true });
  const d = r.doc || {};
  const clean = r.sticky && r.sticky.t800 === r.sticky.t2400 && r.footers === 0 &&
                d.known >= 3 && d.tokenised > 0 && d.chips === d.boxes &&
                d.copies === d.boxes && d.hiddenCopies === 0 && r.shell && r.shell.navLeft <= 96 &&
                d.registered && d.registered.includes('python') &&
                insClean.clampLeaks.length === 0;
  console.log(`  ${clean ? 'caught  ' : 'MISSED  '} control: unmutated page grades clean`);
  if (!clean) {
    console.log(`           sticky=${JSON.stringify(r.sticky)} footers=${r.footers} ` +
                `known=${d.known} tokenised=${d.tokenised} boxes=${d.boxes} chips=${d.chips} ` +
                `copies=${d.copies} hidden=${d.hiddenCopies} navLeft=${r.shell && r.shell.navLeft} ` +
                `clampLeaks=${insClean.clampLeaks.length}`);
    allCaught = false;
  }
  await ctx.close();

  // ── the touch pass ───────────────────────────────────────────────────────
  // Its whole reason to exist is a control that only appears when
  // `(hover: none)` matches, so the case has to prove two things: that the
  // context really is emulating touch, and that a hover-revealed control at a
  // failing tone is seen. The mutation is the exact value the docs shipped
  // with before this pass — .55, which flattens to 3.27:1.
  {
    const tctx = await browser.newContext({
      viewport: { width: 390, height: 844 }, deviceScaleFactor: 3,
      colorScheme: 'dark', hasTouch: true, isMobile: true,
    });
    const tp = await tctx.newPage();
    await tp.goto(`${base}/docs.html#concepts`, { waitUntil: 'networkidle' });
    await tp.waitForTimeout(700);
    const hoverNone = await tp.evaluate(() => matchMedia('(hover: none)').matches);
    const before = await inspect(tp, { isRouter: true, isDark: true });
    await tp.addStyleTag({ content: '@media (hover: none) { .md .anchor { opacity: .55 !important; } }' });
    await tp.waitForTimeout(200);
    const after = await inspect(tp, { isRouter: true, isDark: true });
    const ok = hoverNone && before.lowContrast.length === 0 && after.lowContrast.length > 0;
    console.log(`  ${ok ? 'caught  ' : 'MISSED  '} text-contrast on a hover-revealed control (touch)`);
    if (!ok) {
      console.log(`           hover:none=${hoverNone} clean=${before.lowContrast.length} ` +
                  `mutated=${after.lowContrast.length}`);
      allCaught = false;
    }
    await tctx.close();
  }

  // ── the fence census, driven directly ────────────────────────────────────
  // These two rules decide over fifty-eight chapters' worth of tallies, so
  // proving them by re-rendering the corpus would cost two minutes per case.
  // gradeFenceCensus is pure, so the mutation is a synthetic tally instead —
  // and the control feeds it the real measured corpus, which must grade clean.
  const REAL = { totBoxes: 382, totKnown: 288, totTokenised: 273,
                 langTally: new Map([['json', { known: 113, tokenised: 113 }],
                                     ['python', { known: 71, tokenised: 70 }],
                                     ['sh', { known: 55, tokenised: 43 }],
                                     ['yaml', { known: 5, tokenised: 5 }]]) };
  const censusCases = [
    ['highlight-language-thin',
     { ...REAL, langTally: new Map([...REAL.langTally, ['sh', { known: 55, tokenised: 20 }]]) }],
    ['fence-labels-lost', { ...REAL, totKnown: 270 }],
  ];
  for (const [want, input] of censusCases) {
    const hit = gradeFenceCensus(input).some(f => f.check === want);
    console.log(`  ${hit ? 'caught  ' : 'MISSED  '} ${want}`);
    if (!hit) allCaught = false;
  }
  const censusClean = gradeFenceCensus(REAL);
  console.log(`  ${censusClean.length === 0 ? 'caught  ' : 'MISSED  '} ` +
              `control: the measured fence census grades clean`);
  if (censusClean.length) {
    console.log('           ' + censusClean.map(f => f.check + ': ' + f.detail).join('; '));
    allCaught = false;
  }
  return allCaught;
}

// ---------------------------------------------------------------------------
async function main() {
  if (!existsSync(join(SITE, 'index.html'))) {
    console.error(`check-render: no site/index.html under ${SITE}`);
    process.exit(2);
  }
  const server = await serve(SITE);
  const base = `http://127.0.0.1:${server.address().port}`;
  const browser = await chromium.launch({ headless: true });

  try {
    if (process.argv.includes('--selftest')) {
      console.log('check-render self-test — each invariant is broken on purpose:\n');
      const ok = await selftest(browser, base);
      console.log(ok ? '\nSELF-TEST PASS — every check discriminates.'
                     : '\nSELF-TEST FAIL — a check did not notice its own defect.');
      process.exitCode = ok ? 0 : 1;
      return;
    }

    let sampled = 0;
    for (const vp of VIEWPORTS) {
      for (const theme of ['light', 'dark']) {
        for (const path of ['index.html', 'docs.html']) {
          const r = await checkPage(browser, base, path, theme, vp);
          sampled += r.imgs.length;
        }
      }
    }
    await checkTouch(browser, base);
    await checkCrossPageAnchors(browser, base);
    await checkDocsChapters(browser, base);

    console.log(`\nchecked ${VIEWPORTS.length} viewports × 2 themes × 2 pages; ` +
                `${sampled} rendered images measured\n`);
    notes.forEach(n => console.log('  · ' + n));

    if (findings.length) {
      console.error(`\ncheck-render: ${findings.length} finding(s)\n`);
      const byCheck = {};
      findings.forEach(f => (byCheck[f.check] ||= []).push(f));
      for (const [check, list] of Object.entries(byCheck)) {
        console.error(`  ${check} (${list.length})`);
        // Collapse the viewport dimension: the same defect at eight widths is
        // one defect, and printing it eight times buries the others.
        const seen = new Set();
        list.forEach(f => {
          const key = f.detail;
          if (seen.has(key)) return;
          seen.add(key);
          console.error(`    ${f.where}\n      ${f.detail}`);
        });
      }
      process.exitCode = 1;
    } else {
      console.log('\ncheck-render: clean');
    }
  } finally {
    await browser.close();
    server.close();
  }
}

main().catch(e => { console.error(e); process.exit(2); });
