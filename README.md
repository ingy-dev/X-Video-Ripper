# X Ripper

Paste a public [X](https://x.com) post and download the video or GIF.

X stores GIFs as MP4. X Ripper downloads that file, and the player loops it.

## Run it

Python 3.9 or newer is enough. There are no packages to install.

```bash
python3 server.py
```

Open [http://localhost:8787](http://localhost:8787).

## Deploy

This needs a small server. GitHub Pages cannot run it, because the lookup happens on the server.

The app reads `PORT` and listens on `0.0.0.0`. On Render or Railway, use:

```bash
python3 server.py
```

A `Dockerfile` is included if you would rather ship a container.

```bash
docker build -t x-ripper .
docker run -p 8787:8787 x-ripper
```

Source: [github.com/ingy-dev/X-Video-Ripper](https://github.com/ingy-dev/X-Video-Ripper)

## What it accepts

- `https://x.com/name/status/123`
- `https://twitter.com/name/status/123`
- `https://x.com/i/status/123`
- FxTwitter and FixupX links
- `t.co` links that lead to a post

Private, deleted, and login-only posts are unavailable. Photo-only posts have nothing to download.
