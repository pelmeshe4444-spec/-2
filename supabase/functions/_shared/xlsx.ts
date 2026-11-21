import { strToU8, zipSync } from 'fflate'
import { HttpError } from './auth.ts'

interface Sheet { name: string; widths: number[]; rows: (string | number | null)[][] }
const xml = (value: string): string => value.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;')
const declaration = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
const mainNamespace = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
const relationsNamespace = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'

// Inline string cells preserve names verbatim and prevent values from becoming formulas.
export function workbook(sheets: Sheet[]): Uint8Array {
  const files: Record<string, Uint8Array> = {}
  let totalBytes = 0
  const add = (path: string, contents: string): void => {
    const data = strToU8(declaration + contents)
    totalBytes += data.byteLength
    if (totalBytes > 49_000_000) throw new HttpError(400, 'Файл слишком большой. Сократите период.')
    files[path] = data
  }
  add('[Content_Types].xml', `<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>${sheets.map((_, index) => `<Override PartName="/xl/worksheets/sheet${index + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>`).join('')}</Types>`)
  add('_rels/.rels', `<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="${relationsNamespace}/officeDocument" Target="xl/workbook.xml"/></Relationships>`)
  add('xl/workbook.xml', `<workbook xmlns="${mainNamespace}" xmlns:r="${relationsNamespace}"><sheets>${sheets.map((sheet, index) => `<sheet name="${xml(sheet.name)}" sheetId="${index + 1}" r:id="rId${index + 1}"/>`).join('')}</sheets></workbook>`)
  add('xl/_rels/workbook.xml.rels', `<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">${sheets.map((_, index) => `<Relationship Id="rId${index + 1}" Type="${relationsNamespace}/worksheet" Target="worksheets/sheet${index + 1}.xml"/>`).join('')}<Relationship Id="styles" Type="${relationsNamespace}/styles" Target="styles.xml"/></Relationships>`)
  add('xl/styles.xml', `<styleSheet xmlns="${mainNamespace}"><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs></styleSheet>`)
  for (const [index, sheet] of sheets.entries()) {
    const lastCell = String.fromCharCode(64 + sheet.widths.length) + sheet.rows.length
    const rows = sheet.rows.map((row, number) => `<row r="${number + 1}">${row.map((value, column) => {
      if (value == null) return ''
      const reference = String.fromCharCode(65 + column) + (number + 1), style = number === 0 ? ' s="1"' : ''
      return typeof value === 'number' ? `<c r="${reference}"${style}><v>${value}</v></c>` : `<c r="${reference}" t="inlineStr"${style}><is><t xml:space="preserve">${xml(value)}</t></is></c>`
    }).join('')}</row>`).join('')
    add(`xl/worksheets/sheet${index + 1}.xml`, `<worksheet xmlns="${mainNamespace}"><dimension ref="A1:${lastCell}"/><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><cols>${sheet.widths.map((width, column) => `<col min="${column + 1}" max="${column + 1}" width="${width}" customWidth="1"/>`).join('')}</cols><sheetData>${rows}</sheetData><autoFilter ref="A1:${lastCell}"/></worksheet>`)
  }
  return zipSync(files, { level: 6 })
}
