const form = document.querySelector("#form");
const input = document.querySelector("#url");
const submit = document.querySelector("#submit");
const example = document.querySelector("#example");
const statusEl = document.querySelector("#status");
const result = document.querySelector("#result");

const EXAMPLE = "https://x.com/NASA/status/2102748685792596449";
const POST_HOSTS = new Set([
  "x.com",
  "twitter.com",
  "mobile.twitter.com",
  "mobile.x.com",
  "fxtwitter.com",
  "vxtwitter.com",
  "fixupx.com",
  "fixvx.com",
]);
const SIZE_RE = /\/(\d{2,4})x(\d{2,4})\//;

example.addEventListener("click", () => {
  input.value = EXAMPLE;
  input.focus();
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const url = input.value.trim();
  if (!url) {
    showStatus("Paste a link first.", true);
    return;
  }

  submit.disabled = true;
  submit.textContent = "Ripping";
  result.hidden = true;
  result.innerHTML = "";
  showStatus("Reading the post…", false);

  try {
    const post = await extract(url);
    render(post);
    statusEl.hidden = true;
  } catch (error) {
    showStatus(error.message || "That post could not be read.", true);
  } finally {
    submit.disabled = false;
    submit.textContent = "Rip";
  }
});

function showStatus(message, isError) {
  statusEl.hidden = false;
  statusEl.textContent = message;
  statusEl.classList.toggle("error", isError);
}

async function extract(raw) {
  const ref = parsePostUrl(raw);
  const endpoints = [];
  if (ref.handle) endpoints.push(`https://api.fxtwitter.com/${ref.handle}/status/${ref.id}`);
  endpoints.push(`https://api.fxtwitter.com/status/${ref.id}`);

  let payload = null;
  let lastError = null;
  for (const endpoint of endpoints) {
    try {
      const response = await fetch(endpoint);
      if (response.status === 404) {
        lastError = new Error("That post is private, deleted, or unavailable.");
        continue;
      }
      if (!response.ok) {
        lastError = new Error("X didn't respond. Try again in a moment.");
        continue;
      }
      payload = await response.json();
      if (payload?.code === 200 && payload.tweet) break;
      payload = null;
      lastError = new Error("That post is private, deleted, or unavailable.");
    } catch {
      lastError = new Error("X didn't respond. Try again in a moment.");
    }
  }

  if (!payload?.tweet) throw lastError || new Error("That post is private, deleted, or unavailable.");

  const tweet = payload.tweet;
  const author = tweet.author || {};
  const items = [
    ...itemsFromMedia(tweet.media, "post"),
    ...itemsFromMedia(tweet.quote?.media, "quote"),
  ];
  if (!items.length) throw new Error("That post doesn't include a video or GIF.");

  const handle = author.screen_name || ref.handle || null;
  return {
    id: String(tweet.id || ref.id),
    url: handle ? `https://x.com/${handle}/status/${tweet.id || ref.id}` : `https://x.com/i/status/${ref.id}`,
    text: tweet.text || "",
    author: {
      name: author.name || handle || "X",
      handle,
      avatar: cleanImage(author.avatar_url),
    },
    items,
  };
}

function parsePostUrl(raw) {
  const text = raw.trim();
  if (!text || text.length > 500) throw new Error("Paste a link to a public post on X.");
  if (/^\d{10,22}$/.test(text)) return { id: text, handle: null };

  let url;
  try {
    url = new URL(/^https?:\/\//i.test(text) ? text : `https://${text}`);
  } catch {
    throw new Error("Paste a link to a public post on X.");
  }

  const host = url.hostname.toLowerCase().replace(/^www\./, "");
  if (host === "t.co") {
    throw new Error("Paste the full x.com post link. Short t.co links can't be opened from the page.");
  }
  if (!POST_HOSTS.has(host)) throw new Error("Paste a link to a public post on X.");

  const match = url.pathname.match(/\/status(?:es)?\/(\d+)/);
  if (!match) throw new Error("That link doesn't point at a post. Use a status link from X.");

  const handleMatch = url.pathname.match(/\/([A-Za-z0-9_]{1,15})\/status(?:es)?/);
  let handle = handleMatch ? handleMatch[1] : null;
  if (handle && (handle.toLowerCase() === "i" || handle.toLowerCase() === "web")) handle = null;
  return { id: match[1], handle };
}

function itemsFromMedia(media, origin) {
  if (!media) return [];
  const source = media.all || media.videos || [];
  const items = [];
  for (const entry of source) {
    if (!entry || (entry.type !== "video" && entry.type !== "gif")) continue;
    const raw = [];
    for (const variant of entry.formats || entry.variants || []) {
      const container = String(variant.container || "").toLowerCase();
      const contentType = variant.content_type || "";
      if (container === "m3u8" || container === "hls" || contentType.includes("mpegurl")) continue;
      if (container && container !== "mp4" && !String(contentType).includes("mp4")) continue;
      raw.push(variant);
    }
    if (!raw.length && entry.url) raw.push({ url: entry.url, bitrate: 0, content_type: "video/mp4" });
    const variants = prepareVariants(raw);
    if (!variants.length) continue;
    items.push({
      type: entry.type === "gif" ? "gif" : "video",
      origin,
      thumbnail: cleanImage(entry.thumbnail_url),
      width: entry.width || null,
      height: entry.height || null,
      duration_ms: entry.duration ? Math.round(Number(entry.duration) * 1000) : null,
      variants,
    });
  }
  return items;
}

function prepareVariants(raw) {
  const cleaned = [];
  const seen = new Set();
  for (const variant of raw) {
    const contentType = variant.content_type || variant.type || "";
    const src = variant.url || variant.src || "";
    if (String(contentType).includes("mpegurl") || src.includes(".m3u8")) continue;
    if (!String(contentType).includes("mp4") && !/\.mp4(?:$|\?)/.test(src)) continue;
    let parsed;
    try {
      parsed = new URL(src);
    } catch {
      continue;
    }
    if (parsed.protocol !== "https:" || parsed.hostname !== "video.twimg.com") continue;
    if (seen.has(src)) continue;
    seen.add(src);
    const size = parsed.pathname.match(SIZE_RE);
    cleaned.push({
      url: src,
      bitrate: Number(variant.bitrate) || 0,
      width: size ? Number(size[1]) : null,
      height: size ? Number(size[2]) : null,
    });
  }

  cleaned.sort((a, b) => qualityRank(b) - qualityRank(a) || b.bitrate - a.bitrate);
  const labels = cleaned.map(qualityLabel);
  const counts = {};
  for (const label of labels) counts[label] = (counts[label] || 0) + 1;
  cleaned.forEach((item, index) => {
    const label = labels[index];
    item.label = counts[label] > 1 && item.bitrate ? `${label} · ${formatBitrate(item.bitrate)}` : label;
  });
  return cleaned;
}

function qualityRank(item) {
  return item.width && item.height ? Math.min(item.width, item.height) : 0;
}

function qualityLabel(item) {
  const rank = qualityRank(item);
  if (rank) return `${rank}p`;
  if (item.bitrate) return formatBitrate(item.bitrate);
  return "MP4";
}

function formatBitrate(bitrate) {
  if (bitrate >= 1_000_000) {
    const value = (bitrate / 1_000_000).toFixed(1).replace(/\.0$/, "");
    return `${value} Mbps`;
  }
  if (bitrate >= 1000) return `${Math.round(bitrate / 1000)} kbps`;
  return `${bitrate} bps`;
}

function cleanImage(url) {
  if (!url) return null;
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== "https:" || !["pbs.twimg.com", "abs.twimg.com"].includes(parsed.hostname)) return null;
    return url.replace("_normal.", "_400x400.");
  } catch {
    return null;
  }
}

function render(post) {
  result.innerHTML = post.items.map((item, index) => card(post, item, index)).join("");
  result.hidden = false;
  bindCards(post);
}

function card(post, item, index) {
  const variants = item.variants;
  const selected = variants[0];
  const notes = [];
  if (post.items.length > 1) notes.push(`Clip ${index + 1}`);
  if (item.origin === "quote") notes.push("Quoted post");
  const origin = notes.join(" · ");
  return `
    <article class="card" data-index="${index}">
      <div class="stage">
        <span class="badge">${item.type === "gif" ? "GIF" : "Video"}</span>
        <video
          controls
          playsinline
          preload="metadata"
          ${item.type === "gif" ? "loop muted autoplay" : ""}
          poster="${esc(item.thumbnail || "")}"
          referrerpolicy="no-referrer"
          src="${esc(selected.url)}"
        ></video>
      </div>
      <div class="meta">
        <div class="who">
          ${avatar(post.author)}
          <div>
            <h2>${esc(post.author.name || "X")}</h2>
            <p class="handle">${esc(post.author.handle ? `@${post.author.handle}` : "X")}</p>
          </div>
        </div>
        ${origin ? `<p class="origin">${esc(origin)}</p>` : ""}
        ${index === 0 && post.text ? `<p class="post-text">${esc(post.text)}</p>` : ""}
        <div class="chips" role="radiogroup" aria-label="Quality">
          ${variants
            .map(
              (variant, variantIndex) => `
                <label class="chip">
                  <input type="radio" name="quality-${index}" value="${variantIndex}" ${variantIndex === 0 ? "checked" : ""} />
                  <span>${esc(variant.label)}</span>
                </label>
              `
            )
            .join("")}
        </div>
        <p class="dimensions">${esc(sizeLine(selected, item))}</p>
        <div class="actions">
          <button class="download" type="button">Download ${esc(selected.label)}</button>
          <button class="ghost" type="button">Copy file link</button>
        </div>
      </div>
    </article>
  `;
}

function bindCards(post) {
  result.querySelectorAll(".card").forEach((cardEl) => {
    const index = Number(cardEl.dataset.index);
    const item = post.items[index];
    const video = cardEl.querySelector("video");
    const download = cardEl.querySelector(".download");
    const copy = cardEl.querySelector(".ghost");
    const dimensions = cardEl.querySelector(".dimensions");

    cardEl.querySelectorAll('input[type="radio"]').forEach((radio) => {
      radio.addEventListener("change", () => {
        const variant = item.variants[Number(radio.value)];
        video.src = variant.url;
        video.load();
        download.textContent = `Download ${variant.label}`;
        dimensions.textContent = sizeLine(variant, item);
      });
    });

    download.addEventListener("click", () => {
      const variant = currentVariant(cardEl, item);
      saveFile(variant.url, fileName(post, item, variant, index), download);
    });

    copy.addEventListener("click", async () => {
      const variant = currentVariant(cardEl, item);
      try {
        await navigator.clipboard.writeText(variant.url);
        copy.textContent = "Copied";
        copy.classList.add("copied");
      } catch {
        copy.textContent = "Copy failed";
      }
    });
  });
}

function currentVariant(cardEl, item) {
  const selected = cardEl.querySelector('input[type="radio"]:checked');
  return item.variants[Number(selected?.value || 0)];
}

async function saveFile(url, filename, button) {
  const label = button.textContent;
  button.disabled = true;
  button.textContent = "Downloading";
  try {
    const response = await fetch(url, { referrerPolicy: "no-referrer" });
    if (!response.ok) throw new Error("The video file could not be downloaded.");
    const blob = await response.blob();
    const objectUrl = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = objectUrl;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(objectUrl), 1500);
    button.textContent = label;
  } catch (error) {
    button.textContent = label;
    showStatus(error.message || "The video file could not be downloaded.", true);
  } finally {
    button.disabled = false;
  }
}

function avatar(author) {
  if (author?.avatar) return `<img alt="" src="${esc(author.avatar)}" />`;
  return `<div class="avatar-fallback">${esc((author?.name || "X").slice(0, 1))}</div>`;
}

function sizeLine(variant, item) {
  const width = variant.width || item.width;
  const height = variant.height || item.height;
  const pixels = width && height ? `${width}×${height}` : "";
  const duration = formatDuration(item.duration_ms);
  return [pixels, duration].filter(Boolean).join(" · ");
}

function formatDuration(ms) {
  if (!ms) return "";
  const total = Math.round(ms / 1000);
  const minutes = Math.floor(total / 60);
  const seconds = String(total % 60).padStart(2, "0");
  return `${minutes}:${seconds}`;
}

function fileName(post, item, variant, index) {
  const handle = (post.author.handle || "x").toLowerCase();
  const label = (variant.label || "video").toLowerCase().replace(/[^\da-z]+/g, "");
  const suffix = post.items.length > 1 ? `-${index + 1}` : "";
  const kind = item.type === "gif" ? "gif" : "video";
  return `${handle}-${post.id}${suffix}-${kind}-${label}.mp4`;
}

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[char]);
}
