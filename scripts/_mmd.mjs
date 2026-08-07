import { readFileSync, writeFileSync } from 'node:fs'
import { chromium } from 'playwright'
const md = readFileSync('../README.md', 'utf8')
const code = md.slice(md.indexOf('```mermaid') + 10, md.indexOf('```', md.indexOf('classDef optional'))).trim()
const b = await chromium.launch()
const p = await b.newPage({ viewport: { width: 1200, height: 700 }, deviceScaleFactor: 2 })
await p.setContent(`<html><body style="margin:0;background:#fff"><div id="d"></div>
<script type="module">
import m from 'file://${process.cwd()}/node_modules/mermaid/dist/mermaid.esm.mjs';
m.initialize({startOnLoad:false});
try { const {svg} = await m.render('g', ${JSON.stringify(code)}); document.getElementById('d').innerHTML = svg; window.__ok = true }
catch(e){ document.getElementById('d').textContent = 'MERMAID ERROR: '+e.message; window.__ok = false }
</script></body></html>`, { waitUntil: 'networkidle' })
await p.waitForTimeout(2500)
const ok = await p.evaluate(() => window.__ok)
const txt = await p.textContent('#d')
console.log('render ok:', ok)
if (!ok) console.log(txt.slice(0, 300))
else { await p.locator('#d svg').screenshot({ path: '../docs/screenshots/_mermaid-check.png' }); console.log('screenshot written') }
await b.close()
