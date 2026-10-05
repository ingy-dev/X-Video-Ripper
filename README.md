# X Ripper

Paste a public [X](https://x.com) post and download the video or GIF.

This is a static site. GitHub Pages serves it directly from this repository. There is no server to run.

X stores GIFs as MP4. X Ripper downloads that file, and the player loops it.

## Publish

In the repository on GitHub, open **Settings → Pages**. Set the source to the `main` branch and the folder `/` (root). The site is then available at:

https://ingy-dev.github.io/X-Video-Ripper/

## Run it locally

```bash
python3 -m http.server 4173
```

Open [http://127.0.0.1:4173](http://127.0.0.1:4173).

## What it accepts

- `https://x.com/name/status/123`
- `https://twitter.com/name/status/123`
- `https://x.com/i/status/123`
- FxTwitter and FixupX links

Private, deleted, and photo-only posts have nothing to download. The page reads public posts through [FxTwitter](https://github.com/FxEmbed/FxEmbed), which allows browser requests.
