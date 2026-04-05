import os
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

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
        r"^(IEEE\b)",
        r"^(ACM\b)",
        r"^(PMLR\b)",
        r"^(URL\b)",
        r"^(doi:)",
        r"^(https?://)",
        r"^(pp\.)",
        r"^(volume\b)",
        r"^(Singapore,|Miami,|Portland,|Abu Dhabi,|Atlanta,|New York,)",
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


def find_citations(text):
    results = []

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
            results.append(valid)

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

            lines.append({
                "x0": x0,
                "y0": y0,
                "text": text
            })

    return lines


def cluster_lines_by_columns(lines, x_threshold=80):
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



def is_reference_like_start(line):
    t = normalize_text(line)

    if not t:
        return False

    if is_header_noise(t):
        return False

    if is_continuation_line(t):
        return False

    if re.match(r"^\[\d+\]\s+", t):
        return True

    if re.match(r"^\d+\.\s+", t):
        return True

    # 저자 시작 패턴
    if re.match(r"^[A-Z][A-Za-z'`\-]+(?:\s+[A-Z][A-Za-z.\-']+){1,5},", t):
        return True

    if re.match(r"^[A-Z][A-Za-z'`\-]+,\s*(?:[A-Z]\.|[A-Z][a-z]+)", t):
        return True

    if re.match(r"^[A-Z][A-Za-z'`\-]+\s+(?:and|&)\s+[A-Z][A-Za-z'`\-]+", t):
        return True

    return False


def looks_like_reference_text(text):
    t = normalize_text(text)

    if len(t) < 20:
        return False

    has_year = bool(re.search(r"\b(?:19|20)\d{2}[a-z]?\b", t))
    has_authorish_start = bool(
        re.match(r"^(?:\[\d+\]\s*|\d+\.\s*)?[A-Z][A-Za-z'`\-]+", t)
    )
    has_venue_hint = bool(
        re.search(
            r"doi|https|arxiv|ieee|acm|pmlr|conference|journal|workshop|transactions|symposium|proceedings",
            t,
            re.I,
        )
    )

    if has_authorish_start and has_year:
        return True

    if has_authorish_start and has_venue_hint:
        return True

    return False


def merge_reference_lines(lines):
    refs = []
    cur = None

    for ln in lines:
        t = normalize_text(ln["text"])

        if not t:
            continue

        if re.match(r"^\d+$", t):
            continue

        if re.match(r"^(references|bibliography)$", t, re.I):
            continue

        if is_header_noise(t):
            continue

        # 이미 block이 있으면 continuation 우선 처리
        if cur:
            cur_text = normalize_text(cur["text"])

            # 저자 리스트 줄바꿈: 쉼표로 끝나면 무조건 이어붙임
            if cur_text.endswith(","):
                cur["text"] += " " + t
                continue

            # 하이픈 줄바꿈
            if cur_text.endswith("-"):
                cur["text"] = cur["text"][:-1] + t
                continue

            # venue / URL / doi / location continuation
            if is_continuation_line(t):
                cur["text"] += " " + t
                continue

        # 새 reference 시작
        if is_reference_like_start(t):
            if cur:
                full_text = normalize_text(cur["text"])
                if looks_like_reference_text(full_text):
                    refs.append({"text": full_text})
            cur = {"text": t}
            continue

        # continuation 처리
        if cur:
            cur["text"] += " " + t
        else:
            if looks_like_reference_text(t):
                cur = {"text": t}

    if cur:
        full_text = normalize_text(cur["text"])
        if looks_like_reference_text(full_text):
            refs.append({"text": full_text})

    out = []
    for r in refs:
        txt = normalize_text(r["text"])
        txt = re.sub(r"^\[\d+\]\s*", "", txt)
        txt = re.sub(r"^\d+\.\s*", "", txt)
        txt = normalize_text(txt)

        if looks_like_reference_text(txt):
            out.append({"text": txt})

    return out


def get_ref_blocks(doc, start_page=None, end_page=None):
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

    pages = []

    for i in range(start_page, end_page):
        page = doc[i]
        lines = get_reference_lines(page)
        columns = cluster_lines_by_columns(lines)

        page_refs = []
        for col in columns:
            refs = merge_reference_lines(col["lines"])
            page_refs.extend(refs)

        for r in page_refs:
            pages.append({
                "page": i + 1,
                "text": r["text"]
            })

    return pages


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


def find_best_block(part, blocks):
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


def extract_title(block_text):
    _, raw_title = extract_authors_and_title_from_block(block_text)
    return clean_extracted_title(raw_title)


def make_search_query(part):
    part = clean_part(part)
    part = part.replace("&", "and")
    part = re.sub(r"\bet al\.\b", "", part, flags=re.I)
    part = re.sub(r"\s+", " ", part).strip()
    return part


# -------------------------------
# UI
# -------------------------------
uploaded = st.file_uploader("PDF 업로드", type="pdf")

if uploaded:
    pdf_bytes = uploaded.getvalue()
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    cites = collect_citations(doc)

    left, right = st.columns([0.7, 0.3])

    auto_start = find_reference_start_page(doc)
    default_start = (auto_start + 1) if auto_start is not None else 13
    default_end = min(default_start + 5, len(doc))

    with left:
        st.markdown("### 📄 Reference Page 설정")

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
        pdf_viewer(input=pdf_bytes, height=900)

    if ref_end < ref_start:
        st.error("End page는 Start page보다 크거나 같아야 합니다.")
        blocks = []
    else:
        blocks = get_ref_blocks(doc, start_page=ref_start, end_page=ref_end)

    with right:
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
                f"p.{b['page']} | {b['text'][:120]}..."
                if len(b["text"]) > 120 else f"p.{b['page']} | {b['text']}"
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
                    st.caption(f"Reference page: {blocks[ref_idx]['page']}")
                    st.write(blocks[ref_idx]["text"])
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