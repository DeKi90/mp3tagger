# MP3 Tagger

A web GUI to edit the ID3 tags and cover art of your audio files: batch editing, renaming and
sorting into folders from tags, case conversion, find and replace, and a MusicBrainz lookup that
recognises a CD from the identifier stored in the files.

## Getting started

1. Under **Configuration**, set **Music folders** to where your music is. Home Assistant shares
   `/media` and `/share` with apps, so something like `/media/music` is typical. Network storage
   added in Home Assistant shows up under `/media`.
2. **Start** the app and open **MP3 Tagger** in the sidebar (or use **Open Web UI**).
3. Choose **Open folder…**, pick an album, select files, and edit. Nothing is written to your
   files until you press **Save**.

## Options

| Option | Meaning |
| --- | --- |
| Music folders | Folders the app may open and change. Everything outside them is out of reach. |
| Contact for MusicBrainz | Optional e-mail or web address sent to MusicBrainz so they can reach you if the app misbehaves. |
| iTunes store country | Two-letter code (`de`, `at`, `us`, …) of the iTunes store searched for cover art. |

## Things to know

- **Back up your music first.** The app changes tags and can rename and move files. Every
  change is previewed or kept pending until you save, but saved changes are written to the files.
- **Network use.** Only when you use the lookup: album and artist names, and the CD identifier,
  go to MusicBrainz; cover searches go to the Cover Art Archive and, if you choose it, the iTunes
  Search API. Nothing is sent otherwise.
- **Direct access.** The app opens from the sidebar behind Home Assistant's login. Under
  **Network** you can also give it a host port, but that bypasses the login, so only do it on a
  network you trust.
- **Large libraries.** Open the folder you want to work on rather than the whole library;
  everything in the opened folder (with subfolders) is read when it is opened.

## Support

Report problems with the app's **Log** tab attached.
