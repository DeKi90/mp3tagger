# MP3 Tagger

A web GUI to edit the ID3 tags and cover art of audio files (see [mp3tagger/README.md](mp3tagger/README.md)
for the features). This repository is both a **Home Assistant app repository** and a normal
project; one `Dockerfile` builds **two images**:

| Image | Build | For |
| --- | --- | --- |
| `standalone` | `docker build --target standalone -t mp3tagger mp3tagger` | Docker, a NAS, docker-compose |
| `homeassistant` | built by Home Assistant itself (the default target) | the Home Assistant app |

## Home Assistant

1. In Home Assistant: **Settings → Apps → Install app → ⋮ → Repositories**, add
   `https://github.com/DeKi90/mp3tagger`. Home Assistant has to be able to clone that address
   without logging in, so the repository must be public (an address that needs a login, such as
   a private GitHub repository, cannot be added).
2. Install **MP3 Tagger**. The first install builds the image on your Home Assistant machine,
   which takes a few minutes.
3. Open the app's **Configuration**, set **Music folders** (e.g. `/media/music`), start it, and
   open **MP3 Tagger** from the sidebar.

The app is served through Home Assistant's ingress (so it sits behind your Home Assistant login).
See [mp3tagger/DOCS.md](mp3tagger/DOCS.md) for the options.

### While the repository is private

Home Assistant cannot clone a repository that needs a login, so use it as a **local app**
instead: the `mp3tagger/` folder contains everything the build needs. With the Samba or SSH app
installed, copy that folder into Home Assistant's `addons` share (`/addons` over SSH), then open
the app store, choose **Check for updates**, and install **MP3 Tagger** from the **Local apps**
section. Copy the folder again after each change to update it.

## Standalone Docker

```sh
git clone https://github.com/DeKi90/mp3tagger.git && cd mp3tagger
docker build --target standalone -t mp3tagger mp3tagger
docker run -d --name mp3tagger -p 8080:8080 \
  --user "$(id -u):$(id -g)" \
  -v /path/to/your/music:/music \
  mp3tagger
```

Then open <http://localhost:8080>. Run it as your own user (`--user`) so that changed files keep
their owner. The same as a `docker-compose.yml`:

```yaml
services:
  mp3tagger:
    build:
      context: ./mp3tagger
      target: standalone
    user: "1000:1000"          # your uid:gid
    ports: ["8080:8080"]
    volumes: ["/path/to/your/music:/music"]
    restart: unless-stopped
```

There is no login: do not expose the port to networks you do not trust.

| Environment variable | Default in the image | Meaning |
| --- | --- | --- |
| `MP3TAGGER_ROOTS` | `/music` | Folders the app may open (separate several with `:`) |
| `MP3TAGGER_PORT` | `8080` | Port inside the container |
| `MP3TAGGER_CONTACT` | – | Address sent to MusicBrainz in the User-Agent (optional) |
| `MP3TAGGER_COVER_COUNTRY` | `de` | Two-letter iTunes store country for cover search |

## Development

The project lives in [`mp3tagger/`](mp3tagger/), which is also the Home Assistant app folder
(Home Assistant builds an app from its own folder, so it has to contain the source).

```sh
cd mp3tagger
poetry install
poetry run mp3tagger          # http://127.0.0.1:8080, music in ~/Music (MP3TAGGER_ROOTS)
poetry run pytest
```
