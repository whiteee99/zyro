# Sort the downloads folder into tidy subfolders
1. {"tool": "list_files", "path": "downloads"}
2. Group files by type: installers (.exe .msi), videos (.mp4 .mkv .webm), music (.mp3), images (.png .jpg), documents (.pdf .txt), archives (.zip .rar), everything else.
3. Create missing subfolders and move each group with run_command, one command per group, for example: move "D:\zyro\downloads\*.mp4" "D:\zyro\downloads\videos"
4. Report a short count per folder at the end.
Never delete anything unless the user clearly says to delete.
