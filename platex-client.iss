#define MyAppName "PLatex Client"
#define MyAppVersion "1.0.4"
#define MyAppPublisher "AliceAuto"
#define MyAppExeName "platex-client.exe"

[Setup]
AppId={{7A4F0E14-8F6A-4C49-BE56-7C0D8E8C1A3C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\PLatexClient
DisableDirPage=no
DisableProgramGroupPage=yes
OutputDir=dist\installer
OutputBaseFilename=PLatexClient-1.0.4-win64-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile=assets\platex-client.ico

[Code]
var
  ConfigDirPage: TInputDirWizardPage;

procedure InitializeWizard;
begin
  ConfigDirPage := CreateInputDirPage(wpSelectDir,
    '选择配置目录', '配置文件存储位置',
    '选择 PLatex Client 存储配置、历史记录和日志的目录。' + #13#10 +
    '如果不确定，请使用默认路径。',
    False, '');
  ConfigDirPage.Add('');
  ConfigDirPage.Values[0] := ExpandConstant('{userappdata}\PLatexClient');
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  RegKey: string;
  ConfigDir: string;
begin
  if CurStep = ssPostInstall then
  begin
    ConfigDir := ConfigDirPage.Values[0];
    if ConfigDir <> '' then
    begin
      RegKey := 'Software\PLatexClient';
      RegWriteStringValue(HKCU, RegKey, 'ConfigDir', ConfigDir);
      ForceDirectories(ConfigDir);
      ForceDirectories(ConfigDir + '\logs');
    end;
  end;
end;

function GetConfigDir(Param: string): string;
begin
  Result := ConfigDirPage.Values[0];
end;

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"; Flags: unchecked

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Files]
Source: "dist\platex-client\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "config.example.yaml"; DestDir: "{app}"; Flags: ignoreversion