# Paleta image assets

The public page refresh keeps the existing three-paleta compositions and colors.
The built-in imagegen tool recreated the food detail from the existing image
references, using edit mode and a transparent background. The original reference
files remain available; the pages now use the following WebP exports:

| Asset | Dimensions | Use |
| --- | --- | --- |
| `frontend/src/assets/paletas-hero.webp` | 1254 × 1254 | Homepage hero and sign-in |
| `frontend/src/assets/paletas-hero-768.webp` | 768 × 768 | Smaller responsive hero/sign-in source |
| `frontend/src/assets/paletas-flavors.webp` | 1086 × 1448 | Homepage flavors |
| `frontend/src/assets/paletas-flavors-640.webp` | 640 × 853 | Smaller flavors source and catering form illustration |

Full-size exports keep the generated native resolution. Smaller exports are
downsampled with Lanczos; all preserve alpha. WebP quality is 90 for the full-size
files and 88 for the smaller files. `srcset`, `sizes`, and intrinsic dimensions
select suitable sources without stretching the original low-resolution images.
The hero's circle and yellow badge are HTML/CSS rather than baked into the photo.

## Final hero prompt

Reference: `frontend/src/assets/aneena-paletas-hero.png`.

Use case: precise-object-edit. Asset type: high-resolution transparent cutout for
an existing Mexican paleta website. Primary request: replace the low-resolution
food imagery in the reference with beautifully sharp, photoreal studio food
photography while preserving the same three-paleta fan composition: golden yellow
mango paleta on the left leaning left, bright red strawberry paleta standing
straight in the center in front, creamy white coconut paleta on the right leaning
right. Preserve the elongated rounded rectangular molded paleta shapes and natural
wooden sticks. Show authentic frozen fruit texture, tiny ice crystals, strawberry
seeds, soft natural specular highlights and clean crisp edges. The group fills at
least 92% of the canvas height and 92% width, with a small safety margin; every
stick and edge is fully visible. Output at high native resolution, ideally 2048 by
2048 pixels. Remove ALL existing background graphics: no pink field, no circle,
no yellow badge, no text. The three paletas and their sticks alone on a genuinely
transparent background. No fruit props, no hands, no plate, no logo, no watermark.
Keep the product colors and overall friendly composition matching the reference.
Do not blur or merely enlarge the existing pixels; recreate the photographic detail.

## Final flavors prompt

Reference: `frontend/src/assets/paletas-flavor-preview.png`.

Use case: precise-object-edit. Asset type: high-resolution transparent product
cutout for the existing website's flavor section. Recreate the reference's SAME
three-paleta fan composition as sharply detailed photoreal studio food photography:
purple berry paleta on the left tilted left, orange mango and vivid magenta
dragonfruit swirled paleta standing straight in front in the middle, golden orange
mango paleta on the right tilted right. Keep all three classic elongated rounded
rectangular molded paleta shapes, recessed vertical mold channels, their wooden
sticks, relative overlap and positions. Add clean natural frozen fruit texture,
tiny ice crystals, visible dark dragonfruit seeds in the center swirl and soft
realistic studio highlights, with crisp clean edges. The complete group fills
92% of image height with very little empty margin, all sticks fully visible and
neatly converging. High native resolution, ideally 1536 by 2048 pixels or greater.
Transparent background with real alpha, no colored backdrop or cast backdrop
shadow, no badge, no words, no logos, no decorative objects, no fruit props.
Preserve identity and palette; improve the actual photographic detail instead of
enlarging blurry pixels.
