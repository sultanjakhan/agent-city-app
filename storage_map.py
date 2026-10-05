"""Owner-visible storage locations; never return file contents or access keys."""


def snapshot(store):
    locations = [
        ("Tasks", "Cicada", None),
        ("Executions", "Agent City", store.runs.path),
        ("Processes", "Agent City", store.pipelines.path),
        ("Standards", "Agent City", store.standards.catalog_path),
        ("Project standards", "Agent City", store.standards.path),
        ("Project profiles", "Agent City", store.repo_profiles.path),
        ("Global rules", "Agent City", store.rules.global_path),
        ("Source bindings", "Agent City", store.data_sources.path),
    ]
    connector = store.cicada.settings()
    selected = next((item for item in connector["candidates"] if item["id"] == connector["selectedId"]), None)
    items = [{"name": name, "owner": owner, "path": str(path) if path else None,
              "exists": path.is_file() if path else False} for name, owner, path in locations]
    if selected:
        items[0].update(path=selected["path"], exists=selected.get("exists"), sourceId=selected["id"])
    return {"schemaVersion": 1, "dataDirectory": str(store.directory), "locations": items}
