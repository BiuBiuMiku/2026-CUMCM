import fs from 'node:fs/promises';
import {FileBlob,SpreadsheetFile} from '@oai/artifact-tool';
const root='C:/Users/jesst/Desktop/CUMCM-2026';
const books=[['Result-2','result4-2.xlsx'],['Result-3','result4-3.xlsx']];
await fs.mkdir(`${root}/tmp/problem4-preview`,{recursive:true});
for(const [dir,file] of books){
 const wb=await SpreadsheetFile.importXlsx(await FileBlob.load(`${root}/Problem4/${dir}/${file}`));
 const sheets=dir==='Result-2'?[['计划购电量','A1:G4'],['充放电量','A1:F14'],['紧急购电量','A1:C10']]:[['计划购电量','A1:G4'],['调整购电量','A1:G4'],['充放电量','A1:F14'],['紧急购电量','A1:C10']];
 for(let i=0;i<sheets.length;i++){
  const [sheet,range]=sheets[i];
  console.log((await wb.inspect({kind:'table',range:`'${sheet}'!${range}`,tableMaxRows:4,tableMaxCols:7,maxChars:1600})).ndjson);
  const image=await wb.render({sheetName:sheet,range,scale:1.5,format:'png'});
  await fs.writeFile(`${root}/tmp/problem4-preview/${dir}-${i}.png`,new Uint8Array(await image.arrayBuffer()));
 }
 console.log((await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!',options:{useRegex:true,maxResults:20},maxChars:1000})).ndjson);
}

