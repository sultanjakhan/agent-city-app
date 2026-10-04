"""Local counters, not inferred agent telemetry. No prompts or task content."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile
import threading


class ActivityError(ValueError):
    pass


class SkillActivity:
    def __init__(self, directory):
        self.directory = Path(directory).absolute()
        self.pinned_directory = self.directory.resolve()
        self.path = self.directory / 'skill-activity.json'
        self.lock = threading.RLock()

    def _validate_path(self):
        if self.directory.resolve() != self.pinned_directory:
            raise ActivityError('activity directory changed')
        if self.path.is_symlink() or (self.path.exists() and getattr(self.path.lstat(), 'st_file_attributes', 0) & 0x400):
            raise ActivityError('invalid activity storage')

    def snapshot(self):
        self._validate_path()
        if not self.path.exists():
            return {'schemaVersion': 1, 'startedAt': None, 'skills': {}}
        if self.path.is_symlink() or self.path.stat().st_size > 2 * 1024 * 1024:
            raise ActivityError('invalid activity storage')
        with self.path.open('rb') as stream:
            value = json.loads(stream.read(2 * 1024 * 1024 + 1))
        if not isinstance(value, dict) or value.get('schemaVersion') != 1 or not isinstance(value.get('skills'), dict):
            raise ActivityError('invalid activity format')
        return value

    def record(self, skill_id, kind, agent='user', event_id=None):
        if not isinstance(skill_id, str) or not re.fullmatch(r'skill-[a-f0-9]{24}', skill_id):
            raise ActivityError('unknown skill id')
        if kind not in {'view', 'use'} or agent not in {'user', 'codex', 'claude', 'other'}:
            raise ActivityError('unknown activity kind')
        if event_id is not None and (not isinstance(event_id, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{8,100}', event_id)):
            raise ActivityError('invalid event id')
        with self.lock:
            data = self.snapshot()
            stamp = datetime.now(timezone.utc).isoformat(timespec='seconds')
            data['startedAt'] = data['startedAt'] or stamp
            row = data['skills'].setdefault(skill_id, {'views': 0, 'reportedUses': 0, 'lastViewedAt': None, 'lastUsedAt': None, 'recentEventIds': []})
            if event_id and event_id in row['recentEventIds']:
                return data
            if kind == 'view':
                row['views'] += 1
                row['lastViewedAt'] = stamp
            else:
                row['reportedUses'] += 1
                row['lastUsedAt'] = stamp
                row['lastReporter'] = agent
            if event_id:
                row['recentEventIds'] = (row['recentEventIds'] + [event_id])[-100:]
            encoded = json.dumps(data, ensure_ascii=False).encode('utf-8')
            if len(encoded) > 2 * 1024 * 1024:
                raise ActivityError('activity storage limit reached')
            self._validate_path()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(dir=self.path.parent, prefix='.activity-')
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(encoded)
                    stream.flush()
                    os.fsync(stream.fileno())
                self._validate_path()
                os.replace(temporary, self.path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            return data
