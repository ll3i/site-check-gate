#!/usr/bin/env python3
"""
doc_to_text.py — 공고 문서(.txt/.md/.html/.hwpx/.docx/.pptx/.pdf) → 평문 텍스트.

표를 ' | ' 셀 구분, 행은 줄바꿈으로 유지한다.
표준 라이브러리만 사용. 외부 LLM API 호출 없음.
"""
import sys
sys.dont_write_bytecode = True
import argparse
import html.parser
import json
import os
import re
import sys
import zipfile
from xml.etree import ElementTree as ET

# ---------- stdlib HTML tag stripper (keeps table cell structure) ----------
class _HTMLToText(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self._out = []
        self._cell_buf = []
        self._in_cell = 0
        self._in_pre = False
        self._last_tag = None

    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        if t in ("td", "th"):
            self._in_cell += 1
            self._cell_buf.append("")
        elif t == "tr":
            if self._in_cell:
                self._out.append(" | ".join(self._cell_buf))
                self._cell_buf = []
        elif t == "br":
            if self._in_cell:
                self._cell_buf[-1] += " "
            else:
                self._out.append("")
        elif t == "p":
            if self._in_cell:
                self._cell_buf[-1] += " "
            else:
                self._out.append("")
        elif t == "pre":
            self._in_pre = True
            self._out.append("")
        elif t in ("div", "section", "article", "header", "footer", "nav", "main"):
            self._out.append("")
        self._last_tag = t

    def handle_endtag(self, tag):
        t = tag.lower()
        if t in ("td", "th"):
            self._in_cell -= 1
        elif t == "pre":
            self._in_pre = False
        elif t in ("div", "section", "article", "header", "footer", "nav", "main"):
            self._out.append("")

    def handle_data(self, data):
        if self._in_pre:
            self._out.append(data)
            return
        if self._in_cell:
            self._cell_buf[-1] += data
        else:
            self._out.append(data)

    def get_text(self):
        lines = []
        for item in self._out:
            s = item.strip()
            if s:
                lines.append(s)
        # collapse empty lines
        result = []
        prev_empty = False
        for line in lines:
            empty = (line == "")
            if empty and prev_empty:
                continue
            result.append(line)
            prev_empty = empty
        return "\n".join(result)


def html_to_text(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        raw = f.read()
    p = _HTMLToText()
    try:
        p.feed(raw)
    except Exception:
        pass
    return p.get_text()


def _strip_namespace(tag):
    return tag.split("}")[-1] if "}" in tag else tag


def _iter_text_elements(root, ns=None):
    """Yield (text, element) for w:t / a:t / mc:AlternateContent text runs."""
    for el in root.iter():
        name = _strip_namespace(el.tag)
        if name in ("t",):
            yield el.text or "", el


def _get_drawing_text(slide_root):
    """Extract text from <p:sp>/<p:pic> drawing elements in a slide."""
    texts = []
    for sp in slide_root.iter():
        name = _strip_namespace(sp.tag)
        if name == "sp" or name == "pic":
            for t_el in sp.iter():
                tn = _strip_namespace(t_el.tag)
                if tn == "t" and t_el.text:
                    texts.append(t_el.text)
    return "".join(texts)


def _extract_body_text(body_root, nsmap=None):
    """Extract paragraphs (w:p) text from a document body, joining runs."""
    out = []
    for p_el in body_root.iter():
        if _strip_namespace(p_el.tag) != "p":
            continue
        runs = []
        for t_el in p_el.iter():
            if _strip_namespace(t_el.tag) == "t" and t_el.text:
                runs.append(t_el.text)
        line = "".join(runs)
        if line.strip():
            out.append(line)
    return out


def _docx_text(path):
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        doc_path = "word/document.xml"
        if doc_path not in names:
            return ""
        with z.open(doc_path) as f:
            tree = ET.parse(f)
        root = tree.getroot()
        body = root.find("w:body") if "w:body" in [f"{{{uri}}}{'body'}" for uri in [
            root.tag.split('}')[0].strip('{')
        ]] else root
        # find body element properly
        body_el = None
        for el in root.iter():
            if _strip_namespace(el.tag) == "body":
                body_el = el
                break
        if body_el is None:
            return ""
        paras = _extract_body_text(body_el)
        # also tables
        for tbl in body_el.iter():
            if _strip_namespace(tbl.tag) == "tbl":
                for tr in tbl.iter():
                    if _strip_namespace(tr.tag) == "tr":
                        cells = []
                        for tc in tr.iter():
                            if _strip_namespace(tc.tag) == "tc":
                                cell_runs = []
                                for t_el in tc.iter():
                                    if _strip_namespace(t_el.tag) == "t" and t_el.text:
                                        cell_runs.append(t_el.text)
                                cells.append("".join(cell_runs))
                        if any(cells):
                            paras.append(" | ".join(cells))
        return "\n".join(paras)


def _pptx_text(path):
    with zipfile.ZipFile(path) as z:
        slide_files = sorted(
            n for n in z.namelist()
            if re.match(r"ppt/slides/slide\d+\.xml$", n)
        )
        if not slide_files:
            return ""
        out = []
        for sf in slide_files:
            with z.open(sf) as f:
                tree = ET.parse(f)
            root = tree.getroot()
            slide_texts = []
            for el in root.iter():
                name = _strip_namespace(el.tag)
                if name == "t" and el.text:
                    slide_texts.append(el.text)
            if slide_texts:
                out.append(" ".join(slide_texts))
        return "\n".join(out)


def _hwpx_text(path):
    """HWPX (OWPML) — extract text from section0.xml body."""
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            # find section xml
            section_files = [
                n for n in names
                if re.match(r"Contents/section\d+\.xml$", n)
            ]
            if not section_files:
                # try paragraph-based layout
                section_files = [
                    n for n in names
                    if n.endswith(".xml") and "section" in n.lower()
                ]
            if not section_files:
                return ""
            text_parts = []
            for sf in section_files:
                with z.open(sf) as f:
                    tree = ET.parse(f)
                root = tree.getroot()
                # HWPX uses <hp:p> paragraphs with <hp:t> runs, or <hp:tc> cells
                for el in root.iter():
                    name = _strip_namespace(el.tag)
                    if name == "t" and el.text:
                        text_parts.append(el.text)
                    elif name == "control" and el.text:
                        text_parts.append(el.text)
            return "\n".join(text_parts)
    except Exception:
        return ""


def _pdf_text(path):
    """Try pdftotext (poppler) first, then pypdf if installed."""
    import subprocess
    # pdftotext
    try:
        r = subprocess.run(
            ["pdftotext", "-layout", path, "-"],
            capture_output=True, text=True, timeout=60
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    # pypdf
    try:
        import pypdf
        reader = pypdf.PdfReader(path)
        pages = []
        for page in reader.pages:
            t = page.extract_text()
            if t:
                pages.append(t)
        if pages:
            return "\n".join(pages)
    except (ImportError, Exception):
        pass
    return ""


# ---------- main dispatch ----------
SUPPORTED = {
    ".txt": "text",
    ".md": "text",
    ".markdown": "text",
    ".htm": "html",
    ".html": "html",
    ".hwpx": "hwpx",
    ".docx": "docx",
    ".pptx": "pptx",
    ".pdf": "pdf",
}


def to_text(path):
    ext = os.path.splitext(path)[1].lower()
    kind = SUPPORTED.get(ext)
    if kind is None:
        return None, f"미지원 형식: {ext} (지원: {', '.join(sorted(SUPPORTED))})"

    if not os.path.isfile(path):
        return None, f"파일 없음: {path}"

    if os.path.getsize(path) == 0:
        return "", "빈 파일"

    try:
        if kind == "text":
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                return f.read(), None
        if kind == "html":
            return html_to_text(path), None
        if kind == "docx":
            t = _docx_text(path)
            return t, None if t else "문서에서 텍스트를 추출할 수 없음"
        if kind == "pptx":
            t = _pptx_text(path)
            return t, None if t else "슬라이드에서 텍스트를 추출할 수 없음"
        if kind == "hwpx":
            t = _hwpx_text(path)
            return t, None if t else "HWPX 섹션에서 텍스트를 추출할 수 없음"
        if kind == "pdf":
            t = _pdf_text(path)
            if t:
                return t, None
            return None, "PDF 텍스트 추출 실패(pdftotext/pypdf 미설치 또는 스캔 PDF)"
    except Exception as e:
        return None, f"변환 오류: {e}"


def main():
    ap = argparse.ArgumentParser(
        description="공고 문서 → 평문 텍스트 (표 셀은 ' | ' 구분)"
    )
    ap.add_argument("file", help="입력 파일 경로 (.txt/.md/.html/.hwpx/.docx/.pptx/.pdf)")
    ap.add_argument("--out", "-o", help="출력 파일 경로 (생략 시 stdout)")
    args = ap.parse_args()

    text, err = to_text(args.file)

    if err:
        if err.startswith("파일 없음"):
            print(json.dumps({"error": err, "exit_code": 2}))
            sys.exit(2)
        if err.startswith("미지원") or err.startswith("PDF") or "추출할 수 없음" in err or "추출 실패" in err:
            print(json.dumps({"error": err, "exit_code": 3}))
            sys.exit(3)
        print(json.dumps({"error": err, "exit_code": 3}))
        sys.exit(3)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        print(json.dumps({"ok": True, "chars": len(text), "path": args.out}))
    else:
        print(text)
    sys.exit(0)


if __name__ == "__main__":
    main()
