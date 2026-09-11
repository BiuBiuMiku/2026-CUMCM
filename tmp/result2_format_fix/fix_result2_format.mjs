import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const templatePath = "C:/Users/jesst/Desktop/CUMCM-2026/C题/附件/附件5/result2.xlsx";
const targetPath = "C:/Users/jesst/Desktop/CUMCM-2026/Problem2/results/result2.xlsx";
const tempPath = "C:/Users/jesst/Desktop/CUMCM-2026/tmp/result2_format_fix/result2_checked.xlsx";

const template = await SpreadsheetFile.importXlsx(await FileBlob.load(templatePath));
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(targetPath));

const valueSnapshot = (wb) => JSON.stringify({
  plan: wb.worksheets.getItem("计划购电量").getRange("A2:EQ335").values,
  battery: wb.worksheets.getItem("充放电量").getRange("A2:F2005").values,
  emergency: wb.worksheets.getItem("紧急购电量").getRange("A2:C242").values,
});
const before = valueSnapshot(workbook);
const thin = { style: "thin", color: "#000000" };
const bodyFont = { name: "宋体", size: 10, color: "#000000" };

// Sheet 1 already has the official 334 daily rows. Restore only the template header/style
// and date display; all 334x144 purchase values and the two daily totals remain untouched.
const plan = workbook.worksheets.getItem("计划购电量");
const planTemplate = template.worksheets.getItem("计划购电量");
plan.getRange("A1:EQ1").copyFrom(planTemplate.getRange("A1:EQ1"), "all");
plan.getRange("A2:A335").format.numberFormat = "m/d/yy";
plan.getRange("A2:A335").format.horizontalAlignment = "center";

// Sheet 2 expands the ellipsis to all 334 days. Repeat the original six-row daily frame.
const battery = workbook.worksheets.getItem("充放电量");
const batteryBody = battery.getRange("A2:F2005");
battery.getRange("A1:F1").format = {
  font: bodyFont,
  horizontalAlignment: "center",
  verticalAlignment: "center",
  borders: { preset: "all", style: "thin", color: "#000000" },
};
batteryBody.format.font = bodyFont;
batteryBody.format.horizontalAlignment = "center";
batteryBody.format.verticalAlignment = "center";
batteryBody.format.borders = {
  left: thin, right: thin, insideVertical: thin,
};
battery.getRange("A2:A2005").format.numberFormat = "m/d/yy";
battery.getRange("C2:D2005").format.numberFormat = "0.000000";
battery.getRange("F2:F2005").format.numberFormat = "0.000000";
for (let start = 2; start <= 2005; start += 6) {
  battery.getRange(`A${start}:F${start}`).format.borders = {
    top: thin, left: thin, right: thin, insideVertical: thin,
  };
  const end = start + 5;
  battery.getRange(`A${end}:F${end}`).format.borders = {
    bottom: thin, left: thin, right: thin, insideVertical: thin,
  };
}

// Sheet 3 keeps every emergency-purchase event. Remove only the non-template note block,
// then reproduce the template's three-column grouped frame for all event rows.
const emergency = workbook.worksheets.getItem("紧急购电量");
emergency.getRange("D1:F242").clear({ applyTo: "all" });
emergency.getRange("A1:C1").format = {
  font: bodyFont,
  horizontalAlignment: "center",
  verticalAlignment: "center",
  borders: { preset: "all", style: "thin", color: "#000000" },
};
const emergencyBody = emergency.getRange("A2:C242");
emergencyBody.format.font = bodyFont;
emergencyBody.format.horizontalAlignment = "center";
emergencyBody.format.verticalAlignment = "center";
emergencyBody.format.borders = {
  left: thin, right: thin, insideVertical: thin,
};
emergency.getRange("A2:A242").format.numberFormat = "m/d/yy";
emergency.getRange("C2:C242").format.numberFormat = "0.000000";
const dates = emergency.getRange("A2:A242").values.map(row => row[0]);
for (let i = 0; i < dates.length; i++) {
  const row = i + 2;
  const first = i === 0 || dates[i] !== dates[i - 1];
  const last = i === dates.length - 1 || dates[i] !== dates[i + 1];
  if (first || last) emergency.getRange(`A${row}:C${row}`).format.borders = {
    ...(first ? { top: thin } : {}),
    ...(last ? { bottom: thin } : {}),
    left: thin, right: thin, insideVertical: thin,
  };
}

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(tempPath);
const verified = await SpreadsheetFile.importXlsx(await FileBlob.load(tempPath));
const after = valueSnapshot(verified);
if (before !== after) throw new Error("Result values changed during format-only repair");
await fs.copyFile(tempPath, targetPath);
await fs.unlink(tempPath);
console.log("FORMAT_FIXED_VALUES_UNCHANGED");
