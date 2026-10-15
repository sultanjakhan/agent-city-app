const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');

function editor(){
 const storage=new Map(),sent=[];
 const scope={TextEncoder,crypto:{randomUUID:()=> 'synthetic-operation'},
  localStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value)},
  request:async (route,body)=>{sent.push({route,body});return {};}};
 vm.createContext(scope);
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/shared-tasks.js'),'utf8'),scope);
 vm.runInContext(`sharedState={config:{sourceNamespace:null,transport:'pipe',endpoint:'',profile:'synthetic',client:'synthetic-client'}};loadSharedTasks=async()=>{};`,scope);
 return {scope,storage,sent};
}

test('multibyte editor text within the native byte limit is sent unchanged',async()=>{
 for(const content of ['Я'.repeat(2100),'Я'.repeat(4000),'😀'.repeat(2000),'A'.repeat(8000)]){
  const {scope,sent}=editor();
  await scope.queueShared('create',{title:'Synthetic task',content});
  assert.equal(sent[0].route,'/api/task-sync/queue');
  assert.equal(sent[0].body.arguments.content,content);
 }
});

test('oversized description, patch, comment and rework are refused before storage or transmission',async()=>{
 const long='Я'.repeat(4001);
 for(const [command,args] of [
  ['create',{title:'Synthetic task',content:long}],
  ['patch',{taskId:'task',expectedVersion:1,patch:{content:long}}],
  ['comment',{taskId:'task',expectedVersion:1,comment:long}],
  ['review',{taskId:'task',expectedVersion:1,resultVersion:1,decision:'rework',comment:long}],
  ['create',{title:'Synthetic task',content:'😀'.repeat(2001)}],
 ]){
  const {scope,storage,sent}=editor();
  await assert.rejects(scope.queueShared(command,args),{message:'task_text_too_large'});
  assert.equal(storage.size,0);assert.deepEqual(sent,[]);
 }
});

test('titles use the native 500-byte limit and a rejected edit keeps earlier unsent operations',async()=>{
 const {scope,storage,sent}=editor();
 await scope.queueShared('create',{title:'Я'.repeat(250),content:'Kept'});
 assert.equal(sent[0].body.arguments.title,'Я'.repeat(250));
 sent.length=0;
 const pending=JSON.stringify({'existing-operation':{operationId:'existing-operation',arguments:{content:'Unknown outcome'}}});
 storage.set('agent-city-shared-unsent-v1',pending);
 await assert.rejects(scope.queueShared('patch',{patch:{title:'Я'.repeat(251)}}),{message:'task_title_too_large'});
 assert.equal(storage.get('agent-city-shared-unsent-v1'),pending);assert.deepEqual(sent,[]);
});
