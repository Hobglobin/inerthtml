/* inert.js: browser implementation of the inert/1 verifier and a "lite"
 * sanitizer (no rendering, remote assets are removed rather than embedded).
 * Mirrors src/inerthtml/core.py. Works in browsers and nothing is uploaded. */
(function (root) {
  'use strict';

  const PROFILE = 'inert/1';
  const CSP = "default-src 'none'; script-src 'none'; object-src 'none'; " +
    "style-src 'unsafe-inline'; img-src data:; font-src data:; " +
    "media-src 'none'; frame-src 'none'; connect-src 'none'; " +
    "form-action 'none'; base-uri 'none'";
  const HELPER_CSS = ':where(svg[data-inert-chart]),:where(img[data-inert-frozen])' +
    '{max-width:100%;height:auto}';
  const FORBIDDEN = new Set(['script', 'noscript', 'iframe', 'frame', 'frameset', 'object',
    'embed', 'applet', 'base', 'portal', 'template', 'video', 'audio', 'source', 'track',
    'foreignobject', 'fencedframe', 'link', 'form']);
  const URL_ATTRS = new Set(['href', 'xlink:href', 'src', 'poster', 'background', 'action',
    'formaction', 'data', 'cite', 'longdesc', 'ping', 'srcset', 'imagesrcset', 'srcdoc',
    'manifest', 'codebase', 'archive']);
  const DROP_ATTRS = new Set([...URL_ATTRS].filter(a => !['href', 'xlink:href', 'src'].includes(a)));
  const SAFE_LINK = ['http:', 'https:', 'mailto:', 'tel:'];
  const SAFE_DATA = ['data:image/', 'data:font/', 'data:application/font',
    'data:application/x-font', 'data:application/octet-stream',
    'data:application/vnd.ms-fontobject'];
  const ANIM = new Set(['set', 'animate', 'animatetransform', 'animatemotion']);

  const BAD_CSS = /expression\s*\(|-moz-binding|behavior\s*:|javascript:/gi;
  const CSS_URL = /url\(\s*(?:"([^"]*)"|'([^']*)'|([^)\s]*))\s*\)/gi;
  const CSS_IMPORT = /@import[^;]*;?/gi;
  const CSS_NAMESPACE = /@namespace[^;]*;/gi;
  const CSS_IMAGE_SET = /image-set\(([^)]*)\)/gi;
  const CSS_QUOTED = /["']([^"']*)["']/g;

  const CSS_ESCAPE = /\\([0-9a-fA-F]{1,6})[ \t\n\r\f]?|\\([^\n\r\f0-9a-fA-F])/g;
  const CSS_PLAIN = /^[A-Za-z0-9:\/().@_\-]$/;
  function cssUnescape(css) {
    return String(css).replace(CSS_ESCAPE, (m, hex, ch) => {
      let c = ch;
      if (hex) { const n = parseInt(hex, 16); if (n > 0x10FFFF) return m; c = String.fromCodePoint(n); }
      return CSS_PLAIN.test(c) ? c : m;
    });
  }
  const norm = s => String(s).replace(/[\s\x00-\x1f]/g, '').toLowerCase();
  const safeData = s => SAFE_DATA.some(p => norm(s).startsWith(p));
  const hasScheme = s => /^[a-z][a-z0-9+.-]*:/.test(s);
  const safeScheme = s => SAFE_LINK.some(p => s.startsWith(p));
  const tagName = el => (el.localName || el.nodeName).toLowerCase();
  const isLinkAttr = (name, attr) =>
    name === 'a' || (attr !== 'src' && !['image', 'use', 'feimage'].includes(name));

  function badUrls(css) {
    css = cssUnescape(css).replace(CSS_NAMESPACE, '');
    const bad = [];
    for (const m of css.matchAll(CSS_URL)) {
      const ref = (m[1] || m[2] || m[3] || '').trim();
      if (ref && !ref.startsWith('#') && !safeData(ref)) bad.push(ref);
    }
    for (const m of css.matchAll(CSS_IMAGE_SET)) {
      for (const q of m[1].matchAll(CSS_QUOTED)) {
        if (q[1] && !safeData(q[1])) bad.push(q[1]);
      }
    }
    return bad;
  }

  function checkCss(css, where) {
    css = cssUnescape(css);
    const out = [];
    if (new RegExp(BAD_CSS.source, 'i').test(css)) out.push(`dangerous CSS in ${where}`);
    if (/@import/i.test(css)) out.push(`@import in ${where}`);
    for (const ref of badUrls(css)) out.push(`external url() in ${where}: ${ref.slice(0, 60)}`);
    return out;
  }

  function parse(html) {
    return new DOMParser().parseFromString(html, 'text/html');  // never runs scripts
  }

  /* ------------------------------------------------------------ verify */
  function verify(html) {
    const doc = typeof html === 'string' ? parse(html) : html;
    const problems = new Set();
    const head = doc.head;
    const csp = Array.from(doc.querySelectorAll('meta')).find(
      m => (m.getAttribute('http-equiv') || '').trim().toLowerCase() === 'content-security-policy');
    let ok = !!csp && csp.parentElement === head;
    if (ok) {
      for (const el of head.children) {
        if (el === csp) break;
        if (!(tagName(el) === 'meta' && el.hasAttribute('charset'))) { ok = false; break; }
      }
    }
    if (!ok) {
      problems.add('missing CSP <meta> at the top of <head>');
    } else {
      const pol = (csp.getAttribute('content') || '').split(/\s+/).join(' ');
      const dirs = {};
      for (const d of pol.split(';')) {
        const t = d.trim();
        if (t) dirs[t.split(' ')[0].toLowerCase()] = t;
      }
      if (dirs['default-src'] !== "default-src 'none'") problems.add("CSP must contain default-src 'none'");
      if ((dirs['script-src'] || "script-src 'none'") !== "script-src 'none'") problems.add('CSP must not allow scripts');
      if (dirs['form-action'] !== "form-action 'none'") problems.add("CSP must contain form-action 'none'");
      for (const [d, text] of Object.entries(dirs)) {
        const srcs = text.split(' ').slice(1);
        if (srcs.some(s => !["'none'", "'unsafe-inline'", 'data:'].includes(s))) problems.add(`CSP directive allows remote sources: ${text}`);
        if (srcs.includes("'unsafe-inline'") && d !== 'style-src') problems.add(`CSP allows inline content outside styles: ${text}`);
      }
    }

    for (const el of doc.querySelectorAll('*')) {
      const name = tagName(el);
      if (FORBIDDEN.has(name)) problems.add(`forbidden element <${name}>`);
      if (name === 'meta' && el.getAttribute('http-equiv') &&
          el.getAttribute('http-equiv').trim().toLowerCase() !== 'content-security-policy') {
        problems.add(`forbidden <meta http-equiv=${el.getAttribute('http-equiv')}>`);
      }
      if (name === 'input' && ['password', 'file'].includes((el.getAttribute('type') || '').toLowerCase())) {
        problems.add(`forbidden <input type=${el.getAttribute('type')}>`);
      }
      for (const at of Array.from(el.attributes)) {
        const a = at.name.toLowerCase();
        const v = at.value;
        const low = norm(v);
        if (ANIM.has(name) && a === 'attributename' && ['href', 'xlink:href'].includes(low)) {
          problems.add(`<${name}> animates a link target`);
        }
        if (a.startsWith('on')) {
          problems.add(`event handler ${a} on <${name}>`);
        } else if (a === 'src' || a === 'href' || a === 'xlink:href') {
          if (isLinkAttr(name, a)) {
            if (hasScheme(low) && !safeScheme(low)) problems.add(`unsafe link on <${name}>: ${v.slice(0, 60)}`);
          } else if (name === 'use') {
            if (!low.startsWith('#')) problems.add('<use> references an external resource');
          } else if (!safeData(v)) {
            problems.add(`external resource on <${name}>: ${v.slice(0, 60)}`);
          }
        } else if (URL_ATTRS.has(a)) {
          problems.add(`forbidden attribute ${a} on <${name}>`);
        } else if (a === 'style') {
          checkCss(v, `style attribute on <${name}>`).forEach(p => problems.add(p));
        } else if (cssUnescape(v).toLowerCase().includes('url(')) {
          badUrls(v).forEach(r => problems.add(`external url() in ${a} on <${name}>: ${r.slice(0, 60)}`));
        }
      }
      if (name === 'style') checkCss(el.textContent || '', '<style>').forEach(p => problems.add(p));
    }
    return Array.from(problems).sort();
  }

  /* ------------------------------------------------------------ sanitize (lite) */
  function cleanCss(css, stats) {
    css = cssUnescape(css);
    css = css.replace(CSS_IMPORT, () => { stats.remote++; return ''; });
    const ns = css.match(CSS_NAMESPACE) || [];
    css = css.replace(CSS_NAMESPACE, '');
    css = css.replace(CSS_URL, (m, a, b, c) => {
      const ref = (a || b || c || '').trim();
      if (!ref || ref.startsWith('#')) return m;
      if (ref.toLowerCase().startsWith('data:') && safeData(ref)) return m;
      stats.remote++;
      return 'none';
    });
    css = css.replace(CSS_IMAGE_SET, (m, inner) =>
      `image-set(${inner.replace(CSS_QUOTED, (q, u) => (safeData(u) ? q : (stats.remote++, '""')))})`);
    css = css.replace(BAD_CSS, () => { stats.active++; return '/*removed*/'; });
    return ns.join('') + css;
  }

  function sanitize(html, opts = {}) {
    const stats = { scripts: 0, handlers: 0, forms: 0, links: 0, remote: 0, active: 0 };
    const doc = parse(html);

    const walker = doc.createTreeWalker(doc, NodeFilter.SHOW_COMMENT);
    const comments = [];
    while (walker.nextNode()) comments.push(walker.currentNode);
    comments.forEach(c => c.remove());

    for (const el of Array.from(doc.querySelectorAll('*'))) {
      if (ANIM.has(tagName(el))) {
        const an = Array.from(el.attributes).find(x => x.name.toLowerCase() === 'attributename');
        if (an && ['href', 'xlink:href'].includes(norm(an.value))) { el.remove(); stats.active++; }
      }
    }
    for (const m of Array.from(doc.querySelectorAll('meta'))) {
      if (m.hasAttribute('http-equiv')) { m.remove(); stats.active++; } else if (m.hasAttribute('charset')) m.remove();
    }
    for (const f of Array.from(doc.querySelectorAll('form'))) {
      const div = doc.createElement('div');
      for (const at of Array.from(f.attributes)) div.setAttribute(at.name, at.value);
      div.setAttribute('data-inert-form', '');
      while (f.firstChild) div.appendChild(f.firstChild);
      f.replaceWith(div);
      stats.forms++;
    }
    for (const el of Array.from(doc.querySelectorAll('*'))) {
      const n = tagName(el);
      if (!el.isConnected || !FORBIDDEN.has(n)) continue;
      if (n === 'script') stats.scripts++;
      else if (n === 'link') stats.remote++;
      else stats.active++;
      el.remove();
    }
    for (const st of Array.from(doc.querySelectorAll('style'))) st.textContent = cleanCss(st.textContent || '', stats);
    for (const el of Array.from(doc.querySelectorAll('input'))) {
      if (['password', 'file', 'hidden', 'image'].includes((el.getAttribute('type') || '').toLowerCase())) {
        el.remove(); stats.forms++;
      } else el.setAttribute('disabled', '');
    }
    for (const el of Array.from(doc.querySelectorAll('textarea, select'))) el.setAttribute('disabled', '');
    for (const el of Array.from(doc.querySelectorAll('button'))) el.setAttribute('type', 'button');
    for (const el of Array.from(doc.querySelectorAll('picture'))) el.replaceWith(...el.childNodes);

    for (const el of Array.from(doc.querySelectorAll('*'))) {
      const name = tagName(el);
      for (const at of Array.from(el.attributes)) {
        const a = at.name.toLowerCase();
        const v = at.value;
        if (a.startsWith('on')) { el.removeAttribute(at.name); stats.handlers++; }
        else if (DROP_ATTRS.has(a)) { el.removeAttribute(at.name); stats.remote++; }
        else if (a === 'style') el.setAttribute(at.name, cleanCss(v, stats));
        else if (a === 'src' || a === 'href' || a === 'xlink:href') {
          if (isLinkAttr(name, a)) {
            const low = norm(v);
            const keep = v.trim().startsWith('#') || (safeScheme(low) && !opts.stripLinks);
            if (!keep) {
              el.removeAttribute(at.name);
              if (hasScheme(low) && !safeScheme(low)) stats.links++;
            }
          } else if (name === 'use') {
            if (!v.trim().startsWith('#')) { el.removeAttribute(at.name); stats.remote++; }
          } else if (!safeData(v)) { el.removeAttribute(at.name); stats.remote++; }
        } else if (cssUnescape(v).toLowerCase().includes('url(') && badUrls(v).length) {
          el.removeAttribute(at.name); stats.remote++;
        }
      }
      if (name === 'a') {
        if (el.getAttribute('href')) {
          el.setAttribute('rel', 'noopener noreferrer nofollow');
          el.setAttribute('target', '_blank');
          if (!el.getAttribute('title')) el.setAttribute('title', el.getAttribute('href'));
        } else el.removeAttribute('target');
      }
    }

    const head = doc.head;
    const mk = (attrs) => { const m = doc.createElement('meta'); for (const k in attrs) m.setAttribute(k, attrs[k]); return m; };
    const style = doc.createElement('style');
    style.textContent = HELPER_CSS;
    head.prepend(mk({ charset: 'utf-8' }), mk({ 'http-equiv': 'Content-Security-Policy', content: CSP }),
      mk({ name: 'inert-profile', content: PROFILE }), mk({ name: 'generator', content: 'inerthtml-web 0.1.0' }), style);

    const out = '<!DOCTYPE html>\n' + doc.documentElement.outerHTML;
    return { html: out, stats, problems: verify(out) };
  }

  /* A CSP to prepend when previewing an untrusted file in a sandboxed iframe. */
  const PREVIEW_GUARD = `<meta http-equiv="Content-Security-Policy" content="${CSP}">`;

  root.Inert = { verify, sanitize, CSP, PROFILE, PREVIEW_GUARD };
})(typeof window !== 'undefined' ? window : globalThis);
