; Inno Setup script for Aeronis.
; Produces a proper installer (Start Menu shortcut, optional desktop
; shortcut, uninstaller) from the PyInstaller one-folder build.
;
; Usage (after `pyinstaller desktop.spec` has produced dist\Aeronis):
;   iscc packaging\windows_installer.iss
;
; Output: dist_installer\Aeronis-Setup.exe

#define AppName "Aeronis"
#define AppVersion "0.3.0"
#define AppExeName "Aeronis.exe"

[Setup]
AppName={#AppName}
AppVersion={#AppVersion}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\dist_installer
OutputBaseFilename=Aeronis-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\{#AppExeName}
; No admin rights required — installs to the current user's local app
; data if the user isn't an administrator, Program Files otherwise.
PrivilegesRequired=lowest

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Files]
Source: "..\dist\Aeronis\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
