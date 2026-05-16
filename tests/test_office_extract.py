"""Tests for office document extraction (DOCX, XLSX, ODT, ODS, ODP)."""

import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from codeloom.core.extract import extract_file


def _make_docx(path: Path, paragraphs: list[str]) -> Path:
    """Create a minimal DOCX file with given paragraph texts."""
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = ET.Element(f"{{{ns}}}body")
    for text in paragraphs:
        p = ET.SubElement(body, f"{{{ns}}}p")
        r = ET.SubElement(p, f"{{{ns}}}r")
        t = ET.SubElement(r, f"{{{ns}}}t")
        t.text = text
    doc_xml = ET.tostring(body, encoding="unicode", xml_declaration=False)
    full_doc = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="{ns}">{doc_xml}</w:document>'

    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", full_doc)
    return path


def _make_xlsx(path: Path, sheets: list[tuple[str, list[list[str]]]]) -> Path:
    """Create a minimal XLSX file with given sheet data."""
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    r_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

    shared_strings = []
    sst_items = []

    for _sheet_name, rows in sheets:
        for row in rows:
            for cell in row:
                if cell not in shared_strings:
                    shared_strings.append(cell)
                    si = ET.Element(f"{{{ns}}}si")
                    t = ET.SubElement(si, f"{{{ns}}}t")
                    t.text = cell
                    sst_items.append(si)

    # Build shared strings XML
    sst = ET.Element(f"{{{ns}}}sst")
    sst.set("count", str(len(shared_strings)))
    sst.set("uniqueCount", str(len(shared_strings)))
    for si in sst_items:
        sst.append(si)
    sst_xml = ET.tostring(sst, encoding="unicode", xml_declaration=False)
    full_sst = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><sst xmlns="{ns}">{sst_xml}</sst>'

    with zipfile.ZipFile(path, "w") as z:
        # Write workbook
        wb_ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
        wb = ET.Element(f"{{{wb_ns}}}workbook")
        wb_sheets = ET.SubElement(wb, f"{{{wb_ns}}}sheets")
        for i, (sheet_name, _) in enumerate(sheets):
            ws = ET.SubElement(wb_sheets, f"{{{wb_ns}}}sheet")
            ws.set("name", sheet_name)
            ws.set("sheetId", str(i + 1))
            ws.set(f"{{{r_ns}}}id", f"rId{i + 1}")
        wb_xml = ET.tostring(wb, encoding="unicode", xml_declaration=False)
        full_wb = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="{wb_ns}" xmlns:r="{r_ns}">{wb_xml}</workbook>'
        z.writestr("xl/workbook.xml", full_wb)

        # Write shared strings
        z.writestr("xl/sharedStrings.xml", full_sst)

        # Write sheets
        for i, (sheet_name, rows) in enumerate(sheets):
            sheet_data = ET.Element(f"{{{ns}}}sheetData")
            for ri, row_cells in enumerate(rows):
                row_elem = ET.SubElement(sheet_data, f"{{{ns}}}row")
                row_elem.set("r", str(ri + 1))
                for ci, cell_val in enumerate(row_cells):
                    col_letter = chr(65 + ci)
                    cell_elem = ET.SubElement(row_elem, f"{{{ns}}}c")
                    cell_elem.set("r", f"{col_letter}{ri + 1}")
                    if cell_val in shared_strings:
                        cell_elem.set("t", "s")
                        idx = shared_strings.index(cell_val)
                        v = ET.SubElement(cell_elem, f"{{{ns}}}v")
                        v.text = str(idx)
                    else:
                        v = ET.SubElement(cell_elem, f"{{{ns}}}v")
                        v.text = cell_val
            sheet_xml_body = ET.tostring(sheet_data, encoding="unicode", xml_declaration=False)
            full_sheet = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="{ns}">{sheet_xml_body}</worksheet>'
            z.writestr(f"xl/worksheets/sheet{i + 1}.xml", full_sheet)

    return path


def _make_odt(path: Path, paragraphs: list[str]) -> Path:
    """Create a minimal ODT file with given paragraph texts."""
    ns_text = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
    ns_office = "urn:oasis:names:tc:opendocument:xmlns:office:1.0"

    paras = "\n".join(f'<text:p>{p}</text:p>' for p in paragraphs)
    content_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<office:document-content xmlns:office="{ns_office}" xmlns:text="{ns_text}">'
        f'<office:body><office:text>{paras}</office:text></office:body>'
        f'</office:document-content>'
    )

    with zipfile.ZipFile(path, "w") as z:
        z.writestr("content.xml", content_xml)
    return path


def _make_ods(path: Path, sheets: list[tuple[str, list[list[str]]]]) -> Path:
    """Create a minimal ODS file with given sheet data."""
    ns_table = "urn:oasis:names:tc:opendocument:xmlns:table:1.0"
    ns_text = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
    ns_office = "urn:oasis:names:tc:opendocument:xmlns:office:1.0"

    tables_xml = ""
    for sheet_name, rows in sheets:
        rows_xml = ""
        for row_cells in rows:
            cells_xml = ""
            for cell_val in row_cells:
                cells_xml += f'<table:table-cell office:value-type="string"><text:p>{cell_val}</text:p></table:table-cell>'
            rows_xml += f"<table:table-row>{cells_xml}</table:table-row>"
        tables_xml += f'<table:table table:name="{sheet_name}">{rows_xml}</table:table>'

    content_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<office:document-content xmlns:office="{ns_office}" xmlns:text="{ns_text}" xmlns:table="{ns_table}">'
        f'<office:body><office:spreadsheet>{tables_xml}</office:spreadsheet></office:body>'
        f'</office:document-content>'
    )

    with zipfile.ZipFile(path, "w") as z:
        z.writestr("content.xml", content_xml)
    return path


def _make_odp(path: Path, slides: list[tuple[str, list[str]]]) -> Path:
    """Create a minimal ODP file with given slide data."""
    ns_draw = "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"
    ns_text = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
    ns_office = "urn:oasis:names:tc:opendocument:xmlns:office:1.0"
    ns_pres = "urn:oasis:names:tc:opendocument:xmlns:presentation:1.0"

    pages_xml = ""
    for slide_name, paragraphs in slides:
        paras_xml = "".join(f"<text:p>{p}</text:p>" for p in paragraphs)
        pages_xml += (
            f'<draw:page draw:name="{slide_name}">'
            f'<draw:page-thumbnail/><office:presentation>{paras_xml}</office:presentation>'
            f'</draw:page>'
        )

    content_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<office:presentation xmlns:office="{ns_office}" xmlns:draw="{ns_draw}" xmlns:text="{ns_text}" xmlns:presentation="{ns_pres}">'
        f'<office:body><office:presentation>{pages_xml}</office:presentation></office:body>'
        f'</office:presentation>'
    )

    with zipfile.ZipFile(path, "w") as z:
        z.writestr("content.xml", content_xml)
    return path


class TestDocxExtraction:
    def test_extracts_document_node(self, tmp_path):
        p = _make_docx(tmp_path / "test.docx", ["Hello world"])
        result = extract_file(str(p), "docx", "")
        docs = [n for n in result.nodes if n.kind == "document"]
        assert len(docs) == 1
        assert docs[0].name == "test"

    def test_extracts_paragraphs(self, tmp_path):
        p = _make_docx(tmp_path / "test.docx", ["First para", "Second para"])
        result = extract_file(str(p), "docx", "")
        sections = [n for n in result.nodes if n.kind == "section"]
        assert len(sections) == 2
        assert "First para" in sections[0].source_snippet
        assert "Second para" in sections[1].source_snippet

    def test_empty_document(self, tmp_path):
        p = _make_docx(tmp_path / "empty.docx", [])
        result = extract_file(str(p), "docx", "")
        assert len(result.nodes) == 1  # Only document node

    def test_returns_empty_on_invalid_file(self, tmp_path):
        p = tmp_path / "broken.docx"
        p.write_text("not a zip file")
        result = extract_file(str(p), "docx", "")
        assert len(result.nodes) == 1  # Only document node placeholder


class TestXlsxExtraction:
    def test_extracts_document_node(self, tmp_path):
        p = _make_xlsx(tmp_path / "test.xlsx", [("Sheet1", [["a", "b"], ["1", "2"]])])
        result = extract_file(str(p), "xlsx", "")
        docs = [n for n in result.nodes if n.kind == "document"]
        assert len(docs) == 1
        assert docs[0].name == "test"

    def test_extracts_rows(self, tmp_path):
        p = _make_xlsx(tmp_path / "test.xlsx", [("Sheet1", [["h1", "h2"], ["v1", "v2"]])])
        result = extract_file(str(p), "xlsx", "")
        sections = [n for n in result.nodes if n.kind == "section"]
        assert len(sections) >= 2

    def test_empty_spreadsheet(self, tmp_path):
        p = _make_xlsx(tmp_path / "empty.xlsx", [("Sheet1", [])])
        result = extract_file(str(p), "xlsx", "")
        assert len(result.nodes) == 1

    def test_shared_strings_resolution(self, tmp_path):
        p = _make_xlsx(tmp_path / "test.xlsx", [("Sheet1", [["hello world"]])])
        result = extract_file(str(p), "xlsx", "")
        sections = [n for n in result.nodes if n.kind == "section"]
        if sections:
            assert "hello" in sections[0].source_snippet

    def test_returns_empty_on_invalid_file(self, tmp_path):
        p = tmp_path / "broken.xlsx"
        p.write_text("not a zip file")
        result = extract_file(str(p), "xlsx", "")
        assert len(result.nodes) == 1


class TestOdtExtraction:
    def test_extracts_document_node(self, tmp_path):
        p = _make_odt(tmp_path / "test.odt", ["Hello world"])
        result = extract_file(str(p), "odt", "")
        docs = [n for n in result.nodes if n.kind == "document"]
        assert len(docs) == 1
        assert docs[0].name == "test"

    def test_extracts_paragraphs(self, tmp_path):
        p = _make_odt(tmp_path / "test.odt", ["First para", "Second para"])
        result = extract_file(str(p), "odt", "")
        sections = [n for n in result.nodes if n.kind == "section"]
        assert len(sections) == 2

    def test_returns_empty_on_invalid_file(self, tmp_path):
        p = tmp_path / "broken.odt"
        p.write_text("not a zip file")
        result = extract_file(str(p), "odt", "")
        assert len(result.nodes) == 1


class TestOdsExtraction:
    def test_extracts_document_node(self, tmp_path):
        p = _make_ods(tmp_path / "test.ods", [("Sheet1", [["a", "1"], ["b", "2"]])])
        result = extract_file(str(p), "ods", "")
        docs = [n for n in result.nodes if n.kind == "document"]
        assert len(docs) == 1
        assert docs[0].name == "test"

    def test_extracts_rows(self, tmp_path):
        p = _make_ods(tmp_path / "test.ods", [("Sheet1", [["col1", "col2"]])])
        result = extract_file(str(p), "ods", "")
        sections = [n for n in result.nodes if n.kind == "section"]
        assert len(sections) >= 1

    def test_returns_empty_on_invalid_file(self, tmp_path):
        p = tmp_path / "broken.ods"
        p.write_text("not a zip file")
        result = extract_file(str(p), "ods", "")
        assert len(result.nodes) == 1


class TestOdpExtraction:
    def test_extracts_document_node(self, tmp_path):
        p = _make_odp(tmp_path / "test.odp", [("Slide1", ["Hello world"])])
        result = extract_file(str(p), "odp", "")
        docs = [n for n in result.nodes if n.kind == "document"]
        assert len(docs) == 1
        assert docs[0].name == "test"

    def test_extracts_slides(self, tmp_path):
        p = _make_odp(tmp_path / "test.odp", [("Slide1", ["Title"]), ("Slide2", ["Content"])])
        result = extract_file(str(p), "odp", "")
        sections = [n for n in result.nodes if n.kind == "section"]
        assert len(sections) == 2

    def test_returns_empty_on_invalid_file(self, tmp_path):
        p = tmp_path / "broken.odp"
        p.write_text("not a zip file")
        result = extract_file(str(p), "odp", "")
        assert len(result.nodes) == 1
