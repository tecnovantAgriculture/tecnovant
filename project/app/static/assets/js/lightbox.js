/* Lightbox minimalista para imágenes marcadas con [data-lightbox].
 *
 * Uso: <img src="..." data-lightbox> (o data-lightbox="url-alternativa").
 * Funciona con imágenes insertadas dinámicamente (delegación en document).
 * Cierra con el botón superior derecho, click fuera de la imagen o Escape.
 * Autocontenido: inyecta sus propios estilos (no depende del build Tailwind).
 */
(function () {
  "use strict";

  const STYLE_ID = "img-lightbox-styles";
  const CSS = [
    "[data-lightbox]{cursor:zoom-in}",
    ".img-lightbox{position:fixed;inset:0;z-index:10000;display:flex;align-items:center;justify-content:center;padding:32px;background:rgba(15,23,42,.75);backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px);opacity:0;transition:opacity .22s ease}",
    ".img-lightbox.is-open{opacity:1}",
    ".img-lightbox__box{position:relative;transform:scale(.96);transition:transform .22s ease;margin:0}",
    ".img-lightbox.is-open .img-lightbox__box{transform:scale(1)}",
    ".img-lightbox__img{display:block;max-width:min(90vw,1100px);max-height:85vh;border-radius:14px;background:#fff;box-shadow:0 25px 60px rgba(0,0,0,.45)}",
    ".img-lightbox__close{position:absolute;top:-14px;right:-14px;width:36px;height:36px;display:flex;align-items:center;justify-content:center;border:none;border-radius:9999px;background:#fff;color:#334155;cursor:pointer;box-shadow:0 4px 14px rgba(0,0,0,.35);transition:background .15s ease,transform .15s ease}",
    ".img-lightbox__close:hover{background:#f1f5f9;transform:scale(1.06)}",
    ".img-lightbox__close svg{width:18px;height:18px}",
  ].join("\n");

  let overlay = null;

  function ensureStyles() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = CSS;
    document.head.appendChild(style);
  }

  function onKeydown(ev) {
    if (ev.key === "Escape") close();
  }

  function close() {
    if (!overlay) return;
    const el = overlay;
    overlay = null;
    el.classList.remove("is-open");
    document.body.style.removeProperty("overflow");
    document.removeEventListener("keydown", onKeydown);
    setTimeout(() => el.remove(), 220);
  }

  function open(src, alt) {
    ensureStyles();
    close();
    overlay = document.createElement("div");
    overlay.className = "img-lightbox";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");

    const box = document.createElement("figure");
    box.className = "img-lightbox__box";

    const closeBtn = document.createElement("button");
    closeBtn.type = "button";
    closeBtn.className = "img-lightbox__close";
    closeBtn.setAttribute("aria-label", "Cerrar");
    closeBtn.innerHTML =
      '<svg fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24">' +
      '<path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/></svg>';
    closeBtn.addEventListener("click", close);

    const img = document.createElement("img");
    img.className = "img-lightbox__img";
    img.src = src;
    img.alt = alt || "";
    img.onerror = close;

    box.appendChild(closeBtn);
    box.appendChild(img);
    overlay.appendChild(box);
    overlay.addEventListener("click", (ev) => {
      if (ev.target === overlay) close();
    });

    document.body.appendChild(overlay);
    document.body.style.overflow = "hidden";
    document.addEventListener("keydown", onKeydown);
    requestAnimationFrame(() => {
      if (overlay) overlay.classList.add("is-open");
    });
  }

  document.addEventListener("click", (ev) => {
    const trigger = ev.target.closest("[data-lightbox]");
    if (!trigger) return;
    const img = trigger.tagName === "IMG" ? trigger : trigger.querySelector("img");
    const src =
      trigger.getAttribute("data-lightbox") ||
      (img ? img.currentSrc || img.src : null);
    if (!src) return;
    ev.preventDefault();
    open(src, img ? img.alt : "");
  });
})();
