"""Declarative policy metadata; never grants or enforces runtime access."""
import re

class PolicyValidationError(ValueError):
    pass

_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}$")

def ids(value, field):
    if not isinstance(value, list) or len(value) > 100 or any(not isinstance(x, str) or not _ID.fullmatch(x) for x in value):
        raise PolicyValidationError(f"{field} must contain at most 100 reference IDs")
    if len(set(value)) != len(value):
        raise PolicyValidationError(f"{field} contains duplicate IDs")
    return list(value)

def validate_policy(value):
    fields = {"schemaVersion", "instructions", "sourceIds", "allowedActions", "deniedActions", "defaultPipelineId"}
    if not isinstance(value, dict) or set(value) - fields or type(value.get("schemaVersion")) is not int or value["schemaVersion"] != 1:
        raise PolicyValidationError("invalid project policy schema")
    instructions = value.get("instructions", "")
    if not isinstance(instructions, str) or len(instructions) > 16000:
        raise PolicyValidationError("instructions must be text up to 16000 characters")
    pipeline = value.get("defaultPipelineId")
    if pipeline is not None and (not isinstance(pipeline, str) or not _ID.fullmatch(pipeline)):
        raise PolicyValidationError("defaultPipelineId must be a reference ID or null")
    return {"schemaVersion": 1, "instructions": instructions,
            **{key: ids(value.get(key, []), key) for key in ("sourceIds", "allowedActions", "deniedActions")},
            "defaultPipelineId": pipeline}

def preview_policy(project, pipeline=None, stage=None):
    """Omitted child fields inherit; empty lists deny all. Conflicts stay visible."""
    policy = validate_policy(project)
    allowed = set(policy["allowedActions"])
    denied = set(policy["deniedActions"])
    sources = set(policy["sourceIds"])
    conflicts = []
    def report(scope, field, values):
        for value in sorted(values):
            conflicts.append({"scope": scope, "field": field, "id": value})
    report("project", "allowedActions", allowed & denied)
    allowed -= denied
    for scope, layer in (("pipeline", pipeline), ("stage", stage)):
        if layer is None:
            continue
        if not isinstance(layer, dict) or set(layer) - {"sourceIds", "allowedActions", "deniedActions"}:
            raise PolicyValidationError(f"invalid {scope} restrictions")
        child_denied = set(ids(layer.get("deniedActions", []), "deniedActions"))
        if "allowedActions" in layer:
            requested = set(ids(layer["allowedActions"], "allowedActions"))
            report(scope, "allowedActions", requested - allowed | requested & child_denied)
            allowed &= requested
        if "sourceIds" in layer:
            requested = set(ids(layer["sourceIds"], "sourceIds"))
            report(scope, "sourceIds", requested - sources)
            sources &= requested
        denied |= child_denied
        allowed -= denied
    return {"allowedActions": sorted(allowed), "deniedActions": sorted(denied),
            "sourceIds": sorted(sources), "conflicts": conflicts,
            "actualSupport": "declarative-preview-only", "runtimeEnforced": False}
