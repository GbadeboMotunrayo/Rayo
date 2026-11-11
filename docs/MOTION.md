# Rayo motion standard

How things move in Rayo, and why. Read this before adding or changing an animation.

Rayo runs in a WebKitGTK window that often renders **in software, on the CPU**. So every rule here also serves one other goal: motion should look physical and cost almost nothing.

## 1. Respond on press, not on release

- Anything you can click reacts on **pointer-down**: it shrinks slightly (`scale: .96`, or `.93` for the reactor core) and springs back when released.
- **The hub acts on the first click.** One click opens the radial menu at once. A second click within 300 ms turns it into Bench mode, and a third into the shutdown countdown. Before this, the menu waited 300 ms in case a double-click was coming.

## 2. Springs, not curves

Springs are written as CSS `linear()` curves. These are sampled from a real spring equation, `m·x″ = −k·x − b·x′` (mass 1), so they need no JavaScript. They live in `:root`:

| Token | Spring (k, b) | Feel | Duration | Used for |
|---|---|---|---|---|
| `--spring-snappy` | 500, 40 (ζ 0.89) | Firm, no visible overshoot | `--dur-snappy` 0.5 s | Presses, hover magnify, small state changes |
| `--spring-bounce` | 320, 22 (ζ 0.61, 8.5% overshoot) | Lively | `--dur-bounce` 0.8 s | Things arriving: radial menu, power bar |
| `--spring-gentle` | 180, 26 (ζ 0.97) | Smooth settle | `--dur-gentle` 0.8 s | Live data: bars and fills |
| `--ease-exit` | `cubic-bezier(.23,1,.32,1)` | Quick | `--dur-exit` 0.16 s | Anything leaving |

- **A spring curve only works with its own duration.** The curve is sampled over exactly that time, so always pair `--spring-x` with `--dur-x`.
- **Exits are faster than entrances.** Things arrive on a spring and leave in 0.16 s with no stagger. Closing should never feel like waiting.
- **Stagger only on the way in:** 14 ms between menu items, set with `--i`.
- **Live data settles in 0.8 s.** Stats arrive every second, so a bar finishes moving before the next value lands. The old 1.1 s meant bars never stopped moving.

To make a new spring, sample the equation into about 32 points and check where it settles. The script used is in the commit message that added this file.

## 3. Rubber-banding

Radial menu items lean towards the pointer, but only so far, using iOS's rubber-band formula:

```
offset = (1 − 1 / (c·x / d + 1)) · d      c = 0.55, d = 10 px
```

- The item follows the pointer 1:1 while you move. When the pointer leaves, it springs home on `--spring-bounce`.
- The pull uses the separate `translate` property, so it never fights the `transform` that places and magnifies the item.

## 4. What may move

- **Only `transform` (including `scale` and `translate`) and `opacity`.** Never animate `width`, `height`, `top`, `left` or `margin`. Bars fill with `scaleX`, and their glowing tip moves with `translateX` on a separate `.tip` element.
- **Name every transitioned property.** `transition: all` is not allowed.
- **No new `filter` or `backdrop-filter` blur.** Both re-render every frame in the overlay.
- **Hover effects sit inside `@media (hover:hover) and (pointer:fine)`.**

## 5. Reduced motion

When the system asks for reduced motion, the response is **gentler, not off**:

- Loops stop. This rule already existed.
- Springs become a plain 0.15 s fade.
- The menu fades in place instead of flying out.
- Press shrink and the magnetic pull are switched off.

## 6. Ambient loops tick on a shared 10 fps grid

Looping, decorative animation (rings, orb breathing, blade glow, blinking dots, Bench spinners) does **not** run smoothly. It steps on one shared 100 ms beat.

- **Why.** In the overlay's software renderer, each frame repaints the whole 1920×1200 transparent window: about 85 ms of CPU when everything moves. Smooth loops, and loops on different beats, asked for 60 fps. The renderer pinned a whole core and still only reached about 12 fps, which made it look jittery. On one shared 10 fps beat it measured **98% → about 45% of a core**, and the page has headroom again (its frame loop went from 13 to about 50 fps), so springs you trigger play smoothly.
- **How.** Use `steps(n)` with n = (length of one keyframe segment) ÷ 0.1 s:
  - a ring spinning once in 14 s gets `steps(140)`
  - a 3 s pulse with keyframes at 0%, 50% and 100% has 1.5 s segments, so it gets `steps(15)`

  All loops start at page load, so their steps land on the same beat. A loop off the beat adds frames of its own.
- **Interactions are exempt.** Springs, hover, press and the menu stay smooth. They are short and only run while you act.
- **Hidden things don't animate, and aren't painted.** `opacity: 0` stops neither: the closed Bench kept being painted, and its stat bars re-animated after every 1 s update. That cost about 25% of a core for nothing on screen. A hidden layer gets `visibility: hidden` once its fade-out ends, and pauses its loops (see `.bench`).
- **The renderer's measured costs.** The test harness is described in the commit that added this section.
  - Animation frame rate is the main lever. Removing any single layer of the reactor saves only 5–20%.
  - GPU compositing (`WEBKIT_DISABLE_DMABUF_RENDERER` unset) reached only about 14 fps at a similar total cost, and it has frozen the animation before, so it stays off.

## 7. Calm mode

After a quiet minute (`core/calm.js`) the page adds `html.rayo-calm`: **every loop pauses where it is**, and only the core keeps breathing, as an opacity change on a 2 fps beat (`steps(6)` over a 3 s segment).

- **Why everything, not just the rings.** In the software renderer any running loop repaints the whole window. Pausing only the rings measured 40% → 42% of a core, so no saving. Pausing everything except a 2 fps breath measured **42% → 18%**.
- **What wakes it** for another minute:
  - the pointer, a click or a key
  - a voice state change
  - the desktop shown again after being covered
  - an action
  - a status word changing (`rayo:wake` from `hud.js`)
- **When it never settles:** mid-conversation, or while the menu, power bar, Bench or countdown is open.

## 8. Checking a change

1. `./run.sh` and open `http://localhost:8099`. Click the hub once, twice and three times. Press **Esc** to cancel the countdown.
2. Check all four themes (`?theme=rayo|cyberpunk|cyborg|tron`).
3. Turn reduced motion on in the browser's developer tools and check again.
4. Measure the overlay's CPU (the `WebKitWebProcess` under `rayo-overlay.py`) over 20 s, before and after. It must not go up.
