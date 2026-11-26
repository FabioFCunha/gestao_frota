/* Curated Commons photos served locally; no external API or customer key. */
(() => {
  const pending = new Map();
  async function load(url) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000);
    try {
      const response = await fetch(url, {signal: controller.signal, credentials: 'omit', cache: 'default', redirect: 'error'});
      if (!response.ok) throw new Error('http_' + response.status);
      if (!(response.headers.get('content-type') || '').startsWith('image/')) throw new Error('invalid_content_type');
      const blob = await response.blob();
      if (!blob.size || blob.size > 8 * 1024 * 1024) throw new Error('invalid_image_size');
      return URL.createObjectURL(blob);
    } finally { clearTimeout(timeout); }
  }
  function display(container) {
    const url = container.dataset.vehicleImageUrl;
    if (!url) return;
    if (!pending.has(url)) pending.set(url, load(url));
    const img = container.querySelector('img');
    const fallback = reason => {
      container.dataset.imageState = reason;
      img.hidden = true;
      container.querySelector('svg').style.display = '';
    };
    img.onerror = () => fallback('image_error');
    img.onload = () => {
      container.dataset.imageState = 'image';
      container.querySelector('svg').style.display = 'none';
      img.style.opacity = '1';
      img.hidden = false;
    };
    pending.get(url).then(src => { img.src = src; }).catch(error => fallback(error.name === 'AbortError' ? 'timeout' : error.message));
  }
  const cards = document.querySelectorAll('[data-vehicle-image-url]');
  if ('IntersectionObserver' in window) {
    const observer = new IntersectionObserver(entries => entries.forEach(entry => {
      if (entry.isIntersecting) { observer.unobserve(entry.target); display(entry.target); }
    }), {rootMargin: '150px'});
    cards.forEach(card => observer.observe(card));
  } else cards.forEach(display);
})();
