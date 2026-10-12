# scripts/function.py
import csv
import os
import zipfile

import openpyxl
import pandas as pd

# -------------------------------------------------------------
# 1. Legge le prime n righe di un CSV/TSV/TXT/Excel come DataFrame
# -------------------------------------------------------------
def read_table_preview(path, nrows=10):
    if not os.path.exists(path):
        raise FileNotFoundError(f"{path} does not exist")
    if _is_xlsx(path):
        return _read_xlsx(path, nrows=nrows)
    return _read_delimited_text(path, nrows=nrows)


def read_table_headers(path):
    if not os.path.exists(path):
        raise FileNotFoundError(f"{path} does not exist")
    if _is_xlsx(path):
        return _read_xlsx_headers(path)
    return _read_text_headers(path)


def _is_xlsx(path):
    return zipfile.is_zipfile(path)


def _read_xlsx(path, nrows=10):
    # read_only=True streams rows straight off the zip/XML instead of
    # building a full DOM in memory - the previous hand-rolled
    # ElementTree parser materialized the whole sheet XML (100MB+ for a
    # 20k-gene count matrix) and issued a namespaced find()/findall()
    # per cell, which is what made large uploads crawl.
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb.worksheets[0]
        row_iter = ws.iter_rows(values_only=True)
        try:
            header_row = next(row_iter)
        except StopIteration:
            return pd.DataFrame()
        header = ["" if col is None else str(col).strip() for col in header_row]
        if nrows == 0:
            return pd.DataFrame(columns=header)

        rows = []
        for row in row_iter:
            rows.append(["" if v is None else v for v in row])
            if nrows is not None and len(rows) >= nrows:
                break

        return pd.DataFrame(rows, columns=header)
    finally:
        wb.close()


def _read_xlsx_headers(path):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb.worksheets[0]
        for row in ws.iter_rows(values_only=True):
            return ["" if v is None else str(v).strip() for v in row]
        return []
    finally:
        wb.close()


def _detect_text_separator(sample_text):
    candidates = ["\t", ",", ";", "|"]
    counts = {sep: sample_text.count(sep) for sep in candidates}
    best_sep = max(counts, key=counts.get)
    if counts[best_sep] == 0:
        try:
            dialect = csv.Sniffer().sniff(sample_text, delimiters=candidates)
            return dialect.delimiter
        except Exception:
            return ","
    return best_sep


def _decode_text_bytes(raw):
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    if b"\x00" in raw[:4096]:
        for encoding in ("utf-16", "utf-16-le", "utf-16-be"):
            try:
                return raw.decode(encoding, errors="replace")
            except UnicodeDecodeError:
                continue
    return raw.decode("utf-8-sig", errors="replace")


def _read_text_prefix(path, line_count=12, chunk_size=1024 * 1024, max_bytes=64 * 1024 * 1024):
    chunks = []
    total = 0
    newline_count = 0
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            newline_count += chunk.count(b"\n")
            if newline_count >= line_count or total >= max_bytes:
                break
    return b"".join(chunks)


def _read_delimited_text(path, nrows=10):
    if os.path.getsize(path) == 0:
        return pd.DataFrame()

    # Detecting encoding/separator only ever needs a small prefix, even for a
    # full-file read (nrows=None) - reading the whole file into RAM just to
    # decide how to parse it (then handing pandas an in-memory copy via
    # StringIO instead of the path) used to make every full read of a large
    # count matrix do 3x the necessary memory copies. pandas' C parser reads
    # straight off disk in one pass once we know encoding/separator.
    sample_line_count = 200 if nrows is None else max(int(nrows) + 1, 1)
    prefix = _read_text_prefix(path, line_count=sample_line_count, max_bytes=2 * 1024 * 1024)
    if prefix.startswith((b"\xff\xfe", b"\xfe\xff")) or b"\x00" in prefix[:4096]:
        # errors="replace" below means the -le/-be variants never actually
        # get used (decode never raises) - same as before this rewrite.
        encoding = "utf-16"
    else:
        encoding = "utf-8-sig"
    sample_text = prefix.decode(encoding, errors="replace")
    if not sample_text.strip():
        return pd.DataFrame()
    separator = _detect_text_separator(sample_text[:8192])

    try:
        return pd.read_csv(path, sep=separator, engine="c", encoding=encoding,
                            encoding_errors="replace", nrows=nrows)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def _read_text_headers(path):
    raw = _read_text_prefix(path, line_count=1)
    text = _decode_text_bytes(raw)
    if not text.strip():
        return []
    separator = _detect_text_separator(text[:8192])
    first_line = text.splitlines()[0] if text.splitlines() else ""
    reader = csv.reader([first_line], delimiter=separator)
    try:
        return [str(col).strip() for col in next(reader, [])]
    except Exception:
        return [col.strip() for col in first_line.split(separator)]

# -------------------------------------------------------------
# 2. Restituisce il percorso completo del file caricato
# -------------------------------------------------------------
def get_uploaded_file(uploader_id, file_name):
    """
    Restituisce il path completo del file caricato
    uploader_id: cartella temporanea dell'upload (es: "counts_uploader")
    file_name: nome del file caricato
    """
    return os.path.join("uploads/temp/", uploader_id, file_name)

# -------------------------------------------------------------
# 3. Crea le cartelle necessarie per un nuovo study
# -------------------------------------------------------------
def ensure_dirs(base_dir, study_name):
    """
    Crea la cartella dello studio e sottocartelle se non esistono
    """
    study_folder = os.path.join(base_dir, study_name)
    os.makedirs(study_folder, exist_ok=True)
    return study_folder
