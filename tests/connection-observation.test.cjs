const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../static/app.js'),'utf8');
// Execute the actual detail projection; this is text evidence, not a live renderer.
function details(c,facts){
 const scope={state:{settings:{}},t:x=>x,when:v=>'date:'+v,
  el:(tag,cls,text)=>({tag,text,children:[],append(...items){this.children.push(...items)}})};
 vm.createContext(scope);
 const start=source.indexOf('function connectionDetails('),rest=source.slice(start);
 vm.runInContext(rest.slice(0,rest.search(/\n(?:async )?function /)),scope);
 const before=JSON.stringify({c,facts}),box=scope.connectionDetails({id:'lab'},c,facts);
 assert.equal(JSON.stringify({c,facts}),before);
 const children=box.children[0].children;
 return [children[1].text,children[3].text];
}
const at='2026-10-18T04:00:00+00:00';
test('normalized missing/null facts override invalid and apparently valid raw dates',()=>{
 for(const c of [{},{observedAt:'invalid'},{observedAt:at,updatedAt:at,catalogScope:'published'}]){
  assert.deepEqual(details(c,{catalog:{state:'missing',source:'none',observedAt:null,updatedAt:null}}),['Не получен','Неизвестна']);
 }
});
test('normalized provider and published observations control date and provenance',()=>{
 for(const [source,label] of [['provider_api','API провайдера'],['published_docs','Опубликованная документация']]){
  assert.deepEqual(details({observedAt:'invalid',catalogScope:source==='provider_api'?'published':undefined},
   {catalog:{state:'saved',source,observedAt:at,updatedAt:null}}),[label,'date:'+at]);
 }
});
test('legacy valid provider and published timestamps remain supported',()=>{
 assert.deepEqual(details({updatedAt:at}),['API провайдера','date:'+at]);
 assert.deepEqual(details({observedAt:at,catalogScope:'published'}),['Опубликованная документация','date:'+at]);
 assert.deepEqual(details({observedAt:'invalid',updatedAt:at,sourceKind:'official_docs_snapshot'}),['Опубликованная документация','date:'+at]);
});
test('legacy invalid/missing dates do not invent a saved source',()=>{
 for(const c of [{},{observedAt:'invalid'},{observedAt:'invalid',updatedAt:'invalid',catalogScope:'published'}])
  assert.deepEqual(details(c),['Не получен','Неизвестна']);
});
