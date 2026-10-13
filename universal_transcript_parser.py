"""
Universal Transcript Parser
Module for parsing, normalizing, and attributing speaker dialogue turns
across diverse meeting and interview recording formats (Microsoft Teams,
Zoom WebVTT, Otter.ai, Descript, and standard plain-text transcripts).
"""

import os
import re
import docx
from typing import List, Dict, Any, Optional, Tuple


class UniversalTranscriptParser:
    """
    Parses qualitative interview transcripts into structured, speaker-attributed
    dialogue turns with character-level offsets and timestamp tracking.
    """

    def __init__(self, facilitator_names: Optional[List[str]] = None):
        """
        Initialize parser.
        :param facilitator_names: Optional list of known interviewer/facilitator names.
                                  If omitted, role detection uses question density heuristics.
        """
        self.facilitator_names = [f.strip().lower() for f in facilitator_names] if facilitator_names else []

    def parse_file(self, file_path: str) -> List[Dict[str, Any]]:
        """
        Detect file format and parse into standardized dialogue turns.
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Transcript file not found: {file_path}")

        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".docx":
            return self._parse_docx(file_path)
        elif ext in [".vtt", ".srt"]:
            return self._parse_vtt(file_path)
        elif ext in [".txt", ".md"]:
            return self._parse_text(file_path)
        else:
            raise ValueError(f"Unsupported transcript extension: {ext}")

    def _parse_docx(self, file_path: str) -> List[Dict[str, Any]]:
        """
        Parse Word document transcripts, supporting paragraph formats and table structures.
        """
        doc = docx.Document(file_path)
        raw_entries = []

        # 1. Check if document uses a table layout (common in formal transcription services)
        if len(doc.tables) > 0 and len(doc.tables[0].rows) > 3:
            table = doc.tables[0]
            for row_idx, row in enumerate(table.rows):
                cells = [c.text.strip() for c in row.cells]
                if len(cells) >= 2:
                    speaker_raw = cells[0]
                    text_raw = cells[1]
                    timestamp = cells[2] if len(cells) > 2 else ""
                    if text_raw:
                        raw_entries.append((row_idx, speaker_raw, timestamp, text_raw))
        else:
            # 2. Standard paragraph-based layout (Teams, Otter exports)
            current_speaker = "Unknown"
            current_timestamp = ""
            current_buffer = []
            line_idx = 0

            for p_idx, p in enumerate(doc.paragraphs):
                text = p.text.strip()
                if not text:
                    continue

                # Strip common export noise headers
                if "Meeting Recording" in text and len(text) < 120:
                    continue

                # Detect speaker tag patterns:
                # Format A: "Speaker Name 00:14:22" or "Speaker Name\n00:14:22"
                # Format B: "Speaker Name: Dialogue text..."
                # Format C: "00:14:22 Speaker Name: Dialogue"
                turn_match_a = re.match(r"^([A-Z][a-zA-Z\s\.\-]+?)\s+(\d{1,2}:\d{2}(?::\d{2})?)$", text)
                turn_match_b = re.match(r"^([A-Z][a-zA-Z\s\.\-]+?):\s*(.*)$", text)
                turn_match_c = re.match(r"^(\d{1,2}:\d{2}(?::\d{2})?)\s+([A-Z][a-zA-Z\s\.\-]+?):\s*(.*)$", text)

                if turn_match_a:
                    if current_buffer:
                        raw_entries.append((line_idx, current_speaker, current_timestamp, " ".join(current_buffer)))
                        current_buffer = []
                    current_speaker = turn_match_a.group(1).strip()
                    current_timestamp = turn_match_a.group(2).strip()
                    line_idx = p_idx
                elif turn_match_b:
                    if current_buffer:
                        raw_entries.append((line_idx, current_speaker, current_timestamp, " ".join(current_buffer)))
                        current_buffer = []
                    current_speaker = turn_match_b.group(1).strip()
                    current_timestamp = ""
                    content = turn_match_b.group(2).strip()
                    line_idx = p_idx
                    if content:
                        current_buffer.append(content)
                elif turn_match_c:
                    if current_buffer:
                        raw_entries.append((line_idx, current_speaker, current_timestamp, " ".join(current_buffer)))
                        current_buffer = []
                    current_timestamp = turn_match_c.group(1).strip()
                    current_speaker = turn_match_c.group(2).strip()
                    content = turn_match_c.group(3).strip()
                    line_idx = p_idx
                    if content:
                        current_buffer.append(content)
                else:
                    # Check for newline-delimited timestamps (Teams default export)
                    lines = text.split("\n")
                    if len(lines) >= 2 and re.match(r"^\d{1,2}:\d{2}", lines[0]):
                        if current_buffer:
                            raw_entries.append((line_idx, current_speaker, current_timestamp, " ".join(current_buffer)))
                            current_buffer = []
                        current_timestamp = lines[0].strip()
                        current_buffer.append(lines[1].strip())
                        line_idx = p_idx
                    else:
                        current_buffer.append(text)

            if current_buffer:
                raw_entries.append((line_idx, current_speaker, current_timestamp, " ".join(current_buffer)))

        return self._normalize_turns(raw_entries, os.path.basename(file_path))

    def _parse_vtt(self, file_path: str) -> List[Dict[str, Any]]:
        """
        Parse WebVTT (.vtt) and SubRip (.srt) subtitle transcripts.
        """
        raw_entries = []
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        current_speaker = "Unknown"
        current_ts = ""
        current_text = []
        line_num = 0

        for idx, line in enumerate(lines):
            line_str = line.strip()
            if not line_str or line_str.startswith("WEBVTT") or line_str.isdigit():
                continue

            # Timecode match: 00:01:23.000 --> 00:01:25.000
            tc_match = re.match(r"^(\d{1,2}:\d{2}(?::\d{2})?(?:[,\.]\d{3})?)\s+-->\s+", line_str)
            if tc_match:
                if current_text:
                    raw_entries.append((line_num, current_speaker, current_ts, " ".join(current_text)))
                    current_text = []
                current_ts = tc_match.group(1)
                line_num = idx + 1
                continue

            # Speaker line: <v Speaker Name>Text or Speaker Name: Text
            v_match = re.match(r"^<v\s+([^>]+)>(.*)$", line_str)
            colon_match = re.match(r"^([A-Z][a-zA-Z\s\-]+):\s*(.*)$", line_str)

            if v_match:
                current_speaker = v_match.group(1).strip()
                content = v_match.group(2).strip()
                if content:
                    current_text.append(content)
            elif colon_match:
                current_speaker = colon_match.group(1).strip()
                content = colon_match.group(2).strip()
                if content:
                    current_text.append(content)
            else:
                current_text.append(line_str)

        if current_text:
            raw_entries.append((line_num, current_speaker, current_ts, " ".join(current_text)))

        return self._normalize_turns(raw_entries, os.path.basename(file_path))

    def _parse_text(self, file_path: str) -> List[Dict[str, Any]]:
        """
        Parse plain text (.txt) and Markdown transcripts.
        """
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        raw_entries = []
        current_speaker = "Unknown"
        current_ts = ""
        current_text = []
        start_line = 1

        for idx, line in enumerate(lines):
            line_str = line.strip()
            if not line_str:
                continue

            match = re.match(r"^([A-Z][a-zA-Z\s\.\-]+?)(?:\s+\[?(\d{1,2}:\d{2}(?::\d{2})?)\]?)?:\s*(.*)$", line_str)
            if match:
                if current_text:
                    raw_entries.append((start_line, current_speaker, current_ts, " ".join(current_text)))
                    current_text = []
                current_speaker = match.group(1).strip()
                current_ts = match.group(2) if match.group(2) else ""
                start_line = idx + 1
                content = match.group(3).strip()
                if content:
                    current_text.append(content)
            else:
                current_text.append(line_str)

        if current_text:
            raw_entries.append((start_line, current_speaker, current_ts, " ".join(current_text)))

        return self._normalize_turns(raw_entries, os.path.basename(file_path))

    def _normalize_turns(self, raw_entries: List[Tuple[int, str, str, str]], doc_name: str) -> List[Dict[str, Any]]:
        """
        Normalize speaker turns, calculate character spans, and evaluate facilitator roles.
        """
        # Step 1: Detect facilitator if not explicitly provided
        detected_facilitators = set(self.facilitator_names)
        if not detected_facilitators and raw_entries:
            speaker_question_counts = {}
            for _, speaker, _, text in raw_entries:
                spk_clean = speaker.strip().lower()
                if spk_clean not in ["unknown", ""]:
                    q_count = text.count("?")
                    speaker_question_counts[spk_clean] = speaker_question_counts.get(spk_clean, 0) + q_count

            # If a speaker asked >65% of all questions, mark as facilitator
            total_questions = sum(speaker_question_counts.values())
            if total_questions > 0:
                for spk, count in speaker_question_counts.items():
                    if (count / total_questions) >= 0.50:
                        detected_facilitators.add(spk)

        # Step 2: Build standardized structured turn records
        normalized_turns = []
        char_cursor = 0

        for turn_idx, (line_num, speaker, timestamp, text) in enumerate(raw_entries):
            clean_text = text.strip()
            text_len = len(clean_text)
            spk_lower = speaker.strip().lower()

            is_fac = spk_lower in detected_facilitators or any(f in spk_lower for f in detected_facilitators)

            record = {
                "turn_id": turn_idx + 1,
                "document_name": doc_name,
                "line_number": line_num,
                "timestamp": timestamp,
                "speaker": speaker.strip(),
                "is_facilitator": is_fac,
                "text": clean_text,
                "word_count": len(clean_text.split()),
                "char_start": char_cursor,
                "char_end": char_cursor + text_len
            }
            normalized_turns.append(record)
            char_cursor += text_len + 1

        return normalized_turns
