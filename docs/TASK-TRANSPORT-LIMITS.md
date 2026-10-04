# Task result transport limits

The task result path accepts UTF-8 JSON frames up to 64 KiB at the HTTP queue,
native agent pipe, MCP bridge, and task gateway boundaries. This limit covers
the complete encoded frame, including JSON structure and the trailing newline;
the task result itself remains bounded by the existing TaskSync validation.

The owner broker and delegated CLI use a 256 KiB trusted internal frame budget
to leave room for envelope and JSON overhead. Ordinary owner control messages
remain limited to 16 KiB. JSON is emitted as UTF-8 without ASCII escaping so
Russian result text does not consume an unnecessary six bytes per character.

Malformed and oversized frames are rejected before dispatch. HTTP handlers close
the connection after an oversized body so its tail cannot become the next
request. Existing host, origin, CSRF, owner-session, grant, scope, and route
allowlist checks remain required.
