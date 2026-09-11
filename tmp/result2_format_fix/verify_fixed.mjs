import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";
const path = "C:/Users/jesst/Desktop/CUMCM-2026/Problem2/results/result2_格式修正版.xlsx";
const wb = await SpreadsheetFile.importXlsx(await FileBlob.load(path));
for (const [sheetName, range] of [
  ["计划购电量", "A1:L8"],
  ["计划购电量", "EL1:EQ8"],
  ["充放电量", "A1:F30"],
  ["充放电量", "A1994:F2005"],
  ["紧急购电量", "A1:C25"],
  ["紧急购电量", "A230:C242"],
]) {
  const key = `${sheetName}_${range.replaceAll(":", "-")}`;
  const blob = await wb.render({ sheetName, range, scale: 2, format: "png" });
  await fs.writeFile(`C:/Users/jesst/Desktop/CUMCM-2026/tmp/result2_format_fix/fixed_${key}.png`, new Uint8Array(await blob.arrayBuffer()));
}
for (const [sheetName, range] of [
  ["计划购电量", "A1:EQ8"],
  ["充放电量", "A1:F30"],
  ["紧急购电量", "A1:C25"],
]) {
  console.log((await wb.inspect({ kind:"table", sheetId:sheetName, range, include:"values,formulas", tableMaxRows:8, tableMaxCols:8, maxChars:6000 })).ndjson);
}
console.log((await wb.inspect({
  kind:"match",
  searchTerm:"#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!",
  options:{ useRegex:true, maxResults:300 },
  summary:"final formula error scan",
})).ndjson);
