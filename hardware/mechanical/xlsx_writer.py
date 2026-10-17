"""A minimal .xlsx writer, standard library only.

JLCPCB's templates are .xlsx and their importer has been shown to discard a column it does not
recognise without saying so, so it is handed the format they ship. openpyxl is not available under
KiCad's Python and the fab generator has to run there for pcbnew, so this writes the five parts of a
minimal workbook by hand. Strings are inline, which avoids a sharedStrings part entirely.
"""
import zipfile

CT = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
      '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
      '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
      '<Default Extension="xml" ContentType="application/xml"/>'
      '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
      '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
      '</Types>')
RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '</Relationships>')
WB = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
      '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
      '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>')
WBR = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
       '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
       '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
       '</Relationships>')


def _col(i):
    s = ''
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _esc(v):
    return str(v).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def write(path, rows):
    """rows: list of lists, written as inline strings.

    Every column gets a cell, blanks included. Omitting an empty cell is valid xlsx -- cells carry
    their own address -- but it collapses the row for anything reading positionally, and the PCBWay
    BOM has interior blanks where passives have no manufacturer part number.
    """
    body = []
    for n, row in enumerate(rows, 1):
        cells = ''.join(
            ('<c r="%s%d"/>' % (_col(i), n)) if str(v) == '' else
            ('<c r="%s%d" t="inlineStr"><is><t xml:space="preserve">%s</t></is></c>'
             % (_col(i), n, _esc(v)))
            for i, v in enumerate(row))
        body.append('<row r="%d">%s</row>' % (n, cells))
    sheet = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
             '<sheetData>%s</sheetData></worksheet>' % ''.join(body))
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', CT)
        z.writestr('_rels/.rels', RELS)
        z.writestr('xl/workbook.xml', WB)
        z.writestr('xl/_rels/workbook.xml.rels', WBR)
        z.writestr('xl/worksheets/sheet1.xml', sheet)
