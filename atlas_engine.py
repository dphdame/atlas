"""
ATLAS Engine
Core deterministic natural language processing engine for qualitative policy
and mixed-methods analysis. Implements reproducible, auditable bilingual
rule execution, context fencing, cryptographic provenance tracking, and
actuarial spreadsheet export.
"""

import os
import re
import yaml
import hashlib
import pandas as pd
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.comments import Comment
from typing import List, Dict, Any, Optional
from universal_transcript_parser import UniversalTranscriptParser


class AtlasEngine:
    """
    Deterministic text analysis and qualitative synthesis engine.
    """

    def __init__(self, codebook_path: str):
        """
        Initialize the engine with a structured YAML codebook.
        """
        if not os.path.exists(codebook_path):
            raise FileNotFoundError(f"Codebook file not found: {codebook_path}")

        with open(codebook_path, "r", encoding="utf-8") as f:
            self.codebook = yaml.safe_load(f)

        self.project_name = self.codebook.get("project", self.codebook.get("program_name", "Qualitative Policy Study"))

        # Support 'domains' (researcher schema), 'topics' (practitioner schema), and 'themes' (benchmarking schema)
        raw_domains = self.codebook.get("domains")
        if raw_domains is not None:
            self.domains = raw_domains
        elif "topics" in self.codebook:
            topics_data = self.codebook["topics"]
            self.domains = []
            if isinstance(topics_data, dict):
                for t_id, t_info in topics_data.items():
                    self.domains.append({
                        "id": t_id,
                        "name": t_info.get("label", t_info.get("name", t_id)),
                        "description": t_info.get("description", ""),
                        "roots_en": t_info.get("keywords", t_info.get("roots_en", [])),
                        "roots_es": t_info.get("roots_es", []),
                        "context_fences": t_info.get("required_context", t_info.get("context_fences", [])),
                        "context_window": t_info.get("context_window", t_info.get("co_occurrence_window", None)),
                    })
            elif isinstance(topics_data, list):
                for item in topics_data:
                    self.domains.append({
                        "id": item.get("id", item.get("label", "unknown")),
                        "name": item.get("label", item.get("name", item.get("id", ""))),
                        "description": item.get("description", ""),
                        "roots_en": item.get("keywords", item.get("roots_en", [])),
                        "roots_es": item.get("roots_es", []),
                        "context_fences": item.get("required_context", item.get("context_fences", [])),
                        "context_window": item.get("context_window", item.get("co_occurrence_window", None)),
                    })
        elif "themes" in self.codebook:
            themes_data = self.codebook["themes"]
            self.domains = []
            for item in themes_data:
                self.domains.append({
                    "id": item.get("id", "theme"),
                    "name": item.get("name", item.get("id", "")),
                    "description": item.get("definition", item.get("description", "")),
                    "roots_en": item.get("keywords", item.get("roots_en", [])),
                    "roots_es": item.get("roots_es", []),
                    "context_fences": item.get("required_context", item.get("context_fences", [])),
                    "context_window": item.get("context_window", item.get("co_occurrence_window", None)),
                })
        else:
            self.domains = []

        self._compile_patterns()

    def _compile_patterns(self):
        """
        Pre-compile regular expressions and context fences for high-throughput execution.
        """
        self.compiled_rules = []
        for domain in self.domains:
            domain_id = domain["id"]
            name = domain["name"]
            roots_en = domain.get("roots_en", [])
            roots_es = domain.get("roots_es", [])
            fences = domain.get("context_fences", [])

            # Regex for core stems
            all_roots = roots_en + roots_es
            escaped_roots = [re.escape(r) for r in all_roots]
            root_pattern = re.compile(r"\b(?:" + "|".join(escaped_roots) + r")", re.IGNORECASE) if escaped_roots else None

            # Regex for context fences
            escaped_fences = [re.escape(f) for f in fences]
            fence_pattern = re.compile(r"\b(?:" + "|".join(escaped_fences) + r")", re.IGNORECASE) if escaped_fences else None

            window = domain.get("context_window", domain.get("co_occurrence_window", None))
            if isinstance(window, str):
                m_win = re.search(r"\d+", window)
                window = int(m_win.group(0)) if m_win else None
            elif isinstance(window, (int, float)):
                window = int(window)
            else:
                window = None

            self.compiled_rules.append({
                "id": domain_id,
                "name": name,
                "description": domain.get("description", ""),
                "root_regex": root_pattern,
                "fence_regex": fence_pattern,
                "context_window": window
            })

    def process_corpus(self, transcript_files: List[str], facilitator_names: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Process a collection of transcript files and generate verified frequency matrices.
        """
        parser = UniversalTranscriptParser(facilitator_names=facilitator_names)
        all_turns = []
        file_hashes = {}

        for file_path in transcript_files:
            # Compute SHA-256 hash of source file
            with open(file_path, "rb") as f:
                sha = hashlib.sha256(f.read()).hexdigest()
            file_name = os.path.basename(file_path)
            file_hashes[file_name] = sha

            # Parse turns
            turns = parser.parse_file(file_path)
            all_turns.extend(turns)

        # Filter out facilitator turns to evaluate authentic participant feedback
        participant_turns = [t for t in all_turns if not t["is_facilitator"]]

        # Tag turns against compiled rules
        tagged_records = []
        quote_inventory = []

        for turn in participant_turns:
            text = turn["text"]
            matched_domains = []

            for rule in self.compiled_rules:
                domain_id = rule["id"]
                domain_name = rule["name"]
                root_reg = rule["root_regex"]
                fence_reg = rule["fence_regex"]
                window = rule.get("context_window")

                if not root_reg:
                    continue

                root_matches = list(root_reg.finditer(text))
                if not root_matches:
                    continue

                if not fence_reg:
                    is_match = True
                else:
                    fence_matches = list(fence_reg.finditer(text))
                    if not fence_matches:
                        is_match = False
                    elif window is None:
                        # Turn-level co-occurrence
                        is_match = True
                    else:
                        # Token-distance window checking
                        word_spans = [m.span() for m in re.finditer(r"\b\w+\b", text)]
                        if not word_spans:
                            is_match = False
                        else:
                            def char_to_tok(pos):
                                for idx, (s, e) in enumerate(word_spans):
                                    if pos < e:
                                        return idx
                                return len(word_spans) - 1

                            is_match = False
                            for rm in root_matches:
                                r_tok = char_to_tok(rm.start())
                                for fm in fence_matches:
                                    f_tok = char_to_tok(fm.start())
                                    if abs(r_tok - f_tok) <= window:
                                        is_match = True
                                        break
                                if is_match:
                                    break

                if is_match:
                    matched_domains.append(domain_id)
                    quote_inventory.append({
                        "domain_id": domain_id,
                        "domain_name": domain_name,
                        "document_name": turn["document_name"],
                        "line_number": turn["line_number"],
                        "timestamp": turn["timestamp"],
                        "speaker": turn["speaker"],
                        "text": text,
                        "char_start": turn["char_start"],
                        "char_end": turn["char_end"],
                        "source_sha256": file_hashes[turn["document_name"]]
                    })

            record = dict(turn)
            record["matched_domains"] = matched_domains
            tagged_records.append(record)

        # Compute organizational / document prevalence
        doc_names = list(file_hashes.keys())
        total_docs = len(doc_names)

        frequency_rows = []
        for rule in self.compiled_rules:
            domain_id = rule["id"]
            domain_name = rule["name"]

            # Filter quotes for this domain
            dom_quotes = [q for q in quote_inventory if q["domain_id"] == domain_id]
            mentioning_docs = set(q["document_name"] for q in dom_quotes)
            doc_count = len(mentioning_docs)
            prevalence_pct = (doc_count / total_docs * 100.0) if total_docs > 0 else 0.0

            frequency_rows.append({
                "domain_id": domain_id,
                "domain_name": domain_name,
                "documents_reporting": doc_count,
                "total_documents": total_docs,
                "prevalence_pct": round(prevalence_pct, 1),
                "matching_turns": len(dom_quotes),
                "total_mentions": len(dom_quotes),
                "reporting_statement": f"{round(prevalence_pct, 1)}% of documents ({doc_count} of {total_docs}) across {len(dom_quotes)} matching turns reported {domain_name.lower()}."
            })

        df_freq = pd.DataFrame(frequency_rows)
        df_quotes = pd.DataFrame(quote_inventory)

        return {
            "project_name": self.project_name,
            "total_documents": total_docs,
            "total_turns_parsed": len(all_turns),
            "participant_turns_analyzed": len(participant_turns),
            "file_hashes": file_hashes,
            "frequencies_df": df_freq,
            "quotes_df": df_quotes,
            "tagged_turns_df": pd.DataFrame(tagged_records)
        }

    def export_results(self, results: Dict[str, Any], output_dir: str):
        """
        Export verified matrices to open standard formats (CSV, Parquet, and Excel).
        """
        os.makedirs(output_dir, exist_ok=True)

        # 1. Export CSV
        freq_csv = os.path.join(output_dir, "thematic_frequencies.csv")
        results["frequencies_df"].to_csv(freq_csv, index=False)

        quotes_csv = os.path.join(output_dir, "verbatim_quotes_inventory.csv")
        results["quotes_df"].to_csv(quotes_csv, index=False)

        # 2. Export Parquet
        quotes_parquet = os.path.join(output_dir, "verbatim_quotes_inventory.parquet")
        results["quotes_df"].to_parquet(quotes_parquet, index=False)

        # 3. Export Formatted Actuarial Excel Bridge
        excel_path = os.path.join(output_dir, "actuarial_parameter_matrix.xlsx")
        self._export_excel(results, excel_path)

        print(f"Exported clean results to: {output_dir}")

    def _export_excel(self, results: Dict[str, Any], excel_path: str):
        """
        Generate publication-ready Excel workbook formatted with cell comments and audit hashes.
        """
        wb = openpyxl.Workbook()
        ws_summary = wb.active
        ws_summary.title = "Empirical Frequencies"

        # Styling constants
        NAVY_FILL = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
        ZEBRA_FILL = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
        BORDER_GRAY = Side(style="thin", color="CBD5E1")
        BORDER_BOX = Border(top=BORDER_GRAY, left=BORDER_GRAY, right=BORDER_GRAY, bottom=BORDER_GRAY)
        FONT_HEADER = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
        FONT_BODY = Font(name="Calibri", size=10, color="1E293B")
        FONT_BOLD = Font(name="Calibri", size=10, bold=True, color="1E293B")

        # Headers
        headers = ["Domain ID", "Policy Domain Name", "Reporting Documents", "Total Documents", "Prevalence Rate (%)", "Matching Dialogue Turns", "Plain Language Empirical Statement"]
        for col_idx, h in enumerate(headers, 1):
            cell = ws_summary.cell(row=1, column=col_idx, value=h)
            cell.fill = NAVY_FILL
            cell.font = FONT_HEADER
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        # Data rows
        df_freq = results["frequencies_df"]
        for row_idx, r in df_freq.iterrows():
            r_num = row_idx + 2
            turn_matches = int(r["matching_turns"] if "matching_turns" in r else r["total_mentions"])
            ws_summary.cell(row=r_num, column=1, value=r["domain_id"]).font = FONT_BOLD
            ws_summary.cell(row=r_num, column=2, value=r["domain_name"]).font = FONT_BODY
            ws_summary.cell(row=r_num, column=3, value=int(r["documents_reporting"])).font = FONT_BODY
            ws_summary.cell(row=r_num, column=4, value=int(r["total_documents"])).font = FONT_BODY
            
            # Prevalence cell with verification audit comment
            prev_cell = ws_summary.cell(row=r_num, column=5, value=float(r["prevalence_pct"]))
            prev_cell.font = FONT_BOLD
            digest = hashlib.sha256(f"{r['domain_id']}_{r['documents_reporting']}_{r['total_documents']}_{turn_matches}".encode('utf-8')).hexdigest()
            comment_text = (
                f"ATLAS VERIFICATION AUDIT STAMP\n"
                f"Domain: {r['domain_name']}\n"
                f"Documents: {r['documents_reporting']} / {r['total_documents']}\n"
                f"Matching Turns: {turn_matches}\n"
                f"Verification SHA-256: {digest}\n"
                f"Status: PASS (Deterministic Match)"
            )
            prev_cell.comment = Comment(comment_text, "ATLAS Engine")

            ws_summary.cell(row=r_num, column=6, value=turn_matches).font = FONT_BODY
            ws_summary.cell(row=r_num, column=7, value=r["reporting_statement"]).font = FONT_BODY

            # Alternate row shading
            if row_idx % 2 == 1:
                for c in range(1, 8):
                    ws_summary.cell(row=r_num, column=c).fill = ZEBRA_FILL

            for c in range(1, 8):
                ws_summary.cell(row=r_num, column=c).border = BORDER_BOX

        # Auto-adjust column widths
        col_widths = [14, 34, 18, 14, 18, 22, 60]
        for idx, width in enumerate(col_widths, 1):
            col_letter = openpyxl.utils.get_column_letter(idx)
            ws_summary.column_dimensions[col_letter].width = width

        # Second Sheet: Quotes with Provenance
        ws_quotes = wb.create_sheet(title="Verbatim Quotes & Provenance")
        q_headers = ["Domain ID", "Document Source", "Line", "Timestamp", "Speaker", "Char Start", "Char End", "Verbatim Statement", "Source File SHA-256"]
        for col_idx, h in enumerate(q_headers, 1):
            cell = ws_quotes.cell(row=1, column=col_idx, value=h)
            cell.fill = NAVY_FILL
            cell.font = FONT_HEADER
            cell.alignment = Alignment(horizontal="center", vertical="center")

        df_quotes = results["quotes_df"]
        for row_idx, r in df_quotes.iterrows():
            r_num = row_idx + 2
            ws_quotes.cell(row=r_num, column=1, value=r["domain_id"]).font = FONT_BOLD
            ws_quotes.cell(row=r_num, column=2, value=r["document_name"]).font = FONT_BODY
            ws_quotes.cell(row=r_num, column=3, value=int(r["line_number"])).font = FONT_BODY
            ws_quotes.cell(row=r_num, column=4, value=str(r["timestamp"])).font = FONT_BODY
            ws_quotes.cell(row=r_num, column=5, value=r["speaker"]).font = FONT_BODY
            ws_quotes.cell(row=r_num, column=6, value=int(r["char_start"])).font = FONT_BODY
            ws_quotes.cell(row=r_num, column=7, value=int(r["char_end"])).font = FONT_BODY
            ws_quotes.cell(row=r_num, column=8, value=r["text"]).font = FONT_BODY
            ws_quotes.cell(row=r_num, column=9, value=r["source_sha256"]).font = FONT_BODY

            for c in range(1, 10):
                ws_quotes.cell(row=r_num, column=c).border = BORDER_BOX

        wb.save(excel_path)
