import os
import re
import asyncio
from typing import List, Dict, Any, Optional
from docx import Document
import fitz  # PyMuPDF

def slugify_filename(filename: str, max_len: int = 32) -> str:
    """Build a stable uppercase slug from a file basename (no extension)."""
    base = os.path.splitext(os.path.basename(filename))[0]
    slug = re.sub(r"[^A-Za-z0-9\u0400-\u04FF]+", "-", base.upper())
    slug = re.sub(r"-+", "-", slug).strip("-")
    if not slug:
        slug = "DOC"
    return slug[:max_len].rstrip("-")


def normalize_code(code_str: str) -> str:
    """Normalizes document codes, padding the middle index to 2 digits if necessary."""
    # Replace any dash/space variant with a standard hyphen
    clean = re.sub(r'[\s\-\–\—\u2013\u2014\x96]+', '-', code_str)
    # Check if prefix-number-year matches
    match = re.match(r'^([A-ZА-Яa-zа-я]+)-(\d+)-(\d{4})$', clean)
    if match:
        prefix, num, year = match.groups()
        if len(num) == 1:
            num = f"0{num}"
        return f"{prefix.upper()}-{num}-{year}"
    return clean.upper()

class DocumentParser:
    def __init__(self, target_categories: List[str] = ["Обзоры", "Статьи", "Доклады"]):
        self.target_categories = target_categories

    def parse_docx(self, file_path: str) -> Dict[str, Any]:
        """Parses a DOCX file, extracts metadata and splits content into chunks."""
        doc = Document(file_path)
        
        # Meta extraction heuristics
        title = ""
        code = ""
        year = None
        authors = []
        approver = ""
        
        filename = os.path.basename(file_path)
        # Try to guess year from filename
        year_match = re.search(r'\b(20\d{2})\b', filename)
        if year_match:
            year = int(year_match.group(1))

        # Try to guess code from filename
        # Match pattern with letters, any spaces/dashes, numbers, spaces/dashes, year
        code_regex = r'\b([ОИП|ТИ|ИС|НДС]+[\s\-\–\—\u2013\u2014\x96]*?\d+[\s\-\–\—\u2013\u2014\x96]*?\d{4})\b'
        code_match = re.search(code_regex, filename, re.IGNORECASE)
        if code_match:
            code = normalize_code(code_match.group(1))

        # Parse first 50 paragraphs for metadata
        meta_paras = []
        for i, p in enumerate(doc.paragraphs[:60]):
            text = p.text.strip()
            if not text:
                continue
            meta_paras.append(text)
            
            # Code detection
            if not code:
                code_p_match = re.search(code_regex, text, re.IGNORECASE)
                if code_p_match:
                    code = normalize_code(code_p_match.group(1))
            
            # Approver detection
            if "УТВЕРЖДАЮ" in text or "Утверждаю" in text:
                # Approver is usually in the next few lines
                for next_p in doc.paragraphs[i+1:i+5]:
                    nt = next_p.text.strip()
                    if nt and any(role in nt for role in ["Директор", "Начальник", "Заместитель", "к.г.-м.н.", "Цымбулов", "Козырев"]):
                        approver = nt
                        break

            # Author detection
            if "исполнителей" in text.lower() or "разработчик" in text.lower():
                for next_p in doc.paragraphs[i+1:i+10]:
                    nt = next_p.text.strip()
                    if nt and any(kw in nt.lower() for kw in ["специалист", "инженер", "научный сотрудник", "разработал", "выполнил"]):
                        # Extract name at the end of the line
                        name_match = re.search(r'([А-ЯA-Z][а-яa-z]+\s+[А-ЯA-Z]\.[А-ЯA-Z]\.)', nt)
                        if name_match:
                            authors.append(name_match.group(1))

        # Find title from first few non-empty lines
        # Ignore strings that consist of underscores, dashes, or contains role words
        for p in meta_paras[:15]:
            p_clean = p.strip()
            if len(p_clean) > 12 and not re.search(r'_{3,}|-{3,}|–{3,}|—{3,}', p_clean):
                if not any(x in p_clean.lower() for x in ["утверждаю", "директор", "институт", "департамент", "список", "обзор", "оип", "ти-", "ис-", "оглавление"]):
                    title = p_clean
                    break
        
        if not title:
            # Fallback to filename without extension
            title = os.path.splitext(filename)[0]

        # Scan text and build chunks
        chunks = []
        current_chunk = []
        current_len = 0
        chunk_idx = 0
        current_section = "Введение"
        
        for p in doc.paragraphs:
            text = p.text.strip()
            if not text:
                continue
                
            # Track section headers
            if p.style.name.startswith("Heading") or (len(text) < 100 and re.match(r'^\d+(\.\d+)*\s+[А-ЯA-Z]', text)):
                current_section = text
                
            # If adding this paragraph exceeds chunk size, flush the current chunk
            if current_len + len(text) > 1800 and current_chunk:
                chunks.append({
                    "index": chunk_idx,
                    "text": "\n".join(current_chunk),
                    "section": current_section,
                    "page": None
                })
                chunk_idx += 1
                current_chunk = []
                current_len = 0
                
            current_chunk.append(text)
            current_len += len(text)
            
        # Flush last chunk
        if current_chunk:
            chunks.append({
                "index": chunk_idx,
                "text": "\n".join(current_chunk),
                "section": current_section,
                "page": None
            })

        # Try to extract year from text if not found
        if not year:
            for chunk in chunks[:3]:
                year_match = re.search(r'\b(20\d{2})\b', chunk["text"])
                if year_match:
                    year = int(year_match.group(1))
                    break
        if not year:
            year = 2024  # Default fallback

        return {
            "file_path": file_path,
            "filename": filename,
            "file_slug": slugify_filename(filename),
            "title": title,
            "code": code or "N/A",
            "year": year,
            "authors": list(set(authors)) if authors else ["Не указан"],
            "approver": approver or "Не указан",
            "format": "docx",
            "chunks": chunks
        }

    def parse_pdf(self, file_path: str) -> Dict[str, Any]:
        """Parses a PDF file, extracts metadata and splits content into chunks by pages."""
        doc = fitz.open(file_path)
        filename = os.path.basename(file_path)
        
        # Meta extraction heuristics
        title = os.path.splitext(filename)[0]
        code = ""
        year = None
        
        # Regex for year/code in filename
        year_match = re.search(r'\b(20\d{2})\b', filename)
        if year_match:
            year = int(year_match.group(1))
            
        code_regex = r'\b([ОИП|ТИ|ИС|НДС]+[\s\-\–\—\u2013\u2014\x96]*?\d+[\s\-\–\—\u2013\u2014\x96]*?\d{4})\b'
        code_match = re.search(code_regex, filename, re.IGNORECASE)
        if code_match:
            code = normalize_code(code_match.group(1))

        chunks = []
        chunk_idx = 0
        
        # Read pages
        for page_num in range(doc.page_count):
            text = doc[page_num].get_text().strip()
            if not text:
                continue
                
            # Try to find code/year in the first page text
            if page_num == 0:
                if not code:
                    code_p_match = re.search(code_regex, text, re.IGNORECASE)
                    if code_p_match:
                        code = normalize_code(code_p_match.group(1))
                if not year:
                    year_match = re.search(r'\b(20\d{2})\b', text)
                    if year_match:
                        year = int(year_match.group(1))

            # Chunk by pages or split large pages
            if len(text) > 2000:
                # Split large pages
                paras = text.split("\n\n")
                curr_chunk = []
                curr_len = 0
                for p in paras:
                    pt = p.strip()
                    if not pt:
                        continue
                    if curr_len + len(pt) > 1800 and curr_chunk:
                        chunks.append({
                            "index": chunk_idx,
                            "text": "\n\n".join(curr_chunk),
                            "section": f"Страница {page_num + 1}",
                            "page": page_num + 1
                        })
                        chunk_idx += 1
                        curr_chunk = []
                        curr_len = 0
                    curr_chunk.append(pt)
                    curr_len += len(pt)
                if curr_chunk:
                    chunks.append({
                        "index": chunk_idx,
                        "text": "\n\n".join(curr_chunk),
                        "section": f"Страница {page_num + 1}",
                        "page": page_num + 1
                    })
                    chunk_idx += 1
            else:
                chunks.append({
                    "index": chunk_idx,
                    "text": text,
                    "section": f"Страница {page_num + 1}",
                    "page": page_num + 1
                })
                chunk_idx += 1

        if not year:
            year = 2024  # Default fallback

        return {
            "file_path": file_path,
            "filename": filename,
            "file_slug": slugify_filename(filename),
            "title": title,
            "code": code or "N/A",
            "year": year,
            "authors": ["Не указан"],
            "approver": "Не указан",
            "format": "pdf",
            "chunks": chunks
        }

    def parse_file(self, file_path: str) -> Optional[Dict[str, Any]]:
        """Determines format and parses the file."""
        ext = os.path.splitext(file_path)[1].lower()
        try:
            if ext == ".docx":
                return self.parse_docx(file_path)
            elif ext == ".pdf":
                return self.parse_pdf(file_path)
            else:
                return None
        except Exception as e:
            print(f"Error parsing file {file_path}: {e}")
            return None

    def scan_directory(self, base_dir: str) -> List[str]:
        """Scans directory and returns list of supported files to parse (prioritizing Obzory and Statyi)."""
        supported_files = []
        for root, dirs, files in os.walk(base_dir):
            category_match = False
            for cat in self.target_categories:
                if cat in root:
                    category_match = True
                    break
            
            if not category_match and "Источники информации" in root:
                category_match = True

            if category_match:
                for file in files:
                    ext = os.path.splitext(file)[1].lower()
                    if ext in [".docx", ".pdf"]:
                        supported_files.append(os.path.join(root, file))
        return supported_files
