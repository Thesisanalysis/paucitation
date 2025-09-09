# app.py
import streamlit as st
import pdfplumber
import re
from io import BytesIO

st.set_page_config(page_title="PAU Citation Generator", layout="wide")

# ---------- Helper functions ----------
def capitalize_word(w):
    return w.capitalize() if w else w

def title_case_first_letter(s: str):
    if not s:
        return ""
    s = s.strip()
    return s[0].upper() + s[1:]

def format_author_name_simple(fullname: str):
    """
    Convert "davinder singh" -> "Singh D"
    Handles multiple given names: "rajiv kumar sharma" -> "Sharma R K"
    """
    if not fullname:
        return ""
    parts = re.split(r'\s+', fullname.strip())
    parts = [p for p in parts if p]
    if len(parts) == 1:
        return parts[0].capitalize()
    surname = parts[-1].capitalize()
    initials = " ".join([p[0].upper() for p in parts[:-1]])
    return f"{surname} {initials}"

def parse_authors_block(auth_block: str):
    """Turn 'davinder singh, rajiv sharma and harpreet kaur'
       into 'Singh D, Sharma R and Kaur H'."""
    if not auth_block:
        return ""
    parts = re.split(r'\band\b|&|,|;', auth_block, flags=re.IGNORECASE)
    parts = [p.strip() for p in parts if p.strip()]
    formatted = [format_author_name_simple(p) for p in parts]
    if not formatted:
        return ""
    if len(formatted) == 1:
        return formatted[0]
    if len(formatted) == 2:
        return f"{formatted[0]} and {formatted[1]}"
    return ", ".join(formatted[:-1]) + " and " + formatted[-1]

def extract_doi(text: str):
    m = re.search(r'(10\.\d{4,9}/\S+)', text)
    if m:
        return m.group(1)
    m2 = re.search(r'https?://doi\.org/(\S+)', text)
    if m2:
        return m2.group(1)
    return ""

def extract_year(text: str):
    m = re.search(r'\b(19|20)\d{2}\b', text)
    return m.group(0) if m else ""

def format_journal_name(name: str):
    if not name:
        return ""
    words = re.split(r'\s+', name.strip())
    return " ".join([w.capitalize() for w in words])

def extract_possible_metadata(text_pages: str):
    res = {
        "title": "",
        "authors_raw": "",
        "authors_formatted": "",
        "journal": "",
        "volume": "",
        "pages": "",
        "year": "",
        "doi": ""
    }
    text = text_pages

    # DOI + Year
    res["doi"] = extract_doi(text)
    res["year"] = extract_year(text)

    # Break into lines
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    top_lines = lines[:40]

    # Candidate title (longest line near top)
    candidate_title = ""
    top_for_title = top_lines[:12]
    if top_for_title:
        sorted_by_len = sorted(top_for_title, key=len)
        for ln in reversed(sorted_by_len):
            if 15 <= len(ln) <= 200:
                candidate_title = ln
                break
        if not candidate_title:
            candidate_title = top_for_title[0]

    # Authors guess (line after title)
    author_guess = ""
    try:
        idx = top_lines.index(candidate_title)
        for j in range(idx+1, min(idx+6, len(top_lines))):
            ln = top_lines[j]
            if re.search(r'\b(and|,|&)\b', ln, flags=re.IGNORECASE):
                author_guess = ln
                break
    except ValueError:
        pass

    if not author_guess and len(top_lines) > 1:
        author_guess = top_lines[1]

    # Clean title
    title_clean = re.sub(r'\s+', ' ', candidate_title).strip()

    # Volume/pages detection
    vol_page_match = re.search(r'(\d{1,3})\s*:\s*(\d{1,4}-\d{1,4})', text)
    if vol_page_match:
        res["volume"] = vol_page_match.group(1)
        res["pages"] = vol_page_match.group(2)

    # Journal guess
    journal_guess = ""
    for ln in top_lines[:12]:
        if re.search(r'Journal|Sci|Research', ln, flags=re.IGNORECASE):
            if len(ln) < 60:
                journal_guess = ln
                break

    res["title"] = title_clean
    res["authors_raw"] = author_guess
    res["authors_formatted"] = parse_authors_block(author_guess)
    res["journal"] = format_journal_name(journal_guess)
    return res

def generate_pau_journal(authors_pau, year, title, journal, volume, pages):
    citation = f"{authors_pau} ({year}) {title}. {journal} {volume}:{pages}."
    return citation

# ---------- Streamlit UI ----------
st.title("📘 PAU Citation Generator")
st.markdown("Upload a journal PDF and the app will try to extract metadata. Edit fields if needed and generate a PAU-style citation.")

uploaded_file = st.file_uploader("Upload PDF", type=["pdf"])

extracted = {"title":"","authors_raw":"","authors_formatted":"","journal":"","volume":"","pages":"","year":"","doi":""}

if uploaded_file is not None:
    try:
        with pdfplumber.open(BytesIO(uploaded_file.read())) as pdf:
            text_pages = ""
            for p in pdf.pages[:3]:
                text_pages += (p.extract_text() or "") + "\n"
        extracted = extract_possible_metadata(text_pages)
        st.success("✅ PDF text extracted. Please review the fields below.")
    except Exception as e:
        st.error(f"PDF read error: {e}")

st.subheader("✍️ Edit Metadata")

authors_input = st.text_input("Authors (raw)", value=extracted.get("authors_raw", ""))
authors_formatted = parse_authors_block(authors_input)
authors_pau = st.text_input("Authors (PAU format)", value=authors_formatted)

col1, col2 = st.columns(2)
with col1:
    year_input = st.text_input("Year", value=extracted.get("year", ""))
    volume_input = st.text_input("Volume", value=extracted.get("volume", ""))
with col2:
    pages_input = st.text_input("Pages", value=extracted.get("pages", ""))
    doi_input = st.text_input("DOI", value=extracted.get("doi", ""))

title_input = st.text_area("Article Title", value=extracted.get("title", ""), height=100)
journal_input = st.text_input("Journal Name", value=extracted.get("journal", ""))

if st.button("Generate Citation"):
    if not authors_pau or not year_input or not title_input or not journal_input:
        st.error("⚠️ Please fill Authors, Year, Title, and Journal.")
    else:
        citation_text = generate_pau_journal(authors_pau, year_input, title_case_first_letter(title_input), format_journal_name(journal_input), volume_input, pages_input)
        citation_html = citation_text.replace(journal_input, f"<i>{journal_input}</i>")
        if volume_input:
            citation_html = citation_html.replace(f"{volume_input}:", f"<b>{volume_input}</b>:")
        st.markdown("### ✅ Generated Citation")
        st.markdown(citation_html, unsafe_allow_html=True)
        st.download_button("Download Citation", data=citation_text, file_name="citation.txt")
