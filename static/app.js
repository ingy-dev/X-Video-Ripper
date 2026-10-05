const form = document.querySelector("#form");
const input = document.querySelector("#url");
const submit = document.querySelector("#submit");
const example = document.querySelector("#example");
const status = document.querySelector("#status");
const result = document.querySelector("#result");

const EXAMPLE = "https://x.com/NASA/status/2102748685792596449";

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
    const response = await fetch("/api/rip", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || "That post could not be read.");
    }
    render(data);
    status.hidden = true;
  } catch (error) {
    showStatus(error.message || "That post could not be read.", true);
  } finally {
    submit.disabled = false;
    submit.textContent = "Rip";
  }
});

function showStatus(message, isError) {
  status.hidden = false;
  status.textContent = message;
  status.classList.toggle("error", isError);
}

function render(post) {
  const handle = post.author?.handle ? `@${post.author.handle}` : "X";
  const cards = (post.items || []).map((item, index) => card(post, item, index));
  result.innerHTML = cards.join("");
  result.hidden = false;
  bindCards(post);
}

function card(post, item, index) {
  const variants = item.variants || [];
  const selected = variants[0];
  const notes = [];
  if (post.items.length > 1) notes.push(`Clip ${index + 1}`);
  if (item.origin === "quote") notes.push("Quoted post");
  const origin = notes.join(" · ");
  const name = fileName(post, item, selected, index);
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
          src="${esc(selected ? fileHref(selected, name) : "")}"
        ></video>
      </div>
      <div class="meta">
        <div class="who">
          ${avatar(post.author)}
          <div>
            <h2>${esc(post.author?.name || "X")}</h2>
            <p class="handle">${esc(handleText(post))}</p>
          </div>
        </div>
        ${origin ? `<p class="origin">${esc(origin)}</p>` : ""}
        ${index === 0 && post.text ? `<p class="post-text">${esc(post.text)}</p>` : ""}
        <div class="chips" role="radiogroup" aria-label="Quality">
          ${variants
            .map(
              (variant, variantIndex) => `
                <label class="chip">
                  <input
                    type="radio"
                    name="quality-${index}"
                    value="${variantIndex}"
                    ${variantIndex === 0 ? "checked" : ""}
                  />
                  <span>${esc(variant.label)}</span>
                </label>
              `
            )
            .join("")}
        </div>
        <p class="dimensions">${esc(sizeLine(selected, item))}</p>
        <div class="actions">
          <a class="download" href="${downloadHref(selected, name)}">Download ${esc(selected?.label || "file")}</a>
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
    const link = cardEl.querySelector(".download");
    const copy = cardEl.querySelector(".ghost");
    const dimensions = cardEl.querySelector(".dimensions");

    cardEl.querySelectorAll('input[type="radio"]').forEach((radio) => {
      radio.addEventListener("change", () => {
        const variant = item.variants[Number(radio.value)];
        const name = fileName(post, item, variant, index);
        video.src = fileHref(variant, name);
        video.load();
        link.href = downloadHref(variant, name);
        link.textContent = `Download ${variant.label}`;
        dimensions.textContent = sizeLine(variant, item);
      });
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

function avatar(author) {
  if (author?.avatar) {
    return `<img alt="" src="${esc(author.avatar)}" />`;
  }
  const letter = esc((author?.name || "X").slice(0, 1));
  return `<div class="avatar-fallback">${letter}</div>`;
}

function handleText(post) {
  return post.author?.handle ? `@${post.author.handle}` : "X";
}

function sizeLine(variant, item) {
  if (!variant) return "";
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
  const handle = (post.author?.handle || "x").toLowerCase();
  const label = (variant?.label || "video").toLowerCase().replace(/[^\da-z]+/g, "");
  const suffix = post.items.length > 1 ? `-${index + 1}` : "";
  const kind = item.type === "gif" ? "gif" : "video";
  return `${handle}-${post.id}${suffix}-${kind}-${label}.mp4`;
}

function downloadHref(variant, filename) {
  const params = new URLSearchParams({ src: variant.url, filename });
  return `/api/download?${params}`;
}

function fileHref(variant, filename) {
  const params = new URLSearchParams({ src: variant.url, filename });
  return `/api/file?${params}`;
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
