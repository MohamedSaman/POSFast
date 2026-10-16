; Inno Setup Script for FastPOS Premium Desktop Terminal
#define MyAppName "FastPOS Premium"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "FastPOS"
#define MyAppExeName "FastPOS.exe"

[Setup]
AppId={{A784C512-421D-47C1-87F9-5C3D2E8B9912}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\FastPOS
PrivilegesRequiredOverridesAllowed=commandline dialog
DisableProgramGroupPage=yes
OutputDir=dist
OutputBaseFilename=FastPOS_Setup_v1.0
Compression=lzma
SolidCompression=yes
WizardStyle=modern
SetupIconFile=icon.ico

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "dist\FastPOS\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "icon.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "pos_default.db"; DestDir: "{app}"; DestName: "pos_local.db"; Flags: ignoreversion onlyifdoesntexist

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\icon.ico"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\icon.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
