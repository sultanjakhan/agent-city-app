"""Pure task/run intent contract for two entrances; does not dispatch work."""
import uuid

_NAMESPACE = uuid.UUID('b24cb0d0-f6e8-4abf-88c8-2d25164989c6')


def prepare_intent(origin, task_id, request_id, pipeline_id):
    if origin not in ('cicada', 'agent-city'):
        raise ValueError('Unknown task entrance')
    # UUIDs come from the shared registry/caller; never infer them from a title.
    task = str(uuid.UUID(task_id))
    request = str(uuid.UUID(request_id))
    if not isinstance(pipeline_id, str) or not pipeline_id or len(pipeline_id) > 80:
        raise ValueError('Pipeline reference required')
    return {'schemaVersion':1,'origin':origin,'taskId':task,'requestId':request,
            'pipelineId':pipeline_id,'runId':str(uuid.uuid5(_NAMESPACE,task+':'+request)),
            'status':'prepared','executionSupported':False}


def prepare_pipeline_intent(origin, task_id, request_id, pipeline):
    """Detached immutable snapshot for registry persistence, never a dispatch."""
    import hashlib
    import json
    from pipeline_store import validate
    snapshot = validate(pipeline)
    canonical = json.dumps(snapshot,sort_keys=True,separators=(',',':'),ensure_ascii=False)
    intent = prepare_intent(origin,task_id,request_id,snapshot['id'])
    intent['pipelineSnapshot'] = snapshot
    intent['pipelineSnapshotHash'] = hashlib.sha256(canonical.encode('utf-8')).hexdigest()
    return intent
