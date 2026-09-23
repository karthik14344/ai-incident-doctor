import os
import pypdf

def extract_text_from_pdf(file_path: str):
    """
    Extracts text from PDF file page by page.
    Returns list of objects: [{"page": 1, "text": "..."}, ...]
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    pages_data = []
    try:
        reader = pypdf.PdfReader(file_path)
        for idx, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            # Basic text cleaning
            text = text.strip()
            if text:
                pages_data.append({
                    "page": idx + 1,
                    "text": text
                })
    except Exception:
        # Fallback if file is txt or simple reading error
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
            pages_data.append({
                "page": 1,
                "text": text.strip()
            })
            
    return pages_data
