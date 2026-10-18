const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
function element(tag,cls='',text=''){
 return {tag,cls,text,children:[],append(...nodes){this.children.push(...nodes);},setAttribute(){}};
}
const scope={URLSearchParams,location:{search:''},document:{querySelectorAll:()=>[],createTextNode:text=>element('#text','',text)},$:()=>({addEventListener(){}}),el:element,t:text=>text,when:text=>text,age:()=>0};
vm.createContext(scope);vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/dashboard.js'),'utf8'),scope);
const text=node=>[node.text,...node.children.map(text)].filter(Boolean).join(' ');
const find=(node,cls)=>node.cls===cls?node:node.children.map(n=>find(n,cls)).find(Boolean);
const run=(id,model,extra={})=>({runId:id,sequence:1,agent:'codex',model,provider:null,stage:'Review',status:'done',inputTokens:null,outputTokens:null,mcpCalls:null,skillIds:[],history:[],updatedAt:'2026-10-18T00:00:00Z',firstReportedAt:'2026-10-18T00:00:00Z',...extra});

test('single-attempt stage explicitly shows unknown model instead of agent or configured default',()=>{
 const row=run('unknown',null,{configuredModel:'configured-only',defaultModel:'default-only'});
 const report=scope.drawTaskReport({title:'Synthetic'},[row]);
 assert.match(text(find(report,'stage-report-models')),/Модель не сообщена/);
 assert.doesNotMatch(text(report),/configured-only|default-only/);
});

test('mixed attempts preserve reported models and expose missing model in stage and each attempt',()=>{
 const report=scope.drawTaskReport({title:'Synthetic'},[run('known','reported-model'),run('unknown',null)]);
 const models=text(find(report,'stage-report-models'));
 assert.match(models,/reported-model/);assert.match(models,/Модель не сообщена/);
 const unknown=scope.drawRun(run('unknown',null));
 assert.match(text(find(unknown,'attempt-main')),/Модель не сообщена/);
 assert.match(text(find(unknown,'attempt-subtitle')),/codex/);
});

test('known model and provider stay exact without borrowing another attempt model',()=>{
 const known=scope.drawRun(run('known','reported-model',{provider:'reported-provider'}));
 assert.match(text(known),/reported-provider · reported-model/);
 assert.doesNotMatch(text(known),/Модель не сообщена/);
 assert.equal(scope.modelText(run('unknown',null,{provider:'provider-only',configuredModel:'wrong'})),'Модель не сообщена');
});
