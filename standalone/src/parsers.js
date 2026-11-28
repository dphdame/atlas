// ============================================================================
// ATLAS Standalone Browser Engine — Crypto (SHA-256), ZIP, and File Parsers
// 100% Pure JavaScript, Zero External CDN Dependencies, Exact Python v1.2 Parity
// ============================================================================

const SOFTWARE_TEST_BANNER = "[SOFTWARE_TEST FIXTURE — DEMONSTRATES SOFTWARE MECHANICS ONLY, NOT EMPIRICAL FINDINGS]";
const NOTES_THEMES_SPEAKER = "NoteTaker_Themes";
const DEFAULT_NOTES_EVIDENCE_TYPES = ["key_point_paraphrase", "notable_quote_verbatim"];
const WITH_OBS_NOTES_EVIDENCE_TYPES = ["key_point_paraphrase", "notable_quote_verbatim", "observation"];
const TABULAR_EXTENSIONS = new Set([".csv", ".xlsx"]);
const TRANSCRIPT_EXTENSIONS = new Set([".docx", ".vtt", ".srt", ".txt", ".md"]);

// ----------------------------------------------------------------------------
// 1. Pure-JS FIPS 180-4 SHA-256 (works identically on file:// and https://)
// ----------------------------------------------------------------------------
const SHA256_K = new Uint32Array([
  0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
  0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
  0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
  0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
  0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
  0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
  0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
  0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2
]);

function sha256Bytes(input) {
  const bytes = input instanceof Uint8Array ? input : new TextEncoder().encode(String(input));
  const len = bytes.length;
  const bitLenHi = Math.floor((len * 8) / 0x100000000);
  const bitLenLo = (len * 8) >>> 0;
  const paddedLen = ((len + 9 + 63) >> 6) << 6;
  const padded = new Uint8Array(paddedLen);
  padded.set(bytes);
  padded[len] = 0x80;
  const dv = new DataView(padded.buffer);
  dv.setUint32(paddedLen - 8, bitLenHi, false);
  dv.setUint32(paddedLen - 4, bitLenLo, false);

  let h0 = 0x6a09e667, h1 = 0xbb67ae85, h2 = 0x3c6ef372, h3 = 0xa54ff53a;
  let h4 = 0x510e527f, h5 = 0x9b05688c, h6 = 0x1f83d9ab, h7 = 0x5be0cd19;
  const w = new Uint32Array(64);

  for (let off = 0; off < paddedLen; off += 64) {
    for (let i = 0; i < 16; i++) w[i] = dv.getUint32(off + i * 4, false);
    for (let i = 16; i < 64; i++) {
      const s0 = ((w[i-15] >>> 7) | (w[i-15] << 25)) ^ ((w[i-15] >>> 18) | (w[i-15] << 14)) ^ (w[i-15] >>> 3);
      const s1 = ((w[i-2] >>> 17) | (w[i-2] << 15)) ^ ((w[i-2] >>> 19) | (w[i-2] << 13)) ^ (w[i-2] >>> 10);
      w[i] = (w[i-16] + s0 + w[i-7] + s1) >>> 0;
    }
    let a = h0, b = h1, c = h2, d = h3, e = h4, f = h5, g = h6, h = h7;
    for (let i = 0; i < 64; i++) {
      const S1 = ((e >>> 6) | (e << 26)) ^ ((e >>> 11) | (e << 21)) ^ ((e >>> 25) | (e << 7));
      const ch = (e & f) ^ ((~e) & g);
      const t1 = (h + S1 + ch + SHA256_K[i] + w[i]) >>> 0;
      const S0 = ((a >>> 2) | (a << 30)) ^ ((a >>> 13) | (a << 19)) ^ ((a >>> 22) | (a << 10));
      const maj = (a & b) ^ (a & c) ^ (b & c);
      const t2 = (S0 + maj) >>> 0;
      h = g; g = f; f = e; e = (d + t1) >>> 0;
      d = c; c = b; b = a; a = (t1 + t2) >>> 0;
    }
    h0 = (h0 + a) >>> 0; h1 = (h1 + b) >>> 0; h2 = (h2 + c) >>> 0; h3 = (h3 + d) >>> 0;
    h4 = (h4 + e) >>> 0; h5 = (h5 + f) >>> 0; h6 = (h6 + g) >>> 0; h7 = (h7 + h) >>> 0;
  }
  return [h0, h1, h2, h3, h4, h5, h6, h7].map(x => x.toString(16).padStart(8, "0")).join("");
}

// ----------------------------------------------------------------------------
// 2. Native Browser ZIP Reader & Writer (Zero External Dependencies)
// ----------------------------------------------------------------------------
const CRC32_TABLE = (() => {
  const tbl = new Uint32Array(256);
  for (let i = 0; i < 256; i++) {
    let c = i;
    for (let j = 0; j < 8; j++) c = (c & 1) ? (0xedb88320 ^ (c >>> 1)) : (c >>> 1);
    tbl[i] = c >>> 0;
  }
  return tbl;
})();

function crc32(bytes) {
  let c = 0xffffffff;
  for (let i = 0; i < bytes.length; i++) c = CRC32_TABLE[(c ^ bytes[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

async function inflateRaw(compBytes) {
  const ds = new DecompressionStream("deflate-raw");
  const writer = ds.writable.getWriter();
  writer.write(compBytes);
  writer.close();
  const buf = await new Response(ds.readable).arrayBuffer();
  return new Uint8Array(buf);
}

async function deflateRaw(rawBytes) {
  const cs = new CompressionStream("deflate-raw");
  const writer = cs.writable.getWriter();
  writer.write(rawBytes);
  writer.close();
  const buf = await new Response(cs.readable).arrayBuffer();
  return new Uint8Array(buf);
}

async function readZipEntries(arrayBuffer) {
  const bytes = arrayBuffer instanceof Uint8Array ? arrayBuffer : new Uint8Array(arrayBuffer);
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let eocd = -1;
  const minPos = Math.max(0, bytes.length - 65557);
  for (let i = bytes.length - 22; i >= minPos; i--) {
    if (view.getUint32(i, true) === 0x06054b50) { eocd = i; break; }
  }
  if (eocd < 0) throw new Error("Invalid ZIP/OOXML file (missing end-of-central-directory).");
  const totalEntries = view.getUint16(eocd + 10, true);
  let cdOffset = view.getUint32(eocd + 16, true);
  const decoder = new TextDecoder("utf-8");
  const entries = new Map();

  for (let i = 0; i < totalEntries; i++) {
    if (view.getUint32(cdOffset, true) !== 0x02014b50) break;
    const method = view.getUint16(cdOffset + 10, true);
    const compSize = view.getUint32(cdOffset + 20, true);
    const nameLen = view.getUint16(cdOffset + 28, true);
    const extraLen = view.getUint16(cdOffset + 30, true);
    const commentLen = view.getUint16(cdOffset + 32, true);
    const localHdrOffset = view.getUint32(cdOffset + 42, true);
    const name = decoder.decode(bytes.subarray(cdOffset + 46, cdOffset + 46 + nameLen));

    const localNameLen = view.getUint16(localHdrOffset + 26, true);
    const localExtraLen = view.getUint16(localHdrOffset + 28, true);
    const dataStart = localHdrOffset + 30 + localNameLen + localExtraLen;
    const compData = bytes.subarray(dataStart, dataStart + compSize);
    const data = method === 8 ? await inflateRaw(compData) : compData;
    entries.set(name, data);
    cdOffset += 46 + nameLen + extraLen + commentLen;
  }
  return entries;
}

async function writeZipArchive(entriesMap, mimeType) {
  const encoder = new TextEncoder();
  const localParts = [];
  const cdParts = [];
  let offset = 0;

  for (const [name, rawData] of entriesMap.entries()) {
    const nameBytes = encoder.encode(name);
    const dataBytes = rawData instanceof Uint8Array ? rawData : encoder.encode(String(rawData));
    const crc = crc32(dataBytes);
    const compBytes = await deflateRaw(dataBytes);

    const localHdr = new Uint8Array(30 + nameBytes.length);
    const lv = new DataView(localHdr.buffer);
    lv.setUint32(0, 0x04034b50, true);
    lv.setUint16(4, 20, true);
    lv.setUint16(8, 8, true);
    lv.setUint32(14, crc, true);
    lv.setUint32(18, compBytes.length, true);
    lv.setUint32(22, dataBytes.length, true);
    lv.setUint16(26, nameBytes.length, true);
    localHdr.set(nameBytes, 30);

    const cdHdr = new Uint8Array(46 + nameBytes.length);
    const cv = new DataView(cdHdr.buffer);
    cv.setUint32(0, 0x02014b50, true);
    cv.setUint16(4, 20, true);
    cv.setUint16(6, 20, true);
    cv.setUint16(10, 8, true);
    cv.setUint32(16, crc, true);
    cv.setUint32(20, compBytes.length, true);
    cv.setUint32(24, dataBytes.length, true);
    cv.setUint16(28, nameBytes.length, true);
    cv.setUint32(42, offset, true);
    cdHdr.set(nameBytes, 46);

    localParts.push(localHdr, compBytes);
    cdParts.push(cdHdr);
    offset += localHdr.length + compBytes.length;
  }

  const cdSize = cdParts.reduce((a, p) => a + p.length, 0);
  const eocd = new Uint8Array(22);
  const ev = new DataView(eocd.buffer);
  ev.setUint32(0, 0x06054b50, true);
  ev.setUint16(8, entriesMap.size, true);
  ev.setUint16(10, entriesMap.size, true);
  ev.setUint32(12, cdSize, true);
  ev.setUint32(16, offset, true);

  return new Blob([...localParts, ...cdParts, eocd], { type: mimeType || "application/zip" });
}

function base64ToUint8Array(b64) {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

// ----------------------------------------------------------------------------
// 3. Minimal Safe YAML Parser (supports ATLAS domain / topic / theme codebooks)
// ----------------------------------------------------------------------------
function parseScalarYaml(raw) {
  const s = raw.trim();
  if (!s || s === "null" || s === "~") return null;
  if (s === "true" || s === "True") return true;
  if (s === "false" || s === "False") return false;
  if ((s.startsWith('"') && s.endsWith('"')) || (s.startsWith("'") && s.endsWith("'"))) {
    const q = s[0];
    const inner = s.slice(1, -1);
    return q === '"' ? inner.replace(/\\"/g, '"').replace(/\\n/g, "\n").replace(/\\\\/g, "\\")
                     : inner.replace(/''/g, "'");
  }
  if (/^-?\d+$/.test(s)) return parseInt(s, 10);
  if (/^-?\d+\.\d+$/.test(s)) return parseFloat(s);
  if (s.startsWith("[") && s.endsWith("]")) {
    const inside = s.slice(1, -1).trim();
    if (!inside) return [];
    const items = [];
    let cur = "", inQ = null;
    for (let i = 0; i < inside.length; i++) {
      const ch = inside[i];
      if (inQ) {
        if (ch === "\\" && inQ === '"' && i + 1 < inside.length) { cur += ch + inside[++i]; continue; }
        if (ch === inQ) inQ = null;
        cur += ch;
      } else if (ch === '"' || ch === "'") {
        inQ = ch; cur += ch;
      } else if (ch === ",") {
        items.push(parseScalarYaml(cur)); cur = "";
      } else {
        cur += ch;
      }
    }
    if (cur.trim()) items.push(parseScalarYaml(cur));
    return items;
  }
  return s;
}

function stripYamlComment(line) {
  let inQ = null;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (inQ) {
      if (ch === "\\" && inQ === '"') { i++; continue; }
      if (ch === inQ) inQ = null;
    } else if (ch === '"' || ch === "'") {
      inQ = ch;
    } else if (ch === "#" && (i === 0 || /\s/.test(line[i - 1]))) {
      return line.slice(0, i);
    }
  }
  return line;
}

function parseSimpleYaml(text) {
  const trimmed = String(text || "").trim();
  if (!trimmed) return {};
  if (trimmed.startsWith("{")) return JSON.parse(trimmed);

  const lines = trimmed.replace(/\r\n/g, "\n").replace(/\r/g, "\n").split("\n")
    .map(stripYamlComment)
    .map(ln => ln.replace(/\s+$/, ""))
    .filter(ln => ln.trim().length > 0 && !/^---\s*$/.test(ln.trim()));

  let idx = 0;
  function indentOf(ln) { return ln.match(/^ */)[0].length; }

  function parseChildOfKey(keyIndent) {
    if (idx >= lines.length) return null;
    const first = lines[idx];
    const ind = indentOf(first);
    const stripped = first.slice(ind);
    if ((stripped.startsWith("- ") || stripped === "-") && ind >= keyIndent) {
      return parseList(ind);
    }
    if (ind > keyIndent) {
      return parseMap(ind);
    }
    return null;
  }

  function parseBlock(minIndent) {
    if (idx >= lines.length) return null;
    const first = lines[idx];
    const ind = indentOf(first);
    if (ind < minIndent) return null;
    const stripped = first.slice(ind);
    if (stripped.startsWith("- ") || stripped === "-") {
      return parseList(ind);
    }
    return parseMap(ind);
  }

  function parseList(baseIndent) {
    const arr = [];
    while (idx < lines.length) {
      const ln = lines[idx];
      const ind = indentOf(ln);
      if (ind < baseIndent) break;
      if (ind > baseIndent) break;
      const body = ln.slice(ind);
      if (!(body.startsWith("- ") || body === "-")) break;
      const rest = body.length > 1 ? body.slice(2).trim() : "";
      idx++;
      if (!rest) {
        arr.push(parseBlock(baseIndent + 1));
      } else {
        const kv = splitKeyVal(rest);
        if (kv) {
          const obj = {};
          if (kv.val === "") {
            const child = parseChildOfKey(baseIndent + 2);
            obj[kv.key] = child === null ? [] : child;
          } else {
            obj[kv.key] = parseScalarYaml(kv.val);
          }
          // Merge subsequent indented mapping keys belonging to this list item
          while (idx < lines.length) {
            const nxt = lines[idx];
            const nInd = indentOf(nxt);
            if (nInd <= baseIndent) break;
            const nBody = nxt.slice(nInd);
            if (nBody.startsWith("- ") || nBody === "-") break;
            const nKv = splitKeyVal(nBody);
            if (!nKv) break;
            idx++;
            if (nKv.val === "") {
              const child = parseChildOfKey(nInd);
              obj[nKv.key] = child === null ? [] : child;
            } else {
              obj[nKv.key] = parseScalarYaml(nKv.val);
            }
          }
          arr.push(obj);
        } else {
          arr.push(parseScalarYaml(rest));
        }
      }
    }
    return arr;
  }

  function splitKeyVal(str) {
    let inQ = null;
    for (let i = 0; i < str.length; i++) {
      const ch = str[i];
      if (inQ) {
        if (ch === "\\" && inQ === '"') { i++; continue; }
        if (ch === inQ) inQ = null;
      } else if (ch === '"' || ch === "'") {
        inQ = ch;
      } else if (ch === ":" && (i + 1 === str.length || /\s/.test(str[i + 1]))) {
        const rawKey = str.slice(0, i).trim();
        const key = String(parseScalarYaml(rawKey));
        const val = str.slice(i + 1).trim();
        return { key, val };
      }
    }
    return null;
  }

  function parseMap(baseIndent) {
    const obj = {};
    while (idx < lines.length) {
      const ln = lines[idx];
      const ind = indentOf(ln);
      if (ind < baseIndent) break;
      if (ind > baseIndent) { idx++; continue; }
      const body = ln.slice(ind);
      if (body.startsWith("- ") || body === "-") break;
      const kv = splitKeyVal(body);
      if (!kv) { idx++; continue; }
      idx++;
      if (kv.val === "" || kv.val === ">" || kv.val === "|") {
        if (kv.val === ">" || kv.val === "|") {
          const blockLines = [];
          while (idx < lines.length && indentOf(lines[idx]) > baseIndent) {
            blockLines.push(lines[idx].trim());
            idx++;
          }
          obj[kv.key] = blockLines.join(kv.val === ">" ? " " : "\n");
        } else {
          const nextVal = parseChildOfKey(baseIndent);
          obj[kv.key] = nextVal === null ? [] : nextVal;
        }
      } else {
        obj[kv.key] = parseScalarYaml(kv.val);
      }
    }
    return obj;
  }

  return parseBlock(0) || {};
}

// ----------------------------------------------------------------------------
// 4. Structured Notes (.docx), Transcript (.docx/.txt/.vtt), CSV & XLSX Parsers
// ----------------------------------------------------------------------------
const NOTES_COLUMN_ROLES = {
  "key point": "key_points", "key points": "key_points",
  "notable quote": "notable_quotes", "notable quotes": "notable_quotes",
  "observation": "observations", "observations": "observations",
};
const NOTES_HEADER_SCAN_ROWS = 3;
const RE_NOTES_PARTICIPANT = /^(?:[-•*–—]\s*)?(P\d+)\s*:\s*([\s\S]*)$/i;
const RE_NOTES_THEMES = /^\s*themes(?:\s*\/\s*topics)?(?:\s*\/\s*patterns)?\s*(?::[ \t]*|(?=\n|$))/i;
const RE_NOTES_QUESTION = /^(?:question\s*|q\s*(?=\d+\s*[:.)\-]))(\d+)\b\s*[:.)\-]?\s*([\s\S]*)$/i;
const RE_NOTES_EMBEDDED_QUESTION = /^question\s*\d+\s*(?:[:.)\-]|$)/i;
const RE_NOTES_EMBEDDED_Q_SHORT = /^q\s*\d+\s*[:.)\-]/i;
const RE_NOTES_PROMPT = /^(?:follow[\s-]*ups?|probes?)\s*:/i;
const RE_NOTES_FACILITATOR_PROMPT = /^(?:facilitator|moderator|interviewer|prompt)\s*:/i;
const RE_NOTES_CONSENT = new RegExp(
  "^consent(?:\\s+(?:statement|script|forms?))?(?:\\s*\\([^)]*\\))?\\s*(?:$|:)|" +
  "^consent\\s+(?:statement|script)\\s+(?:(?:was|were)\\s+)?(?:read|reviewed|given|delivered|presented|shared|recited|" +
  "completed|confirmed|signed|received)(?:\\s+(?:again|aloud|to\\s+all|by\\s+all(?:\\s+participants)?))*" +
  "(?:\\s+(?:before|after)\\s+the\\s+(?:paperwork|intake|enrollment|session|interview|discussion|questions?)" +
  "(?:\\s+(?:break|questions?|discussion|session|portion|section))?)?\\s*\\.?$|" +
  "^consent\\s+forms?\\s+(?:(?:was|were)\\s+)?(?:reviewed|read|signed|received|collected|obtained|completed|confirmed)" +
  "(?:\\s+(?:and\\s+(?:reviewed|read|signed|received|collected|obtained|completed|confirmed)|by\\s+all(?:\\s+participants)?))?" +
  "(?:\\s+(?:before|after)\\s+the\\s+(?:paperwork|intake|enrollment|session|interview|discussion|questions?)" +
  "(?:\\s+(?:break|questions?|discussion|session|portion|section))?)?\\s*\\.?$",
  "i"
);
const RE_NOTES_SUMMARY_LABEL = /^(summary\s+of\s+session(?:\s*\([^)]*\))?|main\s+observations(?:\s*\([^)]*\))?(?:\s+ideas)?)\s*(?::\s*(.*)|$)/i;
const RE_TEAMS_HEADER = /^(?:.*-)?Meeting Recording$/;
const RE_VTT_TIMECODE = /^(\d{1,2}:\d{2}(?::\d{2})?(?:[,.]\d{3})?)\s+-->\s+/;
const RE_DOCX_SPEAKER_TS = /^([^\W\d_][\w\u0300-\u036f .\-'\u2019&#]*?) +(\d{1,2}:\d{2}(?::\d{2})?)$/u;
const RE_DOCX_SPEAKER_COLON = /^([^\W\d_][\w\u0300-\u036f .\-'\u2019&#]*?):\s*([\s\S]*)$/u;
const RE_DOCX_TS_SPEAKER_COLON = /^(\d{1,2}:\d{2}(?::\d{2})?) +([^\W\d_][\w\u0300-\u036f .\-'\u2019&#]*?):\s*([\s\S]*)$/u;

const DEFAULT_FACILITATORS = new Set([
  "facilitator", "moderator", "interviewer", "host", "researcher",
  "entrevistador", "entrevistadora", "moderador", "moderadora", "facilitador", "facilitadora"
]);
const SINGLE_WORD_NON_SPEAKERS = new Set([
  "is","are","was","were","am","be","been","being","has","have","had","do","does","did","would","can","could","should","might","must","need","needs","said","says","asked",
  "es","son","fue","era","está","están","tiene","hay",
  "note","notes","summary","example","examples","warning","caution","important","tip","question","answer","date","time","location","topic","subject","title","background","conclusion","context","agenda","action","status","source","reference","result","results","problem","issue","concern","reason","goal","first","second","third","http","https","url","uri","ftp","todo","fixme","mailto","tel","urn","data","file","sms","geo","cid","mid","sip","sips","ssh","git"
]);

function isBanner(text) {
  const s = String(text || "").trim();
  return s === SOFTWARE_TEST_BANNER || s.startsWith("[SOFTWARE_TEST");
}

function joinLines(text) {
  return String(text || "").split(/\r?\n/).map(p => p.trim()).filter(Boolean).join(" ");
}

function boxLines(text) {
  return String(text || "").split(/\r?\n/).map(p => p.trim()).filter(Boolean);
}

function normalizeHeaderCell(text) {
  return joinLines(text).toLowerCase().replace(/[:\-]+$/, "").replace(/\s+/g, " ").trim();
}

function notesColumns(rows) {
  const limit = Math.min(rows.length, NOTES_HEADER_SCAN_ROWS);
  for (let rIdx = 0; rIdx < limit; rIdx++) {
    const cells = rows[rIdx];
    const cols = { key_points: [], notable_quotes: [], observations: [] };
    for (let cIdx = 0; cIdx < cells.length; cIdx++) {
      const role = NOTES_COLUMN_ROLES[normalizeHeaderCell(cells[cIdx])];
      if (role) cols[role].push(cIdx);
    }
    if (cols.key_points.length && cols.notable_quotes.length) {
      return { headerIdx: rIdx, cols };
    }
  }
  return null;
}

function participantSegments(cellText) {
  const lines = String(cellText || "").split(/\r?\n/).map(l => l.trim()).filter(Boolean);
  if (!lines.length) return [];
  const segs = [];
  let curPid = null, curParts = [];
  for (const ln of lines) {
    const m = RE_NOTES_PARTICIPANT.exec(ln);
    if (m) {
      if (curParts.length || curPid !== null) {
        segs.push([curPid, curParts.join(" ").trim()]);
      }
      curPid = m[1].toUpperCase();
      curParts = m[2].trim() ? [m[2].trim()] : [];
    } else {
      curParts.push(ln);
    }
  }
  if (curParts.length || curPid !== null) {
    segs.push([curPid, curParts.join(" ").trim()]);
  }
  return segs.filter(([pid, txt]) => pid !== null || txt.length > 0);
}

function metadataKey(label) {
  const norm = normalizeHeaderCell(label).replace(/\([^)]*\)/g, "").replace(/\s+/g, " ").trim();
  if (!norm) return "";
  if (norm.startsWith("summary of session")) return "summary_of_session";
  if (norm.startsWith("main observations")) return "main_observations";
  return norm.replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
}

function extractParagraphText(pEl) {
  let out = "";
  const walker = pEl.ownerDocument.createTreeWalker(pEl, NodeFilter.SHOW_ELEMENT);
  let node = walker.nextNode();
  while (node) {
    const ln = node.localName;
    if (ln === "t") out += node.textContent || "";
    else if (ln === "tab") out += "\t";
    else if (ln === "br" || ln === "cr") out += "\n";
    node = walker.nextNode();
  }
  return out;
}

function extractCellText(tcEl) {
  const paras = [];
  for (const child of Array.from(tcEl.childNodes)) {
    if (child.nodeType === 1 && child.localName === "p") {
      paras.push(extractParagraphText(child));
    }
  }
  return paras.join("\n").trim();
}

function extractDocxBlocks(xmlDoc) {
  const body = xmlDoc.getElementsByTagNameNS("*", "body")[0];
  if (!body) return [];
  const blocks = [];
  for (const child of Array.from(body.childNodes)) {
    if (child.nodeType !== 1) continue;
    if (child.localName === "p") {
      blocks.push({ para: extractParagraphText(child), rows: null, continued: null });
    } else if (child.localName === "tbl") {
      const trEls = Array.from(child.childNodes).filter(n => n.nodeType === 1 && n.localName === "tr");
      const rows = [];
      const continued = [];
      const prevRowText = [];
      for (const tr of trEls) {
        const rowCells = [];
        const rowCont = new Set();
        let colIdx = 0;
        const tcEls = Array.from(tr.childNodes).filter(n => n.nodeType === 1 && n.localName === "tc");
        for (const tc of tcEls) {
          const tcPr = Array.from(tc.childNodes).find(n => n.nodeType === 1 && n.localName === "tcPr");
          let gridSpan = 1;
          let vMerge = null;
          if (tcPr) {
            const gsEl = Array.from(tcPr.childNodes).find(n => n.nodeType === 1 && n.localName === "gridSpan");
            if (gsEl) {
              const v = parseInt(gsEl.getAttribute("w:val") || gsEl.getAttribute("val") || "1", 10);
              if (Number.isFinite(v) && v > 1) gridSpan = v;
            }
            const vmEl = Array.from(tcPr.childNodes).find(n => n.nodeType === 1 && n.localName === "vMerge");
            if (vmEl) {
              const v = (vmEl.getAttribute("w:val") || vmEl.getAttribute("val") || "continue").toLowerCase();
              vMerge = v === "restart" ? "restart" : "continue";
            }
          }
          const cellText = extractCellText(tc);
          for (let s = 0; s < gridSpan; s++) {
            const isHorizDup = s > 0;
            if (vMerge === "continue") {
              rowCells.push(prevRowText[colIdx] || "");
              rowCont.add(colIdx);
            } else {
              rowCells.push(cellText);
              prevRowText[colIdx] = cellText;
              if (isHorizDup) rowCont.add(colIdx);
            }
            colIdx++;
          }
        }
        rows.push(rowCells);
        continued.push(rowCont);
      }
      blocks.push({ para: "", rows, continued });
    }
  }
  return blocks;
}

function isStructuredNotesBlocks(blocks) {
  return blocks.some(b => b.rows !== null && notesColumns(b.rows) !== null);
}

function parseStructuredNotesBlocks(blocks, fileName, sourceId, includeEvidenceTypes) {
  const includeSet = new Set(includeEvidenceTypes || DEFAULT_NOTES_EVIDENCE_TYPES);
  const metadata = {};
  const questions = {};
  const entries = [];
  const excludedStructuralRows = [];
  const themeEntries = [];
  const pending = { question_id: null, prompt: [] };
  let notesTables = 0;
  let location = 0;

  function recordExcluded(loc, reason, text) {
    const clean = joinLines(text);
    if (clean) excludedStructuralRows.push({ location: loc, reason, text: clean });
  }

  function noteQuestion(text, loc) {
    const m = RE_NOTES_QUESTION.exec(String(text || "").trim());
    if (!m) return false;
    pending.question_id = `Question ${parseInt(m[1], 10)}`;
    pending.prompt = boxLines(m[2]);
    if (loc != null) recordExcluded(loc, "question_heading", text);
    return true;
  }

  function setMetadata(label, value) {
    const k = metadataKey(label);
    if (k && !metadata[k]) metadata[k] = String(value || "").trim();
  }

  function readBox(lines) {
    const colonIdx = lines[0].indexOf(":");
    if (colonIdx < 0) return false;
    const label = lines[0].slice(0, colonIdx);
    const rest = lines[0].slice(colonIdx + 1).trim();
    const k = metadataKey(label);
    if (!k) return false;
    setMetadata(label, (rest ? [rest] : []).concat(lines.slice(1)).join("\n"));
    return true;
  }

  function readMetadataTable(rows) {
    const maxLen = rows.reduce((m, r) => Math.max(m, r.length), 0);
    if (maxLen === 1) {
      const lines = rows.flatMap(r => r[0] ? boxLines(r[0]) : []);
      if (lines.length && !noteQuestion(lines[0], null)) readBox(lines);
      return;
    }
    for (const cells of rows) {
      let col = 0;
      while (col < cells.length) {
        const text = cells[col];
        if (text.endsWith(":")) {
          const val = (col + 1 < cells.length && !cells[col + 1].endsWith(":")) ? cells[col + 1] : "";
          setMetadata(text, boxLines(val).join("\n"));
          col += val ? 2 : 1;
          continue;
        }
        const ci = text.indexOf(":");
        if (ci > 0) {
          const lbl = text.slice(0, ci), rest = text.slice(ci + 1).trim();
          if (rest && lbl.trim().split(/\s+/).length <= 6) setMetadata(lbl, rest);
        }
        col++;
      }
    }
  }

  function structuralRow(rowBlock, cells, cont, cols, questionId) {
    const newCells = [];
    const allCells = [];
    for (let col = 0; col < cells.length; col++) {
      if (cells[col]) {
        allCells.push([col, cells[col]]);
        if (!cont.has(col)) newCells.push([col, cells[col]]);
      }
    }
    if (!newCells.length) return null;
    if (newCells.some(([, c]) => participantSegments(c).some(([pid]) => pid !== null))) return null;

    const hasAnyParticipantTag = allCells.some(([, c]) => participantSegments(c).some(([pid]) => pid !== null));
    const quoteCols = new Set(cols.notable_quotes || []);
    const hasNotableQuote = allCells.some(([col, c]) => quoteCols.has(col) && c.trim().length > 0);
    const kpCols = new Set(cols.key_points || []);
    const order = [...newCells].sort((a, b) => ((kpCols.has(a[0]) ? 0 : 1) - (kpCols.has(b[0]) ? 0 : 1)) || (a[0] - b[0]));

    for (const [labelCol, labelText] of order) {
      const firstLines = boxLines(labelText);
      if (!firstLines.length) continue;
      const head = firstLines[0];
      if ('"\'\u201c\u2018'.includes(head[0])) continue;

      const summaryMatch = RE_NOTES_SUMMARY_LABEL.exec(head);
      const isQFull = RE_NOTES_EMBEDDED_QUESTION.test(head);
      const isQShort = !hasAnyParticipantTag && !hasNotableQuote && !quoteCols.has(labelCol) && RE_NOTES_EMBEDDED_Q_SHORT.test(head);
      const isPromptFull = RE_NOTES_PROMPT.test(head);
      const isPromptFac = !hasAnyParticipantTag && !hasNotableQuote && !quoteCols.has(labelCol) && RE_NOTES_FACILITATOR_PROMPT.test(head);
      const isConsent = RE_NOTES_CONSENT.test(head);
      const isQ = isQFull || isQShort;
      const isPrompt = isPromptFull || isPromptFac;
      if (!(isQ || isPrompt || isConsent || summaryMatch)) continue;

      const extraLines = newCells.filter(([col]) => col !== labelCol).flatMap(([, c]) => boxLines(c));
      const combined = firstLines.concat(extraLines).join("\n");
      if (isQ) {
        const m = RE_NOTES_QUESTION.exec(labelText.trim());
        const nextQ = `Question ${parseInt(m[1], 10)}`;
        questions[nextQ] = boxLines(m[2]).concat(extraLines).join("\n");
        recordExcluded(rowBlock, "embedded_question_row", combined);
        return nextQ;
      }
      if (isPrompt) {
        const pLines = (firstLines.length === 1 && head.endsWith(":") && extraLines.length)
          ? [`${head} ${extraLines[0]}`].concat(extraLines.slice(1))
          : firstLines.concat(extraLines);
        if (questions[questionId] !== undefined) {
          questions[questionId] = boxLines(questions[questionId]).concat(pLines).join("\n");
        }
        recordExcluded(rowBlock, "prompt_row", combined);
        return questionId;
      }
      if (summaryMatch) {
        const rest = (summaryMatch[2] || "").trim();
        setMetadata(summaryMatch[1], (rest ? [rest] : []).concat(firstLines.slice(1), extraLines).join("\n"));
        recordExcluded(rowBlock, "summary_box", combined);
      } else {
        recordExcluded(rowBlock, "consent_row", combined);
      }
      return questionId;
    }
    return null;
  }

  function rowEntries(rowBlock, cells, cols, questionId, cont) {
    const textAt = col => (col < cells.length ? cells[col] : "");
    const hasNewParticipant = cells.some((c, col) => c && !cont.has(col) && participantSegments(c).some(([pid]) => pid !== null));
    if (!hasNewParticipant) {
      const scanCols = Array.from(new Set([...(cols.key_points || []), ...cells.map((_, i) => i)]));
      for (const col of scanCols) {
        if (cont.has(col)) continue;
        const m = RE_NOTES_THEMES.exec(textAt(col));
        if (m) {
          const parts = [cells[col].slice(m[0].length)].concat(
            cells.filter((_, i) => i !== col && !cont.has(i))
          );
          const text = parts.map(joinLines).filter(Boolean).join(" ");
          if (text) themeEntries.push([rowBlock, NOTES_THEMES_SPEAKER, text, "themes_summary", questionId]);
          return;
        }
      }
    }

    const contributions = [];
    for (const [role, evType] of [
      ["key_points", "key_point_paraphrase"],
      ["notable_quotes", "notable_quote_verbatim"],
      ["observations", "observation"],
    ]) {
      for (const col of (cols[role] || [])) {
        const segs = participantSegments(textAt(col));
        for (const [pid, txt] of segs) {
          contributions.push([evType, pid, txt, !cont.has(col)]);
        }
      }
    }
    const labels = new Set(contributions.map(c => c[1]).filter(Boolean));
    const rowPid = labels.size === 1 ? Array.from(labels)[0] : "Unknown";
    for (const [evType, pid, txt, emit] of contributions) {
      if (txt && emit) {
        entries.push([rowBlock, pid || rowPid, txt, evType, questionId]);
      }
    }
  }

  for (const blk of blocks) {
    if (blk.rows === null) {
      location += 1;
      const text = blk.para.trim();
      if (isBanner(text)) continue;
      if (text && !noteQuestion(text, location) && pending.question_id) {
        pending.prompt.push(...boxLines(text));
        recordExcluded(location, "question_prompt_paragraph", text);
      }
      continue;
    }
    const firstBlock = location + 1;
    location += blk.rows.length;
    const rows = blk.rows.map(r => r.map(c => isBanner(c) ? "" : c));
    const found = notesColumns(rows);
    if (!found) {
      readMetadataTable(rows);
      const boxText = rows
        .map(r => r.filter(c => c.trim()).join(" "))
        .filter(Boolean)
        .join(" | ");
      if (boxText.trim()) recordExcluded(firstBlock, "header_or_summary_table", boxText);
      continue;
    }
    const { headerIdx, cols } = found;
    notesTables += 1;
    for (let hIdx = 0; hIdx < headerIdx; hIdx++) {
      noteQuestion(rows[hIdx].filter(Boolean).join(" "), firstBlock + hIdx);
    }
    let questionId = pending.question_id || `Question ${notesTables}`;
    if (pending.question_id) questions[questionId] = pending.prompt.join("\n");
    pending.question_id = null;
    pending.prompt = [];
    for (let rIdx = headerIdx + 1; rIdx < rows.length; rIdx++) {
      const cells = rows[rIdx], cont = blk.continued[rIdx];
      if (notesColumns([cells])) continue;
      const nextQ = structuralRow(firstBlock + rIdx, cells, cont, cols, questionId);
      if (nextQ !== null) { questionId = nextQ; continue; }
      rowEntries(firstBlock + rIdx, cells, cols, questionId, cont);
    }
  }

  metadata.questions = questions;
  metadata.excluded_structural_rows = excludedStructuralRows;

  const kept = entries.filter(e => includeSet.has(e[3]));
  let cursor = 0;
  const turns = kept.map(([blockLoc, speaker, text, evType, qId], idx) => {
    const start = cursor;
    cursor += text.length + 1;
    return {
      document_name: fileName,
      source_id: sourceId,
      unit_id: sourceId,
      turn_id: idx + 1,
      line_number: blockLoc,
      timestamp: "",
      speaker,
      is_facilitator: false,
      text,
      char_start: start,
      char_end: start + text.length,
      document_structure: "focus_group_notes",
      evidence_type: evType,
      question_id: qId,
      group_id: sourceId,
      participant_id: `${sourceId}::${speaker}`,
    };
  });

  const noteTakerThemes = themeEntries.map(([blockLoc, speaker, text, evType, qId], idx) => ({
    document_name: fileName,
    source_id: sourceId,
    turn_id: idx + 1,
    line_number: blockLoc,
    speaker,
    text,
    evidence_type: evType,
    question_id: qId,
  }));

  return { turns, structure: "focus_group_notes", metadata, noteTakerThemes };
}

function isLikelySpeaker(name) {
  const clean = String(name || "").trim();
  if (!clean || clean.length > 60) return false;
  const words = clean.split(/\s+/);
  if (words.length > 6) return false;
  if (words.length === 1 && SINGLE_WORD_NON_SPEAKERS.has(clean.toLowerCase())) return false;
  return /^[A-Z\u00C0-\u024F]/.test(clean[0]);
}

function isFacilitatorSpeaker(speaker, extraFacilitators) {
  const low = String(speaker || "").trim().toLowerCase();
  if (!low) return false;
  if (DEFAULT_FACILITATORS.has(low)) return true;
  for (const base of DEFAULT_FACILITATORS) {
    if (low.startsWith(base + " ") || low.startsWith(base + "#")) return true;
  }
  for (const n of (extraFacilitators || [])) {
    if (n && low === String(n).trim().toLowerCase()) return true;
  }
  return false;
}

function parsePlainTranscriptLines(lines, fileName, sourceId, facilitatorNames, promptPatterns) {
  const promptRegexes = (promptPatterns || []).map(p => new RegExp(p, "i"));
  const rawTurns = [];
  let pendingSpeaker = null, pendingTs = "", pendingLine = 1;

  for (let i = 0; i < lines.length; i++) {
    const lineNo = i + 1;
    const raw = lines[i].trim();
    if (!raw || isBanner(raw) || RE_TEAMS_HEADER.test(raw)) continue;

    const mTs = RE_DOCX_SPEAKER_TS.exec(raw);
    if (mTs && isLikelySpeaker(mTs[1])) {
      pendingSpeaker = mTs[1].trim();
      pendingTs = mTs[2].trim();
      pendingLine = lineNo;
      continue;
    }
    const mTsCol = RE_DOCX_TS_SPEAKER_COLON.exec(raw);
    if (mTsCol && isLikelySpeaker(mTsCol[2]) && mTsCol[3].trim()) {
      rawTurns.push({ lineNo, speaker: mTsCol[2].trim(), ts: mTsCol[1].trim(), text: mTsCol[3].trim() });
      pendingSpeaker = null;
      continue;
    }
    const mCol = RE_DOCX_SPEAKER_COLON.exec(raw);
    if (mCol && isLikelySpeaker(mCol[1]) && mCol[2].trim()) {
      rawTurns.push({ lineNo, speaker: mCol[1].trim(), ts: "", text: mCol[2].trim() });
      pendingSpeaker = null;
      continue;
    }
    if (pendingSpeaker) {
      rawTurns.push({ lineNo: pendingLine, speaker: pendingSpeaker, ts: pendingTs, text: raw });
      pendingSpeaker = null;
    } else {
      rawTurns.push({ lineNo, speaker: "Unknown", ts: "", text: raw });
    }
  }

  let cursor = 0;
  const turns = rawTurns.map((t, idx) => {
    const start = cursor;
    cursor += t.text.length + 1;
    const isFac = isFacilitatorSpeaker(t.speaker, facilitatorNames) ||
      (t.speaker === "Unknown" && promptRegexes.some(rx => rx.test(t.text)));
    return {
      document_name: fileName,
      source_id: sourceId,
      unit_id: sourceId,
      turn_id: idx + 1,
      line_number: t.lineNo,
      timestamp: t.ts,
      speaker: t.speaker,
      is_facilitator: isFac,
      text: t.text,
      char_start: start,
      char_end: start + t.text.length,
      document_structure: "transcript",
      evidence_type: "verbatim_turn",
      question_id: "",
      group_id: sourceId,
      participant_id: sourceId,
    };
  });
  return { turns, structure: "transcript", metadata: {}, noteTakerThemes: [] };
}

function parseVttText(text, fileName, sourceId, facilitatorNames, promptPatterns) {
  const lines = String(text || "").replace(/\r\n/g, "\n").replace(/\r/g, "\n").split("\n");
  const rawTurns = [];
  let i = 0;
  while (i < lines.length) {
    const ln = lines[i].trim();
    const m = RE_VTT_TIMECODE.exec(ln);
    if (!m) { i++; continue; }
    const ts = m[1];
    const startLine = i + 1;
    i++;
    const cueLines = [];
    while (i < lines.length && lines[i].trim() !== "") {
      cueLines.push(lines[i].trim());
      i++;
    }
    const joined = cueLines.join(" ").trim();
    if (!joined || isBanner(joined)) continue;
    let speaker = "Unknown", body = joined;
    const vm = /<v(?:\.[^\s>]*)?\s+([^>]+)>([\s\S]*?)(?:<\/v>|$)/i.exec(joined);
    if (vm) {
      speaker = vm[1].trim();
      body = vm[2].replace(/<\/?[^>]+>/g, "").trim();
    } else {
      const stripped = joined.replace(/<\/?[^>]+>/g, "").trim();
      const cm = RE_DOCX_SPEAKER_COLON.exec(stripped);
      if (cm && isLikelySpeaker(cm[1]) && cm[2].trim()) {
        speaker = cm[1].trim();
        body = cm[2].trim();
      } else {
        body = stripped;
      }
    }
    if (body) rawTurns.push({ lineNo: startLine, speaker, ts, text: body });
  }
  const promptRegexes = (promptPatterns || []).map(p => new RegExp(p, "i"));
  let cursor = 0;
  const turns = rawTurns.map((t, idx) => {
    const start = cursor;
    cursor += t.text.length + 1;
    const isFac = isFacilitatorSpeaker(t.speaker, facilitatorNames) ||
      (t.speaker === "Unknown" && promptRegexes.some(rx => rx.test(t.text)));
    return {
      document_name: fileName,
      source_id: sourceId,
      unit_id: sourceId,
      turn_id: idx + 1,
      line_number: t.lineNo,
      timestamp: t.ts,
      speaker: t.speaker,
      is_facilitator: isFac,
      text: t.text,
      char_start: start,
      char_end: start + t.text.length,
      document_structure: "transcript",
      evidence_type: "verbatim_turn",
      question_id: "",
      group_id: sourceId,
      participant_id: sourceId,
    };
  });
  return { turns, structure: "transcript", metadata: {}, noteTakerThemes: [] };
}

// ----------------------------------------------------------------------------
// 5. CSV & Multi-Sheet Excel (.xlsx) Readers
// ----------------------------------------------------------------------------
function parseCsvRows(text) {
  const clean = String(text || "").replace(/^\uFEFF/, "");
  const rows = [];
  let row = [], cell = "", inQ = false;
  for (let i = 0; i < clean.length; i++) {
    const ch = clean[i];
    if (inQ) {
      if (ch === '"') {
        if (clean[i + 1] === '"') { cell += '"'; i++; }
        else inQ = false;
      } else {
        cell += ch;
      }
    } else if (ch === '"') {
      inQ = true;
    } else if (ch === ",") {
      row.push(cell); cell = "";
    } else if (ch === "\r" || ch === "\n") {
      if (ch === "\r" && clean[i + 1] === "\n") i++;
      row.push(cell); cell = "";
      if (row.some(c => c.length > 0)) rows.push(row);
      row = [];
    } else {
      cell += ch;
    }
  }
  row.push(cell);
  if (row.some(c => c.length > 0)) rows.push(row);
  if (!rows.length) return { headers: [], dataRows: [] };
  const headers = rows[0].map((h, i) => String(h || "").trim() || `Column_${i + 1}`);
  const dataRows = rows.slice(1).map((r, idx) => {
    const obj = {};
    headers.forEach((h, c) => { obj[h] = r[c] !== undefined ? String(r[c]) : ""; });
    return { lineNumber: idx + 2, values: obj };
  });
  return { headers, dataRows };
}

function colLettersToIndex(letters) {
  let col = 0;
  for (let i = 0; i < letters.length; i++) {
    col = col * 26 + (letters.charCodeAt(i) - 64);
  }
  return col - 1;
}

async function readXlsxWorkbook(bytes) {
  const entries = await readZipEntries(bytes);
  const dec = new TextDecoder("utf-8");
  const parser = new DOMParser();

  // Shared strings table
  const sharedStrings = [];
  if (entries.has("xl/sharedStrings.xml")) {
    const ssDoc = parser.parseFromString(dec.decode(entries.get("xl/sharedStrings.xml")), "application/xml");
    for (const si of Array.from(ssDoc.getElementsByTagNameNS("*", "si"))) {
      const tEls = Array.from(si.getElementsByTagNameNS("*", "t"));
      sharedStrings.push(tEls.map(t => t.textContent || "").join(""));
    }
  }

  // Workbook relationships
  const rels = new Map();
  if (entries.has("xl/_rels/workbook.xml.rels")) {
    const rDoc = parser.parseFromString(dec.decode(entries.get("xl/_rels/workbook.xml.rels")), "application/xml");
    for (const rel of Array.from(rDoc.getElementsByTagName("Relationship"))) {
      let target = rel.getAttribute("Target") || "";
      target = target.replace(/^\/+/, "");
      if (!target.startsWith("xl/")) target = "xl/" + target;
      rels.set(rel.getAttribute("Id"), target);
    }
  }

  // Sheet list
  const wbDoc = parser.parseFromString(dec.decode(entries.get("xl/workbook.xml")), "application/xml");
  const sheetEls = Array.from(wbDoc.getElementsByTagNameNS("*", "sheet"));
  const sheets = [];
  for (const sEl of sheetEls) {
    const name = sEl.getAttribute("name") || "Sheet1";
    const rId = sEl.getAttribute("r:id") || sEl.getAttributeNS("http://schemas.openxmlformats.org/officeDocument/2006/relationships", "id") || "";
    const path = rels.get(rId) || `xl/worksheets/sheet${sheets.length + 1}.xml`;
    sheets.push({ name, path });
  }

  function parseSheet(sheetName) {
    const info = sheets.find(s => s.name === sheetName) || sheets[0];
    if (!info || !entries.has(info.path)) return { sheetName: info ? info.name : "", headers: [], dataRows: [] };
    const wsDoc = parser.parseFromString(dec.decode(entries.get(info.path)), "application/xml");
    const rowEls = Array.from(wsDoc.getElementsByTagNameNS("*", "row"));
    const grid = [];
    let maxCols = 0;

    for (const rEl of rowEls) {
      const rNum = parseInt(rEl.getAttribute("r") || String(grid.length + 1), 10);
      const rowMap = new Map();
      for (const cEl of Array.from(rEl.childNodes).filter(n => n.nodeType === 1 && n.localName === "c")) {
        const ref = cEl.getAttribute("r") || "";
        const m = /^([A-Z]+)\d+$/i.exec(ref);
        const cIdx = m ? colLettersToIndex(m[1].toUpperCase()) : rowMap.size;
        const t = cEl.getAttribute("t") || "";
        let val = "";
        if (t === "s") {
          const vEl = Array.from(cEl.childNodes).find(n => n.nodeType === 1 && n.localName === "v");
          const sIdx = vEl ? parseInt(vEl.textContent || "", 10) : -1;
          val = (sIdx >= 0 && sIdx < sharedStrings.length) ? sharedStrings[sIdx] : "";
        } else if (t === "inlineStr") {
          val = Array.from(cEl.getElementsByTagNameNS("*", "t")).map(x => x.textContent || "").join("");
        } else if (t === "b") {
          const vEl = Array.from(cEl.childNodes).find(n => n.nodeType === 1 && n.localName === "v");
          val = vEl && vEl.textContent === "1" ? "TRUE" : "FALSE";
        } else {
          const vEl = Array.from(cEl.childNodes).find(n => n.nodeType === 1 && n.localName === "v");
          val = vEl ? (vEl.textContent || "") : "";
        }
        rowMap.set(cIdx, val);
        if (cIdx + 1 > maxCols) maxCols = cIdx + 1;
      }
      grid.push({ rNum, rowMap });
    }

    if (!grid.length) return { sheetName: info.name, headers: [], dataRows: [] };
    const headerRow = grid[0];
    const headers = [];
    for (let c = 0; c < maxCols; c++) {
      const h = String(headerRow.rowMap.get(c) || "").trim();
      headers.push(h || `Column_${c + 1}`);
    }
    const dataRows = [];
    for (let i = 1; i < grid.length; i++) {
      const { rNum, rowMap } = grid[i];
      const obj = {};
      let anyNonEmpty = false;
      for (let c = 0; c < headers.length; c++) {
        const v = String(rowMap.get(c) || "");
        obj[headers[c]] = v;
        if (v.trim()) anyNonEmpty = true;
      }
      // Keep every physical row so blank answers in text_col are accurately counted
      if (anyNonEmpty || rowMap.size > 0) {
        dataRows.push({ lineNumber: rNum, values: obj });
      }
    }
    return { sheetName: info.name, headers, dataRows };
  }

  return { sheetNames: sheets.map(s => s.name), parseSheet };
}

function detectBestTextColumn(headers, dataRows) {
  const candidates = [];
  for (const h of headers) {
    const low = h.toLowerCase();
    if (/^(id|respondent_id|participant_id|case_id|row_id|timestamp|date|time)$/.test(low)) continue;
    const vals = dataRows.map(r => String(r.values[h] || "").trim()).filter(Boolean);
    if (!vals.length) continue;
    const avgLen = vals.reduce((s, v) => s + v.length, 0) / vals.length;
    const nameBoost = /(response|answer|comment|open|feedback|text|transcript|quote|note|explain|why|describe)/.test(low) ? 40 : 0;
    candidates.push({ h, score: avgLen + nameBoost });
  }
  candidates.sort((a, b) => b.score - a.score);
  return candidates.length ? candidates[0].h : (headers[0] || "");
}

function parseTabularData(parsedTable, fileName, sourceId, opts) {
  const textCol = opts.textCol;
  const idCol = opts.idCol || "";
  const speakerCol = opts.speakerCol || "";
  const policy = opts.duplicateIdPolicy || "per_row"; // "per_row" | "combine" | "error"
  const facilitatorNames = opts.facilitatorNames || [];
  const promptPatterns = opts.promptPatterns || [];
  const promptRegexes = promptPatterns.map(p => new RegExp(p, "i"));

  const rows = parsedTable.dataRows || [];
  const seenIds = new Set();
  const turns = [];
  let skippedBlank = 0;
  let cursor = 0;

  for (const r of rows) {
    const rawText = String(r.values[textCol] || "").trim();
    if (!rawText || isBanner(rawText)) {
      skippedBlank++;
      continue;
    }
    const rawId = idCol ? String(r.values[idCol] || "").trim() : "";
    let unitId;
    if (policy === "per_row") {
      unitId = `${sourceId}::row_${r.lineNumber}`;
    } else if (idCol) {
      if (!rawId) {
        unitId = `${sourceId}#row_${r.lineNumber}`;
      } else {
        if (policy === "error" && seenIds.has(rawId)) {
          throw new Error(`Duplicate ID ${rawId} in column '${idCol}' of ${fileName}.`);
        }
        seenIds.add(rawId);
        unitId = `${sourceId}::${rawId}`;
      }
    } else {
      unitId = `${sourceId}::row_${r.lineNumber}`;
    }

    const speaker = (speakerCol && String(r.values[speakerCol] || "").trim())
      ? String(r.values[speakerCol]).trim()
      : (rawId || `Row ${r.lineNumber}`);
    const isFac = isFacilitatorSpeaker(speaker, facilitatorNames) ||
      promptRegexes.some(rx => rx.test(rawText));

    const start = cursor;
    cursor += rawText.length + 1;
    const turn = {
      document_name: fileName,
      source_id: sourceId,
      unit_id: unitId,
      turn_id: turns.length + 1,
      line_number: r.lineNumber,
      timestamp: "",
      speaker,
      is_facilitator: isFac,
      text: rawText,
      char_start: start,
      char_end: start + rawText.length,
      document_structure: "tabular",
      evidence_type: "verbatim_turn",
      question_id: "",
      group_id: sourceId,
      participant_id: unitId,
    };
    if (policy === "per_row" && idCol) {
      turn.respondent_id = rawId;
    }
    turns.push(turn);
  }

  const uniqueUnits = new Set(turns.filter(t => !t.is_facilitator).map(t => t.unit_id)).size;
  const stats = {
    source_id: sourceId,
    total_rows: rows.length,
    non_blank_rows: turns.length,
    skipped_blank_rows: skippedBlank,
    unique_units: uniqueUnits,
    sheet_name: parsedTable.sheetName || null,
    duplicate_id_policy: policy,
  };
  return { turns, structure: "tabular", metadata: {}, noteTakerThemes: [], tabularStats: stats };
}
