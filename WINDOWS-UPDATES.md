# Windows installation and updates

The native Windows application uses one stable executable path and an external
private storage pointer. Repeated launches focus the existing window for the
same profile and mode. Recovery and update commands are in the title-bar icon
menu (Alt+Space); there is no separate application menu row.

The update service checks at startup and every six hours. It never opens a
browser, terminal or second application window. A newer release is downloaded
and staged while the app runs. The bottom status line shows that it is ready.
After the owner closes the app and its backend drains, an external helper
replaces the package at the same path. The next launch uses the new version.

## Channel

`updates-channel.json` lives beside the private `connection.json`, outside the
repository and installation package. A public GitHub channel needs no account,
GitHub CLI or token on the receiving computer:

```json
{"kind":"github","repository":"sultanjakhan/agent-city-app"}
```

For offline acceptance or a local release folder:

```json
{"kind":"local","path":"C:/release-folder"}
```

Every release must contain `latest.json`, its detached base64 RSA/SHA256
signature `latest.json.sig`, and the named Windows ZIP. The compiled application
pins the public signing key. The ZIP hash and inventory must match, and both
staging and installation verify their contents before running the host self-test.
Invalid packages leave the current installation intact.

Settings, credentials and activity remain in external storage. The private
installation pointer, uninstaller and local receipt are preserved during the
swap. The exact previous installation is retained under the external update
directory for recovery. Processes are never force-killed. If files prevent
restoration, the update records failure and keeps the previous package for
recovery; it does not claim that rollback succeeded.

## Maintainer release

Build an exact clean source commit using `tools/build_desktop.py`. Package and
sign its public inventory using PowerShell 7:

```powershell
./tools/New-AgentCityUpdate.ps1 -Candidate C:/build/candidate -OutputDirectory C:/releases/new-version
```

The signing key is an encrypted DPAPI file outside Git, bound to the maintainer's
Windows account. Its public counterpart is in `desktop/UpdateTrust.cs`. Do not
replace the key for every release. Publish the three generated assets together
on a versioned GitHub Release. A source commit without a Release does not update
installed apps.

The updater authenticates releases independently of Windows Authenticode.
The current executable has not been signed with a Windows publisher certificate.
This implementation covers Windows; macOS installation/update acceptance is
separate. Application source is MIT licensed; dependency notices remain applicable.
