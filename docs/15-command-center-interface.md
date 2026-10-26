# Command-center interface

October 25, 2026. The owner's reference image informs the midnight-blue palette, cyan highlights, fine panel frames, and circular visual language. The composition, illustration, navigation, and implementation are original. The supplied image is not embedded or copied into application assets.

## Layout and data

`web/src/CommandCenter.tsx` replaces the previous three-column overview. A large voice panel sits beside a combined weather/calendar panel. Task activity, Second Brain, and configured systems form the next row. Request shortcuts prepare editable drafts; sending remains an explicit action.

The core retains actual microphone/output-level animation. Its concentric rings, orbital lines, light field, and waveform are CSS/SVG. It uses no generated bitmap, external font, animation package, or continuous JavaScript rendering loop. Existing reduced-motion and hidden-window animation controls remain effective.

The header clock follows the configured timezone. Voice state, task/approval counts, enabled routines, memory connection, MCP tools, and model configuration come from existing APIs. Model cards say **Configured**, since a saved model name alone does not establish provider health. The footer reflects the selected local/cloud profile. The memory constellation is an illustration, not a quantitative graph. No CPU, storage, memory-total, or activity metrics are invented.

Weather and calendar preserve their actual responses and setup actions. Empty or unconfigured states remain explicit. Source attribution is available visually; the spoken source policy is unchanged.

## Shared theme and controls

`web/src/hud.css` extends the common theme across navigation, conversation, tasks, forms, and settings. The dark palette uses cyan highlights with mint status, muted violet for local intelligence, and existing warning/error colors. Light mode keeps the same hierarchy with darker accents.

Microphone mute, stop speaking, emergency stop, private sessions, scope selection, approvals, and settings keep their existing handlers. Navigation buttons retain accessible names when their visual labels collapse. The clock does not announce every tick. CSS animations respect reduced motion and pause when the window is hidden.

Grid rows and sidebar height are bounded by the viewport. Short windows scroll within the workspace/sidebar; controls do not become unreachable below an oversized grid row. The supplementary sidebar voice strip is hidden in shorter windows; the main voice core and toolbar control remain available.

## Correct asset and status delivery

The SVG identity now lives at `web/src/assets/jarvis.svg` and is imported by the React application and HTML favicon. Vite emits a fingerprinted asset under `/assets`, which the existing service serves as an image. The previous public-root `/jarvis.svg` URL reached the SPA fallback and returned HTML, causing a broken logo in the native WebView.

The event stream can replay historical voice transitions during page startup. Voice-state events now refresh the authoritative current status rather than briefly painting an old microphone state over the initial snapshot. Live audio levels continue to update independently.

## Verification

- TypeScript checking and the production Vite build pass.
- Actual authenticated browser checks covered 1320×808, 800×650, and 390×844 layouts, dark/light themes, logo decoding, and horizontal overflow.
- The minimum desktop layout has a bounded workspace and a scrollable sidebar. Mobile navigation retains six accessible names.
- Task navigation, settings fields, and request-draft preparation were exercised without submitting a model request.
- The native app was restarted through Launch Services with its existing signed executable, then the updated interface and restored microphone authorization were inspected.
- UI verification made no model-generation requests and played no test audio. Voice was suspended while the owner was away and restored after the owner returned.

Weather/calendar integrations require separately configured accounts and their own integration tests. Presentation checks do not certify those external connections.

Local screenshots and the UI verification report stay under ignored `output/`. Screenshots can contain personal conversation titles and are not published to the repository.
