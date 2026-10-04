const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {JSDOM}=require('jsdom');
const root=path.resolve(__dirname,'..'),read=file=>fs.readFileSync(path.join(root,file),'utf8');
const declaration=read('desktop/DesktopLocale.cs').match(/SnapshotScript = (".*?");/)[1];
const script=JSON.parse(declaration);
for(const [saved,expected] of [['ru','ru'],['en','en'],['unsupported','ru'],[null,'ru']]){
 const d=new JSDOM('<html><body></body></html>',{url:'http://synthetic.invalid/',runScripts:'outside-only'}),w=d.window;
 assert.equal(w.eval(script),null);
 if(saved!==null)w.localStorage.setItem('agentcity-language',saved);
 const before=w.localStorage.getItem('agentcity-language');
 w.eval(read('static/i18n.js')+';globalThis.I18n=I18n;');
 assert.equal(JSON.stringify(w.eval(script)),JSON.stringify({version:1,language:expected}));
 assert.equal(w.localStorage.getItem('agentcity-language'),before);
 w.I18n.setLanguage(expected==='en'?'ru':'en');
 assert.equal(w.eval(script).language,expected==='en'?'ru':'en');
 // Snapshot reads themselves neither persist a value nor dispatch a language event.
 let changes=0;w.document.addEventListener('agentcity-language-change',()=>changes++);
 const stored=w.localStorage.getItem('agentcity-language');w.eval(script);w.eval(script);
 assert.equal(changes,0);assert.equal(w.localStorage.getItem('agentcity-language'),stored);d.window.close();
}
assert.equal(/localStorage|sessionStorage|fetch|cookie|postMessage|chrome|location/.test(script),false);
console.log('PASS read-only snapshot: existing saved RU/EN and app default, live effective language, no storage/network/event writes');
