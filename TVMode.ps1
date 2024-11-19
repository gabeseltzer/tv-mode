# requires https://github.com/frgnca/AudioDeviceCmdlets
# requires http://www.nirsoft.net/utils/multi_monitor_tool.html
Add-Type -AssemblyName PresentationCore,PresentationFramework
$allAudio = Get-AudioDevice -List

# foreach ($audioDevice in $allAudio){
#   Write-Host $audioDevice.name
#   if ($audioDevice.name -eq "Realtek HD Audio 2nd output (Realtek(R) Audio)") {
#     Write-Host "ladies and gentlemen, we got 'em"
#   }
# }
# WOW I MADE A CHANGE TO PUT IN A PR!!!

$headphoneName = "Realtek HD Audio 2nd output (Realtek(R) Audio)"
$speakerName = "Realtek Digital Output (Realtek(R) Audio)"

$headphonesExist = ($allAudio.name -contains $headphoneName)
$speakersExist = ($allAudio.name -contains $speakerName)

if (-Not $headphonesExist -Or -Not $speakersExist) {
  $errorText = "Something went wrong!"
  if (-Not $headphonesExist) {
    $errorText = "$errorText `nHeadphone device is missing!`nIt should be called $headphoneName"
  }
  if (-Not $speakersExist) {
    $errorText = "$errorText `nSpeaker device is missing!`nIt should be called $speakerName"
  }
  $errorText = 
  [System.Windows.MessageBox]::Show($errorText)
}

$headphoneDevice = ($allAudio | Where-Object {$_.name -eq $headphoneName})
$speakerDevice = ($allAudio | Where-Object {$_.name -eq $speakerName})

$currentDefaultAudioDevice = Get-AudioDevice -Playback

if ($currentDefaultAudioDevice.name -eq $headphoneDevice.name) {
  Write-Host "switching to speaker mode"
  Set-AudioDevice -ID $speakerDevice.ID
  ./MultiMonitorTool/MultiMonitorTool.exe /enable \\.\DISPLAY2
  # "C:\Program Files (x86)\Steam\steam.exe" "steam://open/bigpicture"  
} elseif ($currentDefaultAudioDevice.name -eq $speakerDevice.name) {
  Write-Host "switching to headphone mode"
  Set-AudioDevice -ID $headphoneDevice.ID
  ./MultiMonitorTool/MultiMonitorTool.exe /disable \\.\DISPLAY2
}
