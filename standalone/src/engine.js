// ============================================================================
// ATLAS Standalone Browser Engine — Deterministic Rule Matcher, Audit, & NMF
// Exact parity with atlas_engine.py and atlas_discover.py (v1.2)
// ============================================================================

const VERBATIM_EVIDENCE_TYPES = new Set(["notable_quote_verbatim", "verbatim_turn", ""]);
const SIMPLE_LONG_INFLECTIONS = new Set(["s", "es", "ed", "d", "ing", "er", "ers", "ly", "ies", "y"]);
const NEGATION_CUES = new Set([
  "no", "not", "never", "neither", "nor", "none", "nothing", "nowhere", "without",
  "hardly", "barely", "cannot", "cant", "can't", "dont", "don't", "didnt", "didn't",
  "doesnt", "doesn't", "isnt", "isn't", "arent", "aren't", "wasnt", "wasn't",
  "werent", "weren't", "wont", "won't", "wouldnt", "wouldn't", "couldnt", "couldn't",
  "havent", "haven't", "hasnt", "hasn't", "hadnt", "hadn't",
  "ningun", "ninguna", "nunca", "tampoco", "sin"
]);
const RE_COMBINING_MARK = /\p{Mn}/u;
const RE_WORD_CHAR = /[\p{L}\p{N}_]/u;
const RE_WORD_TOKEN = /[\p{L}\p{N}_]+/gu;
const RE_AUDIT_TOKEN = /[\p{L}\p{N}_]+(?:['\u2019][\p{L}\p{N}_]+)*/gu;

const DISCOVERY_STOPWORDS = new Set([
  "a","about","above","after","again","against","all","also","am","an","and","any","are","as","at",
  "be","because","been","before","being","below","between","both","but","by","can","could","did","do",
  "does","doing","down","during","each","few","for","from","further","get","got","had","has","have",
  "having","he","her","here","hers","herself","him","himself","his","how","i","if","in","into","is",
  "it","its","itself","just","like","many","may","me","more","most","much","my","myself","no","nor",
  "not","now","of","off","on","once","only","or","other","our","ours","ourselves","out","over","own",
  "really","said","same","say","see","she","should","so","some","such","than","that","the","their",
  "theirs","them","themselves","then","there","these","they","thing","things","think","this","those",
  "through","to","too","under","until","up","us","very","want","was","we","were","what","when","where",
  "which","while","who","whom","why","will","with","would","you","your","yours","yourself","yourselves",
  "participant","participants","group","people","person","someone","everyone","something","anything",
  "de","la","el","en","y","que","los","las","un","una","por","para","con","se","su","al","lo","del",
  "es","no","si","mas","como","pero","sus","le","ya","o","fue","este","ha","me","sin","sobre","tambien"
]);
for (let i = 0; i < 100; i++) DISCOVERY_STOPWORDS.add("p" + i);

function foldAccentsWithMap(text) {
  const s = String(text || "");
  const foldedChars = [];
  const indexMap = [];
  for (let i = 0; i < s.length; i++) {
    const ch = s[i];
    const decomp = ch.normalize("NFD");
    for (let j = 0; j < decomp.length; j++) {
      const c = decomp[j];
      if (!RE_COMBINING_MARK.test(c)) {
        foldedChars.push(c);
        indexMap.push(i);
      }
    }
  }
  indexMap.push(s.length);
  return { folded: foldedChars.join(""), indexMap };
}

function foldAccents(text) {
  return foldAccentsWithMap(text).folded;
}

function foldedSpanToOriginal(text, indexMap, foldedStart, foldedEnd) {
  const origStart = indexMap[foldedStart];
  let origEnd = indexMap[foldedEnd - 1] + 1;
  while (origEnd < text.length && RE_COMBINING_MARK.test(text[origEnd])) {
    origEnd++;
  }
  return [origStart, origEnd];
}

function escapeRegExp(s) {
  return String(s).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function termList(val) {
  if (val === null || val === undefined) return [];
  const arr = Array.isArray(val) ? val : [val];
  const out = [];
  const seen = new Set();
  for (const item of arr) {
    if (item === null || item === undefined) continue;
    const t = String(item).trim();
    if (t && !seen.has(t)) { seen.add(t); out.push(t); }
  }
  return out;
}

function parseWindow(val, label, ruleId) {
  if (val === null || val === undefined || val === "") return null;
  if (typeof val === "boolean") throw new Error(`${label} for rule '${ruleId}' must be a nonnegative integer`);
  const n = typeof val === "number" ? val : (/^\d+$/.test(String(val).trim()) ? parseInt(String(val).trim(), 10) : NaN);
  if (!Number.isInteger(n) || n < 0) {
    throw new Error(`${label} for rule '${ruleId}' must be a nonnegative integer, got ${val}`);
  }
  return n;
}

function normalizeCodebookRules(codebook) {
  if (!codebook || typeof codebook !== "object") return [];
  const meta = (codebook.meta && typeof codebook.meta === "object") ? codebook.meta : {};
  const defaultMode = String(codebook.match_mode || meta.match_mode || "prefix").trim().toLowerCase();
  const items = [];
  if (Array.isArray(codebook.domains)) {
    codebook.domains.forEach((d, i) => items.push([d, `domain_${i + 1}`]));
  } else if (codebook.topics) {
    if (Array.isArray(codebook.topics)) {
      codebook.topics.forEach((t, i) => {
        const info = Object.assign({}, t || {});
        if (!info.id && info.label) info.id = info.label;
        items.push([info, `topic_${i + 1}`]);
      });
    } else if (typeof codebook.topics === "object") {
      Object.entries(codebook.topics).forEach(([tid, tinfo]) => {
        const info = Object.assign({}, tinfo || {});
        if (!info.id) info.id = tid;
        items.push([info, String(tid)]);
      });
    }
  } else {
    for (const sec of ["themes", "frictions"]) {
      if (Array.isArray(codebook[sec])) {
        codebook[sec].forEach((d, i) => items.push([d, `${sec}_${i + 1}`]));
      }
    }
  }
  const seen = new Set();
  const rules = [];
  for (const [item, defaultId] of items) {
    if (!item || typeof item !== "object") continue;
    const id = String(item.id || defaultId);
    if (seen.has(id)) throw new Error(`Duplicate theme ID '${id}' in codebook.`);
    seen.add(id);
    const rootsEn = termList([
      ...termList(item.roots_en),
      ...termList(item.roots),
      ...termList(item.keywords),
    ]);
    const matchMode = String(item.match_mode || defaultMode || "prefix").trim().toLowerCase();
    rules.push({
      id,
      name: String(item.name || item.label || id),
      description: String(item.description || item.definition || ""),
      roots_en: rootsEn,
      roots_es: termList(item.roots_es),
      match_mode: matchMode === "exact" ? "exact" : "prefix",
      context_fences: termList(item.context_fences || item.required_context || []),
      context_window: item.context_window !== undefined ? item.context_window : (item.co_occurrence_window ?? null),
      exclude_fences: termList(item.exclude_fences || item.negative_fences || item.exclude_terms || []),
      exclude_window: item.exclude_window !== undefined ? item.exclude_window : null,
    });
  }
  return rules;
}

function compileTermPatterns(terms, matchMode = "prefix") {
  const unique = Array.from(new Set(terms.map(t => foldAccents(t)).filter(Boolean)));
  unique.sort((a, b) => (b.length - a.length) || (a < b ? -1 : a > b ? 1 : 0));
  return unique.map(t => {
    const firstWord = RE_WORD_CHAR.test(t[0]);
    const lastWord = RE_WORD_CHAR.test(t[t.length - 1]);
    const esc = escapeRegExp(t);
    const prefix = firstWord ? "(?<![\\p{L}\\p{N}_])" : "(?<![\\p{L}\\p{N}_])";
    const suffix = matchMode === "exact" ? (lastWord ? "(?![\\p{L}\\p{N}_])" : "(?![\\p{L}\\p{N}_])") : "";
    return new RegExp(prefix + esc + suffix, "giu");
  });
}

function compileFuzzyRoots(terms, minLen = 5) {
  const out = new Set();
  for (const raw of terms) {
    const folded = foldAccents(String(raw || "")).trim().toLowerCase();
    if (folded.length < minLen || /\s/.test(folded) || !/^[\p{L}\p{N}_]+$/u.test(folded)) continue;
    out.add(folded);
  }
  return Array.from(out).sort();
}

function compileRule(domain) {
  const roots = [...(domain.roots_en || []), ...(domain.roots_es || [])];
  const mode = domain.match_mode === "exact" ? "exact" : "prefix";
  return {
    id: domain.id,
    name: domain.name,
    description: domain.description || "",
    match_mode: mode,
    roots_en: [...(domain.roots_en || [])],
    roots_es: [...(domain.roots_es || [])],
    context_fences: [...(domain.context_fences || [])],
    exclude_fences: [...(domain.exclude_fences || [])],
    root_patterns: compileTermPatterns(roots, mode),
    fuzzy_roots: compileFuzzyRoots(roots, 5),
    fence_patterns: compileTermPatterns(domain.context_fences || [], "prefix"),
    context_window: parseWindow(domain.context_window, "context_window", domain.id),
    exclude_patterns: compileTermPatterns(domain.exclude_fences || [], "prefix"),
    exclude_window: parseWindow(domain.exclude_window, "exclude_window", domain.id),
  };
}

function findOverlappingSpans(patterns, text) {
  const seen = new Set();
  const spans = [];
  for (const pat of patterns) {
    let pos = 0;
    while (pos < text.length) {
      pat.lastIndex = pos;
      const m = pat.exec(text);
      if (!m) break;
      const s = m.index, e = m.index + m[0].length;
      const key = `${s}:${e}`;
      if (!seen.has(key)) { seen.add(key); spans.push([s, e]); }
      pos = s + 1;
    }
  }
  spans.sort((a, b) => (a[0] - b[0]) || (b[1] - a[1]));
  return spans;
}

function bisectRight(arr, x) {
  let lo = 0, hi = arr.length;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if (arr[mid] <= x) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

function bisectLeft(arr, x) {
  let lo = 0, hi = arr.length;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if (arr[mid] < x) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

function tokenInterval(tokenStarts, start, end) {
  if (!tokenStarts.length) return [0, 0];
  const first = Math.max(bisectRight(tokenStarts, start) - 1, 0);
  const last = Math.max(bisectRight(tokenStarts, Math.max(end - 1, start)) - 1, first);
  return [first, last];
}

function intervalGap(a, b) {
  return Math.max(0, b[0] - a[1], a[0] - b[1]);
}

function countMentions(spans) {
  let count = 0, coveredTo = -1;
  for (const [s, e] of spans) {
    if (s >= coveredTo) { count++; coveredTo = e; }
  }
  return count;
}

function damerauLevenshtein1(a, b) {
  if (a === b) return false;
  const la = a.length, lb = b.length;
  if (Math.abs(la - lb) > 1) return false;
  if (la === lb) {
    const diffs = [];
    for (let i = 0; i < la; i++) {
      if (a[i] !== b[i]) {
        diffs.push(i);
        if (diffs.length > 2) return false;
      }
    }
    if (diffs.length === 1) return true;
    if (diffs.length === 2) {
      const [i, j] = diffs;
      return j === i + 1 && a[i] === b[j] && a[j] === b[i];
    }
    return false;
  }
  const [shortS, longS] = la < lb ? [a, b] : [b, a];
  let i = 0, j = 0, skipped = false;
  while (i < shortS.length && j < longS.length) {
    if (shortS[i] === longS[j]) { i++; j++; }
    else if (!skipped) { skipped = true; j++; }
    else return false;
  }
  return true;
}

function matchRule(rule, folded, tokenStarts) {
  if (!rule.root_patterns.length) return [];
  const roots = findOverlappingSpans(rule.root_patterns, folded);
  if (!roots.length) return [];

  const hasFences = rule.fence_patterns.length > 0;
  const fenceWin = rule.context_window;
  const fences = hasFences ? findOverlappingSpans(rule.fence_patterns, folded) : [];
  if (hasFences && !fences.length) return [];

  const exclWin = rule.exclude_window;
  const excludes = rule.exclude_patterns.length ? findOverlappingSpans(rule.exclude_patterns, folded) : [];
  if (excludes.length && exclWin === null) return [];

  const fenceToks = fences.map(([s, e]) => tokenInterval(tokenStarts, s, e));
  const exclToks = excludes.map(([s, e]) => tokenInterval(tokenStarts, s, e));

  const qualifying = [];
  for (const [rStart, rEnd] of roots) {
    const rTok = tokenInterval(tokenStarts, rStart, rEnd);
    if (hasFences && fenceWin !== null) {
      if (!fenceToks.some(fTok => intervalGap(rTok, fTok) <= fenceWin)) continue;
    }
    if (exclWin !== null && exclToks.some(xTok => intervalGap(rTok, xTok) <= exclWin)) continue;
    qualifying.push([rStart, rEnd]);
  }
  return qualifying;
}

function matchRuleFuzzy(rule, folded, tokenStarts) {
  if (!rule.fuzzy_roots.length) return [];
  const candidates = [];
  RE_WORD_TOKEN.lastIndex = 0;
  let m;
  while ((m = RE_WORD_TOKEN.exec(folded)) !== null) {
    const tokLower = m[0].toLowerCase();
    if (tokLower.length < 4) continue;
    for (const root of rule.fuzzy_roots) {
      if (damerauLevenshtein1(tokLower, root)) {
        candidates.push([m.index, m.index + m[0].length, root]);
        break;
      }
    }
  }
  if (!candidates.length) return [];

  const hasFences = rule.fence_patterns.length > 0;
  const fenceWin = rule.context_window;
  const fences = hasFences ? findOverlappingSpans(rule.fence_patterns, folded) : [];
  if (hasFences && !fences.length) return [];

  const exclWin = rule.exclude_window;
  const excludes = rule.exclude_patterns.length ? findOverlappingSpans(rule.exclude_patterns, folded) : [];
  if (excludes.length && exclWin === null) return [];

  const fenceToks = fences.map(([s, e]) => tokenInterval(tokenStarts, s, e));
  const exclToks = excludes.map(([s, e]) => tokenInterval(tokenStarts, s, e));

  const qualifying = [];
  for (const [rStart, rEnd, root] of candidates) {
    const rTok = tokenInterval(tokenStarts, rStart, rEnd);
    if (hasFences && fenceWin !== null) {
      if (!fenceToks.some(fTok => intervalGap(rTok, fTok) <= fenceWin)) continue;
    }
    if (exclWin !== null && exclToks.some(xTok => intervalGap(rTok, xTok) <= exclWin)) continue;
    qualifying.push([rStart, rEnd, root]);
  }
  return qualifying;
}

function auditDigest(domainId, documentsReporting, totalDocuments, matchingTurns, prevalencePct, fileHashes) {
  const shas = Object.values(fileHashes).sort().join("+");
  const payload = `${domainId}|${documentsReporting}|${totalDocuments}|${matchingTurns}|${Number(prevalencePct).toFixed(1)}|${shas}`;
  return sha256Bytes(payload);
}

function runAtlasEngine(turnsInput, fileHashes, normalizedRules, opts) {
  const groupBySource = Boolean(opts && opts.groupBySource);
  const spellingTolerance = Boolean(opts && opts.spellingTolerance);
  const compiledRules = normalizedRules.map(compileRule);

  const turns = groupBySource
    ? turnsInput.map(t => ({ ...t, unit_id: t.source_id || t.document_name }))
    : turnsInput.map(t => ({ ...t }));

  const participantTurns = turns.filter(t => !t.is_facilitator);
  const hasRespondentId = participantTurns.some(t => Object.prototype.hasOwnProperty.call(t, "respondent_id"));

  const taggedTurns = [];
  const quotes = [];
  const typoMatches = [];
  const mentionCounts = Object.fromEntries(compiledRules.map(r => [r.id, 0]));

  for (const turn of participantTurns) {
    const text = String(turn.text || "");
    const sourceId = turn.source_id || turn.document_name;
    const unitId = turn.unit_id || sourceId;
    const { folded, indexMap } = foldAccentsWithMap(text);
    const tokenStarts = [];
    RE_WORD_TOKEN.lastIndex = 0;
    let tm;
    while ((tm = RE_WORD_TOKEN.exec(folded)) !== null) tokenStarts.push(tm.index);

    const matchedDomains = [];
    for (const rule of compiledRules) {
      let spans = matchRule(rule, folded, tokenStarts);
      let fuzzyHits = [];
      if (!spans.length && spellingTolerance) {
        fuzzyHits = matchRuleFuzzy(rule, folded, tokenStarts);
        spans = fuzzyHits.map(([s, e]) => [s, e]);
      }
      if (!spans.length) continue;

      mentionCounts[rule.id] += countMentions(spans);
      const [fStart, fEnd] = spans[0];
      const [matchStart, matchEnd] = foldedSpanToOriginal(text, indexMap, fStart, fEnd);

      for (const [fs, fe, froot] of fuzzyHits) {
        const [osI, oeI] = foldedSpanToOriginal(text, indexMap, fs, fe);
        typoMatches.push({
          source_id: sourceId,
          unit_id: unitId,
          turn_id: turn.turn_id,
          line_number: turn.line_number,
          domain_id: rule.id,
          domain_name: rule.name,
          matched_span: text.slice(osI, oeI),
          matched_root: froot,
          match_char_start: osI,
          match_char_end: oeI,
          text,
        });
      }

      matchedDomains.push(rule.id);
      const qRow = {
        domain_id: rule.id,
        domain_name: rule.name,
        document_name: turn.document_name || sourceId,
        source_id: sourceId,
        unit_id: unitId,
        turn_id: turn.turn_id,
        line_number: turn.line_number,
        timestamp: turn.timestamp || "",
        speaker: turn.speaker || "Unknown",
        text,
        char_start: turn.char_start,
        char_end: turn.char_end,
        match_char_start: matchStart,
        match_char_end: matchEnd,
        match_text: text.slice(matchStart, matchEnd),
        source_sha256: fileHashes[sourceId] || "",
        evidence_type: String(turn.evidence_type || ""),
        question_id: String(turn.question_id || ""),
        group_id: String(turn.group_id || ""),
        participant_id: String(turn.participant_id || ""),
      };
      if (hasRespondentId) qRow.respondent_id = String(turn.respondent_id || "");
      quotes.push(qRow);
    }
    taggedTurns.push({ ...turn, matched_domains: matchedDomains });
  }

  // Denominator calculation matching Python _analytical_units
  let totalDocs;
  if (groupBySource) {
    totalDocs = Object.keys(fileHashes).length;
  } else {
    const units = new Set();
    const sourcesWithTurns = new Set();
    for (const t of turns) {
      const sid = t.source_id || t.document_name;
      const uid = t.unit_id || sid;
      sourcesWithTurns.add(sid);
      if (!t.is_facilitator || uid === sid) units.add(uid);
    }
    for (const sid of Object.keys(fileHashes)) {
      const dot = sid.lastIndexOf(".");
      const ext = dot >= 0 ? sid.slice(dot).toLowerCase() : "";
      if (!sourcesWithTurns.has(sid) && !TABULAR_EXTENSIONS.has(ext)) units.add(sid);
    }
    totalDocs = units.size;
  }

  const frequencies = compiledRules.map(rule => {
    const domQuotes = quotes.filter(q => q.domain_id === rule.id);
    const docCount = new Set(domQuotes.map(q => q.unit_id)).size;
    const prevPct = totalDocs > 0 ? Math.round((docCount / totalDocs) * 1000) / 10 : 0.0;
    const statement = `${prevPct.toFixed(1)}% of documents (${docCount} of ${totalDocs}) across ${domQuotes.length} matching turns reported ${rule.name.toLowerCase()}.`;
    return {
      domain_id: rule.id,
      domain_name: rule.name,
      documents_reporting: docCount,
      total_documents: totalDocs,
      prevalence_pct: prevPct,
      matching_turns: domQuotes.length,
      total_mentions: mentionCounts[rule.id],
      reporting_statement: statement,
      audit_sha256: auditDigest(rule.id, docCount, totalDocs, domQuotes.length, prevPct, fileHashes),
    };
  });

  const auditRows = auditFalseAlarmRisks(quotes, compiledRules, typoMatches);

  return {
    total_documents: totalDocs,
    total_turns_parsed: turns.length,
    participant_turns_analyzed: participantTurns.length,
    file_hashes: { ...fileHashes },
    compiled_rules: compiledRules,
    frequencies,
    quotes,
    tagged_turns: taggedTurns,
    spelling_tolerance: spellingTolerance,
    typo_matches: typoMatches,
    audit_rows: auditRows,
    has_respondent_id: hasRespondentId,
  };
}

// ----------------------------------------------------------------------------
// Spot-Check / False-Alarm Audit (Exact Python parity)
// ----------------------------------------------------------------------------
function isWordChar(ch) {
  return RE_WORD_CHAR.test(ch) || RE_COMBINING_MARK.test(ch);
}

function isBenignInflection(foldedSpan, tail, shortMax = 4) {
  if (!tail) return true;
  if (foldedSpan.length <= 3) {
    if (tail === "s") return true;
    if (tail === "es" && /(s|x|z|ch|sh)$/.test(foldedSpan)) return true;
    return false;
  }
  if (foldedSpan.length <= shortMax) {
    if (tail === "s" || tail === "ed" || tail === "ing") return true;
    if (tail === "es" && /(s|x|z|ch|sh)$/.test(foldedSpan)) return true;
    return false;
  }
  return SIMPLE_LONG_INFLECTIONS.has(tail);
}

function auditFalseAlarmRisks(quotes, compiledRules, typoMatches, shortMax = 4, negWindow = 5) {
  if (!quotes || !quotes.length) return [];
  const ruleById = new Map(compiledRules.map(r => [r.id, r]));
  const typoByMatch = new Map();
  for (const tr of (typoMatches || [])) {
    const key = `${tr.source_id}|${tr.unit_id}|${tr.turn_id}|${tr.line_number}|${tr.domain_id}`;
    if (!typoByMatch.has(key)) typoByMatch.set(key, []);
    typoByMatch.get(key).push([tr.match_char_start, tr.match_char_end, tr.matched_span, tr.matched_root]);
  }

  const flagged = [];
  for (const row of quotes) {
    const text = String(row.text || "");
    const domainId = String(row.domain_id || "");
    const domainName = String(row.domain_name || domainId);
    const rule = ruleById.get(domainId);
    const matchKey = `${row.source_id}|${row.unit_id}|${row.turn_id}|${row.line_number}|${domainId}`;
    const typoEntries = typoByMatch.get(matchKey) || [];

    const { folded, indexMap } = foldAccentsWithMap(text);
    const tokenStarts = [];
    RE_WORD_TOKEN.lastIndex = 0;
    let wm;
    while ((wm = RE_WORD_TOKEN.exec(folded)) !== null) tokenStarts.push(wm.index);

    let spans = [];
    if (rule && !typoEntries.length) {
      const qual = matchRule(rule, folded, tokenStarts);
      let coveredTo = -1;
      for (const [fs, fe] of qual) {
        if (fs >= coveredTo) {
          spans.push(foldedSpanToOriginal(text, indexMap, fs, fe));
          coveredTo = fe;
        }
      }
    }
    if (!spans.length) {
      spans = typoEntries.length
        ? typoEntries.map(([s, e]) => [s, e])
        : [[row.match_char_start, row.match_char_end]];
    }

    const extEntries = [];
    const extWords = [];
    const extSeen = new Set();
    const spellingWords = [];
    const spellSeen = new Set();
    const spellPairs = [];
    let shortEntry = null;
    let nearestNeg = null;

    for (const [, , tSpan, tRoot] of typoEntries) {
      const wk = tSpan.trim().toLowerCase();
      if (wk && !spellSeen.has(wk)) {
        spellSeen.add(wk);
        spellingWords.push(tSpan.trim());
        spellPairs.push(`'${tSpan.trim()}' -> '${tRoot}'`);
      }
    }

    const auditToks = [];
    RE_AUDIT_TOKEN.lastIndex = 0;
    let am;
    while ((am = RE_AUDIT_TOKEN.exec(folded)) !== null) {
      auditToks.push({ start: am.index, end: am.index + am[0].length, text: am[0] });
    }

    const hasContext = rule ? rule.fence_patterns.length > 0 : false;
    const hasExclude = rule ? rule.exclude_patterns.length > 0 : false;
    const ruleMode = rule ? rule.match_mode : "prefix";

    for (const [s, e] of spans) {
      const matchedSpan = e > s ? text.slice(s, e) : String(row.match_text || "");
      let wStart = s, wEnd = e;
      while (wStart > 0 && isWordChar(text[wStart - 1])) wStart--;
      while (wEnd < text.length && isWordChar(text[wEnd])) wEnd++;
      const fullWord = wEnd > wStart ? text.slice(wStart, wEnd) : matchedSpan;
      const foldedSpan = foldAccents(matchedSpan).toLowerCase();
      const tail = wEnd > e ? foldAccents(text.slice(e, wEnd)).toLowerCase() : "";
      const headExt = wStart < s;

      if (!typoEntries.length) {
        if ((wEnd > e && !isBenignInflection(foldedSpan, tail, shortMax)) || headExt) {
          extEntries.push([s, e, matchedSpan, fullWord]);
          const wk = fullWord.trim().toLowerCase();
          if (wk && !extSeen.has(wk)) { extSeen.add(wk); extWords.push(fullWord.trim()); }
        }
        if (!shortEntry && ruleMode === "prefix" && !hasContext && !hasExclude && foldedSpan.length > 0 && foldedSpan.length <= shortMax && !foldedSpan.includes(" ")) {
          shortEntry = [s, e, matchedSpan, fullWord];
        }
      }

      if (auditToks.length) {
        const fStart = bisectLeft(indexMap, s);
        const fEnd = bisectLeft(indexMap, e);
        const overlap = [];
        for (let i = 0; i < auditToks.length; i++) {
          if (auditToks[i].end > fStart && auditToks[i].start < Math.max(fEnd, fStart + 1)) overlap.push(i);
        }
        if (overlap.length) {
          const firstT = overlap[0], lastT = overlap[overlap.length - 1];
          const lo = Math.max(0, firstT - negWindow);
          const hi = Math.min(auditToks.length, lastT + 1 + negWindow);
          for (let i = lo; i < hi; i++) {
            if (i >= firstT && i <= lastT) continue;
            const normTok = auditToks[i].text.replace(/\u2019/g, "'").toLowerCase();
            if (NEGATION_CUES.has(normTok)) {
              const dist = Math.min(Math.abs(i - firstT), Math.abs(i - lastT));
              if (!nearestNeg || dist < nearestNeg[0]) {
                nearestNeg = [dist, auditToks[i].text, s, e, matchedSpan, fullWord];
              }
            }
          }
        }
      }
    }

    const codes = [], reasons = [], fixes = [];
    if (typoEntries.length) {
      codes.push("spelling_tolerance");
      reasons.push(`Matched via spelling tolerance (${spellPairs.join(", ")})`);
      fixes.push(`Confirm typo in context; exclude ${spellingWords.map(w => `'${w.toLowerCase()}'`).join(", ")} below if not a real match`);
    }
    if (extEntries.length) {
      codes.push("prefix_extension");
      reasons.push(`Keyword '${extEntries[0][2]}' matched inside longer word ${extWords.map(w => `'${w}'`).join(", ")}`);
      fixes.push(`Exclude ${extWords.map(w => `'${w.toLowerCase()}'`).join(", ")} below, or switch this theme to exact whole-word matching`);
    }
    if (nearestNeg) {
      codes.push("negation_nearby");
      reasons.push(`Negation word '${nearestNeg[1]}' appeared nearby`);
      fixes.push("Read in context to confirm this still belongs in the theme");
    }
    if (shortEntry) {
      codes.push("short_unfenced_root");
      reasons.push(`Short keyword ('${shortEntry[2]}') matched in a theme without exclusion words`);
      if (!codes.includes("prefix_extension")) fixes.push("Review in context or switch this theme to exact whole-word matching");
    }
    if (!codes.length) continue;

    let focusS, focusE, focusSpan, focusWord;
    if (typoEntries.length) { [focusS, focusE, focusSpan] = typoEntries[0]; focusWord = focusSpan; }
    else if (extEntries.length) { [focusS, focusE, focusSpan, focusWord] = extEntries[0]; }
    else if (nearestNeg) { [, , focusS, focusE, focusSpan, focusWord] = nearestNeg; }
    else { [focusS, focusE, focusSpan, focusWord] = shortEntry; }

    const riskLevel = (codes.includes("prefix_extension") || codes.includes("spelling_tolerance")) ? "High" : "Medium";
    flagged.push({
      risk_level: riskLevel,
      domain_id: domainId,
      domain_name: domainName,
      matched_span: focusSpan,
      full_word: focusWord,
      extension_words: extWords.map(w => w.toLowerCase()).join(", "),
      spelling_words: spellingWords.map(w => w.toLowerCase()).join(", "),
      flag_codes: codes.join(","),
      flag_reason: reasons.join("; "),
      suggested_fix: fixes.join("; "),
      speaker: String(row.speaker || ""),
      source_id: String(row.source_id || ""),
      line_number: row.line_number,
      evidence_type: String(row.evidence_type || ""),
      match_char_start: focusS,
      match_char_end: focusE,
      text,
    });
  }

  flagged.sort((a, b) => {
    const ra = a.risk_level === "High" ? 0 : 1, rb = b.risk_level === "High" ? 0 : 1;
    if (ra !== rb) return ra - rb;
    if (a.domain_name !== b.domain_name) return a.domain_name < b.domain_name ? -1 : 1;
    if (a.source_id !== b.source_id) return a.source_id < b.source_id ? -1 : 1;
    return (Number(a.line_number) - Number(b.line_number)) || (a.match_char_start - b.match_char_start);
  });
  return flagged;
}

// ----------------------------------------------------------------------------
// Pure-JS Deterministic Offline Topic Discovery (TF-IDF + NMF, fixed seed 42)
// ----------------------------------------------------------------------------
function mulberry32(seed) {
  let a = seed >>> 0;
  return function() {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function discoverTopicsOffline(turnRecords, nTopics = 4) {
  const nDocs = turnRecords.length;
  if (nDocs < 2) {
    return { topics: [], assignments: [], n_analyzed: nDocs, warning: "Need at least 2 entries to cluster unlisted themes." };
  }
  const docTokens = turnRecords.map(rec => {
    const folded = foldAccents(String(rec.text || "")).toLowerCase();
    const toks = (folded.match(/[a-z]{3,}/g) || []).filter(w => !DISCOVERY_STOPWORDS.has(w));
    return toks;
  });

  const df = new Map();
  docTokens.forEach(toks => {
    for (const w of new Set(toks)) df.set(w, (df.get(w) || 0) + 1);
  });

  const minDf = nDocs >= 10 ? 2 : 1;
  const vocab = Array.from(df.entries())
    .filter(([, c]) => c >= minDf && c < nDocs * 0.95)
    .sort((a, b) => (b[1] - a[1]) || (a[0] < b[0] ? -1 : 1))
    .slice(0, 400)
    .map(([w]) => w);

  if (vocab.length < 2) {
    return { topics: [], assignments: [], n_analyzed: nDocs, warning: "Not enough distinct non-stopword vocabulary to cluster entries." };
  }

  const vocabIdx = new Map(vocab.map((w, i) => [w, i]));
  const V = vocab.length;
  const K = Math.max(2, Math.min(nTopics, Math.min(nDocs, V)));

  // Build L2-normalized TF-IDF matrix X (nDocs x V)
  const X = Array.from({ length: nDocs }, () => new Float64Array(V));
  for (let d = 0; d < nDocs; d++) {
    const counts = new Map();
    for (const w of docTokens[d]) {
      if (vocabIdx.has(w)) counts.set(vocabIdx.get(w), (counts.get(vocabIdx.get(w)) || 0) + 1);
    }
    let normSq = 0;
    for (const [j, tf] of counts.entries()) {
      const idf = Math.log((1 + nDocs) / (1 + df.get(vocab[j]))) + 1;
      const val = tf * idf;
      X[d][j] = val;
      normSq += val * val;
    }
    if (normSq > 0) {
      const inv = 1 / Math.sqrt(normSq);
      for (const j of counts.keys()) X[d][j] *= inv;
    }
  }

  // Deterministic multiplicative-update NMF (X ~ W * H)
  const rng = mulberry32(42);
  const W = Array.from({ length: nDocs }, () => Float64Array.from({ length: K }, () => 0.1 + rng()));
  const H = Array.from({ length: K }, () => Float64Array.from({ length: V }, () => 0.1 + rng()));
  const eps = 1e-9;

  for (let iter = 0; iter < 45; iter++) {
    // Update H: H = H * (W^T X) / (W^T W H)
    const WtX = Array.from({ length: K }, () => new Float64Array(V));
    const WtW = Array.from({ length: K }, () => new Float64Array(K));
    for (let d = 0; d < nDocs; d++) {
      for (let k = 0; k < K; k++) {
        const wdk = W[d][k];
        for (let k2 = 0; k2 < K; k2++) WtW[k][k2] += wdk * W[d][k2];
        for (let j = 0; j < V; j++) if (X[d][j] !== 0) WtX[k][j] += wdk * X[d][j];
      }
    }
    for (let k = 0; k < K; k++) {
      for (let j = 0; j < V; j++) {
        let denom = eps;
        for (let k2 = 0; k2 < K; k2++) denom += WtW[k][k2] * H[k2][j];
        H[k][j] = H[k][j] * (WtX[k][j] / denom);
      }
    }
    // Update W: W = W * (X H^T) / (W H H^T)
    const HHt = Array.from({ length: K }, () => new Float64Array(K));
    for (let k = 0; k < K; k++) {
      for (let k2 = 0; k2 < K; k2++) {
        let s = 0;
        for (let j = 0; j < V; j++) s += H[k][j] * H[k2][j];
        HHt[k][k2] = s;
      }
    }
    for (let d = 0; d < nDocs; d++) {
      for (let k = 0; k < K; k++) {
        let num = 0, den = eps;
        for (let j = 0; j < V; j++) if (X[d][j] !== 0) num += X[d][j] * H[k][j];
        for (let k2 = 0; k2 < K; k2++) den += W[d][k2] * HHt[k2][k];
        W[d][k] = W[d][k] * (num / den);
      }
    }
  }

  // Assign every turn to its strongest topic
  const assignments = [];
  for (let d = 0; d < nDocs; d++) {
    let bestK = 0, bestScore = -1;
    for (let k = 0; k < K; k++) {
      if (W[d][k] > bestScore) { bestScore = W[d][k]; bestK = k; }
    }
    assignments.push({
      index: d,
      source_id: turnRecords[d].source_id,
      turn_id: turnRecords[d].turn_id,
      topic_id: bestK + 1,
      score: bestScore,
    });
  }

  const topics = [];
  for (let k = 0; k < K; k++) {
    const tid = k + 1;
    const members = assignments.filter(a => a.topic_id === tid);
    if (!members.length) continue;
    const topIdx = Array.from({ length: V }, (_, j) => j)
      .sort((a, b) => H[k][b] - H[k][a])
      .slice(0, 7);
    const terms = topIdx.map(j => vocab[j]);
    members.sort((a, b) => b.score - a.score);
    const medoid = turnRecords[members[0].index];
    topics.push({
      topic_id: tid,
      label: terms.slice(0, 3).join(" / "),
      top_terms: terms,
      turn_count: members.length,
      share_pct: Math.round((members.length / nDocs) * 1000) / 10,
      medoid_text: medoid.text,
      medoid_speaker: medoid.speaker || "Unknown",
      medoid_unit_id: medoid.source_id || medoid.unit_id || "",
      medoid_line: medoid.line_number,
    });
  }
  topics.sort((a, b) => (b.turn_count - a.turn_count) || (a.topic_id - b.topic_id));
  return { topics, assignments, n_analyzed: nDocs, warning: null };
}

function computeTopicCodebookOverlap(discovery, turnRecords, domainNames) {
  const byTopic = new Map();
  for (const a of (discovery.assignments || [])) {
    if (!byTopic.has(a.topic_id)) byTopic.set(a.topic_id, []);
    byTopic.get(a.topic_id).push(a.index);
  }
  const out = {};
  for (const t of (discovery.topics || [])) {
    const indices = byTopic.get(t.topic_id) || [];
    const total = indices.length;
    let uncoded = 0;
    const counts = new Map();
    for (const idx of indices) {
      const matched = (turnRecords[idx] && turnRecords[idx].matched_domains) || [];
      if (!matched.length) uncoded++;
      else {
        for (const d of matched) counts.set(d, (counts.get(d) || 0) + 1);
      }
    }
    const covered = total - uncoded;
    let topOverlap = "";
    if (counts.size) {
      const topId = Array.from(counts.entries()).sort((a, b) => (b[1] - a[1]) || (a[0] < b[0] ? -1 : 1))[0][0];
      topOverlap = domainNames.get(topId) || topId;
    }
    const uncodedFrac = total > 0 ? uncoded / total : 0;
    let badge, status;
    if (uncodedFrac >= 0.70) {
      status = "uncoded";
      badge = `Mostly Uncoded by Active Themes (${uncoded} of ${total} uncoded)`;
    } else if (uncodedFrac > 0.30) {
      status = "partial";
      badge = `Partially Uncoded (${uncoded} of ${total} uncoded; overlaps ${topOverlap || "active themes"})`;
    } else {
      status = "covered";
      badge = `Mostly Covered by Active Themes (${covered} of ${total} matched; mostly ${topOverlap || "active themes"})`;
    }
    out[t.topic_id] = { total, uncoded, covered, top_overlap: topOverlap, badge, status, member_indices: indices };
  }
  return out;
}
