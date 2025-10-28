import os
import re
import shutil
import argparse
from mutagen.flac import FLAC
from mutagen.mp4 import MP4
import eyed3
from tqdm import tqdm
import requests
from urllib.parse import urlencode
import mutagen
import eyed3.id3
import logging
from typing import Optional, Tuple, List
import importlib

# Load mutagen.File dynamically to avoid static analysis warnings from Pylance
_mutagen_mod = importlib.import_module('mutagen')
MutagenFile = getattr(_mutagen_mod, 'File', None)

def has_embedded_lyrics(audio) -> bool:
    """Return True if the given Mutagen/eyed3 audio object has embedded lyrics.

    The function accepts different audio object types (FLAC, MP4, eyed3 AudioFile).
    """
    if isinstance(audio, FLAC):
        return 'LYRICS' in audio
    elif isinstance(audio, MP4):
        return bool(audio.tags and ('\xa9lyr' in audio.tags))
    elif isinstance(audio, eyed3.core.AudioFile):
        # audio.tag may be None; use safe getattr to avoid static analysis complaints
        return bool(audio.tag and getattr(audio.tag, 'lyrics', None))
    return False

def embed_lyrics_text_to_file(audio_path: str, lyrics: str) -> Optional[str]:
    """Embed given lyrics text into the audio file.

    Returns the output path if the file was converted (e.g. to mp3). Returns None if embedded in-place.
    Raises an exception on failure.
    """
    import subprocess
    ext = os.path.splitext(audio_path)[1].lower()
    try:
        if ext == '.mp3':
            audio = eyed3.load(audio_path)
            if audio is None:
                raise Exception("Failed to load MP3 for embedding")
            # Ensure tag exists
            if audio.tag is None:
                audio.initTag()
            # audio.tag members are not well-known to type checkers; use getattr/setattr and narrow ignores
            try:
                # Preferred API: use lyrics object if available
                if getattr(audio.tag, 'lyrics', None) is not None:
                    audio.tag.lyrics.set(lyrics)  # type: ignore[attr-defined]
                else:
                    # Fallback: set attribute directly
                    setattr(audio.tag, 'lyrics', lyrics)  # type: ignore[arg-type]
            except Exception:
                # Still attempt to set attribute directly in case library versions differ
                setattr(audio.tag, 'lyrics', lyrics)  # type: ignore[arg-type]
            # Save tag (type checker may not know save exists)
            audio.tag.save(version=eyed3.id3.ID3_V2_3)  # type: ignore[attr-defined]
        elif ext == '.flac':
            audio = FLAC(audio_path)
            audio['LYRICS'] = lyrics
            audio.save()
        elif ext == '.m4a':
            audio = MP4(audio_path)
            # Ensure tags exist before subscripting (mutagen may set tags=None)
            if audio.tags is None:
                # mutagen.mp4.MP4 provides add_tags() to initialize tags
                try:
                    audio.add_tags()
                except Exception:
                    # If tags could not be created, raise to avoid silent failures
                    raise Exception("Unable to initialize MP4 tags for: %s" % audio_path)
            assert audio.tags is not None
            audio.tags['\xa9lyr'] = lyrics
            audio.save()
        else:
            # Convert to mp3 using ffmpeg, then embed
            mp3_path = os.path.splitext(audio_path)[0] + '_converted.mp3'
            subprocess.run([
                'ffmpeg', '-y', '-i', audio_path, mp3_path
            ], check=True)
            audio = eyed3.load(mp3_path)
            if audio is None:
                raise Exception("Failed to load converted MP3 for embedding")
            if audio.tag is None:
                audio.initTag()
            # Set lyrics defensively (type checkers may not know attribute names)
            try:
                if getattr(audio.tag, 'lyrics', None) is not None:
                    audio.tag.lyrics.set(lyrics)  # type: ignore[attr-defined]
                else:
                    setattr(audio.tag, 'lyrics', lyrics)  # type: ignore[arg-type]
            except Exception:
                setattr(audio.tag, 'lyrics', lyrics)  # type: ignore[arg-type]
            audio.tag.save(version=eyed3.id3.ID3_V2_3)  # type: ignore[attr-defined]
            return mp3_path
    except Exception as e:
        raise Exception(f"Failed to embed lyrics: {e}")
    return None

def embed_lrc(directory: str, skip_existing: bool, reduce_lrc: bool, recursive: bool) -> Tuple[int, int, List[str]]:
    """Embed .lrc files found in `directory` into supported audio files.

    Returns a tuple: (total_audio_files, embedded_lyrics_files, failed_files)
    """
    total_audio_files = 0
    embedded_lyrics_files = 0
    failed_files: List[str] = []
    
    audio_files = []
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith('.flac') or file.endswith('.mp3') or file.endswith('.m4a'):
                audio_files.append(os.path.join(root, file))
        if not recursive:
            break

    with tqdm(total=len(audio_files), desc='Embedding LRC files', unit='file') as pbar:
        for audio_path in audio_files:
            file = os.path.basename(audio_path)
            lrc_file = os.path.splitext(file)[0] + '.lrc'
            lrc_path = os.path.join(os.path.dirname(audio_path), lrc_file)
            
            if os.path.exists(lrc_path):
                if skip_existing:
                    audio = None
                    if file.endswith('.flac'):
                        audio = FLAC(audio_path)
                    elif file.endswith('.mp3'):
                        audio = eyed3.load(audio_path)
                    elif file.endswith('.m4a'):
                        audio = MP4(audio_path)
                    if has_embedded_lyrics(audio):
                        pbar.set_postfix({"status": "skipped"})
                        pbar.update(1)
                        continue
                
                try:
                    lyrics = open(lrc_path, 'r', encoding='utf-8').read()
                    embed_lyrics_text_to_file(audio_path, lyrics)
                    
                    embedded_lyrics_files += 1
                    pbar.set_postfix({"status": f"embedded: {file}"})
                    pbar.update(1)
                    pbar.refresh()
                    
                    if reduce_lrc:
                        os.remove(lrc_path)
                        pbar.set_postfix({"status": f"embedded, LRC reduced: {file}"})
                        pbar.update(1)
                        pbar.refresh()
                
                except Exception as e:
                    print(f"Error embedding LRC for {file}: {str(e)}")
                    pbar.set_postfix({"status": f"error: {file}"})
                    pbar.update(1)
                    pbar.refresh()
                    failed_files.append(file)
                    if os.path.exists(lrc_path):
                        shutil.move(lrc_path, lrc_path + ".failed")
                    continue

    return len(audio_files), embedded_lyrics_files, failed_files

import subprocess

def embed_lrc_single(audio_path: str, lrc_path: str) -> Optional[str]:
    """Embed lyrics from an .lrc file into a single audio file.

    Returns output path if conversion was performed, otherwise None.
    """
    lyrics = open(lrc_path, 'r', encoding='utf-8').read()
    return embed_lyrics_text_to_file(audio_path, lyrics)

def read_tags_for_lrclib(audio_path):
    """Extract artist, title, and duration (if available) for LRCLib lookup.

    Returns (artist, title, duration) where artist/title may be None when unavailable.
    """
    ext = os.path.splitext(audio_path)[1].lower()
    artist = title = None
    duration = None
    try:
        if ext == '.mp3':
            audio = eyed3.load(audio_path)
            if audio is not None and audio.tag is not None:
                artist = getattr(audio.tag, 'artist', None)
                title = getattr(audio.tag, 'title', None)
                duration = int(audio.info.time_secs) if getattr(audio, 'info', None) else None
        elif ext == '.flac':
            audio = FLAC(audio_path)
            artist = (audio.get('artist') or [None])[0]
            title = (audio.get('title') or [None])[0]
            duration = int(audio.info.length) if audio.info else None
        elif ext == '.m4a':
            audio = MP4(audio_path)
            tags = audio.tags
            artist = (tags.get('\xa9ART') or [None])[0] if tags else None
            title = (tags.get('\xa9nam') or [None])[0] if tags else None
            duration = int(audio.info.length) if audio.info else None
        else:
            # Generic fallback using mutagen for other formats (wav/ogg/aac/wma/alac etc.)
            if MutagenFile is None:
                # Fallback: try attribute access (runtime)
                mf = importlib.import_module('mutagen').File(audio_path, easy=True)
            else:
                mf = MutagenFile(audio_path, easy=True)
            if mf and mf.tags:
                # easy tags are lists
                artist = (mf.tags.get('artist') or [None])[0]
                title = (mf.tags.get('title') or [None])[0]
            # duration if available
            try:
                if mf and getattr(mf, 'info', None) and getattr(mf.info, 'length', None):
                    duration = int(mf.info.length)
            except Exception:
                pass
    except Exception:
        pass
    return artist, title, duration

def parse_artist_title_from_filename(path: str) -> Tuple[Optional[str], str]:
    """Heuristic parsing from filename like 'Artist - Title.ext' or 'Artist_Title.ext'.

    Returns (artist, title) where artist may be None if not present.
    """
    # Normalize to handle both Windows (\\) and POSIX (/) separators regardless of host OS
    base = os.path.splitext(re.split(r"[\\/]", path)[-1])[0]
    # common patterns
    candidates = []
    if ' - ' in base:
        parts = base.split(' - ', 1)
        if len(parts) == 2:
            candidates.append((parts[0].strip(), parts[1].strip()))
    if '_' in base and not candidates:
        parts = base.split('_', 1)
        if len(parts) == 2:
            candidates.append((parts[0].strip(), parts[1].strip()))
    # fallback: no artist, use full name as title
    if not candidates:
        candidates.append((None, base.strip()))
    return candidates[0]

def fetch_lyrics_from_lrclib(artist: Optional[str], title: Optional[str], duration: Optional[int]=None) -> Optional[str]:
    """Fetch synced lyrics from LRCLib. Returns lyrics string or None.

    artist/title may be None; function returns None in that case.
    """
    if not artist or not title:
        return None
    base = 'https://lrclib.net/api'
    try:
        # Try /get first
        params = {"track_name": title, "artist_name": artist}
        if duration:
            params["duration"] = str(duration)
        r = requests.get(f"{base}/get", params=params, timeout=10)
        if r.status_code == 200:
            data = r.json()
            lyrics = data.get('syncedLyrics') or data.get('plainLyrics')
            if lyrics:
                return lyrics
        # Fallback to /search
        r = requests.get(f"{base}/search", params=params, timeout=10)
        if r.status_code == 200:
            items = r.json()
            if isinstance(items, list) and items:
                # Pick first with syncedLyrics if possible
                best = None
                for it in items:
                    if it.get('syncedLyrics'):
                        best = it
                        break
                if not best:
                    best = items[0]
                return best.get('syncedLyrics') or best.get('plainLyrics')
    except Exception:
        return None
    return None

def embed_lrclib_batch(directory: str, skip_existing: bool, reduce_lrc: bool, recursive: bool) -> Tuple[int, int, List[str]]:
    """Batch embed lyrics from LRCLib into supported files in directory.

    Returns (total_files, embedded_count, failed_list)
    """
    audio_files = []
    for root, dirs, files in os.walk(directory):
        for file in files:
            # Supported formats (some may be converted during embedding)
            if (
                file.endswith('.flac') or file.endswith('.mp3') or file.endswith('.m4a') or
                file.endswith('.wav') or file.endswith('.ogg') or file.endswith('.aac') or
                file.endswith('.wma') or file.endswith('.alac')
            ):
                audio_files.append(os.path.join(root, file))
        if not recursive:
            break

    embedded = 0
    failed = []
    needs_manual = []  # collect for manual input at the end
    with tqdm(total=len(audio_files), desc='LRCLib batch', unit='file') as pbar:
        for audio_path in audio_files:
            file = os.path.basename(audio_path)
            try:
                # Skip if already has lyrics
                if skip_existing:
                    audio_obj = None
                    if file.endswith('.flac'):
                        audio_obj = FLAC(audio_path)
                    elif file.endswith('.mp3'):
                        audio_obj = eyed3.load(audio_path)
                    elif file.endswith('.m4a'):
                        audio_obj = MP4(audio_path)
                    if audio_obj is not None and has_embedded_lyrics(audio_obj):
                        logging.info(f"[SKIP] Already has embedded lyrics: {file}")
                        pbar.set_postfix({"status": "skipped"})
                        pbar.update(1)
                        continue

                artist, title, duration = read_tags_for_lrclib(audio_path)
                if not artist or not title:
                    # try filename fallback
                    f_artist, f_title = parse_artist_title_from_filename(audio_path)
                    if f_artist or f_title:
                        logging.info(f"[FALLBACK] Using filename for tags: artist={f_artist}, title={f_title} for {file}")
                        artist = artist or f_artist
                        title = title or f_title
                if not artist or not title:
                    logging.warning(f"[DEFER] Missing tags for {file}, deferring to manual input at end")
                    needs_manual.append(audio_path)
                    pbar.set_postfix({"status": "defer"})
                    pbar.update(1)
                    continue

                logging.info(f"[QUERY] LRCLib search: artist='{artist}', title='{title}', duration={duration} for {file}")
                lyrics = fetch_lyrics_from_lrclib(artist, title, duration)
                if not lyrics:
                    logging.warning(f"[MISS] No lyrics found on LRCLib for {file}")
                    failed.append(file)
                    pbar.set_postfix({"status": "not found"})
                    pbar.update(1)
                    continue
                embed_lyrics_text_to_file(audio_path, lyrics)
                embedded += 1
                logging.info(f"[EMBED] Embedded lyrics for {file}")
                pbar.set_postfix({"status": f"embedded: {file}"})
                pbar.update(1)
                pbar.refresh()
                if reduce_lrc:
                    # Nothing to remove since no .lrc created; ignore
                    pass
            except Exception as e:
                logging.exception(f"[ERROR] {file}: {e}")
                failed.append(file)
                pbar.set_postfix({"status": f"error: {file}"})
                pbar.update(1)
                pbar.refresh()
                continue

    # Manual input pass at the end
    if needs_manual:
        logging.info(f"[MANUAL] Prompting for {len(needs_manual)} files with missing tags...")
        manual_embedded = _manual_prompt_and_embed(needs_manual)
        embedded += manual_embedded
    return len(audio_files), embedded, failed

def _manual_prompt_and_embed(file_list: List[str]) -> int:
    """Prompt user for artist/title for each file in the list, then fetch and embed. Returns count embedded."""
    import tkinter as tk
    from tkinter import simpledialog, messagebox
    root = tk.Tk()
    root.withdraw()  # Hide main window during prompts
    count = 0
    for audio_path in file_list:
        base = os.path.basename(audio_path)
        # Prefill using filename heuristic
        f_artist, f_title = parse_artist_title_from_filename(audio_path)
        artist = simpledialog.askstring("LRCLib Metadata", f"Enter Artist for\n{base}", initialvalue=f_artist or "")
        if artist is None:
            logging.info(f"[MANUAL] Skip file (artist canceled): {base}")
            continue
        title = simpledialog.askstring("LRCLib Metadata", f"Enter Title for\n{base}", initialvalue=f_title or "")
        if title is None:
            logging.info(f"[MANUAL] Skip file (title canceled): {base}")
            continue
        lyrics = fetch_lyrics_from_lrclib(artist.strip() or None, title.strip() or None, None)
        if not lyrics:
            messagebox.showwarning("LRCLib", f"No lyrics found for:\n{artist} - {title}\n({base})")
            logging.warning(f"[MISS] Manual query not found for {base}")
            continue
        try:
            embed_lyrics_text_to_file(audio_path, lyrics)
            count += 1
            logging.info(f"[EMBED] Embedded (manual) for {base}")
        except Exception as e:
            logging.exception(f"[ERROR] Embedding (manual) failed for {base}: {e}")
            messagebox.showerror("LRCLib", f"Embedding failed for:\n{base}\n{e}")
    root.destroy()
    return count

def main_gui():
    banner = """
██╗     ██████╗  ██████╗██████╗ ██╗   ██╗████████╗
██║     ██╔══██╗██╔════╝██╔══██╗██║   ██║╚══██╔══╝
██║     ██████╔╝██║     ██████╔╝██║   ██║   ██║   
██║     ██╔══██╗██║     ██╔═══╝ ██║   ██║   ██║   
███████╗██║  ██║╚██████╗██║     ╚██████╔╝   ██║   
╚══════╝╚═╝  ╚═╝ ╚═════╝╚═╝      ╚═════╝    ╚═╝   
OG Scripted by TheRedSpy15
Polished by EthanJoyce2010"""

    import tkinter as tk
    from tkinter import filedialog, messagebox

    root = tk.Tk()
    root.title("LRC Embedder")
    # Configure logging to console
    logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')

    tk.Label(root, text=banner, font=("Consolas", 10), justify="left").pack(pady=5)

    # Directory mode variables
    selected_dir = tk.StringVar()
    skip_existing = tk.BooleanVar()
    reduce_lrc = tk.BooleanVar()
    recursive = tk.BooleanVar()

    # Single file mode variables
    selected_audio = tk.StringVar()
    selected_lrc = tk.StringVar()
    single_use_lrclib = tk.BooleanVar()

    def choose_directory():
        dir_path = filedialog.askdirectory(title="Select Audio Directory")
        if dir_path:
            selected_dir.set(dir_path)

    def choose_audio():
        audio_path = filedialog.askopenfilename(
            title="Select Audio File",
            filetypes=[
                ("Audio Files", "*.mp3 *.flac *.m4a *.wav *.ogg *.aac *.wma *.alac"),
                ("All Files", "*.*")
            ]
        )
        if audio_path:
            selected_audio.set(audio_path)

    def choose_lrc():
        lrc_path = filedialog.askopenfilename(title="Select LRC File", filetypes=[("LRC Files", "*.lrc")])
        if lrc_path:
            selected_lrc.set(lrc_path)

    def start_embedding_dir():
        if not selected_dir.get():
            messagebox.showerror("Error", "Please select a directory.")
            return
        total, embedded, failed = embed_lrc(selected_dir.get(), skip_existing.get(), reduce_lrc.get(), recursive.get())
        percentage = (embedded / total) * 100 if total > 0 else 0
        result = f"Total audio files: {total}\nEmbedded lyrics in {embedded} audio files.\nPercentage of audio files with embedded lyrics: {percentage:.2f}%"
        if failed:
            result += "\n\nFailed to embed LRC for the following files:\n" + "\n".join(failed)
        messagebox.showinfo("Embedding Results", result)

    def start_embedding_single():
        if not selected_audio.get():
            messagebox.showerror("Error", "Please select an audio file.")
            return
        try:
            if single_use_lrclib.get():
                artist, title, duration = read_tags_for_lrclib(selected_audio.get())
                if not artist or not title:
                    f_artist, f_title = parse_artist_title_from_filename(selected_audio.get())
                    artist = artist or f_artist
                    title = title or f_title
                if not artist or not title:
                    # prompt user
                    from tkinter import simpledialog
                    base = os.path.basename(selected_audio.get())
                    artist = simpledialog.askstring("LRCLib Metadata", f"Enter Artist for\n{base}", initialvalue=artist or "")
                    title = simpledialog.askstring("LRCLib Metadata", f"Enter Title for\n{base}", initialvalue=title or "")
                lyrics = fetch_lyrics_from_lrclib(artist, title, duration)
                if not lyrics:
                    messagebox.showerror("Error", "Could not find lyrics on LRCLib for this file (ensure Artist/Title tags are set).")
                    return
                logging.info(f"[EMBED] Single (LRCLib) artist='{artist}', title='{title}'")
                result = embed_lyrics_text_to_file(selected_audio.get(), lyrics)
            else:
                if not selected_lrc.get():
                    messagebox.showerror("Error", "Please select an LRC file or enable LRCLib search.")
                    return
                result = embed_lrc_single(selected_audio.get(), selected_lrc.get())
            if result:
                messagebox.showinfo("Success", f"Lyrics embedded! Output: {result}")
            else:
                messagebox.showinfo("Success", "Lyrics embedded!")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def toggle_single_lrclib():
        state = 'disabled' if single_use_lrclib.get() else 'normal'
        entry_lrc.configure(state=state)
        btn_browse_lrc.configure(state=state)

    # Directory mode UI
    frame_dir = tk.LabelFrame(root, text="Batch Mode: Directory", padx=10, pady=10)
    frame_dir.pack(fill="x", padx=10, pady=5)
    tk.Label(frame_dir, text="Select Directory:").pack(side="left")
    tk.Entry(frame_dir, textvariable=selected_dir, width=30).pack(side="left", padx=5)
    tk.Button(frame_dir, text="Browse", command=choose_directory).pack(side="left", padx=5)
    tk.Checkbutton(frame_dir, text="Skip Existing Lyrics", variable=skip_existing).pack(side="left", padx=5)
    tk.Checkbutton(frame_dir, text="Reduce LRC", variable=reduce_lrc).pack(side="left", padx=5)
    tk.Checkbutton(frame_dir, text="Recursive Search", variable=recursive).pack(side="left", padx=5)
    tk.Button(frame_dir, text="Start Batch", command=start_embedding_dir, bg="green", fg="white").pack(side="left", padx=5)

    # LRCLib batch mode UI
    frame_dir_lrclib = tk.LabelFrame(root, text="Batch Mode: LRCLib (Directory)", padx=10, pady=10)
    frame_dir_lrclib.pack(fill="x", padx=10, pady=5)
    tk.Label(frame_dir_lrclib, text="Select Directory:").pack(side="left")
    entry_dir2 = tk.Entry(frame_dir_lrclib, textvariable=selected_dir, width=30)
    entry_dir2.pack(side="left", padx=5)
    tk.Button(frame_dir_lrclib, text="Browse", command=choose_directory).pack(side="left", padx=5)
    tk.Checkbutton(frame_dir_lrclib, text="Skip Existing Lyrics", variable=skip_existing).pack(side="left", padx=5)
    tk.Checkbutton(frame_dir_lrclib, text="Recursive Search", variable=recursive).pack(side="left", padx=5)
    def start_embedding_dir_lrclib():
        if not selected_dir.get():
            messagebox.showerror("Error", "Please select a directory.")
            return
        total, embedded, failed = embed_lrclib_batch(selected_dir.get(), skip_existing.get(), False, recursive.get())
        percentage = (embedded / total) * 100 if total > 0 else 0
        result = f"Total audio files: {total}\nEmbedded (LRCLib) in {embedded} audio files.\nPercentage: {percentage:.2f}%"
        if failed:
            result += "\n\nFailed (no match or error) for:\n" + "\n".join(failed)
        messagebox.showinfo("LRCLib Batch Results", result)
    tk.Button(frame_dir_lrclib, text="Start LRCLib Batch", command=start_embedding_dir_lrclib, bg="#6a5acd", fg="white").pack(side="left", padx=5)

    # Single file mode UI
    frame_single = tk.LabelFrame(root, text="Single File Mode (Any Supported Format)", padx=10, pady=10)
    frame_single.pack(fill="x", padx=10, pady=5)
    tk.Label(frame_single, text="Audio File:").pack(side="left")
    tk.Entry(frame_single, textvariable=selected_audio, width=30).pack(side="left", padx=5)
    tk.Button(frame_single, text="Browse", command=choose_audio).pack(side="left", padx=5)
    tk.Checkbutton(frame_single, text="Search LRCLib", variable=single_use_lrclib, command=toggle_single_lrclib).pack(side="left", padx=5)
    tk.Label(frame_single, text="LRC File:").pack(side="left")
    entry_lrc = tk.Entry(frame_single, textvariable=selected_lrc, width=30)
    entry_lrc.pack(side="left", padx=5)
    btn_browse_lrc = tk.Button(frame_single, text="Browse", command=choose_lrc)
    btn_browse_lrc.pack(side="left", padx=5)
    tk.Button(frame_single, text="Start Single", command=start_embedding_single, bg="blue", fg="white").pack(side="left", padx=5)

    root.mainloop()

def main() -> None:
    """Command-line entrypoint. If no CLI args are given, the GUI is launched.

    CLI modes:
    - --batch DIR : embed .lrc files from DIR
    - --lrclib DIR : search LRCLib and embed for files in DIR
    - --single AUDIO --lrc FILE : embed a single .lrc into AUDIO
    Additional flags: --skip-existing, --reduce, --recursive
    """
    logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
    parser = argparse.ArgumentParser(prog='lrcput', description='Embed LRC lyrics into audio files (GUI if no args)')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--batch', metavar='DIR', help='Embed .lrc files from directory')
    group.add_argument('--lrclib', metavar='DIR', help='Search LRCLib and embed lyrics for files in directory')
    group.add_argument('--single', metavar='AUDIO', help='Embed a single LRC into AUDIO file')
    parser.add_argument('--lrc', metavar='FILE', help='LRC file to embed for --single')
    parser.add_argument('--skip-existing', action='store_true', help='Skip files that already have embedded lyrics')
    parser.add_argument('--reduce', action='store_true', help='Remove .lrc files after successful embedding (batch mode)')
    parser.add_argument('--recursive', action='store_true', help='Recursively search directories')
    args = parser.parse_args()

    # If no args provided, launch GUI
    if not any([args.batch, args.lrclib, args.single]):
        main_gui()
        return

    # CLI modes
    if args.batch:
        total, embedded, failed = embed_lrc(args.batch, args.skip_existing, args.reduce, args.recursive)
        logging.info(f"Total: {total}, Embedded: {embedded}, Failed: {len(failed)}")
    elif args.lrclib:
        total, embedded, failed = embed_lrclib_batch(args.lrclib, args.skip_existing, False, args.recursive)
        logging.info(f"Total: {total}, Embedded: {embedded}, Failed: {len(failed)}")
    elif args.single:
        if not args.lrc:
            parser.error('--single requires --lrc FILE')
        out = embed_lrc_single(args.single, args.lrc)
        if out:
            logging.info(f"Embedded; output file: {out}")
        else:
            logging.info("Embedded in-place")


if __name__ == "__main__":
    main()
