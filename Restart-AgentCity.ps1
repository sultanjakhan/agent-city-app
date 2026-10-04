# A fresh shell has no inherited owner authority; delegate the action to the
# already-running native controller. Never infer ownership from HTTP, PID or title.
[CmdletBinding(SupportsShouldProcess = $true)]
param()
$ErrorActionPreference = 'Stop'
Write-Output 'Use Restart owned child in the existing Agent City owner controller after saving or closing browser drafts.'
Write-Output 'This helper did not discover, stop, start or authorize any server. If its controller is gone, perform explicit owner recovery.'
if ($WhatIfPreference) { return }
exit 3
