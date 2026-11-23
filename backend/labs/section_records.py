"""
Section question download generation.

PDF  → xhtml2pdf (pure Python, no GTK/libgobject required)
DOCX → docxtpl when admin has uploaded a section template,
       python-docx programmatic fallback otherwise.
"""
import io

from django.template.loader import render_to_string
from django.utils import timezone
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt

from accounts.models import CollegeSettings


def section_context(section, questions) -> dict:
    cs = CollegeSettings.load()
    q_list = [
        {
            "question_no": q.question_no,
            "text": q.text,
            "marks": q.marks,
        }
        for q in questions
    ]
    return {
        "college": cs,
        "logo_path": cs.logo.path if cs.logo else None,
        "college_name": cs.college_name,
        "college_address": cs.college_address,
        "section": {
            "number": section.section_number,
            "title": section.title,
            "description": section.description,
            "subject_name": section.subject.name,
            "subject_code": section.subject.code,
            "approved_by": section.approved_by.get_full_name() if section.approved_by else "",
            "approved_at": (
                timezone.localtime(section.approved_at).strftime("%d-%m-%Y")
                if section.approved_at else ""
            ),
        },
        # Flat fields for docxtpl top-level access
        "section_number": section.section_number,
        "section_title": section.title,
        "section_description": section.description,
        "subject_name": section.subject.name,
        "subject_code": section.subject.code,
        "approved_by": section.approved_by.get_full_name() if section.approved_by else "",
        "approved_at": (
            timezone.localtime(section.approved_at).strftime("%d-%m-%Y")
            if section.approved_at else ""
        ),
        "questions": q_list,
        "generated_at": timezone.localtime(timezone.now()).strftime("%d-%m-%Y %H:%M"),
    }


# ---------------------------------------------------------------------------
# PDF via xhtml2pdf  (no system dependencies)
# ---------------------------------------------------------------------------
def _ensure_pdf_engine():
    try:
        import xhtml2pdf  # noqa: F401
        return
    except ImportError:
        pass
    import sys
    from pathlib import Path
    for p in [
        Path.home() / "AppData" / "Local" / "Programs" / "Python" / "Python312" / "Lib" / "site-packages",
        Path.home() / "AppData" / "Local" / "Programs" / "Python" / "Python311" / "Lib" / "site-packages",
        Path.home() / "AppData" / "Local" / "Programs" / "Python" / "Python313" / "Lib" / "site-packages",
        Path.home() / "AppData" / "Local" / "Programs" / "Python" / "Python314" / "Lib" / "site-packages",
    ]:
        if p.exists() and str(p) not in sys.path:
            sys.path.append(str(p))
            try:
                import xhtml2pdf  # noqa: F401
                return
            except ImportError:
                continue


def build_section_pdf(section, questions) -> bytes:
    _ensure_pdf_engine()
    from xhtml2pdf import pisa  # noqa: PLC0415

    ctx = section_context(section, questions)
    html = render_to_string("labs/section_questions.html", ctx)
    buf = io.BytesIO()
    # pisa requires bytes input when html5lib is the parser
    result = pisa.CreatePDF(html.encode("utf-8"), dest=buf)
    if result.err:
        raise RuntimeError(f"xhtml2pdf error: {result.err}")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# DOCX via docxtpl (template) or python-docx (fallback)
# ---------------------------------------------------------------------------
def build_section_docx(section, questions) -> bytes:
    cs = CollegeSettings.load()
    ctx = section_context(section, questions)
    # Try section_template first, then record_template as fallback
    template = cs.section_template or cs.record_template
    if template:
        try:
            return _build_section_docx_from_template(ctx, template.path)
        except Exception:
            pass  # Fall through to programmatic on any template error
    return _build_section_docx_programmatic(ctx)


def _build_section_docx_from_template(ctx, template_path: str) -> bytes:
    from docxtpl import DocxTemplate  # noqa: PLC0415

    tpl = DocxTemplate(template_path)
    tpl.render(ctx)
    buf = io.BytesIO()
    tpl.save(buf)
    return buf.getvalue()


def _build_section_docx_programmatic(ctx) -> bytes:
    """python-docx fallback used when no template is uploaded."""
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Times New Roman"
    style.font.size = Pt(12)
    cs = ctx["college"]
    sec = ctx["section"]

    # Header
    if ctx.get("logo_path"):
        try:
            doc.add_picture(ctx["logo_path"], width=Pt(60))
            doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
        except Exception:
            pass

    h = doc.add_paragraph()
    h.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = h.add_run(cs.college_name.upper())
    r.bold = True
    r.font.size = Pt(15)

    if cs.college_address:
        a = doc.add_paragraph(cs.college_address)
        a.alignment = WD_ALIGN_PARAGRAPH.CENTER

    doc.add_paragraph()

    sub_p = doc.add_paragraph()
    sub_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub_r = sub_p.add_run(f"{sec['subject_code']} – {sec['subject_name']}")
    sub_r.bold = True
    sub_r.font.size = Pt(13)

    title_p = doc.add_paragraph()
    title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_r = title_p.add_run(f"Section {sec['number']}: {sec['title']}")
    title_r.bold = True
    title_r.font.size = Pt(14)

    if sec.get("description"):
        desc_p = doc.add_paragraph(sec["description"])
        desc_p.alignment = WD_ALIGN_PARAGRAPH.CENTER

    doc.add_paragraph()

    # Questions table
    table = doc.add_table(rows=1, cols=3)
    table.style = "Table Grid"
    hdr = table.rows[0].cells
    hdr[0].text = "Q.No"
    hdr[1].text = "Question"
    hdr[2].text = "Marks"
    for cell in hdr:
        for para in cell.paragraphs:
            for run in para.runs:
                run.bold = True

    for q in ctx["questions"]:
        row = table.add_row().cells
        row[0].text = str(q["question_no"])
        row[1].text = q["text"]
        row[2].text = str(q["marks"]) if q["marks"] else ""

    doc.add_paragraph()

    footer_p = doc.add_paragraph()
    footer_p.add_run(
        f"Approved by: {sec.get('approved_by', '')}    "
        f"Date: {sec.get('approved_at', '')}    "
        f"Generated: {ctx['generated_at']}"
    ).italic = True

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
