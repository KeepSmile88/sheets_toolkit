[Setup]
; 应用基础信息
AppName=SheetsToolkit
AppVersion=2.0.3
AppPublisher=KeepSmile88
AppSupportURL=https://github.com/KeepSmile88/sheets_toolkit

; 默认安装位置和压缩属性
DefaultDirName=C:\software\SheetsToolkit
DefaultGroupName=SheetsToolkit
OutputDir=dist
OutputBaseFilename=SheetsToolkit-Windows-Setup
Compression=lzma
SolidCompression=yes

; 权限：最低权限，允许未授权用户仅为自己安装，或者普通标准模式
PrivilegesRequired=lowest

; 图标路径设置
SetupIconFile=resources\main.ico
UninstallDisplayIcon={app}\SheetsToolkit.exe



[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; 这里的相对路径是相对于运行 iscc 所在的目录（我们会在根目录执行，所以填 dist/SheetsToolkit/*）
Source: "dist\SheetsToolkit\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; 包含根目录下的说明文件如果有的话
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; 开始菜单快捷方式
Name: "{group}\SheetsToolkit"; Filename: "{app}\SheetsToolkit.exe"; IconFilename: "{app}\resources\main.ico"
Name: "{group}\{cm:UninstallProgram,SheetsToolkit}"; Filename: "{uninstallexe}"
; 桌面快捷方式
Name: "{autodesktop}\SheetsToolkit"; Filename: "{app}\SheetsToolkit.exe"; Tasks: desktopicon; IconFilename: "{app}\resources\main.ico"

[Run]
Filename: "{app}\SheetsToolkit.exe"; Description: "{cm:LaunchProgram,SheetsToolkit}"; Flags: nowait postinstall skipifsilent
