import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const files = {
  template: "C:/Users/jesst/Desktop/CUMCM-2026/C题/附件/附件5/result2.xlsx",
  current: "C:/Users/jesst/Desktop/CUMCM-2026/Problem2/results/result2.xlsx",
};

for (const [label, path] of Object.entries(files)) {
  const wb = await SpreadsheetFile.importXlsx(await FileBlob.load(path));
  const overview = await wb.inspect({
    kind: "workbook,sheet,table",
    maxChars: 12000,
    tableMaxRows: 14,
    tableMaxCols: 12,
    tableMaxCellChars: 80,
  });
  console.log(`===${label}===`);
  console.log(overview.ndjson);
  const sheets = (await wb.inspect({ kind: "sheet", include: "id,name", maxChars: 5000 })).ndjson
    .trim().split(/\r?\n/).map((line) => JSON.parse(line).name).filter(Boolean);
  console.log(`SHEETS=${JSON.stringify(sheets)}`);
  for (let i = 0; i < sheets.length; i++) {
    const image = await wb.render({ sheetName: sheets[i], autoCrop: "all", scale: 1, format: "png" });
    await fs.writeFile(`C:/Users/jesst/Desktop/CUMCM-2026/tmp/result2_format_fix/${label}_${i + 1}.png`, new Uint8Array(await image.arrayBuffer()));
  }
}
