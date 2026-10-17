# Implementation plan

## Decisions

| Area | Choice | Rationale |
|---|---|---|
| UI + server | NiceGUI on FastAPI | One Python process, stateful event handlers, server push for progress, `ui.aggrid` built in |
| Tag library | mutagen | Full ID3v1/v2.3/v2.4 read/write, APIC cover art, other formats possible later |
| Format scope | MP3 first, format-agnostic tag model | Internal abstraction between UI/services and mutagen |
| Run mode | Local app first, Docker later | Direct path access; design for a configurable music root and path sandbox from day one |
| Packaging | Poetry, in-project `.venv`, Python >= 3.14 | Already set up |
| Testing | pytest, fixture MP3s generated in tests | Core logic is UI-independent and fully testable |

## Architecture

Strict layering so the UI stays thin and the core is testable without a browser.

```
src/mp3tagger/
  core/                 # no NiceGUI / FastAPI imports
    models.py           # Track, TagSet, CoverArt, FieldName (format-agnostic)
    tagio/
      base.py           # TagReader/TagWriter protocol
      id3.py            # mutagen ID3 implementation (v1, v2.3, v2.4)
    library.py          # scan folders, in-memory track collection
    editing.py          # pending-changes buffer: per-track field edits, dirty state, undo stack
    batch.py            # multi-select merge view (<keep>), batch apply
    patterns.py         # %field% pattern parser/formatter (filename<->tag)
    transforms.py       # case conversion, find/replace (regex), auto-numbering
    rename.py           # tag -> filename, collision checks, dry-run preview
  services/
    fs.py               # root-confined path resolution, folder listing
    lookup.py           # MusicBrainz client (Discogs later)
  ui/                   # NiceGUI only
    app.py              # page layout, wiring
    file_grid.py        # ui.aggrid: columns, sort, multi-select
    tag_panel.py        # editor, <keep> handling, cover art widget
    dialogs/            # pattern converters, find/replace, folder browser, lookup
  api.py                # optional REST routes on the same FastAPI app
  config.py             # music root(s), settings (env + file)
  __main__.py           # entry point (poetry script)
tests/
```

### Key design points

- **Tag model:** `TagSet` holds normalised fields (title, artist, album, album artist, year, track, disc, genre, comment, composer) plus cover art. The ID3 backend maps these to frames (TIT2, TPE1, TALB, TPE2, TDRC/TYER, TRCK, TPOS, TCON, COMM, TCOM, APIC). Unknown frames are preserved on write.
- **Edit buffer:** all edits go to a pending-changes layer, not the file. Save writes the dirty tracks. Undo is a stack of change sets over this buffer, so undo is cheap and does not touch disk. Dirty tracks are flagged in the grid.
- **Multi-select:** the panel computes a merged view. Equal values are shown as is, differing values as `<keep>`. Only fields the user changed are applied.
- **Version handling:** the writer takes a target ID3 version, with v1 as an optional extra tag. Converting v2.3 and v2.4 means rewriting date frames (TYER/TDAT vs TDRC) and the text encoding.
- **Blocking I/O:** mutagen is synchronous. Scan, read and save run via `run.io_bound` with progress pushed to the UI.
- **Safety:** write to a temp file and replace atomically for renames. Tag writes use mutagen's in-place save and are guarded by a dirty check. Rename previews are always dry-run first, with collision detection.
- **Path sandbox:** every path goes through `services/fs.py` and is resolved against the configured root(s). This is a no-op friction locally and is required for Docker.
- **Docker readiness:** config via env vars (`MP3TAGGER_ROOTS`, host, port), a server-side folder browser (browsers do not expose real paths), and no reliance on native-window features.

## Phases

- [x] 1. **Foundation:** package layout, config, `__main__`, pytest and ruff setup, dependencies (nicegui, mutagen, httpx).
- [ ] 2. **Read path:** `Track`/`TagSet` models, ID3 reader, folder scan, file grid with sortable and selectable columns, folder browser dialog.
- [ ] 3. **Edit and save:** tag panel for a single track, edit buffer, dirty indicators, save, ID3 v2.3/v2.4 and v1 handling.
- [ ] 4. **Multi-select:** merged view with `<keep>`, batch apply.
- [ ] 5. **Cover art:** view, add, replace, extract, remove.
- [ ] 6. **Converters:** pattern engine, then filename to tag, tag to filename (with preview), tag to tag, auto-numbering.
- [ ] 7. **Transforms:** case conversion, find/replace with regex.
- [ ] 8. **Online lookup:** MusicBrainz import with preview and field mapping (Discogs deferred).
- [ ] 9. **Docker:** Dockerfile, root sandbox hardening, env config, docs.
- [ ] 10. **Optional features:** undo polish, filter/search, actions, export, technical info, playlists.

Technical file info (bitrate, duration) is cheap with mutagen, so it can move up to phase 2.

## Risks

- ID3 version conversion edge cases (date frames, encodings, v1 limits). Cover with fixture-based tests.
- Large libraries: grid performance with thousands of rows. Use AG Grid's client-side model first and move to server-side paging if needed.
- NiceGUI per-client state: keep the library and edit buffer in a per-session object, not module globals, so Docker multi-client use stays correct.
- Python 3.14 requirement: check that nicegui, mutagen and their dependencies install on it, and fall back to 3.12/3.13 if not.
