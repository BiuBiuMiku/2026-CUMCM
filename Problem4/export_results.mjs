import fs from 'node:fs/promises';
import path from 'node:path';
import { FileBlob, SpreadsheetFile } from '@oai/artifact-tool';

const root='C:/Users/jesst/Desktop/CUMCM-2026';
const tasks=[
  {dir:'Result-2',template:'result4-2.xlsx',output:'result4-2.xlsx',maps:[['计划购电量','plan'],['充放电量','battery'],['紧急购电量','emergency']]},
  {dir:'Result-3',template:'result4-3.xlsx',output:'result4-3.xlsx',maps:[['计划购电量','plan'],['调整购电量','adjusted'],['充放电量','battery'],['紧急购电量','emergency']]},
];
const label=t=>`${Math.floor(t/6)}:${String(t%6*10).padStart(2,'0')}`;
const thin={style:'thin',color:'#000000'};

function formatBody(sh,rowCount,cols,groupStarts,groupEnds){
  const body=sh.getRangeByIndexes(1,0,rowCount,cols);
  body.format.font={name:'宋体',size:10,color:'#000000'};
  body.format.horizontalAlignment='center';
  body.format.verticalAlignment='center';
  body.format.borders={preset:'none'};
  for(let col=0;col<cols;col++){
    sh.getRangeByIndexes(1,col,rowCount,1).format.borders={left:thin,right:thin};
  }
  for(const row of groupStarts)sh.getRangeByIndexes(row,0,1,cols).format.borders={left:thin,right:thin,top:thin};
  for(const row of groupEnds)sh.getRangeByIndexes(row,0,1,cols).format.borders={left:thin,right:thin,bottom:thin};
}

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
      sh.getRangeByIndexes(1,0,rows.length,cols).values=rows;
      sh.getRangeByIndexes(1,0,rows.length,1).setNumberFormat('m/d/yy');
      if(key==='battery'){
        const starts=Array.from({length:rows.length/6},(_,i)=>1+i*6);
        const ends=starts.map(r=>r+5);
        formatBody(sh,rows.length,cols,starts,ends);
        sh.getRangeByIndexes(1,2,rows.length,2).setNumberFormat('0.000000');
        sh.getRangeByIndexes(1,5,rows.length,1).setNumberFormat('0.000000');
        for(const row of starts){
          sh.getRangeByIndexes(row,4,1,1).setNumberFormat('h:mm');
          sh.getRangeByIndexes(row+1,4,1,1).setNumberFormat('@');
        }
      }else{
        const starts=[];
        for(let i=0;i<rows.length;i++)if(rows[i][0]!==null)starts.push(1+i);
        const ends=starts.map((r,i)=>(i+1<starts.length?starts[i+1]-1:rows.length));
        formatBody(sh,rows.length,cols,starts,ends);
        sh.getRangeByIndexes(1,2,rows.length,1).setNumberFormat('0.000000');
      }
    }
  }
  console.log((await wb.inspect({kind:'table',range:"'计划购电量'!A1:G3",tableMaxRows:3,tableMaxCols:7,maxChars:1200})).ndjson);
  console.log((await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!',options:{useRegex:true,maxResults:20},maxChars:1000})).ndjson);
  const preview=await wb.render({sheetName:'计划购电量',range:'A1:G4',scale:1.5,format:'png'});
  await fs.writeFile(path.join(base,'results','preview.png'),new Uint8Array(await preview.arrayBuffer()));
  await (await SpreadsheetFile.exportXlsx(wb)).save(path.join(base,task.output));
}
