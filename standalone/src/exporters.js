// ============================================================================
// ATLAS Standalone Browser Exporters — CSV, YAML, JSON Manifest, XLSX, & DOCX
// Pure JavaScript using native CompressionStream ZIP builder (Zero CDN)
// ============================================================================

function escXml(str) {
  return String(str === null || str === undefined ? "" : str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

function csvCell(val) {
  const s = String(val === null || val === undefined ? "" : val);
  if (/[",\r\n]/.test(s)) return '"' + s.replace(/"/g, '""') + '"';
  return s;
}

function rowsToCsv(headers, rows) {
  const lines = [headers.map(csvCell).join(",")];
  for (const r of rows) {
    lines.push(headers.map(h => csvCell(r[h])).join(","));
  }
  return "\uFEFF" + lines.join("\r\n") + "\r\n";
}

function serializeCodebookYaml(rules, projectName) {
  const lines = [
    `project: ${JSON.stringify(projectName || "ATLAS Active Themes")}`,
    `version: "1.2"`,
    `domains:`
  ];
  for (const r of rules) {
    lines.push(`  - id: ${JSON.stringify(r.id)}`);
    lines.push(`    name: ${JSON.stringify(r.name)}`);
    if (r.description) lines.push(`    description: ${JSON.stringify(r.description)}`);
    if (r.match_mode && r.match_mode !== "prefix") lines.push(`    match_mode: ${JSON.stringify(r.match_mode)}`);
    lines.push(`    roots_en:`);
    for (const k of (r.roots_en || [])) lines.push(`      - ${JSON.stringify(k)}`);
    if (r.roots_es && r.roots_es.length) {
      lines.push(`    roots_es:`);
      for (const k of r.roots_es) lines.push(`      - ${JSON.stringify(k)}`);
    }
    if (r.context_fences && r.context_fences.length) {
      lines.push(`    context_fences:`);
      for (const k of r.context_fences) lines.push(`      - ${JSON.stringify(k)}`);
    }
    if (r.context_window !== null && r.context_window !== undefined) {
      lines.push(`    context_window: ${r.context_window}`);
    }
    if (r.exclude_fences && r.exclude_fences.length) {
      lines.push(`    exclude_fences:`);
      for (const k of r.exclude_fences) lines.push(`      - ${JSON.stringify(k)}`);
    }
    if (r.exclude_window !== null && r.exclude_window !== undefined) {
      lines.push(`    exclude_window: ${r.exclude_window}`);
    }
  }
  return lines.join("\n") + "\n";
}

function buildProvenanceManifest(results, meta) {
  const typoPairs = new Set((results.typo_matches || []).map(t => `${t.source_id}|${t.unit_id}|${t.turn_id}|${t.line_number}|${t.domain_id}`));
  return {
    atlas_edition: "Standalone Browser Workbench (v1.2)",
    generated_at_utc: new Date().toISOString(),
    mode: meta.groupMode ? "group_notes" : "individual_units",
    corpus_label: meta.corpusLabel || "",
    is_fixture: Boolean(meta.isFixture),
    total_documents: results.total_documents,
    total_turns_parsed: results.total_turns_parsed,
    participant_turns_analyzed: results.participant_turns_analyzed,
    spelling_tolerance: Boolean(results.spelling_tolerance),
    typo_rescued_matches: typoPairs.size,
    typo_rescued_occurrences: (results.typo_matches || []).length,
    excel_sheet_name: meta.sheetName || null,
    file_hashes: results.file_hashes,
    domains: results.frequencies.map(f => ({
      domain_id: f.domain_id,
      domain_name: f.domain_name,
      documents_reporting: f.documents_reporting,
      total_documents: f.total_documents,
      prevalence_pct: f.prevalence_pct,
      matching_turns: f.matching_turns,
      audit_sha256: f.audit_sha256,
    })),
  };
}

// ----------------------------------------------------------------------------
// Real Multi-Sheet Excel (.xlsx) Generator
// ----------------------------------------------------------------------------
function colIndexToLetters(idx) {
  let s = "", n = idx + 1;
  while (n > 0) {
    const rem = (n - 1) % 26;
    s = String.fromCharCode(65 + rem) + s;
    n = Math.floor((n - 1) / 26);
  }
  return s;
}

function buildSheetXml(headers, dataRows) {
  const rowsXml = [];
  const makeCell = (cIdx, rNum, val, isHeader) => {
    const ref = `${colIndexToLetters(cIdx)}${rNum}`;
    const style = isHeader ? ' s="1"' : "";
    if (!isHeader && typeof val === "number" && Number.isFinite(val)) {
      return `<c r="${ref}"${style}><v>${val}</v></c>`;
    }
    return `<c r="${ref}" t="inlineStr"${style}><is><t xml:space="preserve">${escXml(val)}</t></is></c>`;
  };
  rowsXml.push(`<row r="1">${headers.map((h, i) => makeCell(i, 1, h, true)).join("")}</row>`);
  dataRows.forEach((row, idx) => {
    const rNum = idx + 2;
    rowsXml.push(`<row r="${rNum}">${row.map((v, i) => makeCell(i, rNum, v, false)).join("")}</row>`);
  });
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>` +
    `<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">` +
    `<sheetData>${rowsXml.join("")}</sheetData></worksheet>`;
}

async function buildFrequenciesXlsx(results, meta) {
  const freqHeaders = [
    "Domain ID", "Theme Name",
    meta.groupMode ? "Focus Groups Reporting" : "Units Reporting",
    meta.groupMode ? "Total Focus Groups" : "Total Analytical Units",
    "Prevalence (%)", "Theme Matches", "Total Keyword Mentions", "Audit SHA-256"
  ];
  const freqRows = results.frequencies.map(f => [
    f.domain_id, f.domain_name, f.documents_reporting, f.total_documents,
    f.prevalence_pct, f.matching_turns, f.total_mentions, f.audit_sha256
  ]);

  const hasNonVerb = results.quotes.some(q => !VERBATIM_EVIDENCE_TYPES.has(String(q.evidence_type || "")));
  const evSheetName = hasNonVerb ? "Coded Evidence" : "Verbatim Quotes";
  const includeResp = Boolean(results.has_respondent_id && results.quotes.some(q => String(q.respondent_id || "").trim()));
  const evHeaders = [
    "Domain ID", "Theme Name", "Source File", "Unit ID",
    ...(includeResp ? ["Respondent ID"] : []),
    "Line", "Speaker", "Source Type", "Question", "Matched Span", "Full Entry Text", "Source SHA-256"
  ];
  const evRows = results.quotes.map(q => [
    q.domain_id, q.domain_name, q.source_id, q.unit_id,
    ...(includeResp ? [q.respondent_id || ""] : []),
    Number(q.line_number) || 0, q.speaker, q.evidence_type || "verbatim_turn",
    q.question_id || "", q.match_text, q.text, q.source_sha256
  ]);

  const auditHeaders = ["Field", "Value"];
  const auditRows = [
    ["Edition", "ATLAS Standalone Browser Workbench (v1.2)"],
    ["Generated (UTC)", new Date().toISOString()],
    ["Analysis Mode", meta.groupMode ? "Group / Summarized Notes (1 file = 1 group)" : "Individual Analytical Units"],
    ["Corpus", meta.corpusLabel || ""],
    ["Sample Practice Data", meta.isFixture ? "YES (SOFTWARE_TEST FIXTURE — demonstration only)" : "No"],
    ["Excel Sheet", meta.sheetName || "N/A"],
    ["Spelling Tolerance (DL=1)", results.spelling_tolerance ? "Enabled" : "Off"],
    ["Total Analytical Units / Groups", results.total_documents],
    ["Entries Scanned", results.participant_turns_analyzed],
    ["Total Theme Matches", results.quotes.length],
  ];

  const entries = new Map();
  entries.set("[Content_Types].xml",
    `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>` +
    `<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">` +
    `<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>` +
    `<Default Extension="xml" ContentType="application/xml"/>` +
    `<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>` +
    `<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>` +
    `<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>` +
    `<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>` +
    `<Override PartName="/xl/worksheets/sheet3.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>` +
    `</Types>`
  );
  entries.set("_rels/.rels",
    `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>` +
    `<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">` +
    `<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>` +
    `</Relationships>`
  );
  entries.set("xl/_rels/workbook.xml.rels",
    `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>` +
    `<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">` +
    `<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>` +
    `<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>` +
    `<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet3.xml"/>` +
    `<Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>` +
    `</Relationships>`
  );
  entries.set("xl/workbook.xml",
    `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>` +
    `<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">` +
    `<sheets>` +
    `<sheet name="Empirical Frequencies" sheetId="1" r:id="rId1"/>` +
    `<sheet name="${escXml(evSheetName)}" sheetId="2" r:id="rId2"/>` +
    `<sheet name="Methodology &amp; Audit" sheetId="3" r:id="rId3"/>` +
    `</sheets></workbook>`
  );
  entries.set("xl/styles.xml",
    `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>` +
    `<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">` +
    `<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font></fonts>` +
    `<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF1B2A4A"/></patternFill></fill></fills>` +
    `<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>` +
    `<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>` +
    `<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/></cellXfs>` +
    `<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>` +
    `</styleSheet>`
  );
  entries.set("xl/worksheets/sheet1.xml", buildSheetXml(freqHeaders, freqRows));
  entries.set("xl/worksheets/sheet2.xml", buildSheetXml(evHeaders, evRows));
  entries.set("xl/worksheets/sheet3.xml", buildSheetXml(auditHeaders, auditRows));

  return writeZipArchive(entries, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
}

// ----------------------------------------------------------------------------
// Two-Layer Printable Word Summary Report (.docx) Generator
//   Front Half: Executive Summary (Grade 6–7 prose, embedded PNG bar chart,
//               short group labels, descending sort, direct quotes & evidence)
//   Back Half:  Technical and Audit Appendix (Page Break, run settings,
//               SHA-256 file fingerprints, unlisted clusters, spot-check log,
//               skipped questions and session headers)
// ----------------------------------------------------------------------------
function disambiguateThemeLabels(pairs) {
  // pairs: Array<[domain_id, domain_name]> -> Map<domain_id, uniqueDisplayLabel>
  const labelMap = new Map(pairs.map(([did, name]) => [String(did), String(name)]));
  for (let pass = 0; pass < 3; pass++) {
    const counts = new Map();
    for (const lbl of labelMap.values()) counts.set(lbl, (counts.get(lbl) || 0) + 1);
    const dups = new Set([...counts.entries()].filter(([, c]) => c > 1).map(([k]) => k));
    if (!dups.size) break;
    let changed = false;
    for (const [did, lbl] of [...labelMap.entries()]) {
      if (dups.has(lbl)) {
        const suffix = ` (${did})`;
        if (!lbl.endsWith(suffix)) {
          labelMap.set(did, `${lbl}${suffix}`);
          changed = true;
        }
      }
    }
    if (!changed) {
      for (const [did, lbl] of [...labelMap.entries()]) {
        if (dups.has(lbl)) labelMap.set(did, `${lbl} [id: ${did}]`);
      }
      break;
    }
  }
  return labelMap;
}

function shortenChartLabels(items, maxLen = 34) {
  // Preserve trailing disambiguation suffix (e.g., " (a)" or " [id: a]") when truncating
  const shortenOne = (label, limit) => {
    const s = String(label || "");
    if (s.length <= limit) return s;
    const m = s.match(/(\s+(?:\([^()]{1,20}\)|\[id:\s*[^\]]{1,20}\]))$/);
    if (m) {
      const suf = m[1];
      const keep = Math.max(4, limit - suf.length - 1);
      return s.slice(0, keep).trimEnd() + "…" + suf;
    }
    return s.slice(0, limit - 1).trimEnd() + "…";
  };
  const out = items.map(it => shortenOne(it.label, maxLen));
  // Guarantee uniqueness even if two distinct long labels lacked suffixes before truncation
  const counts = new Map();
  for (const lbl of out) counts.set(lbl, (counts.get(lbl) || 0) + 1);
  for (let i = 0; i < out.length; i++) {
    if (counts.get(out[i]) > 1) {
      const did = items[i].domain_id || String(i + 1);
      const suf = ` (${did})`;
      const keep = Math.max(4, maxLen - suf.length - 1);
      out[i] = String(items[i].label || "").slice(0, keep).trimEnd() + "…" + suf;
    }
  }
  return out;
}

function friendlyGroupLabels(sourceIds) {
  const sids = Array.from(sourceIds || []).map(String);
  const stems = sids.map(s => s.split("/").pop().replace(/\.[^.]+$/, ""));
  const out = {};
  if (sids.length >= 2) {
    const tokenLists = stems.map(st => st.split(/[_\-\s]+/).filter(Boolean));
    let pref = 0;
    const minLen = Math.min(...tokenLists.map(t => t.length));
    while (pref < minLen - 1 && tokenLists.every(t => t[pref].toLowerCase() === tokenLists[0][pref].toLowerCase())) {
      pref++;
    }
    const candidates = tokenLists.map(t => t.slice(pref).join(" ").trim());
    const uniqueNonEmpty = candidates.every(Boolean) && new Set(candidates.map(c => c.toLowerCase())).size === candidates.length;
    if (uniqueNonEmpty) {
      for (let i = 0; i < sids.length; i++) {
        out[sids[i]] = candidates[i].replace(/\b[a-z]/g, ch => ch.toUpperCase());
      }
      return out;
    }
  }
  // Normalize first, then check collisions AFTER normalization (e.g. room_one vs room__one)
  const normalized = stems.map(st => st.replace(/[_\s]+/g, " ").trim());
  const normCounts = new Map();
  for (const nm of normalized) {
    const k = nm.toLowerCase();
    normCounts.set(k, (normCounts.get(k) || 0) + 1);
  }
  for (let i = 0; i < sids.length; i++) {
    const nm = normalized[i];
    out[sids[i]] = (!nm || normCounts.get(nm.toLowerCase()) > 1) ? sids[i] : nm;
  }
  return out;
}

function friendlyExcludedReason(rawReason) {
  const key = String(rawReason || "").trim().toLowerCase();
  const map = {
    header_or_summary_table: "Session header or summary box",
    question_heading: "Discussion question heading",
    question_prompt_paragraph: "Follow-up prompt",
    consent_row: "Consent notice",
    facilitator_row: "Facilitator line",
    facilitator_turn: "Facilitator line",
    note_taker_themes_row: "Note-taker themes summary",
  };
  if (map[key]) return map[key];
  const spaced = key.replace(/_/g, " ").trim();
  return spaced ? spaced.charAt(0).toUpperCase() + spaced.slice(1) : "Skipped header";
}

function wPara(text, opts = {}) {
  const sz = opts.size ? `<w:sz w:val="${opts.size}"/><w:szCs w:val="${opts.size}"/>` : `<w:sz w:val="22"/><w:szCs w:val="22"/>`;
  const bold = opts.bold ? "<w:b/>" : "";
  const italic = opts.italic ? "<w:i/>" : "";
  const color = opts.color ? `<w:color w:val="${opts.color}"/>` : `<w:color w:val="1A1A2E"/>`;
  const spBefore = opts.before !== undefined ? opts.before : 80;
  const spAfter = opts.after !== undefined ? opts.after : 100;
  const keepNext = opts.keepNext ? "<w:keepNext/>" : "";
  const pageBreak = opts.pageBreakBefore ? "<w:pageBreakBefore/>" : "";
  const shading = opts.bg ? `<w:shd w:val="clear" w:color="auto" w:fill="${opts.bg}"/>` : "";
  const border = opts.borderLeft ? `<w:pBdr><w:left w:val="single" w:sz="18" w:space="8" w:color="${opts.borderLeft}"/></w:pBdr>` : "";
  return `<w:p><w:pPr>${pageBreak}${keepNext}<w:spacing w:before="${spBefore}" w:after="${spAfter}" w:line="300" w:lineRule="auto"/>${shading}${border}</w:pPr>` +
    `<w:r><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial"/>${bold}${italic}${color}${sz}</w:rPr>` +
    `<w:t xml:space="preserve">${escXml(text)}</w:t></w:r></w:p>`;
}

function wTable(headers, rows) {
  const cellXml = (text, isHdr, shade) => {
    const fill = isHdr ? "1B2A4A" : (shade ? "F1F5F9" : "FFFFFF");
    const col = isHdr ? "FFFFFF" : "1A1A2E";
    const bold = isHdr ? "<w:b/>" : "";
    return `<w:tc><w:tcPr>` +
      `<w:shd w:val="clear" w:color="auto" w:fill="${fill}"/>` +
      `<w:tcMar><w:top w:w="120" w:type="dxa"/><w:bottom w:w="120" w:type="dxa"/><w:left w:w="130" w:type="dxa"/><w:right w:w="130" w:type="dxa"/></w:tcMar>` +
      `<w:tcBorders><w:bottom w:val="single" w:sz="4" w:space="0" w:color="CBD5E1"/><w:top w:val="none"/><w:left w:val="none"/><w:right w:val="none"/></w:tcBorders>` +
      `<w:vAlign w:val="top"/></w:tcPr>` +
      `<w:p><w:pPr><w:spacing w:before="0" w:after="0" w:line="276" w:lineRule="auto"/></w:pPr>` +
      `<w:r><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial"/>${bold}<w:color w:val="${col}"/><w:sz w:val="20"/><w:szCs w:val="20"/></w:rPr>` +
      `<w:t xml:space="preserve">${escXml(text)}</w:t></w:r></w:p></w:tc>`;
  };
  const hdrRow = `<w:tr><w:trPr><w:tblHeader/><w:cantSplit/></w:trPr>${headers.map(h => cellXml(h, true, false)).join("")}</w:tr>`;
  const bodyRows = rows.map((r, i) =>
    `<w:tr><w:trPr><w:cantSplit/></w:trPr>${r.map(v => cellXml(v, false, i % 2 === 1)).join("")}</w:tr>`
  ).join("");
  return `<w:tbl><w:tblPr><w:tblW w:w="9648" w:type="dxa"/><w:tblBorders><w:top w:val="single" w:sz="8" w:color="1B2A4A"/><w:bottom w:val="single" w:sz="8" w:color="1B2A4A"/><w:insideH w:val="single" w:sz="4" w:color="CBD5E1"/><w:left w:val="none"/><w:right w:val="none"/><w:insideV w:val="none"/></w:tblBorders></w:tblPr>${hdrRow}${bodyRows}</w:tbl>`;
}

async function renderReportBarChartPng(items, titleText, subtitleText, valueFormatter) {
  if (!items.length || typeof document === "undefined") return null;
  // W=1360 at 6.5 in -> 32px font = 11.01pt on-page (>= 10.5pt floor)
  const W = 1360;
  const rowH = 66;
  const topPad = 118;
  const bottomPad = 28;
  const H = topPad + items.length * rowH + bottomPad;
  const leftW = 590;
  const rightW = 265;
  const barAreaW = W - leftW - rightW - 28;
  const maxVal = Math.max(...items.map(i => i.value), 1);

  const canvas = document.createElement("canvas");
  canvas.width = W;
  canvas.height = H;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;

  ctx.fillStyle = "#FFFFFF";
  ctx.fillRect(0, 0, W, H);
  ctx.strokeStyle = "#CBD5E1";
  ctx.lineWidth = 2;
  ctx.strokeRect(1, 1, W - 2, H - 2);

  // Title 38px (~13.1pt) and subtitle 32px (~11.0pt) at 6.5in displayed width
  ctx.fillStyle = "#1B2A4A";
  ctx.font = "bold 38px Arial, Helvetica, sans-serif";
  ctx.textAlign = "left";
  ctx.textBaseline = "top";
  ctx.fillText(titleText, 24, 18);

  ctx.fillStyle = "#4A4A5A";
  ctx.font = "32px Arial, Helvetica, sans-serif";
  ctx.fillText(subtitleText, 24, 66);

  ctx.strokeStyle = "#1B2A4A";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(24, topPad - 10);
  ctx.lineTo(W - 24, topPad - 10);
  ctx.stroke();

  const dispLabels = shortenChartLabels(items, 34);
  items.forEach((it, idx) => {
    const y = topPad + idx * rowH;
    const barY = y + 14;
    const barH = 36;
    const bw = Math.max(6, Math.round((it.value / maxVal) * barAreaW));
    const lbl = dispLabels[idx];

    if (idx % 2 === 1) {
      ctx.fillStyle = "#F8FAFC";
      ctx.fillRect(16, y + 2, W - 32, rowH - 4);
    }

    ctx.fillStyle = "#1A1A2E";
    ctx.font = "32px Arial, Helvetica, sans-serif";
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    ctx.fillText(lbl, leftW - 18, y + rowH / 2);

    ctx.fillStyle = "#E2E8F0";
    ctx.fillRect(leftW, barY, barAreaW, barH);

    ctx.fillStyle = "#1B2A4A";
    ctx.fillRect(leftW, barY, bw, barH);

    ctx.fillStyle = "#1B2A4A";
    ctx.font = "bold 32px Arial, Helvetica, sans-serif";
    ctx.textAlign = "left";
    ctx.fillText(valueFormatter(it), leftW + barAreaW + 16, y + rowH / 2);
  });

  const blob = await new Promise(resolve => canvas.toBlob(resolve, "image/png"));
  if (!blob) return null;
  const bytes = new Uint8Array(await blob.arrayBuffer());
  return { bytes, widthPx: W, heightPx: H };
}

function wDrawingImage(rId, widthIn, heightIn, altText) {
  const cx = Math.round(widthIn * 914400);
  const cy = Math.round(heightIn * 914400);
  return `<w:p><w:pPr><w:spacing w:before="80" w:after="140"/></w:pPr><w:r><w:drawing>` +
    `<wp:inline distT="0" distB="0" distL="0" distR="0" xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing">` +
    `<wp:extent cx="${cx}" cy="${cy}"/>` +
    `<wp:docPr id="1" name="ThemeChart" descr="${escXml(altText)}"/>` +
    `<wp:cNvGraphicFramePr><a:graphicFrameLocks xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" noChangeAspect="1"/></wp:cNvGraphicFramePr>` +
    `<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">` +
    `<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">` +
    `<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">` +
    `<pic:nvPicPr><pic:cNvPr id="0" name="chart1.png" descr="${escXml(altText)}"/><pic:cNvPicPr/></pic:nvPicPr>` +
    `<pic:blipFill><a:blip r:embed="${rId}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>` +
    `<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="${cx}" cy="${cy}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>` +
    `</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>`;
}

async function buildSummaryReportDocx(results, meta, groupMatrix, discovery, discoveryOverlap, excludedRows) {
  const parts = [];
  const nowIso = new Date().toISOString();
  const dateOnly = nowIso.slice(0, 10);
  const utcStamp = nowIso.slice(0, 19).replace("T", " ") + " Coordinated Universal Time (UTC)";
  const shortLabels = friendlyGroupLabels(Object.keys(results.file_hashes).sort());

  // Sort themes descending by matching turns, then groups reporting, then name
  const sortedFreqs = [...results.frequencies].sort(
    (a, b) => (b.matching_turns - a.matching_turns) || (b.documents_reporting - a.documents_reporting) || (a.domain_name < b.domain_name ? -1 : 1)
  );
  const labelMap = disambiguateThemeLabels(sortedFreqs.map(f => [f.domain_id, f.domain_name]));
  const dispThemeName = f => labelMap.get(String(f.domain_id)) || f.domain_name;
  const themesFound = sortedFreqs.filter(f => f.documents_reporting > 0).length;
  const matchedEntries = results.tagged_turns.filter(t => t.matched_domains && t.matched_domains.length > 0).length;
  const unmatchedEntries = Math.max(0, results.participant_turns_analyzed - matchedEntries);

  // ==========================================================================
  // FRONT HALF — EXECUTIVE SUMMARY (Plain English, Grade 6–7, Impersonal)
  // ==========================================================================
  parts.push(wPara("ATLAS Qualitative Summary Report", { size: 36, bold: true, color: "1B2A4A", before: 0, after: 40, keepNext: true }));
  parts.push(wPara(
    `Automated Text-to-Ledger Actuarial Synthesis (ATLAS) · Date: ${dateOnly} · Mode: ${meta.groupMode ? "Focus-Group Notes" : "Individual Responses"}`,
    { size: 20, color: "4A4A5A", before: 0, after: 140 }
  ));

  if (meta.isFixture) {
    parts.push(wPara(
      "SOFTWARE_TEST FIXTURE — Practice Data Notice: This report used built-in sample files. These counts show how the tool works. They are not real study findings.",
      { size: 22, bold: true, color: "7A321E", bg: "FDF3F0", borderLeft: "B4472E", before: 60, after: 140 }
    ));
  }

  // Section 1: Summary at a Glance
  parts.push(wPara("1. Summary at a Glance", { size: 28, bold: true, color: "1B2A4A", before: 140, after: 60, keepNext: true }));
  const unitNoun = meta.groupMode
    ? (results.total_documents === 1 ? "focus group" : "focus groups")
    : (results.total_documents === 1 ? "response unit" : "response units");
  const entryNoun = meta.groupMode ? "notes entries" : "written answers";
  const leadSentence = `This run read ${results.participant_turns_analyzed} ${entryNoun} across ${results.total_documents} ${unitNoun}. ` +
    `${themesFound} of ${sortedFreqs.length} active themes matched at least one entry, for ${results.quotes.length} total theme matches. ` +
    `Full run settings, file fingerprints, and quality checks sit in the Technical Appendix at the back of this report.`;
  parts.push(wPara(leadSentence, { size: 22, before: 40, after: 80 }));
  if (meta.blankSummary) {
    parts.push(wPara(`Survey coverage: ${meta.blankSummary}. Skipped blank cells count empty boxes on this question only, not overall study participation.`, { size: 22, before: 0, after: 100 }));
  }

  parts.push(wPara("Headline Counts", { size: 23, bold: true, color: "3E5872", before: 80, after: 40, keepNext: true }));
  const kpiRows = [
    [meta.groupMode ? "Focus Groups" : "Analytical Units", String(results.total_documents), meta.groupMode ? "1 uploaded file = 1 focus group" : "One unit per transcript or non-blank survey response"],
    ["Themes Found", `${themesFound} of ${sortedFreqs.length}`, "Active themes with at least one match"],
    [meta.entriesLabel || "Entries Scanned", String(results.participant_turns_analyzed), `${matchedEntries} matched a theme; ${unmatchedEntries} matched none`],
    ["Theme Matches", String(results.quotes.length), "Total entry-theme matches; one entry can match 2 or more themes"],
  ];
  parts.push(wTable(["Metric", "Value", "What It Counts"], kpiRows));

  // Section 2: Theme Summary and Chart
  parts.push(wPara("2. Theme Summary and Chart", { size: 28, bold: true, color: "1B2A4A", before: 180, after: 60, keepNext: true }));

  const chartItems = sortedFreqs.filter(f => f.matching_turns > 0).slice(0, 12).map(f => ({
    domain_id: f.domain_id,
    label: dispThemeName(f),
    value: meta.groupMode ? f.matching_turns : f.prevalence_pct,
    groups: f.documents_reporting,
    total: f.total_documents,
    matches: f.matching_turns,
  }));
  let chartAsset = null;
  if (chartItems.length) {
    const chartTitle = meta.groupMode ? "Matched Entries by Theme" : "Share of Units Mentioning Each Theme";
    const chartSub = meta.groupMode
      ? "Shows note volume per theme, not a count of individual people"
      : `Percent of ${results.total_documents} analytical units mentioning each theme`;
    const fmt = meta.groupMode
      ? it => `${it.matches} (${it.groups}/${it.total} groups)`
      : it => `${it.value.toFixed(1)}% (${it.matches})`;
    chartAsset = await renderReportBarChartPng(chartItems, chartTitle, chartSub, fmt);
    if (chartAsset) {
      const dispW = 6.5;
      const dispH = Number(((chartAsset.heightPx / chartAsset.widthPx) * dispW).toFixed(2));
      const alt = `Horizontal bar chart showing ${chartTitle.toLowerCase()}. Top themes: ${chartItems.slice(0, 5).map(i => `${i.label} (${fmt(i)})`).join("; ")}.`;
      parts.push(wDrawingImage("rIdChart1", dispW, dispH, alt));
    }
  } else {
    parts.push(wPara("No active themes matched any entry in this run.", { size: 22, italic: true, color: "4A4A5A", before: 40, after: 100 }));
  }

  if (meta.groupMode && groupMatrix && groupMatrix.groupCols.length) {
    parts.push(wPara("Which Focus Groups Mentioned Each Theme", { size: 23, bold: true, color: "3E5872", before: 120, after: 40, keepNext: true }));
    parts.push(wPara(
      "A checkmark (✓) shows that a group raised the theme, with the number of matching entries in parentheses. A dash (—) means no match. Entry counts show note detail, not how many people agreed.",
      { size: 22, italic: true, color: "4A4A5A", before: 0, after: 60, keepNext: true }
    ));
    const gridHeaders = ["Theme", ...groupMatrix.groupCols.map(g => shortLabels[g] || g), "Groups"];
    const gridRows = groupMatrix.rows.map(r => [
      labelMap.get(String(r.domain_id)) || r.theme_label,
      ...groupMatrix.groupCols.map(g => r.cells[g] > 0 ? `✓ (${r.cells[g]})` : "—"),
      `${r.groups_reporting}/${results.total_documents}`,
    ]);
    parts.push(wTable(gridHeaders, gridRows));
  }

  parts.push(wPara("Theme Counts Breakdown", { size: 23, bold: true, color: "3E5872", before: 120, after: 40, keepNext: true }));
  const sumHeaders = meta.groupMode
    ? ["Theme", "Focus Groups", "Theme Matches", "Direct Quotes", "Key Point Summaries", ...(meta.includeObservations ? ["Observations"] : [])]
    : ["Theme", "Units Mentioning", "Prevalence (%)", "Theme Matches"];
  const sumRows = sortedFreqs.map(f => {
    const dq = results.quotes.filter(q => q.domain_id === f.domain_id);
    const tName = dispThemeName(f);
    if (meta.groupMode) {
      const nVerb = dq.filter(q => VERBATIM_EVIDENCE_TYPES.has(String(q.evidence_type || ""))).length;
      const nPara = dq.filter(q => q.evidence_type === "key_point_paraphrase").length;
      const nObs = dq.filter(q => q.evidence_type === "observation").length;
      return [
        tName, `${f.documents_reporting} of ${f.total_documents}`, String(dq.length),
        String(nVerb), String(nPara), ...(meta.includeObservations ? [String(nObs)] : [])
      ];
    }
    return [tName, `${f.documents_reporting} of ${f.total_documents}`, `${f.prevalence_pct.toFixed(1)}%`, String(f.matching_turns)];
  });
  parts.push(wTable(sumHeaders, sumRows));

  // Section 3: Direct Quotes and Coded Evidence by Theme
  parts.push(wPara("3. Direct Quotes and Coded Evidence by Theme", { size: 28, bold: true, color: "1B2A4A", before: 180, after: 60, keepNext: true }));
  if (!results.quotes.length) {
    parts.push(wPara("No entries matched the active themes in this run.", { size: 22, italic: true, color: "4A4A5A" }));
  } else {
    parts.push(wPara(
      "Each row shows whether the text is a direct quote or a note-taker summary so summaries are not placed in quote marks by mistake.",
      { size: 22, italic: true, color: "4A4A5A", before: 0, after: 80, keepNext: true }
    ));
    for (const f of sortedFreqs) {
      const dq = results.quotes.filter(q => q.domain_id === f.domain_id);
      if (!dq.length) continue;
      // Direct quotes first, then summaries, then observations
      const rankOf = et => VERBATIM_EVIDENCE_TYPES.has(String(et || "")) ? 0 : et === "key_point_paraphrase" ? 1 : 2;
      const ordered = [...dq].sort((a, b) => rankOf(a.evidence_type) - rankOf(b.evidence_type));
      parts.push(wPara(`${dispThemeName(f)} (${dq.length} ${dq.length === 1 ? "match" : "matches"})`, { size: 23, bold: true, color: "0B5F5A", before: 120, after: 40, keepNext: true }));
      const evRows = ordered.slice(0, 25).map(q => {
        const evLabel = q.evidence_type === "notable_quote_verbatim" ? "Direct Quote"
          : q.evidence_type === "key_point_paraphrase" ? "Key Point Summary"
          : q.evidence_type === "observation" ? "Note-Taker Observation"
          : "Direct Response";
        const grp = shortLabels[q.source_id] || q.source_id;
        return [evLabel, `${grp} (Line ${q.line_number}, ${q.speaker})`, q.match_text, q.text];
      });
      parts.push(wTable(["Source Type", "Location", "Matched Word", "Entry Text"], evRows));
      if (dq.length > 25) {
        parts.push(wPara(`Showing the first 25 of ${dq.length} matches in this printable report. Open the Excel workbook or Comma-Separated Values (CSV) file to inspect all rows.`, { size: 20, italic: true, color: "4A4A5A", before: 40, after: 100 }));
      }
    }
  }

  // ==========================================================================
  // BACK HALF — TECHNICAL AND AUDIT APPENDIX (Clean Page Break)
  // ==========================================================================
  parts.push(wPara("Technical and Audit Appendix", { size: 32, bold: true, color: "1B2A4A", before: 0, after: 60, pageBreakBefore: true, keepNext: true }));
  parts.push(wPara(
    "This appendix records run settings, source file fingerprints, unlisted topic clusters, spot-check flags, and skipped lines for method review.",
    { size: 22, color: "4A4A5A", before: 0, after: 120 }
  ));

  // Appendix A: Run Settings & Source File Fingerprints
  parts.push(wPara("Appendix A. Run Settings and Source File Fingerprints", { size: 26, bold: true, color: "1B2A4A", before: 120, after: 60, keepNext: true }));
  const ovRows = [
    ["Analysis Mode", meta.groupMode ? "Group / Summarized Notes (1 file = 1 focus group)" : "Individual Analytical Units"],
    ["Run Timestamp", utcStamp],
    ["Active Themes", `${sortedFreqs.length} themes (${sortedFreqs.map(f => f.domain_name).join(", ")})`],
    ["Note-Taker Observations", meta.includeObservations ? "Included in coding" : "Excluded (Direct Quotes and Key Point Summaries only)"],
    ["Spelling Check", results.spelling_tolerance ? `On — 1-letter typo check (Damerau-Levenshtein distance 1; ${(results.typo_matches || []).length} occurrences)` : "Off"],
    ...(meta.sheetName ? [["Excel Tab", meta.sheetName]] : []),
    ...(meta.blankSummary ? [["Open-Ended Survey Coverage", meta.blankSummary]] : []),
  ];
  parts.push(wTable(["Setting", "Value"], ovRows));

  const fileRows = Object.entries(results.file_hashes).sort((a, b) => a[0].localeCompare(b[0])).map(([sid, sha]) => [shortLabels[sid] || sid, sid, sha.slice(0, 16) + "..."]);
  if (fileRows.length) {
    parts.push(wPara(
      "Each input file below carries a Secure Hash Algorithm 256-bit (SHA-256) digital fingerprint so reviewers can confirm the exact files used.",
      { size: 20, italic: true, color: "4A4A5A", before: 100, after: 40, keepNext: true }
    ));
    parts.push(wTable(["Short Label", "Full Source File Path", "SHA-256 Fingerprint Prefix"], fileRows));
  }

  // Appendix B: Unlisted Topic Clusters
  parts.push(wPara("Appendix B. Unlisted Topic Clusters", { size: 26, bold: true, color: "1B2A4A", before: 160, after: 60, keepNext: true }));
  if (discovery && discovery.topics && discovery.topics.length) {
    parts.push(wPara(
      "ATLAS grouped scanned entries by shared words using Non-Negative Matrix Factorization (NMF), without using the active theme checklist.",
      { size: 20, italic: true, color: "4A4A5A", before: 0, after: 60, keepNext: true }
    ));
    const dRows = discovery.topics.map(t => {
      const ov = (discoveryOverlap && discoveryOverlap[t.topic_id]) || {};
      return [`Cluster ${t.topic_id}: ${t.label}`, `${t.turn_count} of ${discovery.n_analyzed} (${t.share_pct}%)`, ov.badge || "", t.medoid_text];
    });
    parts.push(wTable(["Cluster", "Entries", "Coverage Status", "Most Representative Example"], dRows));
  } else {
    parts.push(wPara("No unsupervised topic clusters were computed for this run.", { size: 20, italic: true, color: "4A4A5A" }));
  }

  // Appendix C: Spot-Check Review Log
  parts.push(wPara("Appendix C. Spot-Check Review Log", { size: 26, bold: true, color: "1B2A4A", before: 160, after: 60, keepNext: true }));
  if (!results.audit_rows.length) {
    parts.push(wPara(`0 of ${results.quotes.length} theme matches were flagged for review.`, { size: 20, color: "0B5F5A" }));
  } else {
    parts.push(wPara(
      "All flagged matches remain counted in the summary tables above until an analyst excludes them.",
      { size: 20, italic: true, color: "4A4A5A", before: 0, after: 60, keepNext: true }
    ));
    const scRows = results.audit_rows.slice(0, 50).map(a => [
      a.flag_codes.includes("spelling_tolerance") ? "Check First (Spelling Match)"
        : a.risk_level === "High" ? "Check First (Partial-Word Match)"
        : "Check in Context",
      a.domain_name, a.matched_span, a.full_word, a.flag_reason
    ]);
    parts.push(wTable(["Review Priority", "Theme", "Matched", "Full Word", "Why Flagged"], scRows));
    if (results.audit_rows.length > 50) {
      parts.push(wPara(`Showing the first 50 of ${results.audit_rows.length} flagged matches in this printable summary. Download the Spot-Check Comma-Separated Values (CSV) report for the complete list.`, { size: 20, italic: true, color: "4A4A5A", before: 40, after: 100 }));
    }
  }

  // Appendix D: Skipped Questions & Session Headers
  parts.push(wPara("Appendix D. Skipped Questions and Session Headers", { size: 26, bold: true, color: "1B2A4A", before: 160, after: 60, keepNext: true }));
  if (!excludedRows || !excludedRows.length) {
    parts.push(wPara("No focus-group headers or question prompts were skipped in this run.", { size: 20, italic: true, color: "4A4A5A" }));
  } else {
    parts.push(wPara(
      `${excludedRows.length} structural header or question rows were skipped before coding so facilitator prompts do not enter theme counts.`,
      { size: 20, italic: true, color: "4A4A5A", before: 0, after: 60, keepNext: true }
    ));
    const exRows = excludedRows.slice(0, 60).map(e => [shortLabels[e.source_id] || e.source_id, String(e.location), friendlyExcludedReason(e.reason), e.text]);
    parts.push(wTable(["Source Group", "Row", "Why Skipped", "Skipped Text"], exRows));
    if (excludedRows.length > 60) {
      parts.push(wPara(`Showing the first 60 of ${excludedRows.length} skipped structural rows in this printable summary.`, { size: 20, italic: true, color: "4A4A5A", before: 40, after: 100 }));
    }
  }

  const docXml = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>` +
    `<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><w:body>` +
    parts.join("") +
    `<w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1296" w:right="1296" w:bottom="1296" w:left="1296"/></w:sectPr>` +
    `</w:body></w:document>`;

  const entries = new Map();
  entries.set("[Content_Types].xml",
    `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>` +
    `<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">` +
    `<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>` +
    `<Default Extension="xml" ContentType="application/xml"/>` +
    (chartAsset ? `<Default Extension="png" ContentType="image/png"/>` : "") +
    `<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>` +
    `</Types>`
  );
  entries.set("_rels/.rels",
    `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>` +
    `<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">` +
    `<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>` +
    `</Relationships>`
  );
  if (chartAsset) {
    entries.set("word/_rels/document.xml.rels",
      `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>` +
      `<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">` +
      `<Relationship Id="rIdChart1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/chart1.png"/>` +
      `</Relationships>`
    );
    entries.set("word/media/chart1.png", chartAsset.bytes);
  }
  entries.set("word/document.xml", docXml);

  return writeZipArchive(entries, "application/vnd.openxmlformats-officedocument.wordprocessingml.document");
}
