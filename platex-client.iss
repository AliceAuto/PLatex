#define MyAppName "PLatex Client"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "AliceAuto"
#define MyAppExeName "platex-client.exe"
#define MyAppScriptName "glm_vision_ocr.py"

[Setup]
AppId={{7A4F0E14-8F6A-4C49-BE56-7C0D8E8C1A3C}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\PLatexClient
DisableDirPage=no
DisableProgramGroupPage=yes
OutputDir=dist\installer
OutputBaseFilename=PLatexClient-0.1.0-win64-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64
UninstallDisplayIcon={app}\{#MyAppExeName}

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "scripts\{#MyAppScriptName}"; DestDir: "{app}\scripts"; Flags: ignoreversion
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "config.example.yaml"; DestDir: "{app}"; Flags: ignoreversion
