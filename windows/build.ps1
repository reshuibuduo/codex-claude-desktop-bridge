$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = Split-Path -Parent $PSScriptRoot
$app = Join-Path $root 'dist\Codex Claude Bridge'
if (Test-Path $app) { Remove-Item -Recurse -Force $app }
$runtime = Join-Path $app 'Resources\runtime'
New-Item -ItemType Directory -Force (Join-Path $runtime 'bridge') | Out-Null
$csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (!(Test-Path $csc)) { throw '.NET Framework C# compiler missing on build machine' }
& $csc /nologo /target:winexe /platform:x64 /optimize+ /utf8output /codepage:65001 "/out:$app\CodexClaudeBridge.exe" /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.Web.Extensions.dll (Join-Path $PSScriptRoot 'TrayApp.cs')
if ($LASTEXITCODE -ne 0) { throw 'C# compilation failed' }
Copy-Item (Join-Path $root 'bridge_core.py') $runtime
Copy-Item (Join-Path $root 'bridge\*.py') (Join-Path $runtime 'bridge')
python (Join-Path $root 'scripts\prepare_runtime.py') --arch windows-x64 --destination (Join-Path $app 'Resources\python')
if ($LASTEXITCODE -ne 0) { throw 'Embedded Python build failed' }
Copy-Item (Join-Path $root 'LICENSE') (Join-Path $app 'Resources')
Copy-Item -Recurse (Join-Path $root 'licenses') (Join-Path $app 'Resources')
Copy-Item (Join-Path $root 'menu\python-runtime.lock.json') (Join-Path $app 'Resources')
Copy-Item (Join-Path $root 'docs\INSTALL-WINDOWS.txt') (Join-Path $app 'INSTALL.txt')
Write-Output 'WINDOWS_BUILD_OK arch=x64 python=embedded authenticode=false'
