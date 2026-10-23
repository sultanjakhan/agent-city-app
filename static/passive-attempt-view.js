'use strict';
// Embedded into the frozen renderer by the exact integration patch; no DOM rebuild.
(function(root){
 const known=value=>Number.isSafeInteger(value)&&value>=0;
 function stageTiming(stage,now=Date.now()){
  if(!stage?.attemptBinding)return null;
  if(known(stage.durationMs))return {value:stage.durationMs,label:stage.durationSource==='derived-from-observed-turn-bounds'?'duration derived from observed turn bounds':'collector-reported duration'};
  const start=Date.parse(stage.startedAt||'');
  if(stage.status==='working'&&!stage.endedAt&&Number.isFinite(start)&&start<=now)
   return {value:now-start,label:'running elapsed · derived from observed start; not completed duration'};
  return {value:null,label:'duration unknown'};
 }
 function stageMetrics(stage,formatNumber,formatDuration,now=Date.now()){
  const timing=stageTiming(stage,now);if(!timing)return null;
  const tokens=stage.usage?.total;
  return `${known(tokens)?formatNumber(tokens):'Unknown'} tokens · ${timing.value===null?'Unknown':formatDuration(timing.value)}`;
 }
 function patchMetrics(item,metricNode,formatNumber,formatDuration,text,formatDateTime,now=Date.now()){
  const timing=stageTiming(item,now);if(!timing)return false;
  const count=value=>known(value)?formatNumber(value):'Unknown',usage=item.usage||{};
  const time=metricNode('time');time.querySelector('.ls-metric-value').textContent=timing.value===null?'Unknown':formatDuration(timing.value);
  time.querySelector('.ls-metric-note').textContent=timing.label+(item.startedAt?` · Started ${formatDateTime(item.startedAt)}`:'');
  const tokens=metricNode('tokens');tokens.querySelector('.ls-metric-value').textContent=count(usage.total);
  tokens.querySelector('.ls-metric-note').textContent=`Input ${count(usage.input)} · Output ${count(usage.output)}`+
   (known(usage.cachedInput)?` · Cached input ${count(usage.cachedInput)}`:'')+(known(usage.reasoningOutput)?` · Reasoning output ${count(usage.reasoningOutput)}`:'');
  const model=metricNode('model');model.querySelector('.ls-metric-value').textContent=item.model?text(item.model):'Unknown';
  model.querySelector('.ls-metric-note').textContent=`Effort · ${item.effort?text(item.effort):'Unknown'} · exact bound turn`;
  return true;
 }
 root.PassiveAttemptView=Object.freeze({stageTiming,stageMetrics,patchMetrics});
})(globalThis);
