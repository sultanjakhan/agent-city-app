param([Int64]$Window,[int]$OwnerPID)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$root=[System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]$Window)
if($root.Current.ProcessId -ne $OwnerPID){throw 'Owned window changed'}
$all=$root.FindAll([System.Windows.Automation.TreeScope]::Subtree,[System.Windows.Automation.Condition]::TrueCondition)
$title=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('0KHQtdGB0YHQuNGPIEFnZW50IENpdHkg0L3QtdC00L7RgdGC0YPQv9C90LA='))
$modelRU=[string]([char]0x041c)+[char]0x043e+[char]0x0434+[char]0x0435+[char]0x043b+[char]0x0438
$blocked=$false;$model=$null
foreach($item in $all){
 try{
  $name=$item.Current.Name
  if($name -eq $title){$blocked=$true}
  if(($name -eq 'Models' -or $name -eq $modelRU) -and -not $model){$model=$item}
 }catch{}
}
$runtime=@();if($model){$runtime=@($model.GetRuntimeId())}
[pscustomobject]@{authDialogVisible=$blocked;modelMenuVisible=[bool]$model;controlCount=$all.Count;modelRuntimeId=$runtime}|ConvertTo-Json -Compress
