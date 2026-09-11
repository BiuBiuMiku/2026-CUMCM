import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";
const files = {
  template: "C:/Users/jesst/Desktop/CUMCM-2026/C题/附件/附件5/result2.xlsx",
  current: "C:/Users/jesst/Desktop/CUMCM-2026/Problem2/results/result2.xlsx",
};
const views = [
  ["计划购电量", "A1:L8", "plan_start"],
  ["计划购电量", "EL1:EQ8", "plan_end"],
  ["充放电量", "A1:F25", "battery_start"],
  ["紧急购电量", "A1:F20", "emergency_start"],
];
for (const [label, path] of Object.entries(files)) {
  const wb = await SpreadsheetFile.importXlsx(await FileBlob.load(path));
  for (const [sheetName, range, suffix] of views) {
    const blob = await wb.render({ sheetName, range, scale: 2, format: "png" });
    await fs.writeFile(`C:/Users/jesst/Desktop/CUMCM-2026/tmp/result2_format_fix/${label}_${suffix}.png`, new Uint8Array(await blob.arrayBuffer()));
  }
}
