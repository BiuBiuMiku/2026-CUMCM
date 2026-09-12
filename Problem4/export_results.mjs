import fs from 'node:fs/promises';
import path from 'node:path';
import { FileBlob, SpreadsheetFile } from '@oai/artifact-tool';

const root='C:/Users/jesst/Desktop/CUMCM-2026';
const tasks=[
  {dir:'Result-2',template:'result4-2.xlsx',output:'result4-2.xlsx',maps:[['计划购电量','plan'],['充放电量','battery'],['紧急购电量','emergency']]},
  {dir:'Result-3',template:'result4-3.xlsx',output:'result4-3.xlsx',maps:[['计划购电量','plan'],['调整购电量','adjusted'],['充放电量','battery'],['紧急购电量','emergency']]},
];
const label=t=>`${Math.floor(t/6)}:${String(t%6*10).padStart(2,'0')}`;
for(const task of tasks){
  const base=path.join(root,'Problem4',task.dir);const tables=JSON.parse(await fs.readFile(path.join(base,'results','tables.json'),'utf8'));
  const wb=await SpreadsheetFile.importXlsx(await FileBlob.load(path.join(root,'C题','附件','附件5',task.template)));
  const timeHeaders=[Array.from({length:144},(_,t)=>`${label(t)}-${label(t+1)}`)];
  for(const [sheet,key] of task.maps){
    const sh=wb.worksheets.getItem(sheet);const rows=tables[key];
    if(key==='plan'||key==='adjusted'){
      if(rows.length!==334||rows.some(r=>r.length!==147))throw Error(`${sheet}: unexpected dimensions`);
      sh.getRange('B1:EO1').values=timeHeaders;sh.getRange('A2:EQ335').values=rows;
      sh.getRange('A2:A335').setNumberFormat('m/d/yy');sh.getRange('B2:EQ335').setNumberFormat('0.000000');
    }else{
      const cols=key==='battery'?6:3;const block=key==='battery'?6:3;
      sh.getUsedRange().offset(1,0).clear({applyTo:'contents'});
      for(let start=1;start<=rows.length;start+=block){
        const len=Math.min(block,rows.length-start+1);sh.getRangeByIndexes(start,0,len,cols).copyFrom(sh.getRangeByIndexes(1,0,len,cols),'all');
      }
      sh.getRangeByIndexes(1,0,rows.length,cols).values=rows;sh.getRangeByIndexes(1,0,rows.length,1).setNumberFormat('m/d/yy');
      sh.getRangeByIndexes(1,2,rows.length,key==='battery'?2:1).setNumberFormat('0.000000');
      if(key==='battery')sh.getRangeByIndexes(1,5,rows.length,1).setNumberFormat('0.000000');
    }
  }
  console.log((await wb.inspect({kind:'table',range:"'计划购电量'!A1:G3",tableMaxRows:3,tableMaxCols:7,maxChars:1200})).ndjson);
  console.log((await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!',options:{useRegex:true,maxResults:20},maxChars:1000})).ndjson);
  const preview=await wb.render({sheetName:'计划购电量',range:'A1:G4',scale:1.5,format:'png'});
  await fs.writeFile(path.join(base,'results','preview.png'),new Uint8Array(await preview.arrayBuffer()));
  await (await SpreadsheetFile.exportXlsx(wb)).save(path.join(base,task.output));
}
