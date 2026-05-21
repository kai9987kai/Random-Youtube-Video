# Random YouTube Link Picker

A small local Tkinter app for picking a random YouTube video or web link from your own saved list.

The old Google Sheets API integration has been removed. Links are now stored locally in `links.json`, which the app creates next to `RandomYouTubeVideos.py` on first run.

## Run

```powershell
python RandomYouTubeVideos.py
```

## Features

- Add, edit, delete, search, favorite, and open saved links.
- Pick a random link without hard-coded row limits.
- Choose shuffle modes: discovery, least-opened, surprise, favorites, or any.
- Import links from clipboard text or files (`.txt`, `.csv`, `.md`, `.json`).
- Import the researched 2,000-link starter pack from `starter_videos.json`.
- Export the current local library to JSON.
- Track open count and last opened time.
- Sort by table columns and search across title, channel, tags, and URL.
- Enrich YouTube titles/channels with the public oEmbed endpoint.
- Keep automatic backup snapshots in `backups/` before saves.
- Undo the last library-changing action.
- Uses only the Python standard library.

## Local Data

Personal links are saved in `links.json` and ignored by Git. This workspace has been seeded with 2,000 local YouTube links. A portable example format is available in `links.example.json`.

The app accepts either the full JSON export format or a simple JSON array of URL strings when importing.

## Tests

```powershell
python -m unittest discover -v
python -m py_compile RandomYouTubeVideos.py
```
