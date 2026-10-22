import re
import uuid
from pathlib import Path
from typing import List, Dict, Any, Optional
import PyPDF2
from backend.config import CHUNK_SIZE, CHUNK_OVERLAP, SOURCE_CREDIBILITY_WEIGHTS

# Header lines at the top of each source section in a trusted dossier, e.g.
#   Source: WHO - Antimicrobial resistance fact sheet
#   URL: https://www.who.int/...
#   Published: 2026-07-16
#   Retrieved: 2026-10-05
#   Type: Official UN health agency
# Sections are separated by a line containing only "---".
HEADER_LINE = re.compile(r"^(Source|URL|Published|Retrieved|Type):\s*(.*)$", re.IGNORECASE)
SECTION_SEPARATOR = re.compile(r"^\s*---\s*$", re.MULTILINE)

def clean_text(text: str) -> str:
    """Sanitizes text by removing abnormal control chars and normalizing whitespace."""
    if not text:
        return ""
    # Normalize unicode spaces and hyphens
    text = text.replace("\u00a0", " ").replace("\u2013", "-").replace("\u2014", "-")
    # Replace multiple newlines or tabs with standard whitespace
    text = re.sub(r"\r\n|\r", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def _has_word(text: str, words: List[str]) -> bool:
    # Whole-word match: plain substrings matched "un" in "fund" and "who" in "whole"
    return any(re.search(rf"\b{re.escape(w)}\b", text) for w in words)


def detect_source_type(filename: str, source_hint: str = "") -> str:
    """Infers credibility tier from source name or filename."""
    combined = re.sub(r"[_\-.]", " ", f"{filename} {source_hint}".lower())
    if _has_word(combined, ["gov", "government", "ministry", "official", "imf", "world bank", "who", "cdc", "un", "united nations", "nasa", "rbi", "federal"]):
        return "Government / Official"
    elif _has_word(combined, ["nature", "science", "lancet", "ieee", "arxiv", "journal", "academic", "university", "paper", "research", "pubmed"]):
        return "Peer-Reviewed Academic"
    elif _has_word(combined, ["reuters", "ap", "bloomberg", "bbc", "hindu", "times", "wsj", "nyt", "guardian", "afp", "news"]):
        return "Established News"
    else:
        return "General Report"


def credibility_for(source_type: str) -> float:
    """0-1 credibility weight for a source type, from SOURCE_CREDIBILITY_WEIGHTS."""
    st_lower = (source_type or "").lower()
    for key, weight in SOURCE_CREDIBILITY_WEIGHTS.items():
        if key in st_lower:
            return weight
    return 0.70


def parse_source_sections(text: str) -> List[Dict[str, Any]]:
    """
    Splits a dossier into source sections. Each section returns its header metadata
    (source, url, publication_date, retrieval_date, source_type) and body text.
    Text without a "Source:" header comes back as a single section with empty metadata.
    """
    sections = []
    for block in SECTION_SEPARATOR.split(text):
        meta: Dict[str, str] = {}
        body_lines = []
        in_header = True
        for line in block.strip().splitlines():
            m = HEADER_LINE.match(line.strip()) if in_header else None
            if m:
                meta[m.group(1).lower()] = m.group(2).strip()
                continue
            if line.strip():
                in_header = False
            if not in_header:
                body_lines.append(line)
        body = "\n".join(body_lines).strip()
        if not body:
            continue
        published = meta.get("published", "")
        sections.append({
            "source": meta.get("source", ""),
            "url": meta.get("url", ""),
            "publication_date": "" if published.lower() in ("", "not stated") else published,
            "retrieval_date": meta.get("retrieved", ""),
            "source_type": meta.get("type", ""),
            "text": body
        })
    return sections

def extract_text_from_file(file_path: Path) -> List[Dict[str, Any]]:
    """
    Extracts text and page numbers from supported file types.
    Returns a list of dicts: [{"page": int, "text": str}]
    """
    ext = file_path.suffix.lower()
    pages_data = []

    if ext == ".pdf":
        try:
            with open(file_path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                for idx, page in enumerate(reader.pages):
                    extracted = page.extract_text() or ""
                    cleaned = clean_text(extracted)
                    if cleaned:
                        pages_data.append({"page": idx + 1, "text": cleaned})
        except Exception as e:
            print(f"Error reading PDF {file_path}: {e}")
    else:
        # Default text, md, json
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = clean_text(f.read())
                if content:
                    pages_data.append({"page": 1, "text": content})
        except Exception as e:
            print(f"Error reading text file {file_path}: {e}")

    return pages_data

def recursive_chunk_text(
    text: str,
    chunk_size: int = CHUNK_SIZE,
    chunk_overlap: int = CHUNK_OVERLAP
) -> List[str]:
    """
    Recursively splits text on natural boundaries (paragraphs -> sentences -> words)
    ensuring each chunk does not cut statements mid-sentence where possible.
    """
    if len(text) <= chunk_size:
        return [text] if text.strip() else []

    # First split by double newline (paragraphs)
    paragraphs = text.split("\n\n")
    chunks = []
    current_chunk = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        if len(current_chunk) + len(para) + 2 <= chunk_size:
            current_chunk = f"{current_chunk}\n\n{para}" if current_chunk else para
        else:
            if current_chunk:
                chunks.append(current_chunk)
                # Keep overlap from the tail of current chunk
                overlap_text = current_chunk[-chunk_overlap:] if len(current_chunk) > chunk_overlap else ""
                current_chunk = overlap_text

            if len(para) > chunk_size:
                # Split large paragraph by sentence
                sentences = re.split(r'(?<=[.?!])\s+', para)
                for sentence in sentences:
                    sentence = sentence.strip()
                    if not sentence:
                        continue
                    if len(current_chunk) + len(sentence) + 1 <= chunk_size:
                        current_chunk = f"{current_chunk} {sentence}" if current_chunk else sentence
                    else:
                        if current_chunk:
                            chunks.append(current_chunk)
                            overlap_text = current_chunk[-chunk_overlap:] if len(current_chunk) > chunk_overlap else ""
                            current_chunk = overlap_text
                        if len(sentence) > chunk_size:
                            # Hard split word by word
                            words = sentence.split(" ")
                            for w in words:
                                if len(current_chunk) + len(w) + 1 <= chunk_size:
                                    current_chunk = f"{current_chunk} {w}" if current_chunk else w
                                else:
                                    if current_chunk:
                                        chunks.append(current_chunk)
                                    current_chunk = w
                        else:
                            current_chunk = f"{current_chunk} {sentence}" if current_chunk else sentence
            else:
                current_chunk = f"{current_chunk}\n\n{para}" if current_chunk else para

    if current_chunk and current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks

def process_document(
    file_path: Path,
    source_name: Optional[str] = None,
    source_type: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Full document ingestion pipeline:
    Extracts, cleans, chunks, and attaches comprehensive metadata.
    """
    file_path = Path(file_path)
    filename = file_path.name
    source = source_name or filename
    source_cat = source_type or detect_source_type(filename, source)

    pages = extract_text_from_file(file_path)
    all_chunks = []
    chunk_counter = 0

    for p_info in pages:
        page_num = p_info["page"]
        # Text dossiers may hold several sources, each with its own URL and dates; those travel
        # with every chunk so evidence can cite the exact page and the judge can check freshness
        sections = parse_source_sections(p_info["text"]) if file_path.suffix.lower() in (".txt", ".md") else \
            [{"source": "", "url": "", "publication_date": "", "retrieval_date": "", "source_type": "", "text": p_info["text"]}]

        for section in sections:
            sec_source = section["source"] or source
            sec_type = section["source_type"] or (detect_source_type(filename, sec_source) if section["source"] else source_cat)
            for chunk_text in recursive_chunk_text(section["text"]):
                if len(chunk_text.strip()) < 25:
                    # Skip meaningless tiny snippets
                    continue

                chunk_counter += 1
                chunk_id = f"{file_path.stem}_p{page_num}_c{chunk_counter}_{uuid.uuid4().hex[:6]}"
                all_chunks.append({
                    "chunk_id": chunk_id,
                    "document_name": filename,
                    "source": sec_source,
                    "source_type": sec_type,
                    "page_number": page_num,
                    "url": section["url"],
                    "publication_date": section["publication_date"],
                    "retrieval_date": section["retrieval_date"],
                    "credibility_score": credibility_for(sec_type),
                    "text": chunk_text,
                    "char_count": len(chunk_text)
                })

    return all_chunks

class DocumentProcessor:
    def __init__(self):
        pass

    def clean_text(self, text: str) -> str:
        return clean_text(text)

    def detect_source_type(self, filename: str, source_hint: str = "") -> str:
        return detect_source_type(filename, source_hint)

    def process_document(self, file_path: Path, source_name: Optional[str] = None, source_type: Optional[str] = None) -> List[Dict[str, Any]]:
        return process_document(file_path, source_name, source_type)

    def chunk_text(
        self,
        text: str,
        chunk_size: int = CHUNK_SIZE,
        overlap: int = CHUNK_OVERLAP,
        source_name: str = "Live Feed",
        file_type: str = "NEWS",
        source_type: str = "Established News",
        extra_metadata: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Chunks raw text string and returns list of chunk dicts formatted for ChromaDB retrieval.
        """
        raw_chunks = recursive_chunk_text(clean_text(text), chunk_size=chunk_size, chunk_overlap=overlap)
        chunks = []
        doc_stem = re.sub(r'[^a-zA-Z0-9]', '_', source_name)[:20]

        for idx, chunk_str in enumerate(raw_chunks):
            if len(chunk_str.strip()) < 20:
                continue
            chunk_id = f"news_{doc_stem}_{idx}_{uuid.uuid4().hex[:6]}"
            chunk_dict = {
                "chunk_id": chunk_id,
                "document_name": source_name,
                "source": source_name,
                "source_type": source_type,
                "page_number": 1,
                "text": chunk_str,
                "char_count": len(chunk_str)
            }
            if extra_metadata:
                chunk_dict.update(extra_metadata)
            chunks.append(chunk_dict)

        return chunks

# Singleton instance
document_processor = DocumentProcessor()

