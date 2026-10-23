const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const scope={};vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../static/passive-attempt-view.js'),'utf8'),scope);
const view=scope.PassiveAttemptView,now=Date.parse('2026-01-01T10:01:00Z');
test('bound running elapsed is labelled and completed unknown duration is never synthesized',()=>{
 const stage={attemptBinding:{readOnly:true},status:'working',startedAt:'2026-01-01T10:00:00Z',endedAt:null,durationMs:null,usage:{total:null}};
 assert.equal(view.stageMetrics(stage,String,String,now),'Unknown tokens · 60000');
 assert.match(view.stageTiming(stage,now).label,/running elapsed.*not completed duration/);
 stage.status='completed';stage.endedAt='2026-01-01T10:01:00Z';
 assert.equal(view.stageTiming(stage,now).value,null);
 assert.equal(view.stageMetrics(stage,String,String,now),'Unknown tokens · Unknown');
 assert.equal(view.stageTiming(stage,now).label,'duration unknown');
 stage.durationMs=321;assert.equal(view.stageMetrics(stage,String,String,now),'Unknown tokens · 321');
 assert.equal(view.stageTiming(stage,now).label,'collector-reported duration');
 stage.usage.total=0;assert.equal(view.stageMetrics(stage,String,String,now),'0 tokens · 321');
 stage.durationMs=0;assert.equal(view.stageMetrics(stage,String,String,now),'0 tokens · 0');
 assert.equal(view.stageTiming({durationMs:999},now),null);
});
test('patchMetrics uses the bound row only and preserves unbound rendering path',()=>{
 const nodes={};
 const metricNode=key=>nodes[key]??=( {value:{},note:{},querySelector(selector){return selector==='.ls-metric-value'?this.value:this.note;}} );
 const item={attemptBinding:{},status:'working',startedAt:'2026-01-01T10:00:00.000000Z',endedAt:null,durationMs:null,model:'turn-model',effort:'turn-effort',usage:{input:7,output:null,total:null,cachedInput:2}};
 assert.equal(view.patchMetrics(item,metricNode,String,String,String,String,now),true);
 assert.equal(nodes.tokens.value.textContent,'Unknown');assert.match(nodes.tokens.note.textContent,/Input 7.*Output Unknown.*Cached input 2/);
 assert.equal(nodes.model.value.textContent,'turn-model');assert.match(nodes.model.note.textContent,/turn-effort.*exact bound turn/);
 assert.match(nodes.time.note.textContent,/running elapsed.*not completed duration/);
 assert.equal(view.patchMetrics({model:'unbound',usage:{total:999}},metricNode,String,String,String,String,now),false);
});
