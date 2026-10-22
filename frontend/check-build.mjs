// Post-build sanity checks: bundle exists, nothing loads from a CDN, index.html is a script-free shell.
import { readFileSync, statSync } from 'node:fs';

const fail = (msg) => { console.error(`check-build: ${msg}`); process.exit(1); };
const html = readFileSync('index.html', 'utf8');
const js = readFileSync('static/app.js', 'utf8');
const css = readFileSync('static/app.css', 'utf8');

if (statSync('static/app.js').size < 100_000) fail('static/app.js is suspiciously small');
if (statSync('static/app.css').size < 5_000) fail('static/app.css is suspiciously small');
for (const host of ['unpkg.com', 'cdn.jsdelivr.net', 'cdnjs.cloudflare.com', 'cdn.tailwindcss.com']) {
  if (html.includes(host)) fail(`index.html references ${host}`);
  if (js.includes(`//${host}`)) fail(`static/app.js references ${host}`);
}
if (/<script(?![^>]*\bsrc=)[^>]*>/i.test(html)) fail('index.html contains an inline <script>');
if (html.includes('text/babel')) fail('index.html still uses in-browser Babel');
if (!css.includes('.apogee-card')) fail('static/app.css is missing app styles');
console.log(`check-build: ok (app.js ${statSync('static/app.js').size} B, app.css ${statSync('static/app.css').size} B)`);
