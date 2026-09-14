const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),ts=require('typescript');
const file=path.resolve(__dirname,'../src/components/world-window/displayTextFit.ts'),mod={exports:{}};
new Function('module','exports','require',ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020,esModuleInterop:true}}).outputText)(mod,mod.exports,request=>require(path.resolve(path.dirname(file),request)));
const {fitDisplayFont,longestDisplayWord}=mod.exports;
for(const variant of ['regular','italic'])for(const text of ['Dreams','Passport','Thailand','Portugal','United Kingdom','Dominican Republic','Washington & Orlando','Alex Morgan','Montréal','東京','Averylongfamilynamewithnospace'])for(const width of [144,168,240,244,340])for(const scale of [1,1.35,2,3]){
 const size=fitDisplayFont(text,40,width,scale,variant);
 assert(Number.isFinite(size)&&size>0&&size<=40);
 if(scale===1)assert.equal(size,40,'Normal theme typography stays unchanged');
 else assert(longestDisplayWord(text,variant)*size*scale<=width-2+.001,'Every whole word fits its allocated heading width when enlarged');
}
assert.equal(fitDisplayFont('Hi',38,340,2),38,'Short titles continue to respect the full user font scaling');
assert.equal(fitDisplayFont('',38,240,2),38,'Empty text remains stable');
assert.equal(fitDisplayFont('Dreams',38,240,NaN),38);
assert.equal(longestDisplayWord('Montréal'),longestDisplayWord('Montreal'),'Accented letters use their bundled base-letter advance');
console.log('Display-fit checks passed: bundled regular/italic metrics, complete words, enlarged widths, unchanged normal typography and safe empty inputs.');
