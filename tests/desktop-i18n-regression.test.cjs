const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
test('EN settings theme/options/aria and compact flow translate and RU toggles back',()=>{
 const sources=['\u0422\u0435\u043c\u0430 ','\u0421\u0438\u0441\u0442\u0435\u043c\u043d\u0430\u044f','\u0421\u0432\u0435\u0442\u043b\u0430\u044f','\u0422\u0451\u043c\u043d\u0430\u044f'];
 const nodes=sources.map(text=>({nodeValue:text,parentElement:{tagName:'OPTION'}}));
 const sourceAria='\u0422\u0435\u043c\u0430 \u0438\u043d\u0442\u0435\u0440\u0444\u0435\u0439\u0441\u0430';
 const attrs={'aria-label':sourceAria};
 const context=vm.createContext({localStorage:{getItem:()=> 'en',setItem:()=>{}},location:{hostname:'synthetic.localhost'},NodeFilter:{SHOW_TEXT:4},
  document:{documentElement:{},body:{},createTreeWalker:()=>{let i=-1;return {nextNode(){i++;return i<nodes.length;},get currentNode(){return nodes[i];}};},
    querySelectorAll:()=>[{getAttribute:key=>attrs[key]??null,setAttribute:(key,value)=>attrs[key]=value}]}});
 const i18n=vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/i18n.js'),'utf8')+';I18n',context);
 i18n.init();assert.deepEqual(nodes.map(n=>n.nodeValue),['Theme ','System','Light','Dark']);assert.equal(attrs['aria-label'],'Interface theme');
 assert.equal(i18n.t('\u0421\u0445\u0435\u043c\u0430'),'Flow');
 i18n.setLanguage('ru');assert.deepEqual(nodes.map(n=>n.nodeValue),sources);assert.equal(attrs['aria-label'],sourceAria);
 assert.equal(i18n.t('\u0421\u0445\u0435\u043c\u0430'),'\u0421\u0445\u0435\u043c\u0430');
});
