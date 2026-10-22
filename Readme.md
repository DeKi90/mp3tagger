# MP3 tagger

Python based (web) GUI to manipulate ID3 audio file tags.

## Main features

- [x] Open folders / add files and show them in a sortable file list with selectable columns (filename, title, artist, album, year, track, genre, path, ...) — folders only so far, single files cannot be added yet
- [x] Multi-selection of files for batch operations
- [x] Tag panel to view and edit the tags of the selected file(s)
- [x] Batch editing of common fields across multiple files (unchanged fields are kept, differing values are shown as `<keep>`)
- [x] Support for ID3v1, ID3v2.3 and ID3v2.4 tags, including conversion between versions
- [x] Standard fields: title, artist, album, album artist, year, track, disc number, genre, comment, composer
- [x] Cover art: view, add, replace, extract and remove embedded images
- [x] Filename → Tag: derive tags from filename patterns (e.g. `%artist% - %title%`)
- [x] Tag → Filename: rename files from tags using a format string
- [x] Tag → Tag: copy values between fields
- [x] Auto-numbering of tracks
- [x] Case conversion (upper, lower, title case, sentence case)
- [x] Find and replace in tag fields, with regular expression support
- [x] Import tags from online databases (e.g. MusicBrainz, Discogs) — MusicBrainz only so far, looked up from the CD identifier (MCDI) or by name

## Optional features

- [ ] Playlist creation
- [ ] Actions: reusable, chainable batch operations (replace, case conversion, remove field, format value, ...)
- [ ] Filter / search the file list
- [x] Undo and save changes (explicit save, with indication of modified files)
- [ ] Export the file list / tags (e.g. CSV, HTML)
- [x] Display of technical file information (bitrate, sample rate, duration, size)
