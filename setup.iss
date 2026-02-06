[Setup]
AppName=Task Tracker
AppVersion=1.0.5
AppPublisher=Nathan Turner
DefaultDirName={autopf}\Task Tracker
DefaultGroupName=Task Tracker
OutputDir=dist-installer
OutputBaseFilename=TaskTrackerSetup-1.0.5
Compression=lzma2
SolidCompression=yes
SetupIconFile=hourglass.ico
UninstallDisplayIcon={app}\timesheet.exe
DisableDirPage=no
DisableProgramGroupPage=no

[Files]
Source: "dist\timesheet\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Task Tracker"; Filename: "{app}\timesheet.exe"
Name: "{commondesktop}\Task Tracker"; Filename: "{app}\timesheet.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Run]
Filename: "{app}\timesheet.exe"; Description: "Launch Task Tracker"; Flags: nowait postinstall skipifsilent
