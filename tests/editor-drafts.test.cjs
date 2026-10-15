const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {JSDOM}=require('jsdom');
const root=path.resolve(__dirname,'..');
const read=file=>fs.readFileSync(path.join(root,file),'utf8');

function fixture(file){
 const dom=new JSDOM(read('static/index.html'),{url:'http://fixture.invalid/',runScripts:'outside-only'}),w=dom.window;
 w.$=id=>w.document.getElementById(id);w.t=value=>value;
 w.el=(tag,cls,text)=>{const node=w.document.createElement(tag);node.className=cls||'';if(text!==undefined)node.textContent=text;return node;};
 w.eval(read('static/drafts.js'));w.eval(read(file)+';window.fixtureEval=code=>eval(code);');
 return {w,close:()=>w.close(),dirty:()=>w.agentCityDrafts.snapshot().dirty};
}
function rules(w,content,preserve=false){
 w.bundle={current:{scope:'global',content},global:{content},repo:null};
 w.fixtureEval('applyRuleScope(bundle,'+preserve+')');
}

test('switching clean rule scopes and discarding after a conflict allow a clean close',()=>{
 const ui=fixture('static/integrations.js'),{w}=ui;
 try{
  rules(w,'Saved rules');const field=w.$('rules-content');w.agentCityDrafts.remember(field);
  rules(w,'Other saved rules');assert.equal(ui.dirty(),false,'loading saved content is not an edit');
  field.value='Unsaved draft';assert.equal(ui.dirty(),true);
  rules(w,'Externally updated rules',true);assert.equal(field.value,'Unsaved draft');assert.equal(ui.dirty(),true);
  w.fixtureEval('setRuleBusy(false)');
  w.$('discard-rules').click();assert.equal(field.value,'Externally updated rules');
  assert.equal(ui.dirty(),false,'explicit discard adopts the current saved baseline');
 }finally{ui.close();}
});

test('loading another saved skill clears the previous editor baseline',()=>{
 const ui=fixture('static/workspace.js'),{w}=ui;
 try{
  w.skill={name:'First',path:'fixture/first',content:'First saved content',history:[]};w.fixtureEval('installSkillDraft(skill)');
  w.agentCityDrafts.remember(w.$('skill-content'));
  w.skill={name:'Second',path:'fixture/second',content:'Second saved content',history:[]};w.fixtureEval('installSkillDraft(skill)');
  assert.equal(ui.dirty(),false);w.$('skill-content').value='Unsaved change';assert.equal(ui.dirty(),true);
 }finally{ui.close();}
});

test('opening a saved extension establishes a fresh form baseline',()=>{
 const ui=fixture('static/workspace.js'),{w}=ui;
 try{
  w.$('project-dialog').showModal=()=>{};w.fixtureEval('projectsSnapshot={projects:[]}');
  w.project={name:'First',repoUrl:'https://example.invalid/1',docsUrl:'https://example.invalid/docs',description:{ru:'One',en:'One'},useCases:[],category:'other'};
  w.fixtureEval('openProject(project)');w.agentCityDrafts.remember(w.$('project-name'));
  w.project.name='Second';w.fixtureEval('openProject(project)');
  assert.equal(ui.dirty(),false);w.$('project-name').value='Unsaved change';assert.equal(ui.dirty(),true);
 }finally{ui.close();}
});
