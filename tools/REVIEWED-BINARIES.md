# Reviewed public binary assets

`verify_separation.py` retains its private-path, credential-format and text scans. The source tree's public ICO image may pass the binary check only when its relative path and SHA256 exactly match `reviewed-binaries.json`, its ICO signature matches, and its baseline/review evidence is present. The current icon was independently viewed and compared byte-for-byte with public base `d3aafd700e4b832f415a18311431d1c75453d8e3`.

Changed hashes, unlisted binaries, invalid manifests and redirected files fail closed. A manifest entry does not override private-directory/private-file detection. New reviewed assets require explicit source review and evidence; no wildcard or extension-wide approval is supported.
