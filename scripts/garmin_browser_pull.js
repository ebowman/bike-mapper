// garmin_browser_pull.js — in-page helpers for pulling Eric's own activity
// history out of an already-authenticated Garmin Connect tab.
//
// Invocation (chrome-devtools MCP, page must be a connect.garmin.com tab):
//   1. evaluate_script pageId=<n> sourcePath=scripts/garmin_browser_pull.js
//        -> installs window.gcPull and returns "installed"
//   2. evaluate_script function="async () => gcPull.listPages(0, 10)"
//        filePath=data/rides/_batches/list_000.json  (repeat with firstPage=10,20,.. (a page index, 10 pages per call) until done:true)
//   3. evaluate_script function="async () => gcPull.downloadBatch([id1,id2,...])"
//        filePath=data/rides/_batches/batch_000.json  (10 ids per call)
//   4. uv run scripts/rides_unpack.py   -> data/rides/<id>.fit + data/rides/index.json
//
// All requests go through the page's own fetch() with credentials:'include'
// and the page's CSRF meta tag, so no cookie or token ever leaves the browser.
// Rate limit: >= 1 s between requests; 30 s back-off (x3) on HTTP 429.
async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const csrf = () => document.querySelector('meta[name="csrf-token"]').content;
  const SPACING_MS = 1000;
  const BACKOFF_MS = 30000;

  async function gcFetch(url) {
    for (let attempt = 0; attempt < 4; attempt++) {
      const r = await fetch(url, {
        credentials: 'include',
        headers: { 'connect-csrf-token': csrf() },
      });
      if (r.status === 429) { await sleep(BACKOFF_MS); continue; }
      return r;
    }
    return new Response(null, { status: 429 });
  }

  // One page of the cycling activity list (newest first).
  async function listPage(start, limit = 100) {
    const r = await gcFetch(
      `/gc-api/activitylist-service/activities/search/activities?start=${start}&limit=${limit}&activityType=cycling`);
    if (!r.ok) throw new Error(`list ${start}: HTTP ${r.status}`);
    return r.json();
  }

  // Several consecutive pages; returns {pages:[{start, activities:[...]}], done}
  async function listPages(firstPage, nPages, limit = 100) {
    const pages = [];
    let done = false;
    for (let p = firstPage; p < firstPage + nPages; p++) {
      const start = p * limit;
      const acts = await listPage(start, limit);
      pages.push({ start, count: acts.length, activities: acts });
      if (acts.length < limit) { done = true; break; }
      await sleep(SPACING_MS);
    }
    return { pages, done };
  }

  function bufToB64(buf) {
    const bytes = new Uint8Array(buf);
    let s = '';
    const CH = 0x8000;
    for (let i = 0; i < bytes.length; i += CH) {
      s += String.fromCharCode.apply(null, bytes.subarray(i, i + CH));
    }
    return btoa(s);
  }

  // Original uploaded file (zip containing <id>_ACTIVITY.fit) for each id.
  async function downloadBatch(ids) {
    const out = [];
    for (const id of ids) {
      const t0 = Date.now();
      try {
        const r = await gcFetch(`/gc-api/download-service/files/activity/${id}`);
        if (!r.ok) {
          out.push({ id, status: r.status, ok: false });
        } else {
          const buf = await r.arrayBuffer();
          out.push({ id, status: r.status, ok: true,
                     contentType: r.headers.get('content-type'),
                     bytes: buf.byteLength, b64: bufToB64(buf) });
        }
      } catch (e) {
        out.push({ id, ok: false, error: String(e) });
      }
      const dt = Date.now() - t0;
      if (dt < SPACING_MS) await sleep(SPACING_MS - dt);
    }
    return out;
  }

  window.gcPull = { listPage, listPages, downloadBatch };
  return 'installed';
}
