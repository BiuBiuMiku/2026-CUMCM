import fs from 'node:fs/promises';
import { FileBlob, SpreadsheetFile } from '@oai/artifact-tool';

const dir = 'C:/Users/jesst/Desktop/CUMCM-2026/tmp/result2_format_fix';
const target = 'C:/Users/jesst/Desktop/CUMCM-2026/Problem2/results/result2.xlsx';
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(target));
const plan = workbook.worksheets.getItem('计划购电量');
const editing = process.argv.includes('--edit');
if (editing) {
  const label = t => `${Math.floor(t / 6)}:${String(t % 6 * 10).padStart(2, '0')}`;
  plan.getRange('B1:EO1').values = [Array.from({length: 144}, (_, t) => `${label(t)}-${label(t+1)}`)];
}
for (const [name, range] of [['start', 'A1:F3'], ['noon', 'BS1:BX3'], ['end', 'EM1:EQ3']]) {
  const blob = await workbook.render({sheetName: '计划购电量', range, scale: 1.5, format:'png'});
  await fs.writeFile(`${dir}/headers_${editing ? 'after' : 'before'}_${name}.png`, new Uint8Array(await blob.arrayBuffer()));
}
console.log((await workbook.inspect({kind:'table',range:"'计划购电量'!BS1:BX3",tableMaxRows:3,tableMaxCols:6,maxChars:1300})).ndjson);
if (editing) {
  console.log((await workbook.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!|#NULL!',options:{useRegex:true,maxResults:10},maxChars:1000})).ndjson);
  await (await SpreadsheetFile.exportXlsx(workbook)).save(`${dir}/result2_headers_candidate.xlsx`);
}
