# Card images for `oryth`

No images yet. Cards without `image` render as text cards, which is the current state of every item.

Rules when adding one (CROSS_PROMO.md §8-2):

- File name: `<item-id>-<w>x<h>.<png|jpg|webp>`, e.g. `oddside-intro-2026w44-1200x630.png`.
- Ratio 1.91:1 (1200×630) or 1:1 (600×600). 200 KB or less.
- **No text inside the image** (title/body carry the words so all 10 locales and font fallbacks work).
- Reference it from the item as
  `"image": {"url": "https://ovject.github.io/feed/img/oryth/<file>", "width": 1200, "height": 630, "alt": "<plain description>"}`.
- The app caches the image file next to its feed state and shows a text card if the download fails.
