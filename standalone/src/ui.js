// ============================================================================
// ATLAS Standalone Browser UI — Concept 2 Open Hairline Editorial Workbench
// Zero decorative icons/emojis, WCAG 2.1 AA, 100% offline, instant recoding
// ============================================================================

function escHtml(s) {
  return String(s === null || s === undefined ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function triggerDownload(blobOrText, filename, mimeType) {
  const blob = blobOrText instanceof Blob ? blobOrText : new Blob([blobOrText], { type: mimeType || "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { document.body.removeChild(a); URL.revokeObjectURL(url); }, 1000);
}

const APP_STATE = {
  files: [], // [{ name, sourceId, bytes: Uint8Array, ext, isStructuredNotes, xlsxInfo?, csvInfo? }]
  isFixture: false,
  groupMode: true,
  includeObservations: false,
  spellingTolerance: false,
  // Tabular options
  sheetName: "",
  textCol: "",
  idCol: "",
  speakerCol: "",
  duplicateIdPolicy: "per_row",
  tabularHasDupIds: false,
  tabularError: null,
  // Theme selections
  selectedCore: new Set(ATLAS_CORE_THEMES.map(r => r.id)),
  selectedAddon: new Set(),
  uploadedYamlName: "",
  uploadedYamlRules: null,
  uploadMode: "replace", // "replace" | "combine"
  sessionRulesOverride: null,
  sessionOverrideLabel: "",
  // Analysis results
  dirty: false,
  runError: null,
  results: null,
  runMeta: null,
  groupMatrix: null,
  excludedRows: [],
  noteTakerThemes: [],
  discovery: null,
  discoveryOverlap: null,
  discoveryK: 4,
  // UI navigation & view controls
  activeTab: "themes", // "themes" | "exports" | "guide"
  activeSubtab: "summary", // "summary" | "evidence" | "discover" | "spotcheck"
  gridShowEntries: false,
  hideZeroThemes: false,
  evFilterTheme: "__all__",
  evFilterFile: "__all__",
  evFilterSpeaker: "__all__",
  evFilterQuestion: "__all__",
  evVerbatimOnly: false,
  evSearch: "",
  evPage: 1,
  evPageSize: 50,
  evShowAll: false,
  scFilterPriority: "__all__",
  scFilterTheme: "__all__",
  scPage: 1,
  scPageSize: 50,
  scShowAll: false,
  spotcheckDomainId: "",
  spotcheckSelectedWords: new Set(),
  spotcheckSetExact: false,
  addTopicId: null,
  addTopicName: "",
  addTopicExact: true,
};

// ----------------------------------------------------------------------------
// File Ingestion & Inspection
// ----------------------------------------------------------------------------
async function inspectFileRecord(name, bytes, sourceIdOverride) {
  const dot = name.lastIndexOf(".");
  const ext = dot >= 0 ? name.slice(dot).toLowerCase() : "";
  const sourceId = sourceIdOverride || name;
  const rec = { name, sourceId, bytes, ext, isStructuredNotes: false, xlsxInfo: null, csvInfo: null, docxBlocks: null };

  if (ext === ".docx") {
    const entries = await readZipEntries(bytes);
    if (!entries.has("word/document.xml")) throw new Error(`'${name}' is not a valid Word (.docx) file.`);
    const docXml = new DOMParser().parseFromString(new TextDecoder("utf-8").decode(entries.get("word/document.xml")), "application/xml");
    const blocks = extractDocxBlocks(docXml);
    rec.docxBlocks = blocks;
    rec.isStructuredNotes = isStructuredNotesBlocks(blocks);
  } else if (ext === ".xlsx") {
    rec.xlsxInfo = await readXlsxWorkbook(bytes);
  } else if (ext === ".csv") {
    rec.csvInfo = parseCsvRows(new TextDecoder("utf-8").decode(bytes));
  } else if (!TRANSCRIPT_EXTENSIONS.has(ext)) {
    throw new Error(`Unsupported file type '${ext || "(none)"}' on '${name}'. Upload .docx, .xlsx, .csv, .txt, or .vtt.`);
  }
  return rec;
}

function refreshTabularPreviewState() {
  const tabFiles = APP_STATE.files.filter(f => TABULAR_EXTENSIONS.has(f.ext));
  APP_STATE.tabularError = null;
  APP_STATE.tabularHasDupIds = false;
  if (!tabFiles.length) return;

  const xlsxFiles = tabFiles.filter(f => f.ext === ".xlsx");
  if (xlsxFiles.length) {
    let commonSheets = [...xlsxFiles[0].xlsxInfo.sheetNames];
    for (let i = 1; i < xlsxFiles.length; i++) {
      const sSet = new Set(xlsxFiles[i].xlsxInfo.sheetNames);
      commonSheets = commonSheets.filter(s => sSet.has(s));
    }
    if (!commonSheets.length) {
      APP_STATE.tabularError = "Uploaded Excel workbooks have different sheet names. Upload workbooks with differing tab layouts one at a time.";
      return;
    }
    if (!commonSheets.includes(APP_STATE.sheetName)) APP_STATE.sheetName = commonSheets[0];
  } else {
    APP_STATE.sheetName = "";
  }

  const parsedTables = tabFiles.map(f =>
    f.ext === ".xlsx" ? f.xlsxInfo.parseSheet(APP_STATE.sheetName) : { sheetName: "", ...f.csvInfo }
  );
  let commonCols = [...parsedTables[0].headers];
  for (let i = 1; i < parsedTables.length; i++) {
    const cSet = new Set(parsedTables[i].headers);
    commonCols = commonCols.filter(c => cSet.has(c));
  }
  if (!commonCols.length) {
    APP_STATE.tabularError = "Uploaded survey tables do not share a common column header. Upload tables with different layouts separately.";
    return;
  }
  if (!commonCols.includes(APP_STATE.textCol)) {
    APP_STATE.textCol = detectBestTextColumn(commonCols, parsedTables[0].dataRows);
  }
  if (APP_STATE.idCol && !commonCols.includes(APP_STATE.idCol)) APP_STATE.idCol = "";
  if (APP_STATE.speakerCol && !commonCols.includes(APP_STATE.speakerCol)) APP_STATE.speakerCol = "";

  // Check duplicate IDs in idCol if selected
  if (APP_STATE.idCol) {
    for (const pt of parsedTables) {
      const seen = new Set();
      for (const r of pt.dataRows) {
        const textVal = String(r.values[APP_STATE.textCol] || "").trim();
        if (!textVal) continue;
        const idVal = String(r.values[APP_STATE.idCol] || "").trim();
        if (idVal) {
          if (seen.has(idVal)) { APP_STATE.tabularHasDupIds = true; break; }
          seen.add(idVal);
        }
      }
    }
  }
}

async function loadFilesFromUser(fileList) {
  APP_STATE.runError = null;
  const loaded = [];
  const usedNames = new Set();
  for (const file of Array.from(fileList)) {
    let sid = file.name;
    let n = 2;
    while (usedNames.has(sid)) { sid = `${file.name} (${n++})`; }
    usedNames.add(sid);
    const buf = await file.arrayBuffer();
    loaded.push(await inspectFileRecord(file.name, new Uint8Array(buf), sid));
  }
  APP_STATE.files = loaded;
  APP_STATE.isFixture = false;
  APP_STATE.groupMode = loaded.some(f => f.isStructuredNotes);
  APP_STATE.sheetName = "";
  APP_STATE.textCol = "";
  APP_STATE.idCol = "";
  APP_STATE.speakerCol = "";
  APP_STATE.duplicateIdPolicy = "per_row";
  refreshTabularPreviewState();
  APP_STATE.dirty = true;
  renderAll();
}

async function loadSampleFocusGroupNotes() {
  APP_STATE.runError = null;
  const loaded = [];
  for (const s of ATLAS_SAMPLE_FILES) {
    const bytes = base64ToUint8Array(s.base64);
    loaded.push(await inspectFileRecord(s.name, bytes, s.source_id));
  }
  APP_STATE.files = loaded;
  APP_STATE.isFixture = true;
  APP_STATE.groupMode = true;
  APP_STATE.includeObservations = false;
  APP_STATE.tabularError = null;
  APP_STATE.dirty = true;
  renderAll();
}

function getEffectiveRules() {
  if (APP_STATE.sessionRulesOverride) return APP_STATE.sessionRulesOverride;
  const rules = [];
  const seenIds = new Set();
  const pushRule = r => {
    let id = r.id, idx = 2;
    while (seenIds.has(id)) id = `${r.id}_${idx++}`;
    seenIds.add(id);
    rules.push({ ...r, id });
  };
  if (APP_STATE.uploadedYamlRules && APP_STATE.uploadMode === "replace") {
    APP_STATE.uploadedYamlRules.forEach(pushRule);
    return rules;
  }
  ATLAS_CORE_THEMES.filter(r => APP_STATE.selectedCore.has(r.id)).forEach(pushRule);
  ATLAS_ADDON_THEMES.filter(r => APP_STATE.selectedAddon.has(r.id)).forEach(pushRule);
  if (APP_STATE.uploadedYamlRules && APP_STATE.uploadMode === "combine") {
    APP_STATE.uploadedYamlRules.forEach(pushRule);
  }
  return rules;
}

function groupLabelsFor(sourceIds) {
  return friendlyGroupLabels(sourceIds);
}

function buildGroupMatrix(results) {
  const groupCols = Object.keys(results.file_hashes).sort();
  const groupLabels = groupLabelsFor(groupCols);
  const labelMap = disambiguateThemeLabels(results.frequencies.map(f => [f.domain_id, f.domain_name]));
  const rows = results.frequencies.map(f => {
    const label = labelMap.get(String(f.domain_id)) || f.domain_name;
    const cells = {};
    for (const g of groupCols) {
      cells[g] = results.quotes.filter(q => q.domain_id === f.domain_id && q.source_id === g).length;
    }
    return {
      domain_id: f.domain_id,
      domain_name: f.domain_name,
      theme_label: label,
      groups_reporting: f.documents_reporting,
      matching_turns: f.matching_turns,
      cells,
    };
  });
  rows.sort((a, b) => (b.matching_turns - a.matching_turns) || (b.groups_reporting - a.groups_reporting) || (a.theme_label < b.theme_label ? -1 : 1));
  return { groupCols, groupLabels, rows };
}

function executeAnalysis(preserveSessionOverride = false) {
  APP_STATE.runError = null;
  if (!preserveSessionOverride) {
    APP_STATE.sessionRulesOverride = null;
    APP_STATE.sessionOverrideLabel = "";
  }
  if (!APP_STATE.files.length) {
    APP_STATE.runError = "Upload one or more files—or load the built-in Focus-Group Notes sample—before clicking Run Analysis.";
    APP_STATE.results = null;
    renderAll();
    return;
  }
  refreshTabularPreviewState();
  if (APP_STATE.tabularError) {
    APP_STATE.runError = APP_STATE.tabularError;
    APP_STATE.results = null;
    renderAll();
    return;
  }
  const rules = getEffectiveRules();
  if (!rules.length) {
    APP_STATE.runError = "Select at least one theme—or upload a custom theme file—before clicking Run Analysis.";
    APP_STATE.results = null;
    renderAll();
    return;
  }

  try {
    const includeEv = APP_STATE.includeObservations ? WITH_OBS_NOTES_EVIDENCE_TYPES : DEFAULT_NOTES_EVIDENCE_TYPES;
    const allTurns = [];
    const fileHashes = {};
    const excludedRows = [];
    const noteTakerThemes = [];
    const tabularStats = [];
    const structures = {};

    for (const f of APP_STATE.files) {
      fileHashes[f.sourceId] = sha256Bytes(f.bytes);
      let parsed;
      if (f.ext === ".docx") {
        if (f.isStructuredNotes) {
          parsed = parseStructuredNotesBlocks(f.docxBlocks, f.name, f.sourceId, includeEv);
        } else {
          const lines = [];
          for (const b of f.docxBlocks) {
            if (b.rows === null) lines.push(b.para);
            else for (const r of b.rows) lines.push(r.filter(Boolean).join(" "));
          }
          parsed = parsePlainTranscriptLines(lines, f.name, f.sourceId, [], []);
        }
      } else if (f.ext === ".vtt" || f.ext === ".srt") {
        parsed = parseVttText(new TextDecoder("utf-8").decode(f.bytes), f.name, f.sourceId, [], []);
      } else if (f.ext === ".txt" || f.ext === ".md") {
        const lines = new TextDecoder("utf-8").decode(f.bytes).replace(/\r\n/g, "\n").split("\n");
        parsed = parsePlainTranscriptLines(lines, f.name, f.sourceId, [], []);
      } else if (f.ext === ".xlsx") {
        const tbl = f.xlsxInfo.parseSheet(APP_STATE.sheetName);
        parsed = parseTabularData(tbl, f.name, f.sourceId, {
          textCol: APP_STATE.textCol,
          idCol: APP_STATE.idCol,
          speakerCol: APP_STATE.speakerCol,
          duplicateIdPolicy: APP_STATE.duplicateIdPolicy,
        });
      } else if (f.ext === ".csv") {
        parsed = parseTabularData({ sheetName: "", ...f.csvInfo }, f.name, f.sourceId, {
          textCol: APP_STATE.textCol,
          idCol: APP_STATE.idCol,
          speakerCol: APP_STATE.speakerCol,
          duplicateIdPolicy: APP_STATE.duplicateIdPolicy,
        });
      }

      structures[f.sourceId] = parsed.structure;
      allTurns.push(...parsed.turns);
      if (parsed.metadata && Array.isArray(parsed.metadata.excluded_structural_rows)) {
        for (const ex of parsed.metadata.excluded_structural_rows) {
          excludedRows.push({ source_id: f.sourceId, ...ex });
        }
      }
      if (parsed.noteTakerThemes && parsed.noteTakerThemes.length) {
        noteTakerThemes.push(...parsed.noteTakerThemes);
      }
      if (parsed.tabularStats) tabularStats.push(parsed.tabularStats);
    }

    const results = runAtlasEngine(allTurns, fileHashes, rules, {
      groupBySource: APP_STATE.groupMode,
      spellingTolerance: APP_STATE.spellingTolerance,
    });

    const allStructNotes = Object.values(structures).length > 0 && Object.values(structures).every(s => s === "focus_group_notes");
    const allTabular = Object.values(structures).length > 0 && Object.values(structures).every(s => s === "tabular");
    const entriesLabel = APP_STATE.groupMode
      ? (allStructNotes ? "Notes Entries Scanned" : "Entries Scanned")
      : (allTabular ? "Written Answers Scanned" : "Turns Scanned");

    let blankSummary = "";
    if (tabularStats.length) {
      const nonBlank = tabularStats.reduce((s, x) => s + x.non_blank_rows, 0);
      const skipped = tabularStats.reduce((s, x) => s + x.skipped_blank_rows, 0);
      const uniq = tabularStats.reduce((s, x) => s + x.unique_units, 0);
      if (APP_STATE.idCol && APP_STATE.duplicateIdPolicy === "combine" && uniq !== nonBlank) {
        blankSummary = `${nonBlank} written answers across ${uniq} unique respondents (${skipped} rows left this question blank)`;
      } else {
        blankSummary = `${nonBlank} written answers scanned (${skipped} rows left this question blank)`;
      }
    }

    APP_STATE.results = results;
    APP_STATE.groupMatrix = APP_STATE.groupMode ? buildGroupMatrix(results) : null;
    APP_STATE.excludedRows = excludedRows;
    APP_STATE.noteTakerThemes = noteTakerThemes;
    APP_STATE.runMeta = {
      groupMode: APP_STATE.groupMode,
      includeObservations: APP_STATE.includeObservations,
      isFixture: APP_STATE.isFixture,
      corpusLabel: APP_STATE.isFixture ? "Sample: Multi-Group Focus-Group Notes (.docx)" : APP_STATE.files.map(f => f.name).join(", "),
      sheetName: APP_STATE.sheetName || null,
      entriesLabel,
      blankSummary,
      allStructNotes,
      hasNotes: Object.values(structures).includes("focus_group_notes"),
    };

    // Offline topic discovery
    const disc = discoverTopicsOffline(results.tagged_turns, APP_STATE.discoveryK);
    const domainNames = new Map(results.frequencies.map(f => [f.domain_id, f.domain_name]));
    APP_STATE.discovery = disc;
    APP_STATE.discoveryOverlap = computeTopicCodebookOverlap(disc, results.tagged_turns, domainNames);
    APP_STATE.dirty = false;
    APP_STATE.evPage = 1;
    APP_STATE.evShowAll = false;
    APP_STATE.scPage = 1;
    APP_STATE.scShowAll = false;

    // Reset spot-check selection if domain no longer flagged
    const flaggedIds = new Set(results.audit_rows.map(a => a.domain_id));
    if (!flaggedIds.has(APP_STATE.spotcheckDomainId)) {
      APP_STATE.spotcheckDomainId = results.audit_rows.length ? results.audit_rows[0].domain_id : "";
      APP_STATE.spotcheckSelectedWords = new Set();
    }
  } catch (err) {
    APP_STATE.runError = String(err && err.message ? err.message : err);
    APP_STATE.results = null;
  }
  renderAll();
}

// ----------------------------------------------------------------------------
// Inline SVG Charts (Zero Altair / Zero External Libraries / Sharp at any Zoom)
// ----------------------------------------------------------------------------
function renderHorizontalBarSvg(items, valueMax, xAxisLabel, valueFormatter, opts = {}) {
  if (!items.length) return `<p class="ed-hint">No themes to display.</p>`;
  const svgId = opts.id || "";
  const titleText = opts.title || xAxisLabel;
  const rowH = 34;
  const leftW = 260;
  const barAreaW = 460;
  const rightW = 135;
  const totalW = leftW + barAreaW + rightW;
  const topPad = 14;
  const bottomPad = 38;
  const svgH = topPad + items.length * rowH + bottomPad;
  const safeMax = Math.max(valueMax, 1);

  const descSummary = items.map(it => `${it.label}: ${valueFormatter(it)}`).join("; ");
  const dispLabels = shortenChartLabels(items, 34);
  const rowsSvg = items.map((it, idx) => {
    const y = topPad + idx * rowH;
    const bw = Math.max(it.value > 0 ? 3 : 0, (it.value / safeMax) * barAreaW);
    const ciLine = (it.ciLow !== undefined && it.ciHigh !== undefined)
      ? `<line x1="${leftW + (it.ciLow / safeMax) * barAreaW}" y1="${y + 13}" x2="${leftW + (it.ciHigh / safeMax) * barAreaW}" y2="${y + 13}" stroke="#0B5F5A" stroke-width="2.5"/>` +
        `<line x1="${leftW + (it.ciLow / safeMax) * barAreaW}" y1="${y + 9}" x2="${leftW + (it.ciLow / safeMax) * barAreaW}" y2="${y + 17}" stroke="#0B5F5A" stroke-width="2"/>` +
        `<line x1="${leftW + (it.ciHigh / safeMax) * barAreaW}" y1="${y + 9}" x2="${leftW + (it.ciHigh / safeMax) * barAreaW}" y2="${y + 17}" stroke="#0B5F5A" stroke-width="2"/>`
      : "";
    const dispLabel = dispLabels[idx];
    return `<g>` +
      `<text x="${leftW - 12}" y="${y + 17}" text-anchor="end" font-family="-apple-system, BlinkMacSystemFont, Segoe UI, Arial, sans-serif" font-size="13" font-weight="600" fill="#1B2A4A">${escHtml(dispLabel)}<title>${escHtml(it.label)}</title></text>` +
      `<rect x="${leftW}" y="${y + 4}" width="${barAreaW}" height="18" fill="#F8FAFC" rx="2"/>` +
      `<rect x="${leftW}" y="${y + 4}" width="${bw.toFixed(1)}" height="18" fill="#1B2A4A" rx="2"><title>${escHtml(it.label)}: ${escHtml(valueFormatter(it))}</title></rect>` +
      ciLine +
      `<text x="${(leftW + bw + 8).toFixed(1)}" y="${y + 17}" font-family="-apple-system, BlinkMacSystemFont, Segoe UI, Arial, sans-serif" font-size="12.5" font-weight="700" fill="#1A1A2E">${escHtml(valueFormatter(it))}</text>` +
      `</g>`;
  }).join("");

  const axisY = topPad + items.length * rowH + 6;
  const idAttr = svgId ? ` id="${escHtml(svgId)}"` : "";
  return `<div class="ed-svg-wrap"><svg${idAttr} xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${totalW} ${svgH}" width="${totalW}" height="${svgH}" style="width:100%;max-width:${totalW}px;height:auto;display:block;" role="img" aria-label="${escHtml(titleText)}">` +
    `<title>${escHtml(titleText)}</title><desc>${escHtml(descSummary)}</desc>` +
    `<rect x="0" y="0" width="${totalW}" height="${svgH}" fill="#FFFFFF"/>` +
    `${rowsSvg}` +
    `<line x1="${leftW}" y1="${axisY}" x2="${leftW + barAreaW}" y2="${axisY}" stroke="#64748B" stroke-width="1"/>` +
    `<text x="${leftW + barAreaW / 2}" y="${axisY + 22}" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, Segoe UI, Arial, sans-serif" font-size="12" fill="#4A4A5A">${escHtml(xAxisLabel)}</text>` +
    `</svg></div>`;
}

function getCsvDownloadSpec(res) {
  const quotes = (res && res.quotes) || [];
  const notableRows = quotes.filter(q => q.evidence_type === "notable_quote_verbatim");
  const verbatimRows = quotes.filter(q => VERBATIM_EVIDENCE_TYPES.has(String(q.evidence_type || "")));
  const hasNotable = notableRows.length > 0;
  const hasTurns = verbatimRows.length > notableRows.length;
  if (hasNotable && !hasTurns) {
    return { label: "Download Direct Quotes (.csv)", filename: "direct_quotes_inventory.csv", rows: notableRows };
  }
  if (hasTurns && !hasNotable) {
    return { label: "Download Verbatim Entries (.csv)", filename: "verbatim_entries_inventory.csv", rows: verbatimRows };
  }
  if (hasNotable && hasTurns) {
    return { label: "Download Verbatim Quotes & Turns (.csv)", filename: "verbatim_quotes_and_turns.csv", rows: verbatimRows };
  }
  return { label: "Download Coded Evidence (.csv)", filename: "coded_evidence_inventory.csv", rows: quotes };
}

// ----------------------------------------------------------------------------
// Main Renderers
// ----------------------------------------------------------------------------
function renderSetupSection() {
  const tabFiles = APP_STATE.files.filter(f => TABULAR_EXTENSIONS.has(f.ext));
  const xlsxFiles = tabFiles.filter(f => f.ext === ".xlsx");
  let tabularHtml = "";

  if (tabFiles.length) {
    if (APP_STATE.tabularError) {
      tabularHtml = `<div class="ed-tabular-box"><div class="ed-notice rust">${escHtml(APP_STATE.tabularError)}</div></div>`;
    } else {
      let commonSheets = [];
      if (xlsxFiles.length) {
        commonSheets = [...xlsxFiles[0].xlsxInfo.sheetNames];
        for (let i = 1; i < xlsxFiles.length; i++) {
          const s = new Set(xlsxFiles[i].xlsxInfo.sheetNames);
          commonSheets = commonSheets.filter(n => s.has(n));
        }
      }
      const parsed0 = tabFiles[0].ext === ".xlsx" ? tabFiles[0].xlsxInfo.parseSheet(APP_STATE.sheetName) : { ...tabFiles[0].csvInfo };
      let commonCols = [...parsed0.headers];
      for (let i = 1; i < tabFiles.length; i++) {
        const pt = tabFiles[i].ext === ".xlsx" ? tabFiles[i].xlsxInfo.parseSheet(APP_STATE.sheetName) : { ...tabFiles[i].csvInfo };
        const cs = new Set(pt.headers);
        commonCols = commonCols.filter(c => cs.has(c));
      }
      // Compute blank-row preview count
      let nonBlank = 0, blank = 0;
      for (const f of tabFiles) {
        const pt = f.ext === ".xlsx" ? f.xlsxInfo.parseSheet(APP_STATE.sheetName) : { ...f.csvInfo };
        for (const r of pt.dataRows) {
          if (String(r.values[APP_STATE.textCol] || "").trim()) nonBlank++; else blank++;
        }
      }
      const sheetPicker = commonSheets.length > 1
        ? `<div class="ed-inline-field"><label for="sel-sheet">Excel Tab</label><select id="sel-sheet" class="ed-select">${commonSheets.map(s => `<option value="${escHtml(s)}" ${s === APP_STATE.sheetName ? "selected" : ""}>${escHtml(s)}</option>`).join("")}</select></div>`
        : "";
      const dupPicker = (APP_STATE.idCol && APP_STATE.tabularHasDupIds)
        ? `<div class="ed-controls-row" style="margin-top:10px;"><span class="ed-gutter-index" style="margin:0;">Repeated IDs detected:</span><div class="ed-radio-group">` +
          `<label class="ed-radio-opt"><input type="radio" name="dup-policy" value="per_row" ${APP_STATE.duplicateIdPolicy === "per_row" ? "checked" : ""}> Keep each row as its own response</label>` +
          `<label class="ed-radio-opt"><input type="radio" name="dup-policy" value="combine" ${APP_STATE.duplicateIdPolicy === "combine" ? "checked" : ""}> Combine repeated rows under one Respondent ID</label>` +
          `</div></div>`
        : "";

      tabularHtml = `<div class="ed-tabular-box">` +
        `<div class="ed-tabular-grid">${sheetPicker}` +
        `<div class="ed-inline-field"><label for="sel-text-col">Open-Ended Response Column</label><select id="sel-text-col" class="ed-select">${commonCols.map(c => `<option value="${escHtml(c)}" ${c === APP_STATE.textCol ? "selected" : ""}>${escHtml(c)}</option>`).join("")}</select></div>` +
        `<div class="ed-inline-field"><label for="sel-id-col">Respondent ID Column (optional)</label><select id="sel-id-col" class="ed-select"><option value="">(None — 1 row = 1 response)</option>${commonCols.map(c => `<option value="${escHtml(c)}" ${c === APP_STATE.idCol ? "selected" : ""}>${escHtml(c)}</option>`).join("")}</select></div>` +
        `<div class="ed-inline-field"><label for="sel-spk-col">Speaker / Group Column (optional)</label><select id="sel-spk-col" class="ed-select"><option value="">(None)</option>${commonCols.map(c => `<option value="${escHtml(c)}" ${c === APP_STATE.speakerCol ? "selected" : ""}>${escHtml(c)}</option>`).join("")}</select></div>` +
        `</div>` +
        `<p class="ed-hint"><strong>${nonBlank} written answers scanned (${blank} rows left this question blank).</strong></p>` +
        dupPicker + `</div>`;
    }
  }

  const chipsHtml = APP_STATE.files.length
    ? `<div class="ed-file-chips">${APP_STATE.files.map((f, i) =>
        `<span class="ed-chip"><span>${escHtml(f.name)}</span><span class="ed-chip-tag">${f.isStructuredNotes ? "3-col notes" : f.ext.replace(".", "")}</span>` +
        `<button type="button" class="ed-chip-rm" data-rm-file="${i}" aria-label="Remove ${escHtml(f.name)}">×</button></span>`
      ).join("")}</div>`
    : `<p class="ed-hint">Word focus-group notes (.docx), transcripts (.docx, .txt, .vtt), or Excel/CSV surveys (1 row per person, any columns — no 3-column reformatting needed).</p>`;

  const effRules = getEffectiveRules();
  const activeSelLine = APP_STATE.sessionRulesOverride
    ? `In-app edit active: ${APP_STATE.sessionOverrideLabel} (${effRules.length} themes)`
    : (APP_STATE.uploadedYamlRules && APP_STATE.uploadMode === "replace")
      ? `Active selection: custom file (${APP_STATE.uploadedYamlName}, ${effRules.length} themes)`
      : APP_STATE.uploadedYamlRules
        ? `Active selection: ${APP_STATE.selectedCore.size + APP_STATE.selectedAddon.size} checked themes + ${APP_STATE.uploadedYamlName} (${effRules.length} total)`
        : `Active selection: ${effRules.length} ${effRules.length === 1 ? "theme" : "themes"}`;

  return `<section class="ed-setup-section" aria-label="Analysis setup">
    <div class="ed-row">
      <div>
        <div class="ed-gutter-index">01 · Files &amp; Mode</div>
        <div class="ed-gutter-heading">Input Files</div>
        <div class="ed-gutter-note">All parsing runs locally in your browser tab. No files leave your machine.</div>
      </div>
      <div>
        <div class="ed-intake-bar" id="dropzone">
          <label class="ed-file-input-label">Choose files (.docx, .xlsx, .csv, .txt, .vtt)<input type="file" id="file-input" multiple accept=".docx,.xlsx,.csv,.txt,.vtt,.srt,.md"></label>
          <span class="ed-sep">|</span>
          <span class="ed-hint" style="margin:0;">or drag &amp; drop here</span>
          <span class="ed-sep">|</span>
          <button type="button" class="ed-text-btn" id="btn-load-sample">Load Sample Focus-Group Notes (2 files)</button>
        </div>
        ${chipsHtml}
        <div class="ed-controls-row">
          <div class="ed-radio-group" role="radiogroup" aria-label="Data Type">
            <label class="ed-radio-opt"><input type="radio" name="data-type" value="group" ${APP_STATE.groupMode ? "checked" : ""}> Group / summarized notes (1 file = 1 group)</label>
            <label class="ed-radio-opt"><input type="radio" name="data-type" value="individual" ${!APP_STATE.groupMode ? "checked" : ""}> Individual transcripts / survey responses</label>
          </div>
        </div>
        <div class="ed-controls-row">
          ${APP_STATE.groupMode ? `<label class="ed-check-opt"><input type="checkbox" id="chk-obs" ${APP_STATE.includeObservations ? "checked" : ""}> Include Note-Taker Observations</label>` : ""}
          <label class="ed-check-opt"><input type="checkbox" id="chk-spelling" ${APP_STATE.spellingTolerance ? "checked" : ""}> Allow minor spelling typos (useful for open-ended surveys)</label>
        </div>
        ${tabularHtml}
      </div>
    </div>

    <div class="ed-row">
      <div>
        <div class="ed-gutter-index">02 · Themes to Code</div>
        <div class="ed-gutter-heading">Theme Rules</div>
        <div class="ed-gutter-note">${escHtml(activeSelLine)}</div>
        ${APP_STATE.sessionRulesOverride ? `<div style="margin-top:8px;"><button type="button" class="ed-text-btn rust" id="btn-reset-edits">Reset in-app theme edits</button></div>` : ""}
      </div>
      <div>
        <details class="ed-drawer" id="drawer-core">
          <summary>Core Evaluation Themes (${APP_STATE.selectedCore.size} of ${ATLAS_CORE_THEMES.length})</summary>
          <div class="ed-drawer-body">
            <div class="ed-drawer-actions">
              <button type="button" class="ed-text-btn" id="btn-core-all">Select all</button>
              <span class="ed-sep">|</span>
              <button type="button" class="ed-text-btn rust" id="btn-core-clear">Clear</button>
            </div>
            <div class="ed-theme-grid">
              ${ATLAS_CORE_THEMES.map(r => `<label class="ed-check-opt" title="${escHtml(r.description)}"><input type="checkbox" data-core-id="${escHtml(r.id)}" ${APP_STATE.selectedCore.has(r.id) ? "checked" : ""}> ${escHtml(r.name)}</label>`).join("")}
            </div>
          </div>
        </details>

        <details class="ed-drawer" id="drawer-addon">
          <summary>Optional Add-On Themes (${APP_STATE.selectedAddon.size} of ${ATLAS_ADDON_THEMES.length})</summary>
          <div class="ed-drawer-body">
            <p class="ed-hint" style="margin-top:0;">Program delivery and policy friction themes (zero overlap with Core themes).</p>
            <div class="ed-drawer-actions">
              <button type="button" class="ed-text-btn" id="btn-addon-all">Select all</button>
              <span class="ed-sep">|</span>
              <button type="button" class="ed-text-btn rust" id="btn-addon-clear">Clear</button>
            </div>
            <div class="ed-theme-grid">
              ${ATLAS_ADDON_THEMES.map(r => `<label class="ed-check-opt" title="${escHtml(r.description)}"><input type="checkbox" data-addon-id="${escHtml(r.id)}" ${APP_STATE.selectedAddon.has(r.id) ? "checked" : ""}> ${escHtml(r.name)}</label>`).join("")}
            </div>
          </div>
        </details>

        <details class="ed-drawer" id="drawer-custom">
          <summary>Upload Custom Themes (.yaml)${APP_STATE.uploadedYamlName ? ` — ${escHtml(APP_STATE.uploadedYamlName)}` : ""}</summary>
          <div class="ed-drawer-body">
            <div class="ed-controls-row" style="margin-top:0;">
              <label class="ed-file-input-label">Choose custom theme file (.yaml / .yml / .json)<input type="file" id="yaml-input" accept=".yaml,.yml,.json"></label>
              ${APP_STATE.uploadedYamlName ? `<button type="button" class="ed-text-btn rust" id="btn-clear-yaml">Remove custom file</button>` : ""}
            </div>
            ${APP_STATE.uploadedYamlRules ? `<div class="ed-controls-row"><div class="ed-radio-group">` +
              `<label class="ed-radio-opt"><input type="radio" name="yaml-mode" value="replace" ${APP_STATE.uploadMode === "replace" ? "checked" : ""}> Use uploaded themes only</label>` +
              `<label class="ed-radio-opt"><input type="radio" name="yaml-mode" value="combine" ${APP_STATE.uploadMode === "combine" ? "checked" : ""}> Combine with checked themes above</label>` +
              `</div></div>` : ""}
          </div>
        </details>
      </div>
    </div>
  </section>`;
}

function renderThemesTab() {
  if (APP_STATE.runError) {
    return `<div class="ed-notice rust" role="alert">${escHtml(APP_STATE.runError)}</div>`;
  }
  if (!APP_STATE.results) {
    return `<div class="ed-notice"><strong>Ready to analyze.</strong> Upload your Word notes, transcripts, or Excel/CSV survey above—or click <strong>Load Sample Focus-Group Notes</strong>—and click <strong>Run Analysis</strong>.</div>`;
  }

  const res = APP_STATE.results;
  const meta = APP_STATE.runMeta;
  const themesFound = res.frequencies.filter(f => f.documents_reporting > 0).length;
  const matchedEntries = res.tagged_turns.filter(t => t.matched_domains && t.matched_domains.length > 0).length;
  const unmatchedEntries = res.participant_turns_analyzed - matchedEntries;

  const sampleBanner = meta.isFixture
    ? `<div class="ed-notice teal"><strong>Sample practice data active</strong> — Built-in focus-group notes are loaded for demonstration only and are not real study findings.</div>`
    : "";

  const dirtyBanner = APP_STATE.dirty
    ? `<div class="ed-notice rust">Settings or files changed since the last run. Click <strong>Run Analysis</strong> to refresh results.</div>`
    : "";

  const provenanceBanner = `<div class="ed-notice">` +
    `<strong>How these themes work:</strong> Charts count matches against the <strong>${res.frequencies.length} predefined themes</strong> selected above — transparent keyword rules, not AI-invented topics. To cluster entries without a preset list, open <strong>Discover Unlisted Themes</strong>.` +
    `<div class="ed-hint" style="margin-top:4px;">Corpus: ${escHtml(meta.corpusLabel)}${meta.blankSummary ? " · " + escHtml(meta.blankSummary) : ""}</div>` +
    `</div>`;

  const kwDrawer = `<details class="ed-drawer" style="margin-bottom:10px;"><summary>View active theme keywords (${res.compiled_rules.length} themes)</summary><div class="ed-drawer-body"><div class="ed-table-wrap"><table class="ed-table"><thead><tr><th>Theme</th><th>Mode</th><th>Keywords</th><th>Excluded Words</th></tr></thead><tbody>` +
    res.compiled_rules.map(r => `<tr><td>${escHtml(r.name)}</td><td>${escHtml(r.match_mode)}</td><td>${escHtml([...r.roots_en, ...r.roots_es].join(", "))}</td><td>${escHtml(r.exclude_fences.join(", ") || "—")}</td></tr>`).join("") +
    `</tbody></table></div></div></details>`;

  const kpiStrip = `<div class="ed-kpi-strip">` +
    `<div class="ed-kpi"><div class="ed-kpi-label">${meta.groupMode ? "Focus Groups" : "Analytical Units"}</div><div class="ed-kpi-value" data-kpi="units">${res.total_documents}</div><div class="ed-kpi-sub">${meta.groupMode ? "1 file = 1 focus group" : "Non-blank units analyzed"}</div></div>` +
    `<div class="ed-kpi"><div class="ed-kpi-label">Themes Found</div><div class="ed-kpi-value" data-kpi="themes-found">${themesFound} of ${res.frequencies.length}</div><div class="ed-kpi-sub">Active themes matched</div></div>` +
    `<div class="ed-kpi"><div class="ed-kpi-label">${escHtml(meta.entriesLabel)}</div><div class="ed-kpi-value" data-kpi="entries">${res.participant_turns_analyzed}</div><div class="ed-kpi-sub">${matchedEntries} matched · ${unmatchedEntries} none</div></div>` +
    `<div class="ed-kpi"><div class="ed-kpi-label">Theme Matches</div><div class="ed-kpi-value" data-kpi="matches">${res.quotes.length}</div><div class="ed-kpi-sub">1 entry can match 2+ themes</div></div>` +
    `</div>`;

  const subtabs = `<div class="ed-subtabs" role="tablist">` +
    [
      ["summary", "Theme Summary"],
      ["evidence", `Coded Evidence (${res.quotes.length})`],
      ["discover", "Discover Unlisted Themes"],
      ["spotcheck", `Spot-Check Matches (${res.audit_rows.length})`],
    ].map(([id, lbl]) => `<button type="button" role="tab" aria-selected="${APP_STATE.activeSubtab === id}" class="ed-subtab ${APP_STATE.activeSubtab === id ? "active" : ""}" data-subtab="${id}">${escHtml(lbl)}</button>`).join("") +
    `</div>`;

  let bodyHtml = "";
  if (APP_STATE.activeSubtab === "summary") bodyHtml = renderSubtabSummary(res, meta);
  else if (APP_STATE.activeSubtab === "evidence") bodyHtml = renderSubtabEvidence(res, meta);
  else if (APP_STATE.activeSubtab === "discover") bodyHtml = renderSubtabDiscover(res, meta);
  else if (APP_STATE.activeSubtab === "spotcheck") bodyHtml = renderSubtabSpotcheck(res, meta);

  return sampleBanner + dirtyBanner + provenanceBanner + kwDrawer + kpiStrip + subtabs + bodyHtml;
}

function renderSubtabSummary(res, meta) {
  let visualHtml = "";
  if (meta.groupMode && APP_STATE.groupMatrix) {
    const gm = APP_STATE.groupMatrix;
    const visRows = APP_STATE.hideZeroThemes ? gm.rows.filter(r => r.matching_turns > 0) : gm.rows;
    const gridControls = `<div class="ed-controls-row" style="justify-content:space-between;margin-top:0;margin-bottom:8px;">` +
      `<div class="ed-radio-group">` +
      `<span class="ed-gutter-index" style="margin:0;">Grid shows:</span>` +
      `<label class="ed-radio-opt"><input type="radio" name="grid-mode" value="presence" ${!APP_STATE.gridShowEntries ? "checked" : ""}> Presence (✓ / —)</label>` +
      `<label class="ed-radio-opt"><input type="radio" name="grid-mode" value="entries" ${APP_STATE.gridShowEntries ? "checked" : ""}> Notes entries per group</label>` +
      `</div>` +
      `<label class="ed-check-opt"><input type="checkbox" id="chk-hide-zero" ${APP_STATE.hideZeroThemes ? "checked" : ""}> Hide 0-match themes</label>` +
      `</div>`;

    const gridTable = visRows.length
      ? `<div class="ed-table-wrap"><table class="ed-grid" aria-label="Focus-Group by Theme Grid"><thead><tr><th class="theme-col">Theme</th>` +
        gm.groupCols.map(g => `<th>${escHtml((gm.groupLabels && gm.groupLabels[g]) || g)}</th>`).join("") +
        `<th class="groups-col">Groups</th></tr></thead><tbody>` +
        visRows.map(r => `<tr><td class="theme-name">${escHtml(r.theme_label)}</td>` +
          gm.groupCols.map(g => {
            const n = r.cells[g] || 0;
            const txt = n > 0 ? (APP_STATE.gridShowEntries ? String(n) : "✓") : "—";
            return n > 0
              ? `<td class="tile present" data-jump-theme="${escHtml(r.domain_id)}" data-jump-file="${escHtml(g)}" title="Click to inspect ${n} matched entries for ${escHtml(r.theme_label)} in ${escHtml(g)}">${txt}</td>`
              : `<td class="tile absent">${txt}</td>`;
          }).join("") +
          `<td class="tile summary">${r.groups_reporting}/${res.total_documents}</td></tr>`
        ).join("") + `</tbody></table></div>`
      : `<p class="ed-hint">All active themes have 0 matches. Uncheck "Hide 0-match themes" to view all rows.</p>`;

    const maxVol = Math.max(...visRows.map(r => r.matching_turns), 1);
    const volItems = visRows.map(r => ({ label: r.theme_label, value: r.matching_turns, groups: r.groups_reporting }));
    const volSvg = renderHorizontalBarSvg(
      volItems, maxVol,
      "Matched Notes Entries (note volume — not participant headcount)",
      it => `${it.value} (${it.groups}/${res.total_documents})`,
      { id: "atlas-main-chart-svg", title: "ATLAS Notes Volume by Theme" }
    );

    const sumTable = `<div class="ed-table-wrap"><table class="ed-table"><thead><tr><th>Theme</th><th>Focus Groups</th><th class="num">Theme Matches</th><th class="num">Verbatim Quotes</th><th class="num">Paraphrased Key Points</th>${meta.includeObservations ? '<th class="num">Note-Taker Observations</th>' : ""}</tr></thead><tbody>` +
      visRows.map(r => {
        const dq = res.quotes.filter(q => q.domain_id === r.domain_id);
        const nVerb = dq.filter(q => VERBATIM_EVIDENCE_TYPES.has(String(q.evidence_type || ""))).length;
        const nPara = dq.filter(q => q.evidence_type === "key_point_paraphrase").length;
        const nObs = dq.filter(q => q.evidence_type === "observation").length;
        return `<tr><td>${escHtml(r.theme_label)}</td><td>${r.groups_reporting} of ${res.total_documents}</td><td class="num">${dq.length}</td><td class="num">${nVerb}</td><td class="num">${nPara}</td>${meta.includeObservations ? `<td class="num">${nObs}</td>` : ""}</tr>`;
      }).join("") + `</tbody></table></div>`;

    visualHtml = `<h2 class="ed-h2" style="margin-top:4px;">Which Focus Groups Mentioned Each Theme?</h2>` +
      `<p class="ed-hint" style="margin-top:0;margin-bottom:10px;">Uniform across all focus groups: ✓ = mentioned in group notes · — = not mentioned. Click any ✓ cell to jump straight to its quotes.</p>` +
      gridControls + gridTable +
      `<h3 class="ed-h3">Notes Volume by Theme</h3>` +
      `<p class="ed-hint" style="margin-top:0;">Counts reflect note detail rather than participant headcount.</p>` +
      volSvg +
      `<h3 class="ed-h3">Theme Summary Table</h3>` + sumTable;
  } else {
    const sorted = [...res.frequencies].sort((a, b) => (b.prevalence_pct - a.prevalence_pct) || (b.matching_turns - a.matching_turns) || (a.domain_name < b.domain_name ? -1 : 1));
    const vis = APP_STATE.hideZeroThemes ? sorted.filter(f => f.matching_turns > 0) : sorted;
    const indSvg = renderHorizontalBarSvg(
      vis.map(f => ({ label: f.domain_name, value: f.prevalence_pct, matches: f.matching_turns })),
      100,
      "Prevalence (% of analytical units)",
      it => `${it.value.toFixed(1)}% (${it.matches})`,
      { id: "atlas-main-chart-svg", title: "ATLAS Theme Prevalence Across Analytical Units" }
    );
    const indTable = `<div class="ed-table-wrap"><table class="ed-table"><thead><tr><th>Theme</th><th>Units Reporting</th><th class="num">Prevalence (%)</th><th class="num">Theme Matches</th></tr></thead><tbody>` +
      vis.map(f => `<tr><td>${escHtml(f.domain_name)}</td><td>${f.documents_reporting} of ${f.total_documents}</td><td class="num">${f.prevalence_pct.toFixed(1)}%</td><td class="num">${f.matching_turns}</td></tr>`).join("") +
      `</tbody></table></div>`;
    visualHtml = `<div class="ed-controls-row" style="justify-content:space-between;margin-top:0;">` +
      `<h2 class="ed-h2" style="margin:0;">Theme Prevalence Across Analytical Units</h2>` +
      `<label class="ed-check-opt"><input type="checkbox" id="chk-hide-zero" ${APP_STATE.hideZeroThemes ? "checked" : ""}> Hide 0-match themes</label></div>` +
      indSvg + `<h3 class="ed-h3">Theme Summary Table</h3>` + indTable;
  }

  const csvSpec = getCsvDownloadSpec(res);
  const dlBar = `<div class="ed-download-bar">` +
    `<button type="button" class="ed-btn-primary" id="btn-dl-docx">Download Full Report (.docx)</button>` +
    `<button type="button" class="ed-btn-secondary" id="btn-dl-xlsx">Download Theme Frequencies (.xlsx)</button>` +
    `<button type="button" class="ed-btn-secondary" id="btn-dl-csv">${escHtml(csvSpec.label)}</button>` +
    `<button type="button" class="ed-btn-secondary" id="btn-dl-svg">Download Chart (.svg)</button>` +
    `</div>`;

  const exclDrawer = APP_STATE.excludedRows.length
    ? `<details class="ed-drawer"><summary>Excluded Questions &amp; Session Headers (${APP_STATE.excludedRows.length} items skipped — click to verify)</summary><div class="ed-drawer-body"><div class="ed-table-wrap"><table class="ed-table"><thead><tr><th>Source File</th><th class="num">Row</th><th>Reason</th><th>Skipped Text</th></tr></thead><tbody>` +
      APP_STATE.excludedRows.map(e => `<tr><td>${escHtml(e.source_id)}</td><td class="num">${e.location}</td><td>${escHtml(e.reason)}</td><td>${escHtml(e.text)}</td></tr>`).join("") +
      `</tbody></table></div></div></details>`
    : "";

  const ntDrawer = APP_STATE.noteTakerThemes.length
    ? `<details class="ed-drawer"><summary>Note-Taker Themes Summary (${APP_STATE.noteTakerThemes.length} reference items — Not Counted in Prevalence)</summary><div class="ed-drawer-body"><div class="ed-table-wrap"><table class="ed-table"><thead><tr><th>Source File</th><th>Question</th><th>Summary Text</th></tr></thead><tbody>` +
      APP_STATE.noteTakerThemes.map(t => `<tr><td>${escHtml(t.source_id)}</td><td>${escHtml(t.question_id)}</td><td>${escHtml(t.text)}</td></tr>`).join("") +
      `</tbody></table></div></div></details>`
    : "";

  return visualHtml + dlBar + exclDrawer + ntDrawer;
}

function paginateItems(items, page, pageSize, showAll) {
  const total = items.length;
  const safeSize = Math.max(1, Number(pageSize) || 50);
  const totalPages = Math.max(1, Math.ceil(total / safeSize));
  const clampedPage = Math.max(1, Math.min(Number(page) || 1, totalPages));
  const needsPaging = total > safeSize;
  if (!total) {
    return { pageItems: [], page: 1, totalPages: 1, startIdx: 0, endIdx: 0, total: 0, needsPaging: false };
  }
  if (showAll || !needsPaging) {
    return { pageItems: items, page: clampedPage, totalPages, startIdx: 1, endIdx: total, total, needsPaging };
  }
  const offset = (clampedPage - 1) * safeSize;
  const pageItems = items.slice(offset, offset + safeSize);
  return {
    pageItems,
    page: clampedPage,
    totalPages,
    startIdx: offset + 1,
    endIdx: offset + pageItems.length,
    total,
    needsPaging,
  };
}

function renderPagerHtml(prefix, pg, showAll, pageSize, noun, position = "top") {
  if (!pg.needsPaging) return "";
  const idSuffix = position === "top" ? "" : `-${position}`;
  const statusText = showAll
    ? `Showing all ${pg.total} ${noun}`
    : `Showing ${pg.startIdx}–${pg.endIdx} of ${pg.total} ${noun} (Page ${pg.page} of ${pg.totalPages})`;
  const buttonsHtml = showAll
    ? `<button type="button" class="ed-btn-secondary" id="${prefix}-show-all${idSuffix}" data-pager-action="${prefix}-show-all">Back to pages (${pageSize}/page)</button>`
    : `<button type="button" class="ed-btn-secondary" id="${prefix}-prev${idSuffix}" data-pager-action="${prefix}-prev" ${pg.page <= 1 ? "disabled" : ""}>Previous</button>` +
      `<button type="button" class="ed-btn-secondary" id="${prefix}-next${idSuffix}" data-pager-action="${prefix}-next" ${pg.page >= pg.totalPages ? "disabled" : ""}>Next</button>` +
      `<button type="button" class="ed-btn-secondary" id="${prefix}-show-all${idSuffix}" data-pager-action="${prefix}-show-all">Show all (${pg.total})</button>`;
  return `<nav class="ed-pager" aria-label="${escHtml(noun)} pagination (${escHtml(position)})" data-pager="${escHtml(prefix)}-${escHtml(position)}">` +
    `<span class="ed-pager-status">${escHtml(statusText)}</span>` +
    `<div class="ed-pager-actions">${buttonsHtml}</div>` +
    `</nav>`;
}

function renderSubtabEvidence(res, meta) {
  const themeOpts = res.frequencies.map(f => `<option value="${escHtml(f.domain_id)}" ${APP_STATE.evFilterTheme === f.domain_id ? "selected" : ""}>${escHtml(f.domain_name)} (${f.matching_turns})</option>`).join("");
  const fileOpts = Object.keys(res.file_hashes).sort().map(sid => `<option value="${escHtml(sid)}" ${APP_STATE.evFilterFile === sid ? "selected" : ""}>${escHtml(sid)}</option>`).join("");
  const speakers = Array.from(new Set(res.quotes.map(q => q.speaker))).sort();
  const spkOpts = speakers.map(s => `<option value="${escHtml(s)}" ${APP_STATE.evFilterSpeaker === s ? "selected" : ""}>${escHtml(s)}</option>`).join("");
  const questions = Array.from(new Set(res.quotes.map(q => String(q.question_id || "").trim()).filter(Boolean)))
    .sort((a, b) => {
      const ma = /\d+/.exec(a), mb = /\d+/.exec(b);
      if (ma && mb) return parseInt(ma[0], 10) - parseInt(mb[0], 10);
      return a < b ? -1 : a > b ? 1 : 0;
    });
  if (APP_STATE.evFilterQuestion !== "__all__" && !questions.includes(APP_STATE.evFilterQuestion)) {
    APP_STATE.evFilterQuestion = "__all__";
  }
  const qOpts = questions.map(q => `<option value="${escHtml(q)}" ${APP_STATE.evFilterQuestion === q ? "selected" : ""}>${escHtml(q)}</option>`).join("");

  let filtered = res.quotes;
  if (APP_STATE.evFilterTheme !== "__all__") filtered = filtered.filter(q => q.domain_id === APP_STATE.evFilterTheme);
  if (APP_STATE.evFilterFile !== "__all__") filtered = filtered.filter(q => q.source_id === APP_STATE.evFilterFile);
  if (APP_STATE.evFilterSpeaker !== "__all__") filtered = filtered.filter(q => q.speaker === APP_STATE.evFilterSpeaker);
  if (APP_STATE.evFilterQuestion !== "__all__") filtered = filtered.filter(q => String(q.question_id || "").trim() === APP_STATE.evFilterQuestion);
  if (APP_STATE.evVerbatimOnly) filtered = filtered.filter(q => VERBATIM_EVIDENCE_TYPES.has(String(q.evidence_type || "")));
  if (APP_STATE.evSearch.trim()) {
    const needle = APP_STATE.evSearch.trim().toLowerCase();
    filtered = filtered.filter(q => q.text.toLowerCase().includes(needle) || q.match_text.toLowerCase().includes(needle));
  }

  const pg = paginateItems(filtered, APP_STATE.evPage, APP_STATE.evPageSize, APP_STATE.evShowAll);
  APP_STATE.evPage = pg.page;

  const questionPickerHtml = questions.length
    ? `<div class="ed-inline-field"><label for="ev-question">Question</label><select id="ev-question" class="ed-select"><option value="__all__">All questions</option>${qOpts}</select></div>`
    : "";

  const countLabel = pg.needsPaging && !APP_STATE.evShowAll
    ? `Showing <strong>${pg.startIdx}–${pg.endIdx}</strong> of <strong>${filtered.length}</strong> matching rows (${res.quotes.length} total)`
    : `Showing <strong>${filtered.length}</strong> of ${res.quotes.length} coded matches`;

  const controls = `<div class="ed-tabular-grid" style="margin-bottom:14px;">` +
    `<div class="ed-inline-field"><label for="ev-theme">Theme</label><select id="ev-theme" class="ed-select"><option value="__all__">All themes</option>${themeOpts}</select></div>` +
    `<div class="ed-inline-field"><label for="ev-file">Source File</label><select id="ev-file" class="ed-select"><option value="__all__">All files</option>${fileOpts}</select></div>` +
    questionPickerHtml +
    `<div class="ed-inline-field"><label for="ev-spk">Speaker</label><select id="ev-spk" class="ed-select"><option value="__all__">All speakers</option>${spkOpts}</select></div>` +
    `<div class="ed-inline-field" style="flex:1;min-width:200px;"><label for="ev-search">Search text</label><input type="text" id="ev-search" class="ed-input" value="${escHtml(APP_STATE.evSearch)}" placeholder="Filter quotes instantly..."></div>` +
    `</div>` +
    `<div class="ed-controls-row" style="justify-content:space-between;margin-top:0;margin-bottom:14px;">` +
    `<label class="ed-check-opt"><input type="checkbox" id="ev-verbatim" ${APP_STATE.evVerbatimOnly ? "checked" : ""}> Verbatim Quotes Only</label>` +
    `<span class="ed-hint" style="margin:0;">${countLabel}</span></div>`;

  const topPager = renderPagerHtml("ev", pg, APP_STATE.evShowAll, APP_STATE.evPageSize, "coded matches", "top");
  const bottomPager = renderPagerHtml("ev", pg, APP_STATE.evShowAll, APP_STATE.evPageSize, "coded matches", "bottom");

  const rowsHtml = pg.pageItems.length
    ? topPager + pg.pageItems.map(q => {
        const s = Math.max(0, Math.min(q.text.length, Number(q.match_char_start) || 0));
        const e = Math.max(s, Math.min(q.text.length, Number(q.match_char_end) || s));
        const highlighted = escHtml(q.text.slice(0, s)) + `<mark>${escHtml(q.text.slice(s, e))}</mark>` + escHtml(q.text.slice(e));
        const evCls = q.evidence_type === "key_point_paraphrase" ? "paraphrase"
          : q.evidence_type === "observation" ? "observation" : "verbatim";
        const evLbl = q.evidence_type === "notable_quote_verbatim" ? "Verbatim Quote"
          : q.evidence_type === "key_point_paraphrase" ? "Paraphrase (Key Point)"
          : q.evidence_type === "observation" ? "Source: Note-Taker Observation"
          : "Verbatim Turn";
        return `<div class="ed-evidence-row">` +
          `<div class="ed-evidence-meta"><span class="ed-badge ${evCls}">${evLbl}</span><span class="ed-badge theme-pill">${escHtml(q.domain_name)}</span></div>` +
          `<div class="ed-quote-text">${highlighted}</div>` +
          `<div class="ed-provenance">SOURCE ${escHtml(q.source_id)} · LINE ${q.line_number}${q.question_id ? " · " + escHtml(q.question_id) : ""} · SPEAKER ${escHtml(q.speaker)}${q.respondent_id ? " · RESPONDENT " + escHtml(q.respondent_id) : ""}</div>` +
          `</div>`;
      }).join("") + bottomPager
    : `<p class="ed-hint">No coded evidence matches the current filters.</p>`;

  return controls + rowsHtml;
}

function renderSubtabDiscover(res, meta) {
  const disc = APP_STATE.discovery;
  const ovMap = APP_STATE.discoveryOverlap || {};
  const settingsDrawer = `<details class="ed-drawer" style="margin-bottom:14px;"><summary>Method settings (Offline TF-IDF + NMF · ${APP_STATE.discoveryK} clusters)</summary><div class="ed-drawer-body"><div class="ed-controls-row" style="margin-top:0;">` +
    `<div class="ed-inline-field"><label for="disc-k">Number of clusters</label><select id="disc-k" class="ed-select">${[2,3,4,5,6,7,8].map(k => `<option value="${k}" ${k === APP_STATE.discoveryK ? "selected" : ""}>${k} clusters</option>`).join("")}</select></div>` +
    `<button type="button" class="ed-btn-secondary" id="btn-rerun-disc">Update Clusters</button>` +
    `</div><p class="ed-hint">Runs deterministic multiplicative-update NMF directly in your browser (seed 42, participant labels p0–p99 filtered out).</p></div></details>`;

  if (!disc || !disc.topics.length) {
    return settingsDrawer + `<div class="ed-notice">${escHtml((disc && disc.warning) || "Not enough entries to discover clusters.")}</div>`;
  }

  const domainMap = new Map(res.frequencies.map(f => [f.domain_id, f.domain_name]));
  const clustersHtml = disc.topics.map(t => {
    const ov = ovMap[t.topic_id] || { badge: "", status: "covered", member_indices: [] };
    const badgeCls = ov.status === "uncoded" ? "observation" : ov.status === "partial" ? "paraphrase" : "theme-pill";
    const membersHtml = (ov.member_indices || []).map(idx => {
      const rec = res.tagged_turns[idx];
      const matched = (rec.matched_domains || []).map(d => domainMap.get(d) || d).join(", ") || "None (uncoded)";
      return `<tr><td>${escHtml(rec.source_id)}</td><td class="num">${rec.line_number}</td><td>${escHtml(matched)}</td><td>${escHtml(rec.text)}</td></tr>`;
    }).join("");
    return `<div class="ed-cluster-row">` +
      `<div><div class="ed-gutter-index">Cluster ${t.topic_id}</div><div class="ed-cluster-stat">${t.turn_count} of ${disc.n_analyzed}</div><div class="ed-gutter-note">${t.share_pct}% of scanned entries</div></div>` +
      `<div><div class="ed-evidence-meta"><strong style="font-size:16px;color:var(--ui-navy);">${escHtml(t.label)}</strong><span class="ed-badge ${badgeCls}">${escHtml(ov.badge)}</span></div>` +
      `<div class="ed-keywords">Keywords: ${escHtml(t.top_terms.join(", "))}</div>` +
      `<div class="ed-hint" style="margin-top:0;"><strong>Most representative example:</strong></div>` +
      `<div class="ed-quote-text" style="border-left:2px solid var(--ui-navy);padding-left:12px;">${escHtml(t.medoid_text)}</div>` +
      `<div class="ed-provenance" style="margin-bottom:8px;">SOURCE ${escHtml(t.medoid_unit_id)} · LINE ${t.medoid_line} · SPEAKER ${escHtml(t.medoid_speaker)}</div>` +
      `<details class="ed-drawer"><summary>View all ${ov.member_indices.length} entries in Cluster ${t.topic_id}</summary><div class="ed-drawer-body"><div class="ed-table-wrap"><table class="ed-table"><thead><tr><th>Source File</th><th class="num">Line</th><th>Active Theme Match</th><th>Entry Text</th></tr></thead><tbody>${membersHtml}</tbody></table></div></div></details>` +
      `</div></div>`;
  }).join("");

  if (APP_STATE.addTopicId === null || !disc.topics.some(t => t.topic_id === APP_STATE.addTopicId)) {
    APP_STATE.addTopicId = disc.topics[0].topic_id;
  }
  const addBox = `<div style="margin-top:22px;padding-top:16px;border-top:2px solid var(--ui-navy);">` +
    `<h3 class="ed-h3" style="margin-top:0;">Add a Discovered Cluster to Active Themes</h3>` +
    `<div class="ed-tabular-grid">` +
    `<div class="ed-inline-field" style="min-width:260px;"><label for="add-topic-sel">Cluster to add</label><select id="add-topic-sel" class="ed-select">${disc.topics.map(t => `<option value="${t.topic_id}" ${t.topic_id === APP_STATE.addTopicId ? "selected" : ""}>Cluster ${t.topic_id}: ${escHtml(t.label)} (${t.turn_count} entries)</option>`).join("")}</select></div>` +
    `<div class="ed-inline-field" style="flex:1;min-width:220px;"><label for="add-topic-name">New theme name (optional)</label><input type="text" id="add-topic-name" class="ed-input" value="${escHtml(APP_STATE.addTopicName)}" placeholder="Leave blank to use cluster keywords"></div>` +
    `</div>` +
    `<div class="ed-controls-row">` +
    `<label class="ed-check-opt"><input type="checkbox" id="add-topic-exact" ${APP_STATE.addTopicExact ? "checked" : ""}> Use exact whole-word matching (recommended)</label>` +
    `<button type="button" class="ed-btn-primary" id="btn-add-topic">Add Theme to Active Themes</button>` +
    `</div></div>`;

  return settingsDrawer + clustersHtml + addBox;
}

function renderSubtabSpotcheck(res, meta) {
  const rows = res.audit_rows || [];
  if (!res.quotes.length) return `<div class="ed-notice">No theme matches to spot-check in the current corpus.</div>`;
  if (!rows.length) return `<div class="ed-notice teal"><strong>0 of ${res.quotes.length} theme matches flagged for review.</strong></div>`;

  const nSpell = rows.filter(r => r.flag_codes.includes("spelling_tolerance")).length;
  const nPref = rows.filter(r => r.flag_codes.includes("prefix_extension")).length;
  const nCtx = rows.filter(r => r.risk_level === "Medium").length;

  const grouped = new Map();
  for (const r of rows) {
    const prio = r.flag_codes.includes("spelling_tolerance") ? "Check First (Spelling Match)"
      : r.risk_level === "High" ? "Check First (Partial-Word Match)"
      : "Check in Context (Negation or Short Word)";
    const key = `${prio}|${r.domain_name}|${r.matched_span}|${r.full_word}|${r.flag_reason}`;
    if (!grouped.has(key)) grouped.set(key, { prio, domain_name: r.domain_name, matched_span: r.matched_span, full_word: r.full_word, count: 0, reason: r.flag_reason, fix: r.suggested_fix });
    grouped.get(key).count++;
  }

  const flaggedDomains = Array.from(new Map(rows.map(r => [r.domain_id, r.domain_name])).entries());
  if (!flaggedDomains.some(([id]) => id === APP_STATE.spotcheckDomainId)) {
    APP_STATE.spotcheckDomainId = flaggedDomains[0][0];
    APP_STATE.spotcheckSelectedWords = new Set();
  }
  const domRows = rows.filter(r => r.domain_id === APP_STATE.spotcheckDomainId);
  const excludable = Array.from(new Set(
    domRows.flatMap(r => [r.extension_words, r.spelling_words].join(",").split(",").map(w => w.trim().toLowerCase()).filter(Boolean))
  )).sort();

  const pillsHtml = excludable.length
    ? `<div class="ed-word-pills">${excludable.map(w => `<label class="ed-word-pill"><input type="checkbox" data-excl-word="${escHtml(w)}" ${APP_STATE.spotcheckSelectedWords.has(w) ? "checked" : ""}> ${escHtml(w)}</label>`).join("")}</div>`
    : `<p class="ed-hint">No partial-word or spelling false-alarm words on this theme (use exact whole-word matching below if needed).</p>`;

  const prioLabelOf = r => r.flag_codes.includes("spelling_tolerance") ? "Check First (Spelling Match)"
    : r.risk_level === "High" ? "Check First (Partial-Word Match)"
    : "Check in Context (Negation or Short Word)";
  const priorities = Array.from(new Set(rows.map(prioLabelOf)));
  if (APP_STATE.scFilterPriority !== "__all__" && !priorities.includes(APP_STATE.scFilterPriority)) APP_STATE.scFilterPriority = "__all__";
  if (APP_STATE.scFilterTheme !== "__all__" && !flaggedDomains.some(([id]) => id === APP_STATE.scFilterTheme)) APP_STATE.scFilterTheme = "__all__";

  const filteredExamples = rows.filter(r =>
    (APP_STATE.scFilterPriority === "__all__" || prioLabelOf(r) === APP_STATE.scFilterPriority) &&
    (APP_STATE.scFilterTheme === "__all__" || r.domain_id === APP_STATE.scFilterTheme)
  );

  const scPg = paginateItems(filteredExamples, APP_STATE.scPage, APP_STATE.scPageSize, APP_STATE.scShowAll);
  APP_STATE.scPage = scPg.page;
  const scTopPager = renderPagerHtml("sc", scPg, APP_STATE.scShowAll, APP_STATE.scPageSize, "flagged sentences", "top");
  const scBottomPager = renderPagerHtml("sc", scPg, APP_STATE.scShowAll, APP_STATE.scPageSize, "flagged sentences", "bottom");

  const examplesListHtml = scPg.pageItems.length
    ? scTopPager + scPg.pageItems.map(r => {
        const s = Math.max(0, Math.min(r.text.length, Number(r.match_char_start) || 0));
        const e = Math.max(s, Math.min(r.text.length, Number(r.match_char_end) || s));
        const highlighted = escHtml(r.text.slice(0, s)) + `<mark>${escHtml(r.text.slice(s, e))}</mark>` + escHtml(r.text.slice(e));
        const prio = prioLabelOf(r);
        const badgeCls = r.risk_level === "High" ? "observation" : "paraphrase";
        return `<div class="ed-evidence-row" data-spotcheck-example="1">` +
          `<div class="ed-evidence-meta"><span class="ed-badge ${badgeCls}">${escHtml(prio)}</span><span class="ed-badge theme-pill">${escHtml(r.domain_name)}</span></div>` +
          `<div class="ed-quote-text">${highlighted}</div>` +
          `<div class="ed-provenance">SOURCE ${escHtml(r.source_id)} · LINE ${r.line_number} · SPEAKER ${escHtml(r.speaker)} · ${escHtml(r.flag_reason)}</div>` +
          `</div>`;
      }).join("") + scBottomPager
    : `<p class="ed-hint">No flagged sentences match the current Spot-Check filters.</p>`;

  const examplesHtml = `<div style="margin-top:20px;padding-top:16px;border-top:1px solid var(--ui-hairline);">` +
    `<h3 class="ed-h3" style="margin-top:0;">Inspect Flagged Sentences in Context (${filteredExamples.length} of ${rows.length})</h3>` +
    `<div class="ed-tabular-grid" style="margin-bottom:12px;">` +
    `<div class="ed-inline-field"><label for="sc-filter-prio">Review Priority</label><select id="sc-filter-prio" class="ed-select"><option value="__all__">All priorities</option>${priorities.map(p => `<option value="${escHtml(p)}" ${APP_STATE.scFilterPriority === p ? "selected" : ""}>${escHtml(p)}</option>`).join("")}</select></div>` +
    `<div class="ed-inline-field"><label for="sc-filter-theme">Theme</label><select id="sc-filter-theme" class="ed-select"><option value="__all__">All flagged themes</option>${flaggedDomains.map(([id, nm]) => `<option value="${escHtml(id)}" ${APP_STATE.scFilterTheme === id ? "selected" : ""}>${escHtml(nm)}</option>`).join("")}</select></div>` +
    `</div>` +
    examplesListHtml +
    `</div>`;

  return `<div class="ed-notice rust"><strong>All flagged matches below are currently counted in your charts and tables until you exclude them.</strong></div>` +
    `<p style="margin-bottom:10px;"><strong>${rows.length} of ${res.quotes.length} theme matches flagged for review</strong> · Check First (Partial-Word): <strong>${nPref}</strong> · Check First (Spelling): <strong>${nSpell}</strong> · Check in Context: <strong>${nCtx}</strong></p>` +
    `<div class="ed-table-wrap"><table class="ed-table"><thead><tr><th>Review Priority</th><th>Theme</th><th>Matched</th><th>Full Word</th><th class="num">Matches</th><th>Why Flagged</th></tr></thead><tbody>` +
    Array.from(grouped.values()).map(g => `<tr><td>${escHtml(g.prio)}</td><td>${escHtml(g.domain_name)}</td><td>${escHtml(g.matched_span)}</td><td>${escHtml(g.full_word)}</td><td class="num">${g.count}</td><td>${escHtml(g.reason)}</td></tr>`).join("") +
    `</tbody></table></div>` +
    `<div style="margin-bottom:18px;"><button type="button" class="ed-btn-secondary" id="btn-dl-spotcheck">Download Spot-Check Report (.csv)</button></div>` +
    `<div style="padding-top:16px;border-top:2px solid var(--ui-navy);">` +
    `<h3 class="ed-h3" style="margin-top:0;">Exclude False Matches from a Theme</h3>` +
    `<div class="ed-inline-field" style="max-width:360px;"><label for="sc-domain">Theme to tighten</label><select id="sc-domain" class="ed-select">${flaggedDomains.map(([id, nm]) => `<option value="${escHtml(id)}" ${id === APP_STATE.spotcheckDomainId ? "selected" : ""}>${escHtml(nm)} (${escHtml(id)})</option>`).join("")}</select></div>` +
    pillsHtml +
    `<div class="ed-controls-row">` +
    `<label class="ed-check-opt"><input type="checkbox" id="sc-exact" ${APP_STATE.spotcheckSetExact ? "checked" : ""}> Switch this theme to exact whole-word matching</label>` +
    `<button type="button" class="ed-btn-primary" id="btn-apply-spotcheck">Exclude Selected Words &amp; Re-Run</button>` +
    `</div></div>` +
    examplesHtml;
}

function renderExportsTab() {
  if (!APP_STATE.results) {
    return `<div class="ed-notice">Run an analysis first to generate downloadable Word reports, Excel workbooks, CSV inventories, and SHA-256 provenance manifests.</div>`;
  }
  const res = APP_STATE.results;
  const meta = APP_STATE.runMeta;

  let ciSection = "";
  if (!meta.groupMode && res.total_documents > 0) {
    const N = res.total_documents;
    const ciRows = res.frequencies.map(f => {
      const p = f.documents_reporting / N;
      const se = Math.sqrt((p * (1 - p)) / N);
      const lo = Math.max(0, (p - 1.96 * se) * 100);
      const hi = Math.min(100, (p + 1.96 * se) * 100);
      return { ...f, p, se, lo, hi };
    });
    const ciSvg = renderHorizontalBarSvg(
      ciRows.map(r => ({ label: r.domain_name, value: r.prevalence_pct, ciLow: r.lo, ciHigh: r.hi })),
      100,
      "Prevalence (% of analytical units, with 95% Binomial CI)",
      it => `${it.value.toFixed(1)}% [${it.ciLow.toFixed(1)}–${it.ciHigh.toFixed(1)}]`
    );
    ciSection = `<h3 class="ed-h3">Statistical Uncertainty (Individual Mode · N = ${N})</h3>` +
      `<p class="ed-hint" style="margin-top:0;">Binomial standard errors and 95% confidence intervals across independent analytical units.</p>` +
      `<div class="ed-table-wrap"><table class="ed-table"><thead><tr><th>Theme</th><th class="num">Units</th><th class="num">Prevalence (%)</th><th class="num">Binomial SE</th><th class="num">95% CI (%)</th></tr></thead><tbody>` +
      ciRows.map(r => `<tr><td>${escHtml(r.domain_name)}</td><td class="num">${r.documents_reporting} / ${N}</td><td class="num">${r.prevalence_pct.toFixed(1)}%</td><td class="num">${r.se.toFixed(4)}</td><td class="num">${r.lo.toFixed(1)}% – ${r.hi.toFixed(1)}%</td></tr>`).join("") +
      `</tbody></table></div>` + ciSvg;
  }

  const csvSpec = getCsvDownloadSpec(res);
  const showSeparateVerbatim = csvSpec.filename !== "coded_evidence_inventory.csv" && csvSpec.rows.length < res.quotes.length;
  return `<h2 class="ed-h2" style="margin-top:0;">Analyst Downloads</h2>` +
    `<p class="ed-hint" style="margin-top:0;">Generated directly inside your browser from the active run snapshot.</p>` +
    `<div class="ed-download-bar">` +
    `<button type="button" class="ed-btn-primary" id="btn-dl-docx-2">Download Full Report (.docx)</button>` +
    `<button type="button" class="ed-btn-secondary" id="btn-dl-xlsx-2">Download Theme Frequencies (.xlsx)</button>` +
    `<button type="button" class="ed-btn-secondary" id="btn-dl-csv-2">Download All Coded Evidence (.csv)</button>` +
    (showSeparateVerbatim ? `<button type="button" class="ed-btn-secondary" id="btn-dl-verbatim-2">${escHtml(csvSpec.label)}</button>` : "") +
    `<button type="button" class="ed-btn-secondary" id="btn-dl-yaml-2">Save Active Themes (.yaml)</button>` +
    `</div>` +
    ciSection +
    `<h2 class="ed-h2">Audit &amp; Reproducibility Files</h2>` +
    `<div class="ed-notice teal"><strong>Cryptographic Provenance Active:</strong> Every uploaded file and theme prevalence row is bound by a deterministic SHA-256 digest matching the ATLAS Python reference engine.</div>` +
    `<div class="ed-download-bar">` +
    `<button type="button" class="ed-btn-secondary" id="btn-dl-manifest">Download Provenance Manifest (.json)</button>` +
    `<button type="button" class="ed-btn-secondary" id="btn-dl-spotcheck-2">Download Spot-Check Report (.csv)</button>` +
    `</div>` +
    `<div class="ed-table-wrap"><table class="ed-table"><thead><tr><th>Source File</th><th>SHA-256 Digest</th></tr></thead><tbody>` +
    Object.entries(res.file_hashes).map(([sid, sha]) => `<tr><td>${escHtml(sid)}</td><td style="font-family:monospace;font-size:12px;">${escHtml(sha)}</td></tr>`).join("") +
    `</tbody></table></div>`;
}

function renderGuideTab() {
  return `<h2 class="ed-h2" style="margin-top:0;">Quick Reference — Zero-Install Browser Edition</h2>
    <div class="ed-row">
      <div><div class="ed-gutter-index">Privacy</div><div class="ed-gutter-heading">100% Local</div></div>
      <div><p>This single HTML file runs completely offline inside Microsoft Edge or Chrome. Uploaded Word notes, transcripts, and Excel surveys are parsed in browser memory and never leave your computer.</p></div>
    </div>
    <div class="ed-row">
      <div><div class="ed-gutter-index">Counts</div><div class="ed-gutter-heading">Presence vs. Note Volume</div></div>
      <div><p>In <strong>Group Mode</strong> (1 file = 1 focus group), lead with the <strong>Group × Theme Grid (✓ / —)</strong> to report how many focus groups raised a theme. Use <strong>Theme Matches</strong> (Notes Volume) as supporting detail—never as a participant headcount. In <strong>Excel surveys</strong>, blank cells in optional open-ended questions are reported as <em>written answers scanned (X rows left this question blank)</em> rather than a study response rate.</p></div>
    </div>
    <div class="ed-row">
      <div><div class="ed-gutter-index">Transcripts</div><div class="ed-gutter-heading">Speaker Labels Checklist</div></div>
      <div><p>For virtual Zoom or Microsoft Teams transcripts, turn on speaker-attributed transcription and verify speaker names (like <code>Facilitator:</code> vs. <code>P1:</code>) before uploading. For in-person audio, one shared mic cannot reliably distinguish voices—run in <strong>Group Mode</strong> (1 file = 1 group) unless speakers are manually tagged.</p></div>
    </div>
    <div class="ed-row">
      <div><div class="ed-gutter-index">Quality Check</div><div class="ed-gutter-heading">Spot-Check &amp; Typos</div></div>
      <div><p>Turn on <strong>Allow minor spelling typos</strong> for open-ended surveys with misspellings (e.g., <code>gorceries</code> → <code>groceries</code>). Every typo rescue and partial-word match is surfaced in <strong>Spot-Check Matches</strong>—and stays counted in your tables until you click <strong>Exclude Selected Words &amp; Re-Run</strong>.</p></div>
    </div>`;
}

function renderAll() {
  const root = document.getElementById("atlas-app");
  const statusText = APP_STATE.results
    ? (APP_STATE.dirty ? "Inputs changed — click Run Analysis" : `${APP_STATE.results.quotes.length} matches across ${APP_STATE.results.total_documents} ${APP_STATE.runMeta.groupMode ? "groups" : "units"}`)
    : `${APP_STATE.files.length} ${APP_STATE.files.length === 1 ? "file" : "files"} staged`;

  const mainContent = APP_STATE.activeTab === "themes" ? renderThemesTab()
    : APP_STATE.activeTab === "exports" ? renderExportsTab()
    : renderGuideTab();

  root.innerHTML = `
    <header class="ed-masthead">
      <div>
        <div class="ed-eyebrow">ATLAS · Zero-Install Local Browser Edition (v1.2)</div>
        <h1 class="ed-title">ATLAS Qualitative Coding Workbench</h1>
        <div class="ed-subtitle">Deterministic coding, topic discovery, and auditable Word/Excel exports for focus-group notes, transcripts, and surveys. Runs 100% locally in your browser — uploaded files are never sent to GitHub or any server.</div>
      </div>
      <div class="ed-masthead-right">
        <span class="ed-status-pill ${APP_STATE.dirty ? "is-dirty" : ""}">${escHtml(statusText)}</span>
        <button type="button" class="ed-btn-primary" id="btn-run">Run Analysis</button>
      </div>
    </header>
    ${renderSetupSection()}
    <nav class="ed-tabs" role="tablist" aria-label="Main workspace tabs">
      <button type="button" role="tab" aria-selected="${APP_STATE.activeTab === "themes"}" class="ed-tab ${APP_STATE.activeTab === "themes" ? "active" : ""}" data-tab="themes">Themes &amp; Quotes</button>
      <button type="button" role="tab" aria-selected="${APP_STATE.activeTab === "exports"}" class="ed-tab ${APP_STATE.activeTab === "exports" ? "active" : ""}" data-tab="exports">Exports &amp; Audit Files</button>
      <button type="button" role="tab" aria-selected="${APP_STATE.activeTab === "guide"}" class="ed-tab ${APP_STATE.activeTab === "guide" ? "active" : ""}" data-tab="guide">Quick Reference</button>
    </nav>
    <main>${mainContent}</main>
    <footer class="ed-footer">
      <span>ATLAS Standalone Browser Edition (Non-AI Deterministic Engine) · Zero External Network Calls · MIT License</span>
      <span>Questions or help using or adapting ATLAS? Contact Victoria Cholette (<a href="https://github.com/dphdame" target="_blank" rel="noopener noreferrer">@dphdame</a> · <a href="mailto:hello@tooearlytosay.com">hello@tooearlytosay.com</a>)</span>
    </footer>`;

  bindEvents();
}

// ----------------------------------------------------------------------------
// Event Wiring
// ----------------------------------------------------------------------------
function downloadEvidenceCsv(useTab1Spec) {
  const res = APP_STATE.results;
  if (!res) return;
  const spec = useTab1Spec ? getCsvDownloadSpec(res) : { filename: "coded_evidence_inventory.csv", rows: res.quotes };
  const includeResp = Boolean(res.has_respondent_id && res.quotes.some(q => String(q.respondent_id || "").trim()));
  const headers = ["domain_id","domain_name","source_id","unit_id",...(includeResp ? ["respondent_id"] : []),"line_number","speaker","evidence_type","question_id","match_text","text","source_sha256"];
  triggerDownload(rowsToCsv(headers, spec.rows), spec.filename, "text/csv;charset=utf-8");
}

function downloadChartSvg() {
  const svg = document.getElementById("atlas-main-chart-svg");
  if (!svg) return;
  const serializer = new XMLSerializer();
  const xml = `<?xml version="1.0" encoding="UTF-8"?>\n` + serializer.serializeToString(svg);
  triggerDownload(xml, "atlas_theme_chart.svg", "image/svg+xml;charset=utf-8");
}

function downloadSpotcheckCsv() {
  const res = APP_STATE.results;
  if (!res) return;
  const headers = ["risk_level","domain_id","domain_name","matched_span","full_word","extension_words","spelling_words","flag_codes","flag_reason","suggested_fix","speaker","source_id","line_number","text"];
  triggerDownload(rowsToCsv(headers, res.audit_rows), "atlas_spot_check_report.csv", "text/csv;charset=utf-8");
}

function bindEvents() {
  const $ = id => document.getElementById(id);

  if ($("btn-run")) $("btn-run").onclick = () => executeAnalysis(true);
  if ($("btn-load-sample")) $("btn-load-sample").onclick = () => loadSampleFocusGroupNotes();

  const fileInput = $("file-input");
  if (fileInput) {
    fileInput.onchange = e => { if (e.target.files && e.target.files.length) loadFilesFromUser(e.target.files); };
  }
  const dz = $("dropzone");
  if (dz) {
    dz.ondragover = e => { e.preventDefault(); dz.classList.add("drag-over"); };
    dz.ondragleave = () => dz.classList.remove("drag-over");
    dz.ondrop = e => {
      e.preventDefault(); dz.classList.remove("drag-over");
      if (e.dataTransfer.files && e.dataTransfer.files.length) loadFilesFromUser(e.dataTransfer.files);
    };
  }

  document.querySelectorAll("[data-rm-file]").forEach(btn => {
    btn.onclick = () => {
      APP_STATE.files.splice(parseInt(btn.dataset.rmFile, 10), 1);
      if (!APP_STATE.files.length) APP_STATE.isFixture = false;
      refreshTabularPreviewState();
      APP_STATE.dirty = true;
      renderAll();
    };
  });

  document.querySelectorAll('input[name="data-type"]').forEach(r => {
    r.onchange = () => { APP_STATE.groupMode = r.value === "group"; APP_STATE.dirty = true; renderAll(); };
  });
  if ($("chk-obs")) $("chk-obs").onchange = e => { APP_STATE.includeObservations = e.target.checked; APP_STATE.dirty = true; renderAll(); };
  if ($("chk-spelling")) $("chk-spelling").onchange = e => { APP_STATE.spellingTolerance = e.target.checked; APP_STATE.dirty = true; renderAll(); };

  if ($("sel-sheet")) $("sel-sheet").onchange = e => { APP_STATE.sheetName = e.target.value; APP_STATE.textCol = ""; refreshTabularPreviewState(); APP_STATE.dirty = true; renderAll(); };
  if ($("sel-text-col")) $("sel-text-col").onchange = e => { APP_STATE.textCol = e.target.value; refreshTabularPreviewState(); APP_STATE.dirty = true; renderAll(); };
  if ($("sel-id-col")) $("sel-id-col").onchange = e => { APP_STATE.idCol = e.target.value; refreshTabularPreviewState(); APP_STATE.dirty = true; renderAll(); };
  if ($("sel-spk-col")) $("sel-spk-col").onchange = e => { APP_STATE.speakerCol = e.target.value; APP_STATE.dirty = true; renderAll(); };
  document.querySelectorAll('input[name="dup-policy"]').forEach(r => {
    r.onchange = () => { APP_STATE.duplicateIdPolicy = r.value; APP_STATE.dirty = true; renderAll(); };
  });

  const clearSessionOverride = () => {
    APP_STATE.sessionRulesOverride = null;
    APP_STATE.sessionOverrideLabel = "";
  };
  if ($("btn-core-all")) $("btn-core-all").onclick = () => { clearSessionOverride(); APP_STATE.selectedCore = new Set(ATLAS_CORE_THEMES.map(r => r.id)); APP_STATE.dirty = true; renderAll(); };
  if ($("btn-core-clear")) $("btn-core-clear").onclick = () => { clearSessionOverride(); APP_STATE.selectedCore = new Set(); APP_STATE.dirty = true; renderAll(); };
  if ($("btn-addon-all")) $("btn-addon-all").onclick = () => { clearSessionOverride(); APP_STATE.selectedAddon = new Set(ATLAS_ADDON_THEMES.map(r => r.id)); APP_STATE.dirty = true; renderAll(); };
  if ($("btn-addon-clear")) $("btn-addon-clear").onclick = () => { clearSessionOverride(); APP_STATE.selectedAddon = new Set(); APP_STATE.dirty = true; renderAll(); };

  document.querySelectorAll("[data-core-id]").forEach(cb => {
    cb.onchange = () => {
      clearSessionOverride();
      if (cb.checked) APP_STATE.selectedCore.add(cb.dataset.coreId); else APP_STATE.selectedCore.delete(cb.dataset.coreId);
      APP_STATE.dirty = true; renderAll();
    };
  });
  document.querySelectorAll("[data-addon-id]").forEach(cb => {
    cb.onchange = () => {
      clearSessionOverride();
      if (cb.checked) APP_STATE.selectedAddon.add(cb.dataset.addonId); else APP_STATE.selectedAddon.delete(cb.dataset.addonId);
      APP_STATE.dirty = true; renderAll();
    };
  });

  if ($("yaml-input")) {
    $("yaml-input").onchange = async e => {
      const f = e.target.files && e.target.files[0];
      if (!f) return;
      try {
        const text = await f.text();
        const parsed = parseSimpleYaml(text);
        const rules = normalizeCodebookRules(parsed);
        if (!rules.length) throw new Error(`Uploaded theme file '${f.name}' contains no themes.`);
        clearSessionOverride();
        APP_STATE.uploadedYamlName = f.name;
        APP_STATE.uploadedYamlRules = rules;
        APP_STATE.runError = null;
        APP_STATE.dirty = true;
      } catch (err) {
        APP_STATE.runError = `Could not parse custom theme file: ${err.message || err}`;
      }
      renderAll();
    };
  }
  if ($("btn-clear-yaml")) $("btn-clear-yaml").onclick = () => { clearSessionOverride(); APP_STATE.uploadedYamlName = ""; APP_STATE.uploadedYamlRules = null; APP_STATE.dirty = true; renderAll(); };
  document.querySelectorAll('input[name="yaml-mode"]').forEach(r => {
    r.onchange = () => { clearSessionOverride(); APP_STATE.uploadMode = r.value; APP_STATE.dirty = true; renderAll(); };
  });
  if ($("btn-reset-edits")) $("btn-reset-edits").onclick = () => executeAnalysis(false);

  document.querySelectorAll("[data-tab]").forEach(btn => {
    btn.onclick = () => { APP_STATE.activeTab = btn.dataset.tab; renderAll(); };
  });
  document.querySelectorAll("[data-subtab]").forEach(btn => {
    btn.onclick = () => { APP_STATE.activeSubtab = btn.dataset.subtab; renderAll(); };
  });

  // Summary grid controls & cell click-to-jump
  document.querySelectorAll('input[name="grid-mode"]').forEach(r => {
    r.onchange = () => { APP_STATE.gridShowEntries = r.value === "entries"; renderAll(); };
  });
  if ($("chk-hide-zero")) $("chk-hide-zero").onchange = e => { APP_STATE.hideZeroThemes = e.target.checked; renderAll(); };
  document.querySelectorAll("[data-jump-theme]").forEach(td => {
    td.onclick = () => {
      APP_STATE.evFilterTheme = td.dataset.jumpTheme;
      APP_STATE.evFilterFile = td.dataset.jumpFile;
      APP_STATE.evFilterSpeaker = "__all__";
      APP_STATE.evFilterQuestion = "__all__";
      APP_STATE.evPage = 1;
      APP_STATE.evShowAll = false;
      APP_STATE.activeSubtab = "evidence";
      renderAll();
    };
  });

  // Evidence filters & pagination
  const resetEvPage = () => { APP_STATE.evPage = 1; APP_STATE.evShowAll = false; };
  if ($("ev-theme")) $("ev-theme").onchange = e => { APP_STATE.evFilterTheme = e.target.value; resetEvPage(); renderAll(); };
  if ($("ev-file")) $("ev-file").onchange = e => { APP_STATE.evFilterFile = e.target.value; resetEvPage(); renderAll(); };
  if ($("ev-question")) $("ev-question").onchange = e => { APP_STATE.evFilterQuestion = e.target.value; resetEvPage(); renderAll(); };
  if ($("ev-spk")) $("ev-spk").onchange = e => { APP_STATE.evFilterSpeaker = e.target.value; resetEvPage(); renderAll(); };
  if ($("ev-verbatim")) $("ev-verbatim").onchange = e => { APP_STATE.evVerbatimOnly = e.target.checked; resetEvPage(); renderAll(); };
  if ($("ev-search")) {
    $("ev-search").oninput = e => {
      const pos = e.target.selectionStart;
      APP_STATE.evSearch = e.target.value;
      resetEvPage();
      renderAll();
      const el = document.getElementById("ev-search");
      if (el) { el.focus(); el.setSelectionRange(pos, pos); }
    };
  }
  document.querySelectorAll("[data-pager-action]").forEach(btn => {
    btn.onclick = () => {
      const act = btn.dataset.pagerAction;
      if (act === "ev-prev") APP_STATE.evPage = Math.max(1, APP_STATE.evPage - 1);
      else if (act === "ev-next") APP_STATE.evPage = APP_STATE.evPage + 1;
      else if (act === "ev-show-all") { APP_STATE.evShowAll = !APP_STATE.evShowAll; if (!APP_STATE.evShowAll) APP_STATE.evPage = 1; }
      else if (act === "sc-prev") APP_STATE.scPage = Math.max(1, APP_STATE.scPage - 1);
      else if (act === "sc-next") APP_STATE.scPage = APP_STATE.scPage + 1;
      else if (act === "sc-show-all") { APP_STATE.scShowAll = !APP_STATE.scShowAll; if (!APP_STATE.scShowAll) APP_STATE.scPage = 1; }
      renderAll();
    };
  });

  // Discovery controls
  if ($("disc-k")) $("disc-k").onchange = e => { APP_STATE.discoveryK = parseInt(e.target.value, 10); };
  if ($("btn-rerun-disc")) {
    $("btn-rerun-disc").onclick = () => {
      if (!APP_STATE.results) return;
      APP_STATE.discovery = discoverTopicsOffline(APP_STATE.results.tagged_turns, APP_STATE.discoveryK);
      const dm = new Map(APP_STATE.results.frequencies.map(f => [f.domain_id, f.domain_name]));
      APP_STATE.discoveryOverlap = computeTopicCodebookOverlap(APP_STATE.discovery, APP_STATE.results.tagged_turns, dm);
      renderAll();
    };
  }
  if ($("add-topic-sel")) $("add-topic-sel").onchange = e => { APP_STATE.addTopicId = parseInt(e.target.value, 10); };
  if ($("add-topic-name")) $("add-topic-name").oninput = e => { APP_STATE.addTopicName = e.target.value; };
  if ($("add-topic-exact")) $("add-topic-exact").onchange = e => { APP_STATE.addTopicExact = e.target.checked; };
  if ($("btn-add-topic")) {
    $("btn-add-topic").onclick = () => {
      const t = APP_STATE.discovery && APP_STATE.discovery.topics.find(x => x.topic_id === APP_STATE.addTopicId);
      if (!t) return;
      const base = getEffectiveRules().map(r => ({ ...r, roots_en: [...r.roots_en], roots_es: [...r.roots_es], context_fences: [...r.context_fences], exclude_fences: [...r.exclude_fences] }));
      const name = APP_STATE.addTopicName.trim() || `Discovered: ${t.label}`;
      let id = "discovered_" + foldAccents(name).toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
      const used = new Set(base.map(r => r.id));
      let n = 2; while (used.has(id)) id = `${id}_${n++}`;
      base.push({
        id, name, description: "Added from offline topic discovery",
        match_mode: APP_STATE.addTopicExact ? "exact" : "prefix",
        roots_en: [...t.top_terms], roots_es: [], context_fences: [], context_window: null, exclude_fences: [], exclude_window: null
      });
      APP_STATE.sessionRulesOverride = base;
      APP_STATE.sessionOverrideLabel = `Added "${name}"`;
      APP_STATE.addTopicName = "";
      executeAnalysis(true);
    };
  }

  // Spot-check controls
  const resetScPage = () => { APP_STATE.scPage = 1; APP_STATE.scShowAll = false; };
  if ($("sc-filter-prio")) $("sc-filter-prio").onchange = e => { APP_STATE.scFilterPriority = e.target.value; resetScPage(); renderAll(); };
  if ($("sc-filter-theme")) $("sc-filter-theme").onchange = e => { APP_STATE.scFilterTheme = e.target.value; resetScPage(); renderAll(); };
  if ($("sc-domain")) $("sc-domain").onchange = e => { APP_STATE.spotcheckDomainId = e.target.value; APP_STATE.spotcheckSelectedWords = new Set(); renderAll(); };
  if ($("sc-exact")) $("sc-exact").onchange = e => { APP_STATE.spotcheckSetExact = e.target.checked; };
  document.querySelectorAll("[data-excl-word]").forEach(cb => {
    cb.onchange = () => {
      if (cb.checked) APP_STATE.spotcheckSelectedWords.add(cb.dataset.exclWord);
      else APP_STATE.spotcheckSelectedWords.delete(cb.dataset.exclWord);
    };
  });
  if ($("btn-apply-spotcheck")) {
    $("btn-apply-spotcheck").onclick = () => {
      const words = Array.from(APP_STATE.spotcheckSelectedWords);
      if (!words.length && !APP_STATE.spotcheckSetExact) return;
      const base = getEffectiveRules().map(r => ({ ...r, roots_en: [...r.roots_en], roots_es: [...r.roots_es], context_fences: [...r.context_fences], exclude_fences: [...r.exclude_fences] }));
      const target = base.find(r => r.id === APP_STATE.spotcheckDomainId);
      if (!target) return;
      if (APP_STATE.spotcheckSetExact) target.match_mode = "exact";
      if (words.length) {
        const had = target.exclude_fences.length > 0;
        const existLow = new Set(target.exclude_fences.map(x => foldAccents(x).toLowerCase()));
        for (const w of words) if (!existLow.has(w)) target.exclude_fences.push(w);
        if (!had && target.exclude_window === null) target.exclude_window = 0;
      }
      APP_STATE.sessionRulesOverride = base;
      APP_STATE.sessionOverrideLabel = `Tightened "${target.name}"`;
      APP_STATE.spotcheckSelectedWords = new Set();
      APP_STATE.spotcheckSetExact = false;
      executeAnalysis(true);
    };
  }

  // Downloads
  const doDocx = async () => {
    const blob = await buildSummaryReportDocx(APP_STATE.results, APP_STATE.runMeta, APP_STATE.groupMatrix, APP_STATE.discovery, APP_STATE.discoveryOverlap, APP_STATE.excludedRows);
    triggerDownload(blob, "atlas_summary_report.docx");
  };
  const doXlsx = async () => {
    const blob = await buildFrequenciesXlsx(APP_STATE.results, APP_STATE.runMeta);
    triggerDownload(blob, "atlas_theme_frequencies.xlsx");
  };
  const doManifest = () => {
    const mf = buildProvenanceManifest(APP_STATE.results, APP_STATE.runMeta);
    triggerDownload(JSON.stringify(mf, null, 2) + "\n", "provenance_manifest.json", "application/json;charset=utf-8");
  };
  const doYaml = () => {
    const y = serializeCodebookYaml(getEffectiveRules(), "ATLAS Active Themes");
    triggerDownload(y, "atlas_active_codebook.yaml", "application/x-yaml;charset=utf-8");
  };

  if ($("btn-dl-docx")) $("btn-dl-docx").onclick = doDocx;
  if ($("btn-dl-docx-2")) $("btn-dl-docx-2").onclick = doDocx;
  if ($("btn-dl-xlsx")) $("btn-dl-xlsx").onclick = doXlsx;
  if ($("btn-dl-xlsx-2")) $("btn-dl-xlsx-2").onclick = doXlsx;
  if ($("btn-dl-csv")) $("btn-dl-csv").onclick = () => downloadEvidenceCsv(true);
  if ($("btn-dl-svg")) $("btn-dl-svg").onclick = downloadChartSvg;
  if ($("btn-dl-csv-2")) $("btn-dl-csv-2").onclick = () => downloadEvidenceCsv(false);
  if ($("btn-dl-verbatim-2")) $("btn-dl-verbatim-2").onclick = () => downloadEvidenceCsv(true);
  if ($("btn-dl-yaml-2")) $("btn-dl-yaml-2").onclick = doYaml;
  if ($("btn-dl-manifest")) $("btn-dl-manifest").onclick = doManifest;
  if ($("btn-dl-spotcheck")) $("btn-dl-spotcheck").onclick = downloadSpotcheckCsv;
  if ($("btn-dl-spotcheck-2")) $("btn-dl-spotcheck-2").onclick = downloadSpotcheckCsv;
}

// Expose deterministic testing/parity hook
window.__ATLAS_API__ = {
  state: APP_STATE,
  loadSampleFocusGroupNotes,
  executeAnalysis,
  inspectFileRecord,
  refreshTabularPreviewState,
  buildSummaryReportDocx,
  buildFrequenciesXlsx,
  buildProvenanceManifest,
  parseSimpleYaml,
  normalizeCodebookRules,
  sha256Bytes,
  renderAll,
};

document.addEventListener("DOMContentLoaded", () => { renderAll(); });
