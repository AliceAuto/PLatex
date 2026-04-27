#define MyAppName "PLatex Client"
#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif
#define MyAppPublisher "AliceAuto"
#define MyAppExeName "platex-client.exe"
#define ConfigSubDir "PLatexClient"

[Setup]
AppId={{7A4F0E14-8F6A-4C49-BE56-7C0D8E8C1A3C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\PLatexClient
DisableDirPage=no
DisableProgramGroupPage=yes
OutputDir=dist\installer
OutputBaseFilename=PLatexClient-{#MyAppVersion}-win64-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile=assets\platex-client.ico

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Registry]
Root: HKCU; Subkey: "Software\PLatexClient"; ValueType: string; ValueName: "InstallDir"; ValueData: "{app}"; Flags: createvalueifdoesntexist uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\PLatexClient"; ValueType: string; ValueName: "ConfigDir"; ValueData: "{userappdata}\{#ConfigSubDir}"; Flags: createvalueifdoesntexist uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\PLatexClient"; ValueType: string; ValueName: "Version"; ValueData: "{#MyAppVersion}"; Flags: uninsdeletekeyifempty

[UninstallDelete]

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startupicon"; Description: "开机自动启动"; GroupDescription: "附加任务:"; Flags: unchecked

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[Files]
Source: "dist\platex-client\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion; Check: FileExists(ExpandConstant('{src}\README.md'))
Source: "config.example.yaml"; DestDir: "{app}"; Flags: ignoreversion onlyifdoesntexist; Check: FileExists(ExpandConstant('{src}\config.example.yaml'))

[Code]
function GetConfigDir: string;
var
  ConfigDir: string;
begin
  if RegQueryStringValue(HKCU, 'Software\PLatexClient', 'ConfigDir', ConfigDir) and (ConfigDir <> '') then
    Result := ConfigDir
  else
    Result := ExpandConstant('{userappdata}\{#ConfigSubDir}');
end;

function IsUpgrade: Boolean;
var
  PrevVersion: string;
begin
  Result := RegQueryStringValue(HKCU, 'Software\PLatexClient', 'Version', PrevVersion) and (PrevVersion <> '');
end;

procedure BackupUserConfig;
var
  ConfigDir, BackupDir, ConfigFile, SrcFile: string;
  FindRec: TFindRec;
begin
  ConfigDir := GetConfigDir;

  if not DirExists(ConfigDir) then
    Exit;

  ConfigFile := ConfigDir + '\config.yaml';
  if not FileExists(ConfigFile) then
    Exit;

  BackupDir := ConfigDir + '\backups\' + GetDateTimeString('yyyy-mm-dd_hh-nn-ss', '-', ':');

  if not ForceDirectories(BackupDir) then
  begin
    Log('BackupUserConfig: Failed to create backup directory: ' + BackupDir);
    Exit;
  end;

  if FileExists(ConfigFile) then
  begin
    if not FileCopy(ConfigFile, BackupDir + '\config.yaml') then
      Log('BackupUserConfig: Failed to backup config.yaml')
    else
      Log('BackupUserConfig: Backed up config.yaml to ' + BackupDir);
  end;

  if DirExists(ConfigDir + '\scripts') then
  begin
    if not ForceDirectories(BackupDir + '\scripts') then
      Log('BackupUserConfig: Failed to create scripts backup directory')
    else if FindFirst(ConfigDir + '\scripts\*', FindRec) then
    begin
      try
        repeat
          if (FindRec.Name <> '.') and (FindRec.Name <> '..') then
          begin
            SrcFile := ConfigDir + '\scripts\' + FindRec.Name;
            if not FileCopy(SrcFile, BackupDir + '\scripts\' + FindRec.Name) then
              Log('BackupUserConfig: Failed to backup script config: ' + FindRec.Name)
            else
              Log('BackupUserConfig: Backed up script config: ' + FindRec.Name);
          end;
        until not FindNext(FindRec);
      finally
        FindClose(FindRec);
      end;
    end;
  end;

  Log('BackupUserConfig: Backup completed to ' + BackupDir);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
  begin
    if IsUpgrade then
    begin
      Log('CurStepChanged: Upgrade detected, backing up user config...');
      BackupUserConfig;
    end;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ConfigDir: string;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    ConfigDir := GetConfigDir;
    if DirExists(ConfigDir) then
    begin
      if MsgBox('是否保留配置文件和历史数据？', mbConfirmation, MB_YESNO) = IDNO then
      begin
        if DelTree(ConfigDir, True, True, True) then
          Log('CurUninstallStepChanged: Removed config directory: ' + ConfigDir)
        else
          Log('CurUninstallStepChanged: Failed to remove config directory: ' + ConfigDir);
      end
      else
        Log('CurUninstallStepChanged: User chose to keep config directory: ' + ConfigDir);
    end;
  end;
end;
