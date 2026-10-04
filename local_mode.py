"""No profile access or background transport in explicitly local-only mode."""
class LocalOnlyCloud:
    remote = ()

    def __init__(self, *args, **kwargs):
        pass

    def status(self):
        return {"configured": None, "state": "paused", "error": None, "endpoint": None,
                "device": None, "lastSync": None, "notice": "Cloud operations are disabled in local-only mode."}

    def start(self):
        pass

    def sync(self):
        raise RuntimeError("Cloud operations are disabled in local-only mode")

    def configure(self, value):
        raise RuntimeError("Cloud operations are disabled in local-only mode")
