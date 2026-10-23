const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const scope={};vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../static/passive-attempt-view.js'),'utf8'),scope);
const view=scope.PassiveAttemptView,now=Date.parse('2026-01-01T10:01:00Z');
test('bound running elapsed is labelled and completed unknown duration is never synthesized',()=>{
 const stage={attemptBinding:{readOnly:true},status:'running',startedAt:'2026-01-01T10:00:00Z',endedAt:null,durationMs:null,usage:{total:null}};
 assert.match(view.stageMetrics(stage,String,String,now),/Unknown tokens.*60000.*running elapsed.*not completed duration/);
 stage.status='completed';stage.endedAt='2026-01-01T10:01:00Z';
 assert.equal(view.stageTiming(stage,now).value,null);
 assert.match(view.stageMetrics(stage,String,String,now),/Unknown.*duration unknown/);
 stage.durationMs=321;assert.match(view.stageMetrics(stage,String,String,now),/321.*collector-reported duration/);
 assert.equal(view.stageTiming({durationMs:999},now),null);
});
