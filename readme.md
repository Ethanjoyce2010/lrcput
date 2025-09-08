# Audio Lyrics Embedding Script (lrcput.py)

The `lrcput.py` script allows you to embed LRC (Lyrics) files into FLAC, MP3, and M4A audio files.  
It now supports:

- **Batch embedding (directory mode)** from local `.lrc` files.
- **Batch LRCLib mode (directory)** that searches LRCLib online for lyrics based on file tags and embeds them automatically.
- **Single file embedding (any supported format, with optional conversion)** via a graphical interface, including a toggle to fetch lyrics directly from LRCLib without selecting a local `.lrc` file.

**This script was designed to embed lyrics acquired from [lrcget](https://github.com/tranxuanthang/lrcget).**
It can also retrieve lyrics from [LRCLib](https://lrclib.net/) when enabled.

---

## Requirements

- Python 3.x  
- Required Python libraries (install with `pip install`):  
  - `mutagen`  
  - `eyed3`  
  - `tqdm`  
  - `requests` (for LRCLib API)
- `ffmpeg` (only required for embedding lyrics into unsupported formats in Single mode, since they are converted to MP3)

You can install all dependencies with:

```sh
pip install -r requirements.txt
```

---

## Features

- **Batch Mode (Directory)**  
  Embed `.lrc` files into all `.flac`, `.mp3`, and `.m4a` audio files in a directory.  
  Options:  
  - Skip existing lyrics  
  - Delete `.lrc` after embedding (`reduce`)  
  - Recursive directory search  

- **Batch Mode: LRCLib (Directory)**  
  Search [LRCLib](https://lrclib.net/) for lyrics using the audio file's tags (Artist/Title and optionally Duration) and embed them directly.  
  Options:  
  - Skip existing lyrics  
  - Recursive directory search  
  Notes:  
  - Works for `.flac`, `.mp3`, and `.m4a` files whose tags are present.  
  - If Artist/Title tags are missing, the track will be skipped (no reliable search).

- **Single File Mode**  
  Embed an `.lrc` file into a chosen audio file.  
  - Supports `.mp3`, `.flac`, `.m4a` directly  
  - Other formats (`.wav`, `.ogg`, `.aac`, `.wma`, `.alac`, etc.) are converted to MP3 using `ffmpeg` before embedding  
  - A checkbox labeled `Search LRCLib` lets you fetch lyrics from LRCLib based on the audio file's tags. When checked, the LRC file selector is disabled (grayed out) and no local `.lrc` is required.

- **GUI (Tkinter)**  
  - Simple graphical interface  
  - File pickers for selecting directories, audio files, and LRC files  
  - Embedding progress and results shown in popup dialogs  

---

## Usage

1. Place your audio files and their corresponding `.lrc` files in the same directory.  
   (Example: `song.mp3` and `song.lrc`)  

2. Run the script:  
   ```sh
   python lrcput.py
   ```

3. In the GUI:  
   - Use `Batch Mode: Directory` to embed from local `.lrc` files.  
   - Use `Batch Mode: LRCLib` to automatically find and embed lyrics from LRCLib. Ensure your audio files have Artist/Title tags.  
   - Use `Single File Mode` to embed from a chosen `.lrc` file, or tick `Search LRCLib` to fetch lyrics online and disable the `.lrc` input.
