# MP3 tagger

Python based (web) GUI to manipulate ID3 audio file tags.

## Main features

- [ ] Open folders / add files and show them in a sortable file list with selectable columns (filename, title, artist, album, year, track, genre, path, ...)
- [ ] Multi-selection of files for batch operations
- [ ] Tag panel to view and edit the tags of the selected file(s)
- [ ] Batch editing of common fields across multiple files (unchanged fields are kept, differing values are shown as `<keep>`)
- [ ] Support for ID3v1, ID3v2.3 and ID3v2.4 tags, including conversion between versions
- [ ] Standard fields: title, artist, album, album artist, year, track, disc number, genre, comment, composer
- [ ] Cover art: view, add, replace, extract and remove embedded images
- [ ] Filename → Tag: derive tags from filename patterns (e.g. `%artist% - %title%`)
- [ ] Tag → Filename: rename files from tags using a format string
- [ ] Tag → Tag: copy values between fields
- [ ] Auto-numbering of tracks
- [ ] Case conversion (upper, lower, title case, sentence case)
- [ ] Find and replace in tag fields, with regular expression support
- [ ] Import tags from online databases (e.g. MusicBrainz, Discogs)

## Optional features

- [ ] Playlist creation- [ ] Actions: reusable, chainable batch operations (replace, case conversion, remove field, format value, ...)
- [ ] Filter / search the file list
- [ ] Undo and save changes (explicit save, with indication of modified files)
- [ ] Export the file list / tags (e.g. CSV, HTML)
- [ ] Display of technical file information (bitrate, sample rate, duration, size)