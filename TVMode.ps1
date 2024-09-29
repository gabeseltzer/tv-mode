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
  
  # Small off, LG off, TV on
  # MultiMonitorTool.exe /SetMonitors "Name=MONITOR\SAM0D3B\{4d36e96e-e325-11ce-bfc1-08002be10318}\0005 Primary=1 BitsPerPixel=32 Width=3840 Height=2160 DisplayFlags=0 DisplayFrequency=60 DisplayOrientation=0 PositionX=2560 PositionY=0" "Name=MONITOR\SAM0A59\{4d36e96e-e325-11ce-bfc1-08002be10318}\0007 BitsPerPixel=0 Width=0 Height=0 DisplayFlags=0 DisplayFrequency=0 DisplayOrientation=0 PositionX=0 PositionY=0" 
  
  # Small off, LG on, TV on
  ./MultiMonitorTool/MultiMonitorTool.exe /SetMonitors "Name=MONITOR\SAM0A59\{4d36e96e-e325-11ce-bfc1-08002be10318}\0007 BitsPerPixel=0 Width=0 Height=0 DisplayFlags=0 DisplayFrequency=0 DisplayOrientation=0 PositionX=0 PositionY=0" "Name=MONITOR\GSM5B7F\{4d36e96e-e325-11ce-bfc1-08002be10318}\0011 Primary=1 BitsPerPixel=32 Width=2560 Height=1440 DisplayFlags=0 DisplayFrequency=144 DisplayOrientation=0 PositionX=0 PositionY=0" "Name=MONITOR\SAM0D3B\{4d36e96e-e325-11ce-bfc1-08002be10318}\0005 BitsPerPixel=32 Width=3840 Height=2160 DisplayFlags=0 DisplayFrequency=60 DisplayOrientation=0 PositionX=2560 PositionY=0"
  
  # "C:\Program Files (x86)\Steam\steam.exe" "steam://open/bigpicture" 
} elseif ($currentDefaultAudioDevice.name -eq $speakerDevice.name) {
  Write-Host "switching to headphone mode"
  Set-AudioDevice -ID $headphoneDevice.ID
  
  # Small on, LG on, TV off
  # MultiMonitorTool.exe /SetMonitors "Name=MONITOR\GSM5B7F\{4d36e96e-e325-11ce-bfc1-08002be10318}\0011 Primary=1 BitsPerPixel=32 Width=2560 Height=1440 DisplayFlags=0 DisplayFrequency=144 DisplayOrientation=0 PositionX=0 PositionY=0"  "Name=MONITOR\SAM0D3B\{4d36e96e-e325-11ce-bfc1-08002be10318}\0005 BitsPerPixel=0 Width=0 Height=0 DisplayFlags=0 DisplayFrequency=0 DisplayOrientation=0 PositionX=0 PositionY=0"
  
  # Small on, LG off, TV on
  ./MultiMonitorTool/MultiMonitorTool.exe /SetMonitors "Name=MONITOR\SAM0A59\{4d36e96e-e325-11ce-bfc1-08002be10318}\0007 BitsPerPixel=32 Width=1920 Height=1080 DisplayFlags=0 DisplayFrequency=60 DisplayOrientation=0 PositionX=4294965376 PositionY=240" "Name=MONITOR\GSM5B7F\{4d36e96e-e325-11ce-bfc1-08002be10318}\0011 BitsPerPixel=0 Width=0 Height=0 DisplayFlags=0 DisplayFrequency=0 DisplayOrientation=0 PositionX=0 PositionY=0" "Name=MONITOR\SAM0D3B\{4d36e96e-e325-11ce-bfc1-08002be10318}\0005 BitsPerPixel=32 Width=3840 Height=2160 DisplayFlags=0 DisplayFrequency=60 DisplayOrientation=0 PositionX=2560 PositionY=0"
}