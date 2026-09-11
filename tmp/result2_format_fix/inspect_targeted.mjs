import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

for (const [label, path] of [
  ["template", "C:/Users/jesst/Desktop/CUMCM-2026/C题/附件/附件5/result2.xlsx"],
  ["current", "C:/Users/jesst/Desktop/CUMCM-2026/Problem2/results/result2.xlsx"],
]) {
  const wb = await SpreadsheetFile.importXlsx(await FileBlob.load(path));
  console.log(`===${label}===`);
  for (const [sheetName, ranges] of Object.entries({
    "计划购电量": ["A1:H4", "EL1:EQ4"],
    "充放电量": ["A1:F20"],
    "紧急购电量": ["A1:F12"],
  })) {
    const sheet = wb.worksheets.getItem(sheetName);
    console.log(sheetName, sheet.tables.items.map(t => ({ name:t.name, style:t.style, showHeaders:t.showHeaders, showTotals:t.showTotals })));
    for (const range of ranges) {
      console.log((await wb.inspect({ kind:"table", sheetId:sheetName, range, include:"values,formulas", tableMaxRows:20, tableMaxCols:10, maxChars:6000 })).ndjson);
      console.log((await wb.inspect({ kind:"computedStyle", sheetId:sheetName, range, maxChars:12000 })).ndjson);
    }
  }
}
