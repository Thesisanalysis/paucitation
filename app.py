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
        # single name -> capitalize
        return parts[0].capitalize()
    surname = parts[-1].capitalize()
    initials = " ".join([p[0].upper() for p in parts[:-1]])
    return f"{surname} {initials}"

def parse_authors_block(auth_block: str):
    """
    Input examples:
      "davinder singh, rajiv sharma and harpreet kaur"
      "D. Singh, R. Sharma & H. Kaur"
    Return PAU-style authors string: "Singh D, Sharma R and Kaur H"
    """
    if not auth_block:
        return ""
    # split on ' and ' or '&' or commas
    parts = re.split(r'\band\b|&|,|;', auth_block, flags=re.IGNORECASE)
    parts = [p.strip() for p in parts if p.strip()]
    formatted = [format_author_name_simple(p) for p in parts]
    if not formatted:
        return ""
    if len(formatted) == 1:
        return formatted[0]
    if len(formatted) == 2:
        return f"{formatted[0]}, and {formatted[1]}"  # we'll replace comma pattern later to match "and" without comma if desired
    # three or more -> join with commas, last joined with 'and' (without Oxford comma as per earlier examples)
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
    # Find first 4-digit year between 1900 and 2029 (safe range)
    m = re.search(r'\b(19|20)\d{2}\b', text)
    if m:
        return m.group(0)
    return ""

def format_journal_name(name: str):
    if not name:
        return ""
    # simple capitalization of each word (Curr Sci -> Curr Sci)
    words = re.split(r'\s+', name.strip())
    return " ".join([w.capitalize() for w in words])

def extract_possible_metadata(text_pages: str):
    """
    Heuristic extraction:
      - Look for DOI
      - Find year
      - Split early lines to try to find Title and Authors
      - Find Volume and pages pattern: e.g., 'Vol 25:158-160' or '25:158-160' or '25(3):158-160' or '25: 158-160'
      - Journal name: may appear near header or after title; fallback: user must edit
    """
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

    # DOI
    res["doi"] = extract_doi(text)

    # Year
    res["year"] = extract_year(text)

    # Break into lines; filter out short/garbage lines
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    # Prefer the top region
    top_lines = lines[:40]

    # Heuristic: If there's a line fully uppercase and longer -> maybe title
    candidate_title = ""
    # Many PDFs have Title on a separate line -> choose the longest short line among first 12 lines
    top_for_title = top_lines[:12] if len(top_lines) >= 12 else top_lines
    if top_for_title:
        sorted_by_len = sorted(top_for_title, key=lambda s: len(s))
        # Choose a line with moderate length (not too short)
        for ln in reversed(sorted_by_len):
            if 15 <= len(ln) <= 200:
                candidate_title = ln
                break
        if not candidate_title:
            candidate_title = top_for_title[0]

    # Attempt authors detection: often appears immediately after title
    author_guess = ""
    try:
        idx = top_lines.index(candidate_title)
        # authors likely in lines after idx, within next 4 lines
        for j in range(idx+1, min(idx+6, len(top_lines))):
            ln = top_lines[j]
            # if line has commas or 'and' or multiple words and not parentheses
            if 3 <= len(ln.split()) <= 10 and re.search(r'\b(and|,|&)\b', ln, flags=re.IGNORECASE):
                author_guess = ln
                break
            # sometimes authors without commas but names with capitals
            if re.search(r'\b[A-Za-z]+\s+[A-Za-z]+', ln) and len(ln.split()) <= 6:
                # but ensure it's not an affiliation like "Department of X..."
                if not re.search(r'\bUniversity\b|\bDepartment\b|\bInstitute\b|\bSchool\b|\bCollege\b', ln, flags=re.IGNORECASE):
                    author_guess = ln
                    break
    except ValueError:
        author_guess = ""

    # If above heuristics failed, look for common author line patterns in top 12
    if not author_guess:
        for ln in top_for_title:
            if re.search(r'\b[A-Za-z]+\s+[A-Za-z]+\b', ln):
                if re.search(r'\b(and|,|&)\b', ln, flags=re.IGNORECASE) or (len(ln.split()) <= 8):
                    if not re.search(r'\b(Department|University|Institute|Laboratory|Centre|Center|College)\b', ln, flags=re.IGNORECASE):
                        author_guess = ln
                        break

    # If still empty, try next line after first line
    if not author_guess and len(top_lines) > 1:
        author_guess = top_lines[1]

    # Some titles may have trailing footnotes or authors; sanitize title
    title_clean = re.sub(r'\s+', ' ', candidate_title).strip()
    title_clean = re.sub(r'\d+\s*$', '', title_clean).strip()

    # Volume/pages detection: look through text for patterns like 25:158-160 or 25(3): 158-160
    vol_page_match = re.search(r'(\b\d{1,3}\b)\s*(?:\(|\:)\s*(\d{1,3})\s*\)?\s*[:\-]\s*(\d{1,4}\-\d{1,4})', text)
    if not vol_page_match:
        vol_page_match = re.search(r'(\b\d{1,3}\b)\s*:\s*(\d{1,4}\-\d{1,4})', text)
    if vol_page_match:
        # Several capture layouts -> fallback mapping
        if len(vol_page_match.groups()) >= 3:
            res["volume"] = vol_page_match.group(1)
            res["pages"] = vol_page_match.group(3)
        elif len(vol_page_match.groups()) >= 2:
            res["volume"] = vol_page_match.group(1)
            res["pages"] = vol_page_match.group(2)

    # Journal name detection: look for lines with short names from top region, or lines containing 'Journal' or 'J.'
    journal_guess = ""
    for ln in top_lines[:12]:
        if re.search(r'\bJournal\b|\bJ\b|\bTransactions\b|\bProceedings\b|\bScience\b|\bResearch\b', ln, flags=re.IGNORECASE):
            if len(ln) < 60:
                journal_guess = ln
                break
    if not journal_guess:
        # fallback - pick the line after title if it seems not authors
        try:
            idx = top_lines.index(candidate_title)
            if idx+2 < len(top_lines):
                maybe = top_lines[idx+2]
                if len(maybe) < 60 and not re.search(r'\bUniversity\b|\bDepartment\b|\bInstitute\b', maybe, flags=re.IGNORECASE):
                    journal_guess = maybe
        except ValueError:
            pass

    # Finalize
    res["title"] = title_clean
    res["authors_raw"] = author_guess
    res["authors_formatted"] = parse_authors_block(author_guess)
    res["journal"] = format_journal_name(journal_guess)
    # if journal empty, leave blank for user edit
    # volume/pages/year already attempted
    return res

def generate_pau_journal(authors_pau, year, title, journal, volume, pages):
    # Authors already in PAU format
    # Rules: Author(s) (Year) Title. JournalName Volume:pages.
    # Volume should be bold in HTML output; for plain text leave normal
    authors_pau = authors_pau.strip()
    year = year.strip()
    title = title.strip()
    journal = journal.strip()
    volume = volume.strip()
    pages = pages.strip()
    # Build
    # replace any redundant punctuation/spaces
    citation = f"{authors_pau} ({year}) {title}. {journal} {volume}:{pages}."
    return citation

# ---------- Streamlit UI ----------
st.title("PAU Citation Generator — Streamlit")
st.markdown("Upload a journal PDF and the app will try to extract metadata (title, authors, year, journal, volume, pages, DOI). Edit fields if needed and generate a PAU-style citation.")

col1, col2 = st.columns([1, 1])
with col1:
    uploaded_file = st.file_uploader("Upload PDF (journal article preferred)", type=["pdf"])
with col2:
    st.write("")  # placeholder
    st.write("Tips:")
    st.markdown("- Best results when the uploaded PDF is a published journal article PDF (not scanned images).")
    st.markdown("- The app reads first pages and uses heuristics — always check extracted fields and correct if needed.")
    st.markdown("- After confirm, click **Generate citation**. Use Download to save the citation text.")

extracted = {
    "title": "",
    "authors_raw": "",
    "authors_formatted": "",
    "journal": "",
    "volume": "",
    "pages": "",
    "year": "",
    "doi": ""
}

if uploaded_file is not None:
    try:
        bytes_data = uploaded_file.read()
        with pdfplumber.open(BytesIO(bytes_data)) as pdf:
            max_pages = min(3, len(pdf.pages))
            text_pages = ""
            for p in range(max_pages):
                page = pdf.pages[p]
                text = page.extract_text() or ""
                text_pages += text + "\n"
        # Extract metadata heuristically
        extracted = extract_possible_metadata(text_pages)
        st.success("Text extracted from PDF (first pages). Check and edit detected fields below.")
    except Exception as e:
        st.error(f"Failed to read PDF: {e}")

# If no PDF uploaded, allow blank manual entry
st.subheader("Detected / Edit metadata")
c1, c2 = st.columns(2)

with c1:
    authors_input = st.text_input("Authors (raw)", value=extracted.get("authors_raw", ""))
    st.caption("You may edit raw author line. Example inputs: 'davinder singh, rajiv sharma and harpreet kaur' or 'D. Singh, R. Sharma & H. Kaur'.")
    authors_formatted = parse_authors_block(authors_input) if authors_input else extracted.get("authors_formatted", "")
    st.text_input("Authors (PAU formatted)", value=authors_formatted, key="authors_pau")
    year_input = st.text_input("Year", value=extracted.get("year", ""))
    doi_input = st.text_input("DOI (if detected)", value=extracted.get("doi", ""))
    journal_input = st.text_input("Journal name (will be auto-capitalized)", value=extracted.get("journal", ""))
with c2:
    title_input = st.text_area("Article title", value=extracted.get("title", ""), height=120)
    volume_input = st.text_input("Volume", value=extracted.get("volume", ""))
    pages_input = st.text_input("Pages (e.g., 158-160)", value=extracted.get("pages", ""))
    # Source type enhancement - default Journal
    source_type = st.selectbox("Source type", ["Journal article", "Book", "Book chapter", "Thesis (MSc/PhD)", "Conference", "Report/Website"])

# Allow user to re-format authors using a button (take authors_raw and produce PAU)
if st.button("Format authors from raw"):
    new_formatted = parse_authors_block(authors_input)
    st.session_state["authors_pau"] = new_formatted
    st.experimental_rerun()

# Provide small transformations
if st.button("Auto-capitalize journal & title"):
    journal_input = format_journal_name(journal_input)
    title_input = title_case_first_letter(title_input)
    # write back into session (Streamlit text_input can't be programmatically set except via session_state key)
    st.session_state["journal_name_temp"] = journal_input
    st.session_state["title_temp"] = title_input
    st.experimental_rerun()

# Show current editable fields (pull possibly updated session_state)
authors_pau_final = st.session_state.get("authors_pau", parse_authors_block(authors_input))
journal_name_final = st.session_state.get("journal_name_temp", journal_input)
title_final = st.session_state.get("title_temp", title_input)
year_final = year_input
volume_final = volume_input
pages_final = pages_input
doi_final = doi_input

st.markdown("---")
if st.button("Generate PAU citation"):
    # Validate some fields quickly
    if not authors_pau_final:
        st.error("Author(s) missing or not formatted. Please provide author names.")
    elif not year_final:
        st.error("Year missing.")
    elif not title_final:
        st.error("Title missing.")
    else:
        # Format author string: ensure "Surname Initials, Surname Initials and Surname Initials"
        # parse_authors_block already returns that format (with commas and 'and')
        authors_for_citation = authors_pau_final
        # Clean journal name
        journal_for_cit = format_journal_name(journal_name_final)
        # Title: first letter capitalized
        title_for_cit = title_case_first_letter(title_final.strip())
        # Build citation (plain text)
        citation_text = generate_pau_journal(authors_for_citation, year_final, title_for_cit, journal_for_cit, volume_final, pages_final)

        # Show nicely with italicized journal name (HTML)
        citation_html = citation_text.replace(journal_for_cit, f"<i>{journal_for_cit}</i>")
        # Bold volume if present
        if volume_final:
            citation_html = citation_html.replace(f"{volume_final}:", f"<b>{volume_final}</b>:")

        st.markdown("#### Generated PAU citation")
        st.markdown(citation_html, unsafe_allow_html=True)

        # Download as txt
        txt_download = citation_text
        if doi_final:
            txt_download += f"\nDOI: {doi_final}"
        st.download_button("Download citation (TXT)", data=txt_download, file_name="pau_citation.txt")

        # Copy to clipboard instructions (Streamlit cannot reliably access clipboard server-side)
        st.info("To copy: click the Download button and copy the content, or manually select & copy the citation above.")

# Footer: small notes and deploy hint
st.markdown("---")
st.caption("Heuristics: the PDF parser reads first pages and uses heuristics to find title/authors/year/doi. Always check extracted fields. For production-grade parsing, a backend parser tuned per publisher (or publisher metadata like CrossRef) improves accuracy.")

st.markdown("""
**Deploy instructions (Streamlit Cloud)**  
1. Create a GitHub repo and push this `app.py`.  
2. In the repo, add a `requirements.txt` with:
