---
name: add-animated-top-dock
description: "Build Animated Top Dock from its verified authored source using DOM + CSS + WebGL + Three.js r128, including the complete renderer, interactions, and required assets. Use when Codex needs to implement, port, or adapt this effect without requiring the ThreeUI package or reconstructing the visual from an approximation."
---

# Build Animated Top Dock

## Description

Sable’s proximity-spring menu in four fits: the authored centred dock, a modern command bar, a fitted pixel-terminal strip, and a vertical refracting Three.js glass rail.

Recreate the authored behavior from the verified source, not from screenshots or the abbreviated orchestration sample in this skill. The implementation may live directly in the target project and does not require `@designcodeio/threeui`.

## Technologies

- Semantic nav and button controls with authored inline SVG icons
- Scoped glass CSS with backdrop filtering and active/focus states
- Per-item spring integration driven by horizontal pointer proximity
- ResizeObserver, fine-pointer capability checks, keyboard focus, and reduced motion
- The exact embedded Fragment Mono font for dock labels

## Verified source material

- `ascii-page-transition-v1.html — exact top menu dock`
- `src/shaders/animated-top-dock/topDockController.ts`
- `src/shaders/animated-top-dock/AnimatedTopDock.tsx`
- `src/shaders/animated-top-dock/retroPixelField.ts`
- `src/shaders/animated-top-dock/glassParticleField.ts`
- `src/shaders/fonts/fragment-mono.woff2`

Source revision: `5a736cd3c1f6f19802f61ebb10e1701b9f7aa26e`

## Implementation steps

1. Open every verified source file listed above and identify the renderer, host lifecycle, styles, and assets before editing.
2. Build one logo control and the five authored SYSTEM, METHOD, WORK, ACCESS, and NOTES items with the source icon geometry.
3. Measure each item at rest, then compute a smoothstep influence from pointer distance using the authored 122 px proximity radius.
4. Integrate each item toward its target with spring 0.19 and damping 0.70, applying at most 17 px width, 16 px height, and 3.5 px downward growth.
5. Mirror pointer proximity for keyboard focus, retain the selected-item paper state, and reset cleanly when focus or pointer leaves.
6. Disable resizing motion on coarse pointers, narrow screens, and reduced-motion systems while keeping the nav fully usable.
7. Re-measure on resize and remove all observers, listeners, media-query handlers, and animation frames on teardown.
8. Give the local component a sized, overflow-controlled parent and verify desktop, mobile, reduced-motion, and context-loss behavior.

Asset handling: Copy the exact extracted Fragment Mono file for the dock labels; all SVG menu icons are inline and require no other assets.

## Local component example

Import the copied local component rather than a package entrypoint:

```tsx
import { AnimatedTopDock } from "./effects/animated-top-dock/AnimatedTopDock";
import "./effects/animated-top-dock/styles.css";

export function Scene() {
  return <div className="effect-frame"><AnimatedTopDock proximity={122} spring={0.19} damping={0.7} /></div>;
}
```

## Core renderer pattern

This excerpt documents orchestration only. Copy the exact shader, geometry, pass, and interaction code from the verified source files.

```tsx
const influence = smoothstep(clamp(1 - distance / 122, 0, 1));
state.velocity += (influence - state.value) * 0.19;
state.velocity *= 0.70;
state.value += state.velocity;
item.style.transform = `translateY(${state.value * 3.5}px)`;
```

## Behavior contract

- Runtime: DOM + CSS + WebGL + Three.js r128
- Passes: 1 spring layout pass across every dock item, plus 1 shader pass on the pixel and glass variants
- Interaction: Pointer proximity, keyboard focus, active selection, pointer parallax, reduced motion, and mobile static mode
- Assets: Exact embedded Fragment Mono font extracted from the authored source
- **renderer** (variant): DOM + CSS, raw WebGL, or Three.js r128
- **variant** (optional): sable | modern | retro | glass
- **fit** (variant): centred | horizontal | vertical
- **items** (fixed): 1 brand + 5 menu items
- **proximity** (default): 122 px
- **spring** (default): 0.19 / 0.70
- **motion** (adaptive): Pointer + focus + reduced motion

## Verification

1. Compare the rendered composition, animation timing, pointer behavior, and state transitions with the source implementation.
2. Exercise resize, high-DPI, mobile/coarse-pointer, reduced-motion, tab visibility, and WebGL context-loss paths where applicable.
3. Confirm every animation frame, observer, listener, geometry, buffer, texture, framebuffer, material, and renderer is released on teardown.
4. Check the browser console and confirm the effect renders at native-or-better backing resolution.

## Guardrails

- Do not substitute a visually similar package, demo, shader, or runtime.
- Do not approximate, reconstruct, or simplify the authored GLSL, render passes, geometry, interaction state, or assets.
- Keep exact source and asset hashes under regression tests when the source project provides them.
- Adapt only the surrounding host boundary needed by the target project; keep renderer behavior intact.
