param([Parameter(Mandatory = $true)][string]$TestBinary)

$ErrorActionPreference = 'Stop'
$managerRoot = Split-Path $PSScriptRoot -Parent
$repoRoot = Split-Path (Split-Path $managerRoot -Parent) -Parent
$account = 'knutest' + [Guid]::NewGuid().ToString('N').Substring(0, 8)
$password = ConvertTo-SecureString ('Knu!' + [Guid]::NewGuid().ToString('N')) -AsPlainText -Force
$scratch = Join-Path $managerRoot ('.dev\smoke-' + [Guid]::NewGuid().ToString('N'))
$process = $null
$created = $false
$originalAcl = Get-Acl -LiteralPath $repoRoot
$exitCode = 1

# Hosted Windows runners are elevated. PostgreSQL intentionally refuses an
# elevated server. Test the real, unchanged binaries as an ordinary local
# user, without disabling that protection or installing a Windows service.
try {
    $user = New-LocalUser -Name $account -Password $password -AccountNeverExpires
    $created = $true
    $users = Get-LocalGroup -SID 'S-1-5-32-545'
    Add-LocalGroupMember -Group $users -Member $user

    $acl = Get-Acl -LiteralPath $repoRoot
    $acl.AddAccessRule([System.Security.AccessControl.FileSystemAccessRule]::new(
        $user.SID, 'ReadAndExecute', 'ContainerInherit,ObjectInherit', 'None', 'Allow'))
    Set-Acl -LiteralPath $repoRoot -AclObject $acl
    $null = New-Item -ItemType Directory -Path $scratch
    $scratchAcl = Get-Acl -LiteralPath $scratch
    $scratchAcl.AddAccessRule([System.Security.AccessControl.FileSystemAccessRule]::new(
        $user.SID, 'Modify', 'ContainerInherit,ObjectInherit', 'None', 'Allow'))
    Set-Acl -LiteralPath $scratch -AclObject $scratchAcl

    $info = [System.Diagnostics.ProcessStartInfo]::new()
    $info.FileName = (Resolve-Path -LiteralPath $TestBinary).Path
    $info.Arguments = 'native_development_smoke --ignored --nocapture'
    $info.WorkingDirectory = $managerRoot
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.UserName = $account
    $info.Domain = '.'
    $info.Password = $password
    $info.LoadUserProfile = $true
    $info.EnvironmentVariables['TEMP'] = $scratch
    $info.EnvironmentVariables['TMP'] = $scratch
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $info.StandardOutputEncoding = [System.Text.Encoding]::UTF8
    $info.StandardErrorEncoding = [System.Text.Encoding]::UTF8
    $process = [System.Diagnostics.Process]::Start($info)
    $stdout = $process.StandardOutput.ReadToEndAsync()
    $stderr = $process.StandardError.ReadToEndAsync()
    if (-not $process.WaitForExit(180000)) {
        $process.Kill($true)
        $process.WaitForExit()
        throw 'Unprivileged native smoke timed out; its process tree was stopped.'
    }
    Write-Output $stdout.GetAwaiter().GetResult()
    Write-Output $stderr.GetAwaiter().GetResult()
    $exitCode = $process.ExitCode
} finally {
    if ($null -ne $process) {
        if (-not $process.HasExited) { $process.Kill($true); $process.WaitForExit() }
        $process.Dispose()
    }
    Set-Acl -LiteralPath $repoRoot -AclObject $originalAcl
    if (Test-Path -LiteralPath $scratch) { Remove-Item -LiteralPath $scratch -Recurse -Force }
    if ($created) { Remove-LocalUser -Name $account }
    $password.Dispose()
}
exit $exitCode
