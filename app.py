import io
import json
import os
import base64
import concurrent.futures
from typing import List, Dict, Tuple

import pandas as pd
import streamlit as st
from PIL import Image
from pdf2image import convert_from_bytes
import pytesseract

from google import genai
from google.genai import types

# Optional: Set tesseract path only if still needed for raw text extraction
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

poppler_path = r'C:\Users\Swathi\Downloads\Release-25.12.0-0\poppler-25.12.0\Library\bin'
os.environ["POPPLER_PATH"] = poppler_path

# ---------- Environment Diagnostics ---------- #
def diagnose_environment():
    st.subheader("Environment Diagnostics")
    
    # 1. Tesseract Check
    st.write("Checking Tesseract...")
    try:
        ver = pytesseract.get_tesseract_version()
        st.success(f"Tesseract found: Version {ver}")
    except Exception as e:
        st.error(f"Tesseract NOT found or error: {e}")
        st.info(f"Expected path: {pytesseract.pytesseract.tesseract_cmd}")
        
    # 2. Poppler Check
    st.write("Checking Poppler...")
    try:
        from pdf2image.exceptions import PDFInfoNotInstalledError
        from pdf2image import pdfinfo_from_bytes
        # Try a dummy call with minimal bytes
        st.write(f"Poppler path: {poppler_path}")
        st.success("Poppler environment variable is set.")
    except Exception as e:
        st.error(f"Poppler check failed: {e}")

    # 3. API Key Check
    st.write("Checking Gemini API Connectivity...")
    try:
        client = genai.Client(api_key="")
        # List models is a good lightweight check
        models = client.models.list()
        st.success("Gemini API connection successful.")
    except Exception as e:
        st.error(f"Gemini API check failed: {e}")

# ---------- OCR Cleaning ---------- #
def clean_ocr_text(text: str) -> str:
    """Return text mostly raw to avoid merging distinct table rows or points. 
    The LLM is highly capable of re-stitching broken sentences based on images."""
    return text.strip()

# ---------- OCR ---------- #
def process_page(i: int, img: Image.Image, lang: str) -> Tuple[int, Dict, str]:
    try:
        text = pytesseract.image_to_string(img, lang=lang)
        msg = f"Page {i}: OCR complete"
    except Exception as exc:  # capture per-page OCR failure
        text = f"[OCR error on page {i}: {exc}]"
        msg = f"Page {i}: OCR error: {exc}"
    return i, {"page": i, "text": clean_ocr_text(text), "image": img}, msg

def extract_text_from_pdf(uploaded_file, lang: str, dpi: int = 300, log_callback=None) -> List[Dict]:
    """Return [{'page':1, 'text':..., 'image': PIL.Image}, ...] using Tesseract OCR. Calls log_callback(page, message) after each page if provided."""
    pdf_bytes = uploaded_file.read()
    max_workers = min(os.cpu_count() or 4, 8)
    
    # Process PDF to images using multiple threads
    pages = convert_from_bytes(pdf_bytes, dpi=dpi, poppler_path=poppler_path, thread_count=max_workers)
    
    results_dict = {}
    
    # Process OCR in parallel
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_page, i, img, lang): i for i, img in enumerate(pages, start=1)}
        for future in concurrent.futures.as_completed(futures):
            i, result, msg = future.result()
            results_dict[i] = result
            if log_callback:
                log_callback(i, msg)
                
    # Sort results to maintain original page order
    results = [results_dict[i] for i in sorted(results_dict.keys())]
    return results


# ---------- Grouping ---------- #
def group_pages(
    en_pages: List[Dict],
    ta_pages: List[Dict],
    en_window: int = 10,
    ta_window: int = 11,
) -> List[Dict]:
    """
    Groups pages into matching chunks. Continues until BOTH sets of pages are exhausted.
    """
    pairs = []
    en_idx = ta_idx = 0
    # Loop while AT LEAST one list has pages remaining
    while en_idx < len(en_pages) or ta_idx < len(ta_pages):
        en_slice = en_pages[en_idx : en_idx + en_window]
        ta_slice = ta_pages[ta_idx : ta_idx + ta_window]
        
        # If one slice is empty but the other isn't, Gemini should handle it as unmatched
        en_images = [p["image"] for p in en_slice]
        ta_images = [p["image"] for p in ta_slice]
        
        en_text_ref = "\n\n".join(p["text"] for p in en_slice)
        ta_text_ref = "\n\n".join(p["text"] for p in ta_slice)
        
        en_start = en_slice[0]['page'] if en_slice else "N/A"
        en_end = en_slice[-1]['page'] if en_slice else "N/A"
        ta_start = ta_slice[0]['page'] if ta_slice else "N/A"
        ta_end = ta_slice[-1]['page'] if ta_slice else "N/A"
        
        en_range = f"{en_start}–{en_end}"
        ta_range = f"{ta_start}–{ta_end}"
        
        pairs.append({
            "en_images": en_images,
            "ta_images": ta_images,
            "en_text": en_text_ref,
            "ta_text": ta_text_ref,
            "en_range": en_range,
            "ta_range": ta_range
        })
        
        en_idx += en_window
        ta_idx += ta_window
    return pairs


# ---------- Multimodal LLM Alignment (Gemini) ---------- #
def align_with_llm(client: genai.Client, en_images: List[Image.Image], ta_images: List[Image.Image], en_text: str, ta_text: str, model_id: str = "gemini-3-flash-preview") -> List[Dict]:
    """
    Calls Gemini multimodally to align paragraphs and tabled contents from two sets of page images.
    Uses provided Tesseract text as the source of truth for content.
    Returns JSON array of objects with keys English_sentence, Tamil_sentence.
    """
    sys_prompt = """You are a precision bilingual aligner. You will be provided with images of PDF pages and Tesseract-extracted text for English and Tamil.
Your primary directive is to maintain structural integrity and perform an absolutely EXHAUSTIVE extraction:
1. SUBHEADINGS (e.g., "ABSTRACT:", "ORDER:", "READ:", "FINANCE DEPARTMENT") MUST always be separate rows. Do NOT merge them with other text.
2. RETAIN English entities (Email IDs, Reference Codes, IDs, and Numbers) in their original English form within the `Tamil_sentence` column if they appear that way in the source. Do NOT translate or garble them.
3. IGNORE page numbers, footers, and running headers (e.g., "Page 1", "3", "1 of 10"). Do NOT include them in the output.
4. DO NOT split dates (e.g., 11-04-2016) or reference numbers (e.g., G.O. Nos) into separate rows. If a list item ends with "dated:", the date on the NEXT line MUST be merged.
5. PHONE NUMBERS: Merge area codes and numbers into a single row. Do NOT split '044' and '25665659' into two rows; they belong together.
6. TREAT table rows as atomic units. DO NOT merge contents from different table columns into a single row.
7. ALIGN table headers precisely: Column 1 EN matches Column 1 TA, etc.
8. USE the provided TEXT blocks as the content source of truth, and IMAGES as the layout/alignment source of truth.
9. ENSURE every sentence or table cell has a corresponding pair. If a sentence exists on one side but NOT on the other, leave the opposite cell EMPTY ("").
10. SEMANTIC ALIGNMENT: Prioritize semantic matching, but aim for maximum coverage. If in doubt, pair the nearest segments.
11. NO HALLUCINATIONS: Do NOT add any text, titles, or headers that are not explicitly present in the provided source text and images.
12. SENTENCE-BY-SENTENCE (CRITICAL): Do NOT group multiple independent sentences or entire paragraphs into a single output row. You MUST separate big paragraphs into individual sentences so each JSON object contains exactly English_sentence and Tamil_sentence.
13. EXHAUSTIVE EXTRACTION (CRITICAL): You MUST extract and align EVERY SINGLE SENTENCE and EVERY SINGLE TABLE ROW from the input text. If the text has 50 sentences/rows, your JSON array MUST contain 50 objects. DO NOT CONDENSE, DO NOT SUMMARIZE, DO NOT SKIP. Process the text exhaustively from top to bottom.
14. OUTPUT ONLY a valid JSON array of objects. Each object MUST contain two keys: 'English_sentence' and 'Tamil_sentence'."""
    
    user_prompt = f"""
Below are images of PDF pages and the extracted text reference. 

[ENGLISH EXTRACTED TEXT]
{en_text}

[TAMIL EXTRACTED TEXT]
{ta_text}

TASK:
1. Extract and align the text strictly SENTENCE-BY-SENTENCE and TABLE ROW-BY-TABLE ROW. 
2. NEVER return a giant paragraph block in a single row. Break them down.
3. SUBHEADINGS: Keep them as standalone rows.
4. ENTITIES: Retain Email IDs, website URLs, and codes in English.
5. SKIP all page numbers and footers.
6. For TABLES: Extract row by row.
7. Use Unicode Tamil from the reference text to avoid garbled output.
8. COMPLETE THE JOB: You MUST extract EVERY SINGLE row and sentence of data from the extracted text. Do not compress multiple sentences into 3 or 4 large objects. Return a 1:1 mapped output array for the entire text.

Return ONLY a JSON array.
"""
    
    # Construct parts: English images, then Tamil images, then the prompt
    parts = []
    
    def pil_to_bytes(img: Image.Image) -> bytes:
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='PNG')
        return img_byte_arr.getvalue()

    for img in en_images:
        parts.append(types.Part.from_bytes(data=pil_to_bytes(img), mime_type="image/png"))
    for img in ta_images:
        parts.append(types.Part.from_bytes(data=pil_to_bytes(img), mime_type="image/png"))
    parts.append(types.Part.from_text(text=user_prompt))

    contents = [
        types.Content(
            role="user",
            parts=parts,
        ),
    ]
    
    cfg = types.GenerateContentConfig(
        temperature=0.1,
        max_output_tokens=8192,
        response_mime_type="application/json",
        system_instruction=[types.Part.from_text(text=sys_prompt)],
    )
    
    try:
        response = client.models.generate_content(
            model=model_id,
            contents=contents,
            config=cfg,
        )
        collected = response.text
        
        # Verbose Logging of response
        with st.expander("Show Raw LLM Response (Debugging)", expanded=False):
            st.code(collected, language="json")

        # Robust JSON extraction and parsing
        collected_clean = collected.strip()
        # Remove markdown ticks if present
        if collected_clean.startswith("```json"):
            collected_clean = collected_clean[7:]
        elif collected_clean.startswith("```"):
            collected_clean = collected_clean[3:]
        if collected_clean.endswith("```"):
            collected_clean = collected_clean[:-3]
        collected_clean = collected_clean.strip()

        try:
            data = json.loads(collected_clean)
        except json.JSONDecodeError as decode_error:
            # Try to fix truncated JSON by finding the last closing brace and appending array closure
            import re
            match = re.search(r"(\[.*\])", collected_clean, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(1))
                except json.JSONDecodeError:
                    st.error(f"Failed to parse JSON for this batch inside array. Raw: {collected[:500]}...")
                    return []
            else:
                if not collected_clean.endswith("]"):
                    # Attempt truncation fix
                    last_brace_idx = collected_clean.rfind("}")
                    if last_brace_idx != -1:
                        fixed_json = collected_clean[:last_brace_idx+1] + "\n]"
                        try:
                            data = json.loads(fixed_json)
                        except json.JSONDecodeError:
                            st.error(f"Failed to parse even after fixing truncation. Raw: {collected[:500]}...")
                            return []
                    else:
                        st.error(f"Failed to parse JSON (truncated, no objects found). Raw: {collected[:500]}...")
                        return []
                else:
                    st.error(f"Failed to parse JSON for this batch. Raw: {collected[:500]}...")
                    return []
        
        # Handle cases where LLM returns {"data": [...]} instead of directly the list
        if isinstance(data, dict):
            # Debug: show keys if it's an object
            st.warning(f"Batch returned object instead of list. Keys: {list(data.keys())}")
            for val in data.values():
                if isinstance(val, list):
                    data = val
                    break
        
        if not isinstance(data, list):
            st.error(f"Batch returned non-list data type: {type(data)}")
            return []

        # Normalize keys as required by the app (case-insensitive and support variations)
        normalized = []
        for item in data:
            if not isinstance(item, dict):
                continue
            
            # Find best match for English key
            en_val = ""
            for k in ["English_sentence", "english_sentence", "English", "english", "en", "EN", "English Sentence"]:
                if k in item:
                    en_val = str(item[k]).strip()
                    break
            
            # Find best match for Tamil key
            ta_val = ""
            for k in ["Tamil_sentence", "tamil_sentence", "Tamil", "tamil", "ta", "TA", "Tamil Sentence"]:
                if k in item:
                    ta_val = str(item[k]).strip()
                    break
            
            if en_val or ta_val:
                normalized.append({
                    "English_sentence": en_val,
                    "Tamil_sentence": ta_val,
                })
        
        st.write(f"  Alignment complete: {len(normalized)} rows extracted.")
        return normalized
    except Exception as e:
        st.error(f"Error during alignment: {e}")
        return []


# ---------- Dataset assembly ---------- #
def create_dataset(alignment_batches: List[List[Dict]]) -> pd.DataFrame:
    rows = []
    seen = set()
    for batch in alignment_batches:
        if not isinstance(batch, list):
            continue
        for row in batch:
            if not isinstance(row, dict):
                continue
            en = row.get("English_sentence", "").strip()
            ta = row.get("Tamil_sentence", "").strip()
            # Deduplicate while preserving order
            fingerprint = (en, ta)
            if fingerprint not in seen:
                rows.append({"English_sentence": en, "Tamil_sentence": ta})
                seen.add(fingerprint)
    
    return pd.DataFrame(rows, columns=["English_sentence", "Tamil_sentence"])



# ---------- Streamlit UI ---------- #
def main():
    st.set_page_config(page_title="PDF to English–Tamil MT Dataset Generator", layout="wide")
    st.title("PDF to English–Tamil MT Dataset Generator")

    # Initialize session state
    if "df" not in st.session_state:
        st.session_state.df = None
    if "csv_bytes" not in st.session_state:
        st.session_state.csv_bytes = None
    if "xlsx_bytes" not in st.session_state:
        st.session_state.xlsx_bytes = None
    if "en_raw_text" not in st.session_state:
        st.session_state.en_raw_text = ""
    if "ta_raw_text" not in st.session_state:
        st.session_state.ta_raw_text = ""

    st.sidebar.header("Diagnostics & Debugging")
    if st.sidebar.button("Run Environment Check"):
        diagnose_environment()
        
    if st.sidebar.button("Run Alignment Self-Test (Mock Data)"):
        st.subheader("Alignment Self-Test")
        mock_en = "This is a test sentence.\nThis is a second sentence."
        mock_ta = "இது ஒரு சோதனை வாக்கியம்.\nஇது இரண்டாவது வாக்கியம்."
        st.write("Attempting to align mock data using Gemini...")
        client = genai.Client(api_key="AIzaSyDmUXxV62V1sKKqCVOR1l4q76nEkr9yx4k")
        # Pass empty images for mock test
        results = align_with_llm(client, [], [], mock_en, mock_ta)
        if results:
            st.success(f"Self-test succeeded. Aligned {len(results)} rows.")
            st.dataframe(pd.DataFrame(results))
        else:
            st.error("Self-test failed (returned 0 results). Check API or Prompt.")

    col1, col2 = st.columns(2)
    en_pdf = col1.file_uploader("English PDF", type=["pdf"])
    ta_pdf = col2.file_uploader("Tamil PDF", type=["pdf"])
    
    st.info("💡 **Tip for large files (e.g. 200 pages):** The app will automatically process all 200 pages in smaller chunks. Set 'Pages per group' to 1 or 2 so the AI doesn't get overwhelmed and skip rows. The script will iterate through all 200 pages automatically.")
    
    en_window = st.number_input("English pages per group", min_value=1, value=1)
    ta_window = st.number_input("Tamil pages per group", min_value=1, value=1)
    stride = st.number_input("Grouping stride", min_value=1, value=1)

    if st.button("Generate Dataset", type="primary"):
        if not en_pdf or not ta_pdf:
            st.error("Please upload both PDFs.")
            return

        # Ensure we read from the beginning
        en_pdf.seek(0)
        ta_pdf.seek(0)

        # Step 1: Raw Text Extraction for Download
        with st.status("Step 1: Extracting Raw Text...", expanded=True) as status:
            st.write("Extracting English text...")
            en_pages = extract_text_from_pdf(en_pdf, lang="eng")
            st.session_state.en_raw_text = "\n\n".join(p["text"] for p in en_pages)
            st.write(f"  English extraction complete: {len(en_pages)} pages, {len(st.session_state.en_raw_text)} characters.")
            
            st.write("Extracting Tamil text...")
            ta_pages = extract_text_from_pdf(ta_pdf, lang="tam")
            st.session_state.ta_raw_text = "\n\n".join(p["text"] for p in ta_pages)
            st.write(f"  Tamil extraction complete: {len(ta_pages)} pages, {len(st.session_state.ta_raw_text)} characters.")
            status.update(label="Raw text extraction complete", state="complete")

        # Step 2: Grouping
        with st.status("Step 2: Grouping pages...", expanded=True) as status:
            st.write(f"Generating groups for EN ({len(en_pages)} pages) and TA ({len(ta_pages)} pages)...")
            grouped = group_pages(en_pages, ta_pages, en_window, ta_window)
            st.write(f"  Total groups created: {len(grouped)}")
            status.update(label=f"Created {len(grouped)} groups", state="complete")

        # Step 3: LLM Alignment
        all_aligned_data = []
        log_container = st.container()
        with st.status("Step 3: Aligning with LLM...", expanded=True) as status:
            client = genai.Client(api_key="AIzaSyDmUXxV62V1sKKqCVOR1l4q76nEkr9yx4k")
            for idx, g in enumerate(grouped, start=1):
                msg = f"**Processing Group {idx}** (EN: {g['en_range']}, TA: {g['ta_range']})"
                st.write(msg)
                
                en_char_count = len(g['en_text'])
                ta_char_count = len(g['ta_text'])
                st.write(f"  Input size: EN={en_char_count} chars, TA={ta_char_count} chars")
                
                if not g['en_text'].strip() and not g['ta_text'].strip():
                    st.warning(f"  Group {idx} has NO text to align. Skipping.")
                    continue
                
                aligned = align_with_llm(client, g['en_images'], g['ta_images'], g['en_text'], g['ta_text'])
                if not aligned:
                    st.error(f"  Group {idx} produced ZERO results. This batch failed.")
                else:
                    st.success(f"  Group {idx} success: {len(aligned)} rows aligned.")
                all_aligned_data.append(aligned)
            status.update(label="LLM alignment phase complete", state="complete")

        # Step 4: Dataset Assembly
        df = create_dataset(all_aligned_data)
        st.session_state.df = df
        
        # Prepare downloads
        st.session_state.csv_bytes = df.to_csv(index=False).encode("utf-8")
        
        xlsx_buffer = io.BytesIO()
        df.to_excel(xlsx_buffer, index=False, engine='openpyxl')
        st.session_state.xlsx_bytes = xlsx_buffer.getvalue()

    # Results Display (Outside the button block for persistence)
    if st.session_state.en_raw_text or st.session_state.ta_raw_text:
        st.divider()
        st.subheader("Extracted Raw Text")
        tcol1, tcol2 = st.columns(2)
        if st.session_state.en_raw_text:
            tcol1.download_button(
                "Download Extracted English Text",
                data=st.session_state.en_raw_text,
                file_name="extracted_en.txt",
                mime="text/plain",
            )
        if st.session_state.ta_raw_text:
            tcol2.download_button(
                "Download Extracted Tamil Text",
                data=st.session_state.ta_raw_text,
                file_name="extracted_ta.txt",
                mime="text/plain",
            )

    if st.session_state.df is not None:
        st.divider()
        st.subheader("Aligned Dataset Preview")
        st.dataframe(st.session_state.df, width='stretch')
        
        c1, c2 = st.columns(2)
        c1.download_button(
            "Download CSV",
            data=st.session_state.csv_bytes,
            file_name="en_ta_dataset.csv",
            mime="text/csv",
        )
        c2.download_button(
            "Download XLSX",
            data=st.session_state.xlsx_bytes,
            file_name="en_ta_dataset.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


if __name__ == "__main__":
    main()
