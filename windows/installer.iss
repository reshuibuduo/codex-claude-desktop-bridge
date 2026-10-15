#ifndef AppVersion
  #error AppVersion must be supplied by the release script
#endif
[Setup]
AppId={{5E8DCB9D-A77E-47BD-B06B-BB3856CD6626}
AppName=Codex Claude Bridge
AppVersion={#AppVersion}
AppPublisher=Codex Claude Bridge contributors
AppPublisherURL=https://github.com/reshuibuduo/codex-claude-desktop-bridge
DefaultDirName={localappdata}\Programs\Codex Claude Bridge
DefaultGroupName=Codex Claude Bridge
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19045
UninstallDisplayIcon={app}\CodexClaudeBridge.exe
OutputDir=..\dist\release
OutputBaseFilename=Codex-Claude-Bridge-{#AppVersion}-Windows-x64-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
LicenseFile=..\LICENSE
[Files]
Source: "..\dist\Codex Claude Bridge\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\Codex Claude Bridge"; Filename: "{app}\CodexClaudeBridge.exe"
Name: "{group}\Uninstall Codex Claude Bridge"; Filename: "{uninstallexe}"
[Run]
Filename: "{app}\CodexClaudeBridge.exe"; Description: "Launch Codex Claude Bridge"; Flags: nowait postinstall skipifsilent
[UninstallRun]
Filename: "{app}\CodexClaudeBridge.exe"; Parameters: "--pause"; Flags: runhidden waituntilterminated; RunOnceId: "PauseBinding"
; No config/project deletion. Restore project MCP with its installation manifest before uninstalling.
