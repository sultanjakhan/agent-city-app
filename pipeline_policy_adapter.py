"""Read-only adapter to fc5a51a RepoProfiles / project_policy.preview_policy.

No policy storage, defaults, permission grants or independent policy validator.
Dependencies are passed explicitly so this patch can precede the policy patch.
"""
from pipeline_store import preview


def preview_repository_pipeline(pipeline, repo_profiles, preview_policy,
                                pipeline_restrictions=None, stage_restrictions=None,
                                model_ids=(), skill_ids=()):
    result = preview(pipeline, model_ids=model_ids, skill_ids=skill_ids)
    # projectId is an existing repository ID, validated by RepoProfiles.read.
    profile = repo_profiles.read(pipeline['projectId'])
    result['projectPolicyRevision'] = profile['revision']
    policy = profile.get('policy')
    result['projectPolicySource'] = 'repository-profiles.json'
    result['projectBudgetSupport'] = 'unknown'
    result['warnings'].append('Project policy fc5a51a has no budget fields; project budget ceiling is unknown.')
    if policy is None:
        result['projectPolicy'] = None
        result['warnings'].append('No saved project policy; no action/source authorization inferred.')
        return result
    restrictions = stage_restrictions or {}
    if not isinstance(restrictions, dict) or set(restrictions) - {s['id'] for s in pipeline['stages']}:
        raise ValueError('Unknown stage restriction ID')
    policy_result = preview_policy(policy, pipeline_restrictions)
    stages = {s['id']:preview_policy(policy,pipeline_restrictions,restrictions.get(s['id'])) for s in pipeline['stages']}
    result['projectPolicy'] = {'pipeline':policy_result,'stages':stages}
    result['conflicts'].extend(policy_result['conflicts'])
    for scope, stage_result in stages.items():
        result['conflicts'].extend({**c,'stageId':scope} for c in stage_result['conflicts'])
    return result
