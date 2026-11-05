// Renders the NSIS installer artwork (sidebar 328x628, header 300x114 — 2x for high-DPI).
// Usage: node scripts/render-installer-art.js  (needs Playwright), then convert the PNGs to 24-bit BMP:
//   python -c "from PIL import Image; [Image.open(f\"app/src-tauri/installer/{n}.png\").convert(\"RGB\").save(f\"app/src-tauri/installer/{n}.bmp\") for n in (\"sidebar\",\"header\")]"
const { chromium } = require('playwright');
const fs = require('fs');
const svg = fs.readFileSync(require('path').join(__dirname, '../branding/moth-emblem.svg'), 'utf8').replace('<svg', '<svg width="100%" height="100%"');
const font = `font-family: 'Inter', 'Segoe UI', sans-serif;`;
const sidebar = (w, h) => `
<div style="width:${w}px;height:${h}px;position:relative;overflow:hidden;background:#080808;${font}">
  <div style="position:absolute;inset:0;background:radial-gradient(circle at 50% 30%, rgba(193,18,31,0.38) 0%, rgba(193,18,31,0.10) 32%, transparent 58%)"></div>
  <svg style="position:absolute;inset:0" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">
    <g stroke="#5a0810" stroke-width="2" fill="none" opacity="0.9">
      <path d="M0 ${h-96} H64 L88 ${h-72} H150"/><circle cx="150" cy="${h-72}" r="3.5" fill="#5a0810"/>
      <path d="M0 ${h-52} H96 L114 ${h-34} H170"/><circle cx="170" cy="${h-34}" r="3.5" fill="#5a0810"/>
      <path d="M${w} ${h-106} H${w-52} L${w-74} ${h-84} H${w-128}"/><circle cx="${w-128}" cy="${h-84}" r="3.5" fill="#5a0810"/>
    </g>
  </svg>
  <div style="position:absolute;left:${(w-236)/2}px;top:70px;width:236px;height:236px;filter:drop-shadow(0 0 22px rgba(193,18,31,0.55))">${svg}</div>
  <div style="position:absolute;top:322px;width:100%;text-align:center;color:#fff;font-weight:700;font-size:46px;letter-spacing:18px;padding-left:18px">MOTH</div>
  <div style="position:absolute;top:378px;width:100%;text-align:center;color:#9a9a9a;font-weight:300;font-size:21px;letter-spacing:14px;padding-left:14px">CODE</div>
  <div style="position:absolute;top:426px;left:${w/2-40}px;width:80px;height:2px;background:#C1121F;box-shadow:0 0 12px #C1121F"></div>
  <div style="position:absolute;top:446px;width:100%;text-align:center;color:#8a8a8a;font-size:15px;letter-spacing:0.5px;line-height:23px">Independent AI coding agent<br/>trained from scratch</div>
</div>`;
const header = (w, h) => `
<div style="width:${w}px;height:${h}px;position:relative;overflow:hidden;background:#080808;${font}">
  <div style="position:absolute;inset:0;background:radial-gradient(circle at 78% 50%, rgba(193,18,31,0.35) 0%, transparent 55%)"></div>
  <div style="position:absolute;right:58px;top:${(h-96)/2}px;width:96px;height:96px;filter:drop-shadow(0 0 10px rgba(193,18,31,0.6))">${svg}</div>
  <div style="position:absolute;right:12px;bottom:8px;width:2px;height:${h-16}px;background:linear-gradient(#C1121F, transparent)"></div>
</div>`;
(async () => {
  const b = await chromium.launch();
  for (const [name, w, h, fn] of [['sidebar', 328, 628, sidebar], ['header', 300, 114, header]]) {
    const p = await b.newPage({ viewport: { width: w, height: h }, deviceScaleFactor: 1 });
    await p.setContent(`<html><body style="margin:0">${fn(w, h)}</body></html>`);
    await p.screenshot({ path: require('path').join(__dirname, `../app/src-tauri/installer/${name}.png`) });
  }
  await b.close();
})();
