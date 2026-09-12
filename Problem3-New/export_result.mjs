import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { FileBlob, SpreadsheetFile } from '@oai/artifact-tool';

const here=path.dirname(fileURLToPath(import.meta.url));
const root=path.dirname(here);
const temp=path.join(root,'tmp','problem3_new_preview');
await fs.mkdir(temp,{recursive:true});
const wb=await SpreadsheetFile.importXlsx(await FileBlob.load(path.join(root,'C题','附件','附件5','result3.xlsx')));
const ranges=[['计划购电量','A1:G5'],['调整购电量','A1:G5'],['充放电量','A1:F14'],['紧急购电量','A1:C9']];
if(process.argv.includes('--preview')){
  for(let i=0;i<ranges.length;i++){
    const [name,range]=ranges[i];
    const image=await wb.render({sheetName:name,range,scale:1.5,format:'png'});
    await fs.writeFile(path.join(temp,`template_${i}.png`),new Uint8Array(await image.arrayBuffer()));
  }
  console.log((await wb.inspect({kind:'sheet',include:'id,name'})).ndjson);
}else{
  const data=JSON.parse(await fs.readFile(path.join(here,'results','tables.json'),'utf8'));
  const originalHeaders=ranges.map(([name])=>JSON.stringify(wb.worksheets.getItem(name).getUsedRange().getRow(0).values));
  for(const [name,key] of [['计划购电量','plan'],['调整购电量','adjusted']]){
    const sh=wb.worksheets.getItem(name);const rows=data[key];
    if(rows.length!==334||rows.some(r=>r.length!==147))throw Error('Unexpected plan dimensions');
    sh.getRange('A2:EQ335').values=rows;
    sh.getRange('B2:EQ335').setNumberFormat('0.000000');
  }
  for(const [name,key,cols] of [['充放电量','battery',6],['紧急购电量','emergency',3]]){
    const sh=wb.worksheets.getItem(name);const rows=data[key];
    // Expand the template ellipsis using its existing daily block formats.
    const old=sh.getUsedRange();old.offset(1,0).clear({applyTo:'contents'});
    const block=key==='battery'?6:3;
    for(let start=1;start<=rows.length;start+=block){
      const len=Math.min(block,rows.length-start+1);
      sh.getRangeByIndexes(start,0,len,cols).copyFrom(sh.getRangeByIndexes(1,0,len,cols),'all');
    }
    sh.getRangeByIndexes(1,0,rows.length,cols).values=rows;
    sh.getRangeByIndexes(1,0,rows.length,1).setNumberFormat('m/d/yy');
    sh.getRangeByIndexes(1,2,rows.length,key==='battery'?2:1).setNumberFormat('0.000000');
    const body=sh.getRangeByIndexes(1,0,rows.length,cols);
    body.format.font={name:'宋体',size:10,color:'#000000'};
    body.format.horizontalAlignment='center';
    body.format.verticalAlignment='center';
    body.format.rowHeight=15;
    const thin={style:'thin',color:'#000000'};
    body.format.borders={preset:'none'};
    body.format.borders={left:thin,right:thin,insideVertical:thin};
    if(key==='battery'){
      sh.getRangeByIndexes(1,5,rows.length,1).setNumberFormat('0.000000');
      for(let i=0;i<rows.length;i+=6){
        sh.getRangeByIndexes(i+1,0,1,6).format.borders={top:thin,left:thin,right:thin,insideVertical:thin};
        sh.getRangeByIndexes(i+6,0,1,6).format.borders={bottom:thin,left:thin,right:thin,insideVertical:thin};
      }
    }
    if(key==='emergency'){
      for(let i=0;i<rows.length;i++){
        const first=rows[i][0]!==null;
        const last=i===rows.length-1||rows[i+1][0]!==null;
        sh.getRangeByIndexes(i+1,0,1,3).format.borders={
          left:thin,right:thin,insideVertical:thin,
          top:first?thin:{style:'none'},bottom:last?thin:{style:'none'}};
      }
    }
  }
  for(let i=0;i<ranges.length;i++){
    const [name,range]=ranges[i];const sh=wb.worksheets.getItem(name);
    if(originalHeaders[i]!==JSON.stringify(sh.getUsedRange().getRow(0).values))throw Error('Header changed: '+name);
    const image=await wb.render({sheetName:name,range,scale:1.5,format:'png'});
    await fs.writeFile(path.join(temp,`result_${i}.png`),new Uint8Array(await image.arrayBuffer()));
    console.log((await wb.inspect({kind:'table',range:`'${name}'!${range}`,tableMaxRows:3,tableMaxCols:7,maxChars:1500})).ndjson);
  }
  console.log((await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!|#NULL!',options:{useRegex:true,maxResults:30},summary:'Formula error check'})).ndjson);
  const requested=process.argv.find(a=>a.toLowerCase().endsWith('.xlsx'));
  const outputPath=requested?path.resolve(requested):path.join(here,'results','result3.xlsx');
  const out=await SpreadsheetFile.exportXlsx(wb);await out.save(outputPath);
  console.log('Saved '+outputPath);
}
