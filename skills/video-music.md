# Download videos, music and files the right way
- YouTube or similar link: {"tool": "download_video", "url": "...", "kind": "video"} -- use "audio" instead of "video" when only the music is wanted (mp3).
- A direct file link: {"tool": "download_file", "url": "..."}
- Everything lands in D:\zyro\downloads (videos and music in downloads\videos).
- After a download, offer to open it: {"tool": "open_file", "path": "downloads\videos\NAME"}
- yt-dlp supports over 1000 sites, so try download_video even for links of sites not on the open_site allowed list.
