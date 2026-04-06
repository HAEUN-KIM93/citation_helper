import os
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from streamlit_drawable_canvas import st_canvas
from PIL import Image
import io
import fitz
import requests
import streamlit as st
from bs4 import BeautifulSoup
from streamlit_pdf_viewer import pdf_viewer


st.set_page_config(layout="wide")
st.title("📚 Citation Explorer FINAL")


# -------------------------------
# basic utils
# -------------------------------
def normalize_text(s):
    s = re.sub(r"\s+", " ", s or "")
    return s.strip()


def normalize_year(year):
    if not year:
        return ""
    return re.sub(r"[a-z]$", "", year.lower())   # 2021a -> 2021


def safe_get(url, **kwargs):
    headers = kwargs.pop("headers", {})
    headers.setdefault("User-Agent", "Mozilla/5.0")
    return requests.get(url, headers=headers, timeout=15, **kwargs)


# -------------------------------
# arXiv
# -------------------------------
def fetch_arxiv_data(query):
    try:
        query = urllib.parse.quote(query)
        url = f"http://export.arxiv.org/api/query?search_query=ti:{query}&max_results=5"

        with urllib.request.urlopen(url, timeout=15) as r:
            xml = r.read().decode("utf-8")

        root = ET.fromstring(xml)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        entries = root.findall("atom:entry", ns)
        if not entries:
            return None

        for entry in entries:
            title_el = entry.find("atom:title", ns)
            summary_el = entry.find("atom:summary", ns)

            result_title = normalize_text(title_el.text if title_el is not None else "")
            if not result_title:
                continue

            pdf_url = ""
            for l in entry.findall("atom:link", ns):
                if l.get("title") == "pdf":
                    pdf_url = l.get("href", "")
                    break

            return {
                "title": result_title,
                "summary": normalize_text(summary_el.text if summary_el is not None else ""),
                "pdf_url": pdf_url,
                "source": "arXiv(search)",
            }

        return None
    except Exception:
        return None


def fetch_arxiv_by_url(url):
    try:
        m = re.search(r"arxiv\.org/(?:abs|pdf)/([^/?#]+)", url)
        if not m:
            return None

        paper_id = m.group(1).replace(".pdf", "")
        api_url = f"http://export.arxiv.org/api/query?id_list={paper_id}"

        with urllib.request.urlopen(api_url, timeout=15) as r:
            xml = r.read().decode("utf-8")

        root = ET.fromstring(xml)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        entry = root.find("atom:entry", ns)
        if entry is None:
            return None

        title_el = entry.find("atom:title", ns)
        summary_el = entry.find("atom:summary", ns)

        return {
            "title": normalize_text(title_el.text if title_el is not None else ""),
            "summary": normalize_text(summary_el.text if summary_el is not None else ""),
            "pdf_url": f"https://arxiv.org/pdf/{paper_id}.pdf",
            "source": "arXiv(URL)",
        }
    except Exception:
        return None


# -------------------------------
# OpenReview
# -------------------------------
def fetch_openreview_data(query):
    try:
        res = safe_get(
            "https://openreview.net/search",
            params={"term": query},
        )
        soup = BeautifulSoup(res.text, "html.parser")

        forum = None
        for a in soup.find_all("a", href=True):
            if a["href"].startswith("/forum?id="):
                forum = "https://openreview.net" + a["href"]
                break

        if not forum:
            return None

        return fetch_openreview_by_url(forum)
    except Exception:
        return None


def fetch_openreview_by_url(url):
    try:
        res = safe_get(url)
        soup = BeautifulSoup(res.text, "html.parser")

        title_tag = soup.find("meta", {"property": "og:title"})
        desc_tag = soup.find("meta", {"property": "og:description"})

        title = ""
        summary = ""

        if title_tag and title_tag.get("content"):
            title = normalize_text(title_tag["content"])

        if desc_tag and desc_tag.get("content"):
            summary = normalize_text(desc_tag["content"])

        if not title:
            h1 = soup.find("h1")
            if h1:
                title = normalize_text(h1.get_text())

        if not summary:
            abstract_div = soup.find("div", {"class": "note-content-value"})
            if abstract_div:
                summary = normalize_text(abstract_div.get_text())

        pdf = ""
        for a in soup.find_all("a", href=True):
            if a["href"].startswith("/pdf?id="):
                pdf = "https://openreview.net" + a["href"]
                break

        return {
            "title": title,
            "summary": summary,
            "pdf_url": pdf or url,
            "source": "OpenReview(URL)",
        }

    except Exception:
        return None


# -------------------------------
# Semantic Scholar
# -------------------------------
def fetch_semantic(query):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY")
        if api_key:
            headers["x-api-key"] = api_key

        res = requests.get(
            "https://api.semanticscholar.org/graph/v1/paper/search",
            params={"query": query, "limit": 1, "fields": "title,abstract,url,openAccessPdf"},
            headers=headers,
            timeout=15,
        )
        data = res.json()

        if not data.get("data"):
            return None

        p = data["data"][0]

        pdf_url = ""
        if isinstance(p.get("openAccessPdf"), dict):
            pdf_url = p["openAccessPdf"].get("url", "") or ""
        if not pdf_url:
            pdf_url = p.get("url", "")

        return {
            "title": normalize_text(p.get("title", "")),
            "summary": normalize_text(p.get("abstract", "")),
            "pdf_url": pdf_url,
            "source": "Semantic Scholar(search)",
        }
    except Exception:
        return None


def fetch_semantic_by_url(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY")
        if api_key:
            headers["x-api-key"] = api_key

        res = requests.get(
            "https://api.semanticscholar.org/graph/v1/paper/search",
            params={
                "query": url,
                "limit": 1,
                "fields": "title,abstract,url,openAccessPdf"
            },
            headers=headers,
            timeout=15,
        )
        data = res.json()

        if not data.get("data"):
            return None

        p = data["data"][0]

        pdf_url = ""
        if isinstance(p.get("openAccessPdf"), dict):
            pdf_url = p["openAccessPdf"].get("url", "") or ""
        if not pdf_url:
            pdf_url = p.get("url", "") or url

        return {
            "title": normalize_text(p.get("title", "")),
            "summary": normalize_text(p.get("abstract", "")),
            "pdf_url": pdf_url,
            "source": "Semantic Scholar(URL)",
        }
    except Exception:
        return None


def fetch_paper(query):
    return (
        fetch_openreview_data(query)
        or fetch_semantic(query)
        or fetch_arxiv_data(query)
    )


def fetch_paper_from_url(url):
    if not url:
        return None

    try:
        if "openreview.net" in url:
            return fetch_openreview_by_url(url)

        if "arxiv.org" in url:
            return fetch_arxiv_by_url(url)

        return fetch_semantic_by_url(url)
    except Exception:
        return None


def fetch_paper_from_doi(doi):
    try:
        if not doi:
            return None

        doi = doi.strip()
        doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi, flags=re.I)
        doi_url = f"https://doi.org/{doi}"

        headers = {"User-Agent": "Mozilla/5.0"}
        api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY")
        if api_key:
            headers["x-api-key"] = api_key

        res = requests.get(
            "https://api.semanticscholar.org/graph/v1/paper/search",
            params={
                "query": doi,
                "limit": 1,
                "fields": "title,abstract,url,openAccessPdf"
            },
            headers=headers,
            timeout=15,
        )
        data = res.json()

        if data.get("data"):
            p = data["data"][0]

            pdf_url = ""
            if isinstance(p.get("openAccessPdf"), dict):
                pdf_url = p["openAccessPdf"].get("url", "") or ""
            if not pdf_url:
                pdf_url = p.get("url", "") or doi_url

            return {
                "title": normalize_text(p.get("title", "")),
                "summary": normalize_text(p.get("abstract", "")),
                "pdf_url": pdf_url,
                "source": "Semantic Scholar(DOI)",
            }

        return {
            "title": "",
            "summary": "",
            "pdf_url": doi_url,
            "source": "DOI(URL)",
        }

    except Exception:
        return None
def is_header_noise(text):
    t = normalize_text(text)
    return bool(re.match(r"^Under review as a conference paper", t, re.I))


def is_continuation_line(text):
    t = normalize_text(text)

    patterns = [
        r"^(In\b)",
        r"^(Proceedings\b)",
        r"^(International Conference\b)",
        r"^(Conference\b)",
        r"^(Journal\b)",
        r"^(Transactions\b)",
        r"^(Learning Representations\b)",
        r"^(Pattern Recognition\b)",
        r"^(Language Processing\b)",
        r"^(Association for Computational Linguistics\b)",
        r"^(Curran Associates\b)",
        r"^(Springer\b)",
        r"^(JMLR\.org\b)",
        r"^(PMLR\b)",
        r"^(IEEE\b)",
        r"^(ACM\b)",
        r"^(URL\b)",
        r"^(doi:)",
        r"^(https?://)",
        r"^(pp\.)",
        r"^(pages\b)",
        r"^(volume\b)",
        r"^(editor[s]?,\b)",
        r"^(Singapore,|Miami,|Portland,|Abu Dhabi,|Atlanta,|New York,|Paris,|Berlin,|Dublin,|Toronto,|Montreal,)",
    ]

    return any(re.match(p, t, re.I) for p in patterns)
# -------------------------------
# citation extraction
# -------------------------------
def clean_part(p):
    p = re.sub(r"^\d+\s+", "", p)
    p = re.sub(r"\s+", " ", p)
    return p.strip()


def is_valid_citation_part(p):
    has_year = re.search(r"\b(?:19|20)\d{2}[a-z]?\b", p)
    has_author = re.search(r"\b[A-Z][a-zA-Z\-']+", p)

    has_real_author = (
        "et al" in p.lower()
        or "&" in p
        or " and " in p.lower()
        or len(re.findall(r"\b[A-Z][a-zA-Z\-']+", p)) >= 2
    )

    return bool(has_year and has_author and has_real_author)

def iter_reference_lines_across_pages(doc, start_page, end_page):
    """
    reference section의 line들을
    page -> column(left to right) -> y(top to bottom)
    순서로 이어붙여 반환
    """
    all_lines = []

    for i in range(start_page, end_page):
        page = doc[i]
        page_lines = get_reference_lines(page)
        columns = cluster_lines_by_columns(page_lines)

        for col_idx, col in enumerate(columns):
            for ln in col["lines"]:
                if should_skip_reference_line(ln["text"]):
                    continue

                all_lines.append({
                    "page": i + 1,
                    "col": col_idx,
                    "x0": ln["x0"],
                    "y0": ln["y0"],
                    "text": ln["text"],
                })

    return all_lines
def find_numeric_citations(text):
    results = []
    seen = set()

    # [28], [1], [12, 13] 같은 것 중 우선 단일 번호
    for m in re.finditer(r"\[(\d+)\]", text):
        num = m.group(1)
        key = (num,)
        if key not in seen:
            seen.add(key)
            results.append([f"[{num}]"])

    return results

def is_valid_narrative(p):
    first_word = p.split()[0]
    blacklist = {"Figure", "Table", "Section", "Appendix", "Eq", "Equation"}
    return first_word not in blacklist


def find_citations(text):
    results = []
    seen = set()

    # 1) parenthetical author-year
    for m in re.finditer(r"\(([^()]*)\)", text):
        content = m.group(1)

        if not re.search(r"[A-Za-z]", content):
            continue

        if not re.search(r"\b(?:19|20)\d{2}[a-z]?\b", content):
            continue

        parts = [clean_part(p) for p in content.split(";")]

        valid = []
        for p in parts:
            if is_valid_citation_part(p):
                valid.append(p)

        if valid:
            key = tuple(valid)
            if key not in seen:
                seen.add(key)
                results.append(valid)

    # 2) narrative author-year
    narrative_pattern = re.compile(
        r"\b[A-Z][a-zA-Z\-']+(?:\s+(?:et al\.|&\s+[A-Z][a-zA-Z\-']+|and\s+[A-Z][a-zA-Z\-']+))?\s*\((?:19|20)\d{2}[a-z]?\)"
    )

    for m in narrative_pattern.finditer(text):
        p = normalize_text(m.group(0))
        if is_valid_narrative(p):
            key = (p,)
            if key not in seen:
                seen.add(key)
                results.append([p])

    # 3) numeric citations
    for m in re.finditer(r"\[(\d+)\]", text):
        p = f"[{m.group(1)}]"
        key = (p,)
        if key not in seen:
            seen.add(key)
            results.append([p])

    return results

def collect_citations(doc):
    out = []
    seen = set()

    for i in range(len(doc)):
        text = doc[i].get_text()
        groups = find_citations(text)

        for g in groups:
            key = (i + 1, tuple(g))
            if key in seen:
                continue
            seen.add(key)

            out.append({
                "page": i + 1,
                "parts": g,
            })

    return out


# -------------------------------
# reference extraction
# -------------------------------
def find_reference_start_page(doc):
    for i in range(len(doc)):
        page = doc[i]
        data = page.get_text("dict")

        for block in data.get("blocks", []):
            if block.get("type") != 0:
                continue

            for line in block.get("lines", []):
                spans = line.get("spans", [])
                if not spans:
                    continue

                text = "".join(span.get("text", "") for span in spans)
                text = normalize_text(text)

                if not text:
                    continue

                if re.fullmatch(r"(?:\d+(?:\.\d+)?)?\s*REFERENCES", text, flags=re.I):
                    return i

                if re.fullmatch(r"(?:\d+(?:\.\d+)?)?\s*BIBLIOGRAPHY", text, flags=re.I):
                    return i

    return None


def get_reference_lines(page):
    data = page.get_text("dict")
    lines = []

    page_h = page.rect.height

    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue

        for line in block.get("lines", []):
            spans = line.get("spans", [])
            if not spans:
                continue

            text = "".join(span.get("text", "") for span in spans)
            text = normalize_text(text)
            if not text:
                continue

            x0 = min(span["bbox"][0] for span in spans)
            y0 = min(span["bbox"][1] for span in spans)
            x1 = max(span["bbox"][2] for span in spans)
            y1 = max(span["bbox"][3] for span in spans)

            # 페이지 상단/하단의 러닝헤더, 페이지번호 제거용
            if y0 < 35:
                continue
            if y1 > page_h - 25:
                continue

            lines.append({
                "x0": x0,
                "y0": y0,
                "x1": x1,
                "y1": y1,
                "text": text
            })

    return lines


def cluster_lines_by_columns(lines, x_threshold=120):
    if not lines:
        return []

    lines_sorted = sorted(lines, key=lambda z: z["x0"])
    cols = []

    for ln in lines_sorted:
        placed = False
        for col in cols:
            if abs(ln["x0"] - col["anchor"]) <= x_threshold:
                col["lines"].append(ln)
                placed = True
                break
        if not placed:
            cols.append({
                "anchor": ln["x0"],
                "lines": [ln]
            })

    for col in cols:
        col["lines"].sort(key=lambda z: z["y0"])

    cols.sort(key=lambda c: c["anchor"])
    return cols
def render_page_to_png(doc, page_index, zoom=2.0):
    page = doc[page_index]
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    return pix.tobytes("png")


    

def is_author_year_reference_start(line):
    t = normalize_text(line)
    if not t or is_header_noise(t) or is_continuation_line(t):
        return False

    # 중요: author-year에서는 "^\d+\.\s+" 절대 쓰지 않기
    if re.match(r"^[A-Z]\.\s*[A-Z][A-Za-z'`\-]+", t):
        return True

    if re.match(r"^[A-Z][A-Za-z'`\-]+,\s*(?:[A-Z]\.|[A-Z][a-z]+)", t):
        return True

    if re.match(r"^[A-Z][A-Za-z'`\-]+(?:\s+[A-Z][A-Za-z.\-']+){1,5},", t):
        return True

    if re.match(
        r"^[A-Z][A-Za-z'`\-]+\s+[A-Z][A-Za-z'`\-]+"
        r"\s+(?:and|&)\s+"
        r"[A-Z][A-Za-z'`\-]+\s+[A-Z][A-Za-z'`\-]+(?:\.|,)",
        t
    ):
        return True

    if re.match(
        r"^[A-Z][A-Za-z'`\-]+\s+[A-Z][A-Za-z'`\-]+(?:\.|,)",
        t
    ):
        return True

    return False

def looks_like_reference_text(text):
    t = normalize_text(text)

    if len(t) < 20:
        return False

    has_year = bool(re.search(r"\b(?:19|20)\d{2}[a-z]?\b", t))

    # 기존 author-like 시작 + 이니셜 시작 둘 다 허용
    has_authorish_start = bool(
        re.match(
            r"^(?:\[\d+\]\s*|\d+\.\s*)?(?:"
            r"[A-Z][A-Za-z'`\-]+"          # Lucas / Bengio
            r"|"
            r"[A-Z]\.\s*[A-Z][A-Za-z'`\-]+" # L. Ouyang / A. Jain
            r")",
            t
        )
    )

    has_numeric_start = bool(re.match(r"^\[\d+\]\s+", t))

    has_venue_hint = bool(
        re.search(
            r"doi|https|arxiv|ieee|acm|pmlr|conference|journal|workshop|transactions|symposium|proceedings|neurips|iclr|acl|emnlp",
            t,
            re.I,
        )
    )

    return (has_authorish_start or has_numeric_start) and (has_year or has_venue_hint)
def is_numeric_reference_start(line):
    t = normalize_text(line)
    if not t or is_header_noise(t):
        return False
    return bool(re.match(r"^\[\d+\]\s+", t))


def extract_numeric_ref_id(text):
    t = normalize_text(text)
    m = re.match(r"^\[(\d+)\]\s+", t)
    return int(m.group(1)) if m else None


def merge_reference_lines_numeric_across_pages(lines):
    refs = []
    cur = None

    for ln in lines:
        t = normalize_text(ln["text"])
        if not t:
            continue

        # 새 reference 시작
        if is_numeric_reference_start(t):
            if cur:
                cur["text"] = cleanup_reference_text(cur["text"])
                refs.append(cur)

            cur = {
                "page_start": ln["page"],
                "page_end": ln["page"],
                "ref_id": extract_numeric_ref_id(t),
                "text": t
            }
            continue

        # continuation
        if cur:
            cur["page_end"] = ln["page"]

            if cur["text"].endswith("-"):
                cur["text"] = cur["text"][:-1] + t
            else:
                cur["text"] += " " + t

    if cur:
        cur["text"] = cleanup_reference_text(cur["text"])
        refs.append(cur)

    return refs
def merge_reference_lines_author_year_across_pages(lines):
    refs = []
    cur = None

    for ln in lines:
        t = normalize_text(ln["text"])
        if not t:
            continue

        if should_skip_reference_line(t):
            continue

        if cur:
            cur_text = normalize_text(cur["text"])

            if cur_text.endswith(","):
                cur["text"] += " " + t
                cur["page_end"] = ln["page"]
                continue

            if cur_text.endswith("-"):
                cur["text"] = cur["text"][:-1] + t
                cur["page_end"] = ln["page"]
                continue

            if is_continuation_line(t):
                cur["text"] += " " + t
                cur["page_end"] = ln["page"]
                continue

        if is_author_year_reference_start(t):
            if cur:
                cur["text"] = cleanup_reference_text(cur["text"])
                refs.append(cur)
            cur = {
                "page_start": ln["page"],
                "page_end": ln["page"],
                "text": t
            }
            continue

        if cur:
            cur["text"] += " " + t
            cur["page_end"] = ln["page"]

    if cur:
        cur["text"] = cleanup_reference_text(cur["text"])
        refs.append(cur)

    return refs


def get_ref_blocks(doc, start_page=None, end_page=None, mode="auto"):
    if start_page is None:
        start_page = find_reference_start_page(doc)
    else:
        start_page = start_page - 1  # 1-index -> 0-index

    if start_page is None:
        return []

    if end_page is None:
        end_page = len(doc)
    else:
        end_page = min(end_page, len(doc))

    all_lines = iter_reference_lines_across_pages(doc, start_page, end_page)

    if not all_lines:
        return []

    if mode == "numeric":
        refs = merge_reference_lines_numeric_across_pages(all_lines)
    elif mode == "author_year":
        refs = merge_reference_lines_author_year_across_pages(all_lines)
    else:
        numeric_count = sum(1 for ln in all_lines if is_numeric_reference_start(ln["text"]))
        if numeric_count >= 3:
            refs = merge_reference_lines_numeric_across_pages(all_lines)
        else:
            refs = merge_reference_lines_author_year_across_pages(all_lines)

    out = []
    for r in refs:
        txt = normalize_text(r["text"])
        if not txt:
            continue

        out.append({
            "page": r["page_start"],
            "page_start": r["page_start"],
            "page_end": r["page_end"],
            "ref_id": r.get("ref_id"),
            "text": txt
        })

    return out

# -------------------------------
# citation -> reference matching
# -------------------------------
def parse_citation_authors_year(part):
    year_match = re.search(r"\b((?:19|20)\d{2}[a-z]?)\b", part)
    year = year_match.group(1) if year_match else ""

    cleaned = re.sub(r"\bet al\.?,?\b", "", part, flags=re.I)
    tokens = re.findall(r"[A-Za-z][A-Za-z\-']+", cleaned)

    stop = {"and", "et", "al", "in", "of", "on", "for", "the"}
    authors = [t.lower() for t in tokens if t.lower() not in stop]

    return authors, year

def cleanup_reference_text(ref):
    ref = normalize_text(ref)

    # URL 붙이기
    ref = re.sub(r"https:\s+//", "https://", ref)
    ref = re.sub(r"http:\s+//", "http://", ref)

    # paper_files/paper/ /file/... 같은 것 붙이기
    ref = re.sub(r"/\s+/file/", "/file/", ref)

    # doi spacing
    ref = re.sub(r"doi:\s+", "doi: ", ref)

    ref = re.sub(r"\s+", " ", ref).strip()
    return ref
def find_best_block(part, blocks):
    part = normalize_text(part)

    # numeric citation: [13]
    m_num = re.fullmatch(r"\[(\d+)\]", part)
    if m_num:
        num = m_num.group(1)

        for b in blocks:
            text = normalize_text(b["text"])
            if re.match(rf"^\[{re.escape(num)}\]\s*", text):
                return b
        return None

    # author-year citation
    authors, year = parse_citation_authors_year(part)
    norm_year = normalize_year(year)

    best = None
    best_score = -1

    for b in blocks:
        text = b["text"].lower()

        matched_authors = [
            a for a in authors
            if re.search(rf"\b{re.escape(a)}\b", text)
        ]

        has_year = bool(
            norm_year and re.search(rf"\b{re.escape(norm_year)}\b", text)
        )

        if not matched_authors or not has_year:
            continue

        score = 10 * len(matched_authors)

        if matched_authors:
            first_matched = matched_authors[0]
            if re.search(rf"\b{re.escape(first_matched)}\b", text[:120]):
                score += 3

        if score > best_score:
            best_score = score
            best = b

    return best

# -------------------------------
# sub-reference extraction inside matched block
# -------------------------------
def split_block_by_reference_patterns(block_text):
    text = normalize_text(block_text)
    if not text:
        return []

    text = re.sub(r"https:\s+//", "https://", text)
    text = re.sub(r"http:\s+//", "http://", text)
    text = re.sub(r"doi:\s+", "doi: ", text)

    text = re.sub(
        r"(https?://[^\s]+)\s+(?=[A-Z][A-Za-z'`\-]+(?:\s+[A-Z][A-Za-z.\-']+){1,6}\.)",
        r"\1 ||REF_SPLIT|| ",
        text
    )

    text = re.sub(
        r"(doi:\s*10\.\d{4,9}/[^\s]+)\s+(?=[A-Z][A-Za-z'`\-]+(?:\s+[A-Z][A-Za-z.\-']+){1,6}\.)",
        r"\1 ||REF_SPLIT|| ",
        text,
        flags=re.I
    )

    text = re.sub(
        r"((?:19|20)\d{2}[a-z]?\.)\s+(?=[A-Z][A-Za-z'`\-]+(?:\s+[A-Z][A-Za-z.\-']+){1,6}\.)",
        r"\1 ||REF_SPLIT|| ",
        text
    )

    text = re.sub(
        r"((?:openreview\.net|arxiv\.org|aclanthology\.org|proceedings\.mlr\.press)[^\s]*)\s+(?=[A-Z][A-Za-z'`\-]+(?:\s+[A-Z][A-Za-z.\-']+){1,6}\.)",
        r"\1 ||REF_SPLIT|| ",
        text,
        flags=re.I
    )

    parts = [normalize_text(p) for p in text.split("||REF_SPLIT||") if normalize_text(p)]
    return parts


def score_candidate(candidate_text, citation_part):
    authors, year = parse_citation_authors_year(citation_part)
    norm_year = normalize_year(year)
    text = candidate_text.lower()

    matched_authors = [
        a for a in authors
        if re.search(rf"\b{re.escape(a)}\b", text)
    ]

    has_year = bool(
        norm_year and re.search(rf"\b{re.escape(norm_year)}\b", text)
    )

    if not matched_authors or not has_year:
        return -999

    score = 10 * len(matched_authors)

    if matched_authors:
        first_matched = matched_authors[0]
        if re.search(rf"\b{re.escape(first_matched)}\b", text[:120]):
            score += 3

    if len(candidate_text) > 800:
        score -= 2

    return score


def extract_matching_subreference(block_text, citation_part):
    text = normalize_text(block_text)
    if not text:
        return text

    candidates = split_block_by_reference_patterns(text)
    if not candidates:
        return text

    scored = []
    for c in candidates:
        s = score_candidate(c, citation_part)
        scored.append((s, c))

    scored.sort(key=lambda x: x[0], reverse=True)

    best_score, best_text = scored[0]

    if best_score <= 0 or len(best_text) < 40:
        return text

    return best_text


# -------------------------------
# url / doi / title extraction
# -------------------------------
def extract_urls_from_block(text):
    if not text:
        return []

    fixed = re.sub(r"(https?://)\s+", r"\1", text)

    urls = re.findall(r"(https?://[^\s]+)", fixed)
    cleaned = []
    for u in urls:
        u = u.strip().rstrip(").,;]")
        cleaned.append(u)

    return cleaned


def extract_doi_from_block(text):
    if not text:
        return ""

    fixed = normalize_text(text)
    fixed = re.sub(r"(10\.\d{4,9}/)\s+", r"\1", fixed)

    m = re.search(
        r"\b(10\.\d{4,9}/[-._;()/:A-Z0-9]+)\b",
        fixed,
        flags=re.I
    )
    if not m:
        return ""

    return m.group(1).rstrip(").,;]")


def split_reference_sentences(text):
    text = normalize_text(text)

    text_for_title = re.split(
        r"\b(?:URL|doi|https?://)\b",
        text,
        maxsplit=1,
        flags=re.IGNORECASE
    )[0].strip()

    parts = re.split(r"(?<=[A-Za-z0-9])\.\s+(?=[A-Z0-9])", text_for_title)
    parts = [p.strip(" .") for p in parts if p.strip(" .")]
    return parts


def extract_authors_and_title_from_block(block_text):
    parts = split_reference_sentences(block_text)

    if len(parts) < 2:
        return "", ""

    authors = parts[0]
    title = parts[1]
    return authors, title


def clean_extracted_title(title):
    title = normalize_text(title)
    title = re.sub(r",?\s*(?:19|20)\d{2}[a-z]?$", "", title).strip()

    title = re.split(
        r"\b(?:In|Proceedings|Advances in|Journal|Transactions|Conference|Workshop)\b",
        title,
        maxsplit=1
    )[0].strip()

    return title

def is_page_number_line(text):
    t = normalize_text(text)
    return bool(re.fullmatch(r"\d+", t))


def should_skip_reference_line(text):
    t = normalize_text(text)
    if not t:
        return True
    if is_header_noise(t):
        return True
    if re.match(r"^(references|bibliography)$", t, re.I):
        return True
    if is_page_number_line(t):
        return True
    return False
def extract_title(block_text):
    _, raw_title = extract_authors_and_title_from_block(block_text)
    return clean_extracted_title(raw_title)


def make_search_query(part):
    part = clean_part(part)
    part = part.replace("&", "and")
    part = re.sub(r"\bet al\.\b", "", part, flags=re.I)
    part = re.sub(r"\s+", " ", part).strip()
    return part

def detect_reference_mode(lines):
    numeric_count = sum(1 for ln in lines if is_numeric_reference_start(ln["text"]))
    author_like_count = sum(1 for ln in lines if is_author_year_reference_start(ln["text"]))

    if numeric_count >= 3 and numeric_count >= author_like_count * 0.3:
        return "numeric"
    return "author_year"
# -------------------------------
# UI
# -------------------------------
uploaded = st.file_uploader("PDF 업로드", type="pdf")

if uploaded:
    

    if "page_drawings" not in st.session_state:
        st.session_state["page_drawings"] = {}

    pdf_bytes = uploaded.getvalue()
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    blocks = []
    best = None
    cites = collect_citations(doc)
    

    left, right = st.columns([0.7, 0.3])

    auto_start = find_reference_start_page(doc)
    default_start = (auto_start + 1) if auto_start is not None else min(13, len(doc))
    default_start = max(1, min(default_start, len(doc)))
    default_end = max(default_start, min(default_start + 5, len(doc)))

    with left:
        st.markdown("### 📄 Reference Page 설정")
        ref_mode = st.radio(
        "Reference parsing mode",
        options=["auto", "numeric", "author_year"],
        format_func=lambda x: {
            "auto": "Auto",
            "numeric": "Numeric [1], [2], [3]",
            "author_year": "Author-Year (Bengio, 2009)"
        }[x],
        horizontal=True,
        key="ref_mode_radio"
    )

        col1, col2 = st.columns(2)

        with col1:
            ref_start = st.number_input(
                "Start page",
                min_value=1,
                max_value=len(doc),
                value=default_start,
                step=1,
                key="ref_start_input"
            )

        with col2:
            ref_end = st.number_input(
                "End page",
                min_value=1,
                max_value=len(doc),
                value=default_end,
                step=1,
                key="ref_end_input"
            )

        st.markdown("---")
        st.markdown("### 👀 Reading / Note")

        view_page = st.number_input(
            "View page",
            min_value=1,
            max_value=len(doc),
            value=1,
            step=1,
            key="view_page_input"
        )

        zoom = st.slider(
            "Zoom",
            min_value=1.0,
            max_value=3.0,
            value=2.0,
            step=0.1,
            key="page_zoom_slider"
        )


        colA, colB = st.columns([0.7, 0.3])

        with colA:
            drawing_mode = st.radio(
            "Mode",
            ["freedraw", "line", "rect", "transform"],
            horizontal=True,
            key=f"drawing_mode_{view_page}"
                                    )

            stroke_color = st.color_picker(
                "Color",
                "#ff0000",
                key=f"color_{view_page}"
            )

            stroke_width = st.slider(
                "Width",
                1, 10, 3,
                key=f"width_{view_page}"
            )

        with colB:
            st.caption("Tip:")
            st.caption("- freedraw → 필기")
            st.caption("- line → 밑줄")
            st.caption("- rect → 박스")
        
        initial_drawing = st.session_state["page_drawings"].get(view_page)
        page_img = render_page_to_png(doc, view_page - 1, zoom=zoom)
        img = Image.open(io.BytesIO(page_img))

        # ✅ 이 줄 추가 (무조건 보이게)
        st.image(page_img)

        # ✅ 옵션으로 canvas
        use_canvas = st.checkbox("✏️ Enable annotation", value=False)

        if use_canvas:
            canvas_result = st_canvas(
                background_image=img,
                drawing_mode=drawing_mode,
                stroke_width=stroke_width,
                stroke_color=stroke_color,
                fill_color="rgba(255, 255, 0, 0.2)",
                height=img.height,
                width=img.width,
                initial_drawing=initial_drawing,
                key=f"canvas_{view_page}",
            )
       
        # -----------------------
# 🎯 선택 삭제 기능 추가
# -----------------------
        if canvas_result and canvas_result.json_data is not None:
            objects = canvas_result.json_data.get("objects", [])

            if objects:
                selected_idx = st.selectbox(
                    "Select object to delete",
                    range(len(objects)),
                    format_func=lambda i: f"Object {i}",
                    key=f"select_obj_{view_page}"
                )

                if st.button("🗑 Delete selected object", key=f"delete_obj_{view_page}"):
                    objects.pop(selected_idx)

                    st.session_state["page_drawings"][view_page] = {
                        "objects": objects,
                        "background": canvas_result.json_data.get("background", None)
                    }

                    st.success("Deleted!")
                    st.rerun()
        draw_col1, draw_col2 = st.columns(2)
        with draw_col1:
            if st.button("💾 Save Drawing", key=f"save_draw_{view_page}"):
                st.session_state["page_drawings"][view_page] = canvas_result.json_data
                st.success("Saved drawing!")

        with draw_col2:
            if st.button("🗑 Clear Drawing", key=f"clear_draw_{view_page}"):
                st.session_state["page_drawings"].pop(view_page, None)
                st.success("Cleared drawing!")
        
        

        
    if ref_end < ref_start:
        st.error("End page는 Start page보다 크거나 같아야 합니다.")
        blocks = []
    else:   
        all_lines_preview = iter_reference_lines_across_pages(doc, ref_start - 1, ref_end)

        if ref_mode == "auto":
            detected_mode = detect_reference_mode(all_lines_preview)
            st.caption(f"Auto detected mode: {detected_mode}")

        blocks = get_ref_blocks(
            doc,
            start_page=ref_start,
            end_page=ref_end,
            mode=ref_mode
        )
       

    with right:
        best = None
        st.subheader("Citation 선택")
        if not cites:
            st.warning("citation을 찾지 못했습니다.")
        else:
            cite_labels = [
                f"p.{c['page']} " + "; ".join(c["parts"])
                for c in cites[:200]
            ]

            selected_cite_idx = st.selectbox(
                "Citation group",
                options=range(len(cite_labels)),
                format_func=lambda i: cite_labels[i],
                key="cite_selectbox"
            )

            selected_cite = cites[selected_cite_idx]

            st.markdown("---")
            st.markdown("### 선택된 Citation Group")
            st.write(f"p.{selected_cite['page']} " + "; ".join(selected_cite["parts"]))

            parts = selected_cite["parts"]

            selected_part = st.selectbox(
                "Citation part",
                options=parts,
                key="part_selectbox"
            )

            st.markdown("### 선택된 citation")
            st.write(selected_part)

            best = find_best_block(selected_part, blocks)

            if best:
                subrefs = extract_matching_subreference(best["text"],selected_part)

                if subrefs:
                    scored = [(score_candidate(c, selected_part), c) for c in subrefs]
                    scored.sort(key=lambda x: x[0], reverse=True)

                    best_score, best_sub = scored[0]

                    if best_score > 0 and len(best_sub) > 40:
                        matched_text = best_sub
                    else:
                        matched_text = best["text"]
                else:
                    matched_text = best["text"]

                st.markdown("### matched block")
                with st.container(border=True):
                    if best.get("page_start") and best.get("page_end"):
                        if best["page_start"] == best["page_end"]:
                            st.caption(f"Reference page: {best['page_start']}")
                        else:
                            st.caption(f"Reference pages: {best['page_start']}–{best['page_end']}")
                    else:
                        st.caption(f"Reference page: {best['page']}")
                    st.write(matched_text)

                authors, _ = extract_authors_and_title_from_block(matched_text)
                title = extract_title(matched_text)
                urls = extract_urls_from_block(matched_text)
                doi = extract_doi_from_block(matched_text)

                ref_url = urls[-1] if urls else ""

                if authors:
                    st.markdown("### authors")
                    st.write(authors)

                st.markdown("### extracted title")
                st.write(title if title else "(title 추출 실패)")

                if ref_url:
                    st.markdown("### detected URL")
                    st.write(ref_url)

                if doi:
                    st.markdown("### detected DOI")
                    st.write(doi)

                st.markdown("### 검색 결과")

                with st.spinner("논문 검색 중..."):
                    info = None
                    q = ""

                    if ref_url:
                        info = fetch_paper_from_url(ref_url)

                    if not info and doi:
                        info = fetch_paper_from_doi(doi)

                    if not info and title:
                        q = title
                        info = fetch_paper(q)

                    if not info:
                        q = make_search_query(selected_part)
                        info = fetch_paper(q)

                if info:
                    st.success(info["source"])
                    st.write(info["title"] or "(제목 없음)")
                    st.write(info["summary"] or "(summary 없음)")

                    if info["pdf_url"]:
                        st.link_button("📥 논문 PDF 열기", info["pdf_url"], use_container_width=True)
                    else:
                        st.caption("PDF 링크를 찾지 못했습니다.")
                else:
                    st.error("논문을 찾지 못했습니다.")
                    if ref_url:
                        st.code(ref_url)
                    elif q:
                        st.code(q)
            else:
                st.warning("matched block을 찾지 못했습니다.")

            st.markdown("---")
            st.markdown("### 전체 Reference Block 보기")

            ref_options = [
    (
        f"pp.{b['page_start']}-{b['page_end']} | {b['text'][:120]}..."
        if b.get("page_start") != b.get("page_end")
        else f"p.{b['page_start']} | {b['text'][:120]}..."
    )
    if len(b["text"]) > 120 else
    (
        f"pp.{b['page_start']}-{b['page_end']} | {b['text']}"
        if b.get("page_start") != b.get("page_end")
        else f"p.{b['page_start']} | {b['text']}"
    )
    for b in blocks
]

            if ref_options:
                ref_idx = st.selectbox(
                    "Reference block 선택",
                    options=range(len(ref_options)),
                    format_func=lambda i: ref_options[i],
                    key="ref_block_selectbox"
                )

                with st.container(border=True):
                    b = blocks[ref_idx]
                    if b.get("page_start") == b.get("page_end"):
                        st.caption(f"Reference page: {b['page_start']}")
                    else:
                        st.caption(f"Reference pages: {b['page_start']}–{b['page_end']}")
                    st.write(b["text"])
            else:
                st.info("reference block이 없습니다.")

        if cites:
            with st.expander("매칭 디버그"):
                authors_dbg, year_dbg = parse_citation_authors_year(selected_part)
                norm_year_dbg = normalize_year(year_dbg)

                st.write("selected_part:", selected_part)
                st.write("parsed authors:", authors_dbg)
                st.write("parsed year:", year_dbg)
                st.write("normalized year:", norm_year_dbg)

                rows = []
                for i, b in enumerate(blocks[:300]):
                    text = b["text"].lower()
                    matched_authors = [
                        a for a in authors_dbg
                        if re.search(rf"\b{re.escape(a)}\b", text)
                    ]
                    has_year = bool(
                        norm_year_dbg and re.search(rf"\b{re.escape(norm_year_dbg)}\b", text)
                    )

                    rows.append({
                        "idx": i,
                        "page": b["page"],
                        "matched_authors": matched_authors,
                        "has_year": has_year,
                        "text_head": b["text"][:200]
                    })

                filtered = [r for r in rows if r["matched_authors"]]
                st.write("author matched blocks:", filtered[:20])

            with st.expander("subref debug"):
                if best:
                    st.write("ORIGINAL BLOCK:")
                    st.write(best["text"])

                    st.write("SPLIT CANDIDATES:")
                    subrefs_dbg = split_block_by_reference_patterns(best["text"])
                    for i, sref in enumerate(subrefs_dbg):
                        st.write(f"[{i}] score={score_candidate(sref, selected_part)}")
                        st.write(sref)
                        st.markdown("---")

        with st.expander("RAW reference lines"):
            for i, b in enumerate(blocks[:50]):
                st.write(i, b["text"][:200])
        