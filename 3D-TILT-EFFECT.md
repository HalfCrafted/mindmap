# 3D Tilt Effect on Mouse Hover

This document explains the 3D perspective tilt effect used on gallery cards in the portfolio website, where elements appear to "bend" toward the mouse cursor position.

## Overview

The effect creates a subtle 3D rotation that follows the mouse position, making elements appear to tilt toward where the user is hovering. This is achieved by:

1. Tracking mouse position relative to the element's center
2. Calculating rotation angles based on distance from center
3. Applying CSS 3D transforms in real-time

## How It Works

### Core Concept

The effect uses CSS 3D transforms with `perspective`, `rotateX`, and `rotateY` to create the illusion of a card tilting in 3D space. The rotation amounts are calculated based on how far the mouse is from the element's center.

```
Mouse at top    → Card tilts backward (negative rotateX)
Mouse at bottom → Card tilts forward  (positive rotateX)
Mouse at left   → Card tilts right    (negative rotateY)
Mouse at right  → Card tilts left     (positive rotateY)
```

### Mathematical Breakdown

1. **Get element dimensions and center point:**
   ```javascript
   const rect = element.getBoundingClientRect();
   const centerX = rect.left + rect.width / 2;
   const centerY = rect.top + rect.height / 2;
   ```

2. **Calculate mouse offset from center:**
   ```javascript
   const mouseX = e.clientX - centerX;
   const mouseY = e.clientY - centerY;
   ```

3. **Normalize to -1 to 1 range:**
   ```javascript
   const normX = mouseX / (rect.width / 2);   // -1 (left edge) to 1 (right edge)
   const normY = mouseY / (rect.height / 2);  // -1 (top edge) to 1 (bottom edge)
   ```

4. **Calculate tilt angles:**
   ```javascript
   const tiltStrength = 5; // Maximum degrees of rotation
   const tiltX = normY * -tiltStrength;  // Inverted: top → back, bottom → forward
   const tiltY = normX * tiltStrength;   // Normal: left → right tilt, right → left tilt
   ```

5. **Apply 3D transform:**
   ```javascript
   element.style.transform = `perspective(1000px) rotateX(${tiltX}deg) rotateY(${tiltY}deg) translateZ(10px)`;
   ```

## Implementation

### Required CSS

```css
.tiltable-element {
    /* Enable 3D transforms */
    transform-style: preserve-3d;

    /* Set initial state (no tilt) */
    transform: perspective(1000px) rotateX(0deg) rotateY(0deg) translateZ(0px);

    /* Smooth transition for natural feel - use bouncy easing */
    transition: transform 0.4s cubic-bezier(0.34, 1.56, 0.64, 1);
}
```

**Key CSS Properties:**

| Property | Purpose |
|----------|---------|
| `transform-style: preserve-3d` | Ensures child elements participate in 3D space |
| `perspective(1000px)` | Sets viewing distance (lower = more dramatic effect) |
| `rotateX()` | Tilts forward/backward |
| `rotateY()` | Tilts left/right |
| `translateZ()` | Lifts element toward viewer (creates "pop" effect) |
| `transition` | Smooths the movement; bouncy easing adds life |

### Required JavaScript

```javascript
document.querySelectorAll('.tiltable-element').forEach(element => {
    const tiltStrength = 5; // Max degrees of tilt (adjust to taste)
    const liftAmount = 10;  // Pixels to lift toward viewer

    element.addEventListener('mousemove', (e) => {
        // Get element position and dimensions
        const rect = element.getBoundingClientRect();
        const centerX = rect.left + rect.width / 2;
        const centerY = rect.top + rect.height / 2;

        // Calculate mouse offset from center
        const mouseX = e.clientX - centerX;
        const mouseY = e.clientY - centerY;

        // Normalize to -1 to 1 range
        const normX = mouseX / (rect.width / 2);
        const normY = mouseY / (rect.height / 2);

        // Calculate tilt angles
        const tiltX = normY * -tiltStrength; // Negative because Y-axis is inverted
        const tiltY = normX * tiltStrength;

        // Apply transform
        element.style.transform = `perspective(1000px) rotateX(${tiltX}deg) rotateY(${tiltY}deg) translateZ(${liftAmount}px)`;
    });

    element.addEventListener('mouseleave', () => {
        // Reset to flat when mouse leaves
        element.style.transform = 'perspective(1000px) rotateX(0deg) rotateY(0deg) translateZ(0px)';
    });
});
```

## Tunable Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `tiltStrength` | 5 | Maximum rotation in degrees. Higher = more dramatic tilt |
| `liftAmount` | 10 | Pixels to "lift" element toward viewer on hover |
| `perspective` | 1000px | Viewing distance. Lower = more exaggerated 3D effect |
| `transition duration` | 0.4s | How long the animation takes |
| `easing` | `cubic-bezier(0.34, 1.56, 0.64, 1)` | Bouncy overshoot easing |

### Adjusting Intensity

**Subtle effect (for secondary elements):**
```javascript
const tiltStrength = 2;
const liftAmount = 5;
```

**Dramatic effect (for featured content):**
```javascript
const tiltStrength = 10;
const liftAmount = 20;
```

## Complete Standalone Example

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>3D Tilt Effect</title>
    <style>
        .card-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 2rem;
            padding: 2rem;
        }

        .tilt-card {
            background: white;
            border: 2px solid #0A0A0A;
            padding: 2rem;

            /* 3D Tilt Requirements */
            transform-style: preserve-3d;
            transform: perspective(1000px) rotateX(0deg) rotateY(0deg) translateZ(0px);
            transition: transform 0.4s cubic-bezier(0.34, 1.56, 0.64, 1),
                        box-shadow 0.2s ease;
        }

        .tilt-card:hover {
            box-shadow: 8px 8px 0 #0A0A0A;
        }

        .tilt-card h3 {
            margin: 0 0 1rem 0;
        }

        .tilt-card p {
            margin: 0;
            color: #666;
        }
    </style>
</head>
<body>
    <div class="card-grid">
        <div class="tilt-card">
            <h3>Card One</h3>
            <p>Hover over me to see the 3D tilt effect in action.</p>
        </div>
        <div class="tilt-card">
            <h3>Card Two</h3>
            <p>The card tilts toward your mouse cursor position.</p>
        </div>
        <div class="tilt-card">
            <h3>Card Three</h3>
            <p>Move your mouse around to explore the effect.</p>
        </div>
    </div>

    <script>
        document.querySelectorAll('.tilt-card').forEach(card => {
            const tiltStrength = 5;
            const liftAmount = 10;

            card.addEventListener('mousemove', (e) => {
                const rect = card.getBoundingClientRect();
                const centerX = rect.left + rect.width / 2;
                const centerY = rect.top + rect.height / 2;

                const mouseX = e.clientX - centerX;
                const mouseY = e.clientY - centerY;

                const normX = mouseX / (rect.width / 2);
                const normY = mouseY / (rect.height / 2);

                const tiltX = normY * -tiltStrength;
                const tiltY = normX * tiltStrength;

                card.style.transform = `perspective(1000px) rotateX(${tiltX}deg) rotateY(${tiltY}deg) translateZ(${liftAmount}px)`;
            });

            card.addEventListener('mouseleave', () => {
                card.style.transform = 'perspective(1000px) rotateX(0deg) rotateY(0deg) translateZ(0px)';
            });
        });
    </script>
</body>
</html>
```

## Reusable Function

For cleaner code, wrap the effect in a reusable function:

```javascript
function applyTiltEffect(selector, options = {}) {
    const {
        tiltStrength = 5,
        liftAmount = 10,
        perspective = 1000
    } = options;

    document.querySelectorAll(selector).forEach(element => {
        element.style.transformStyle = 'preserve-3d';
        element.style.transform = `perspective(${perspective}px) rotateX(0deg) rotateY(0deg) translateZ(0px)`;

        element.addEventListener('mousemove', (e) => {
            const rect = element.getBoundingClientRect();
            const centerX = rect.left + rect.width / 2;
            const centerY = rect.top + rect.height / 2;

            const normX = (e.clientX - centerX) / (rect.width / 2);
            const normY = (e.clientY - centerY) / (rect.height / 2);

            const tiltX = normY * -tiltStrength;
            const tiltY = normX * tiltStrength;

            element.style.transform = `perspective(${perspective}px) rotateX(${tiltX}deg) rotateY(${tiltY}deg) translateZ(${liftAmount}px)`;
        });

        element.addEventListener('mouseleave', () => {
            element.style.transform = `perspective(${perspective}px) rotateX(0deg) rotateY(0deg) translateZ(0px)`;
        });
    });
}

// Usage examples:
applyTiltEffect('.card');
applyTiltEffect('.featured-item', { tiltStrength: 8, liftAmount: 15 });
applyTiltEffect('.subtle-element', { tiltStrength: 2, liftAmount: 5 });
```

## Browser Support

This effect uses CSS 3D transforms which are supported in all modern browsers:
- Chrome 36+
- Firefox 16+
- Safari 9+
- Edge 12+

## Performance Considerations

- The effect uses `mousemove` which fires frequently; transforms are GPU-accelerated so performance is generally good
- For many elements on a page, consider using `requestAnimationFrame` to throttle updates
- Avoid applying to very large elements or too many elements simultaneously

## Common Issues

| Issue | Solution |
|-------|----------|
| Effect looks flat | Ensure `transform-style: preserve-3d` is set |
| Jerky animation | Add proper transition to the element |
| Elements clip/overlap strangely | Adjust `perspective` value or add `z-index` |
| Effect too subtle | Increase `tiltStrength` |
| Effect too dramatic | Decrease `tiltStrength` and `perspective` |
