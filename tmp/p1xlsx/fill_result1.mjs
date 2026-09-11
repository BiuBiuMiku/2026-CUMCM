import fs from 'node:fs/promises';
import path from 'node:path';
import { FileBlob, SpreadsheetFile } from '@oai/artifact-tool';

const root = process.cwd();
const scratch = path.join(root, 'tmp', 'p1xlsx');
const template = path.join(root, 'C题', '附件', '附件5', 'result1.xlsx');
const wb = await SpreadsheetFile.importXlsx(await FileBlob.load(template));
const saveRender = async (sheetName, range, name) => {
  const blob = await wb.render({sheetName, range, scale: 1.6, format:'png'});
  await fs.writeFile(path.join(scratch,name), new Uint8Array(await blob.arrayBuffer()));
};
if (process.argv.includes('--inspect')) {
  console.log((await wb.inspect({kind:'workbook,sheet,table',maxChars:3500,tableMaxRows:8,tableMaxCols:6})).ndjson);
  await saveRender('计划购电量','A1:B10','before_plan.png');
  await saveRender('充放电量','A1:E7','before_storage.png');
} else {
  const evidence = JSON.parse(await fs.readFile(path.join(root,'Problem1','problem1_lp_evidence.json'),'utf8'));
  const rows = evidence.schedule;
  if (rows.length !== 144) throw new Error('Expected 144 rows');
  const plan = wb.worksheets.getItem('计划购电量');
  const storage = wb.worksheets.getItem('充放电量');
  plan.getRange('A2:A145').values = rows.map(r=>[`${r.start}-${r.end}`]);
  plan.getRange('B2:B145').values = rows.map(r=>[r.purchase_kwh]);
  storage.getRange('B2:C7').values = evidence.four_hour_blocks.map(r=>[r.charge_kwh,r.discharge_kwh]);
  storage.getRange('E2:E3').values = [[evidence.results.soc_start_kwh],[evidence.results.soc_end_kwh]];
  plan.getRange('B2:B145').setNumberFormat('0.000000');
  storage.getRange('B2:C7').setNumberFormat('0.000000');
  storage.getRange('E2:E3').setNumberFormat('0.00');
  console.log((await wb.inspect({kind:'region',sheetId:'计划购电量',range:'A1:B5',maxChars:1200})).ndjson);
  console.log((await wb.inspect({kind:'region',sheetId:'充放电量',range:'A1:E7',maxChars:2400})).ndjson);
  console.log((await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!',options:{useRegex:true,maxResults:20},maxChars:1000})).ndjson);
  const sum = plan.getRange('B2:B145').values.reduce((a,r)=>a+r[0],0);
  if(Math.abs(sum-evidence.results.purchase_kwh)>1e-7) throw new Error('Purchase total mismatch');
  await saveRender('计划购电量','A1:B10','after_plan.png');
  await saveRender('充放电量','A1:E7','after_storage.png');
  const out = await SpreadsheetFile.exportXlsx(wb);
  await out.save(path.join(root,'Problem1','result1.xlsx'));
  console.log(JSON.stringify({output:'Problem1/result1.xlsx',purchase_kwh:sum,source_cost_yuan:evidence.results.cost_yuan}));
}
