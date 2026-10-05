const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

class Element {
 constructor(tag='div',text=''){this.tag=tag;this.textContent=text;this.children=[];this.value='';this.hidden=false;this.open=false;}
 append(...nodes){this.children.push(...nodes);}
 replaceChildren(...nodes){this.children=[...nodes];}
 setAttribute(name,value){this[name]=value;}
 addEventListener(){}
 showModal(){this.open=true;}
 close(){this.open=false;}
}
const content=node=>node.textContent+node.children.map(content).join('');
function fixture(request){
 const nodes=new Map(),get=id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);};
 const navigated=[],selected=[];
 const context=vm.createContext({request,$:get,el:(tag,cls,text='')=>new Element(tag,text),t:value=>value,encodeURIComponent,
  window:{AgentCityStandards:{selectRepository:async id=>{selected.push(id);return true;}}},
  setView:view=>navigated.push(view),toast:message=>{throw Error(message);}});
 const source=fs.readFileSync(path.join(__dirname,'../static/integrations.js'),'utf8');
 vm.runInContext(source.slice(0,source.indexOf("$('repos-search').addEventListener")),context);
 return {context,get,navigated,selected,setRepo(repo){context.fixtureRepo=repo;vm.runInContext('currentRepo=fixtureRepo',context);}};
}
const repo=id=>({id,name:id,path:'/workspace/'+id,branch:'main',instructions:[],profile:{extensionIds:[],revision:'profile-1'}});

test('project Standards navigation selects the real repo and restores the same draft without writing',async()=>{
 const actual=repo('repo-real'),requests=[];
 const ui=fixture(async url=>{requests.push(url);if(url==='/api/repositories')return{repositories:[actual]};if(url.startsWith('/api/standards/assignments?repoId='))return{repoId:actual.id,standardRefs:[{id:'neutral-workspace',version:'1'}]};throw Error('Unexpected request: '+url);});
 ui.setRepo(actual);ui.get('repo-dialog').open=true;ui.get('project-policy-instructions').value='Unsaved project draft';
 const formNode=ui.get('project-policy-instructions');
 await vm.runInContext('openRepoStandards()',ui.context);
 assert.deepEqual(ui.navigated,['standards']);assert.deepEqual(ui.selected,[actual.id]);assert.equal(ui.get('repo-dialog').open,false);
 await vm.runInContext('renderRepos()',ui.context);await Promise.resolve();
 assert.equal(ui.get('repo-dialog').open,true);assert.equal(ui.get('project-policy-instructions'),formNode);assert.equal(formNode.value,'Unsaved project draft');
 assert.match(content(ui.get('repo-standard-refs')),/neutral-workspace · v1/);
 assert.deepEqual(requests,['/api/repositories','/api/standards/assignments?repoId=repo-real']);
});

test('late standard references cannot replace the currently selected project',async()=>{
 let resolveFirst;
 const ui=fixture(url=>url.endsWith('repo-first')?new Promise(resolve=>{resolveFirst=resolve;}):Promise.resolve({standardRefs:[{id:'second-standard',version:'2'}]}));
 ui.setRepo(repo('repo-first'));const first=vm.runInContext("renderRepoStandards('repo-first')",ui.context);
 ui.setRepo(repo('repo-second'));await vm.runInContext("renderRepoStandards('repo-second')",ui.context);
 resolveFirst({standardRefs:[{id:'first-standard',version:'1'}]});await first;
 assert.match(content(ui.get('repo-standard-refs')),/second-standard · v2/);assert.doesNotMatch(content(ui.get('repo-standard-refs')),/first-standard/);
});

test('unavailable project standards remain an explicit read error',async()=>{
 const ui=fixture(async()=>{throw Error('Source unavailable');});ui.setRepo(repo('repo-real'));
 await vm.runInContext("renderRepoStandards('repo-real')",ui.context);
 assert.equal(content(ui.get('repo-standard-refs')),'Source unavailable');assert.equal(ui.get('repo-standard-refs').children[0].role,'alert');
});
