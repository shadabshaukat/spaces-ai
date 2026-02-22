## SpacesAI UI Updates

### Summary
- Implemented a mobile-first SaaS UI that maps cleanly to an iOS app layout.
- Added iOS-inspired list separators, pressed states, and subtle micro-interactions.
- Introduced a bottom navigation bar for quick access to Search, Library, Upload, Research, and Account.

### Layout & Navigation
- Added a sticky bottom navigation bar with five primary actions and matching icons.
- Updated the top bar title to “SpacesAI”.
- Ensured the app shell has spacing for the mobile bottom nav.
- Introduced an iOS-style PWA shell with tabbed screens and screen headers.

### Search Experience
- Refined search panel spacing, tabs, and settings panel styling for mobile-first layout.
- Added fade/slide-in micro-interactions for answer, results, and image results.
- Added staggered animation for result items and image cards.

### Knowledge Base
- Reworked Knowledge Base list into a clean iOS table-like list.
- Added separators, reduced padding, and tightened metadata layout.
- Improved thumbnail/preview sizing for consistency.
- Simplified KB metadata to highlight source/storage/created date, with a secondary line for chunks/images/tags.
- Rebalanced image gallery cards so captions and tags sit below left-aligned thumbnails.

### Upload Flow
- Updated the upload dropzone with rounded corners, gradients, and press states.
- Refined progress list styling with elevated cards and iOS-like separators.
- Updated dropzone helper text to “Drop files here or use the file chooser above.”
- Limited image embedding status badges to image uploads only, with warnings only when image embeddings fail.

### Auth & Account
- Refactored auth cards with larger radii, gradient surface, and full-width CTAs.
- Added pressed states for buttons and cards.
- Restyled the Account toolbar into stacked segmented-control blocks for Space selection and New space creation.
- Added a logged-out landing panel with a “Try SpacesAI” CTA that opens the auth modal only on click.
- Limited the Account tab to Spaces when logged in.

### iOS-Style Polish Recommendations
- Use a consistent 8/12/16 spacing scale across panels, cards, and list rows.
- Add subtle haptic-like feedback via scale/opacity changes on press states for buttons and tabs.
- Maintain a single typographic hierarchy (headline/section/label/body) across Search, KB, Upload, and Account.
- Keep modal headers aligned to iOS sheet patterns with a centered title and optional close button.
- Use muted monochrome icons with consistent stroke weight across the bottom nav.

### Micro-Interactions & Motion
- Added press/hover transitions on buttons, tabs, and cards.
- Added subtle fade/slide transitions for search results, image cards, and answer panels.
- Added active tab states for the bottom navigation to mirror iOS tab selection.

### Image Search
- Ensured image search card actions stay pinned to the bottom for consistent layouts.
- Added Enter-key support for image mode searches across the main input, tags, and Top-K fields.
- Rendered all KB image tags (no truncation) and filtered numeric OCR noise.
- Styled image tags as purple gradient pills for consistent visual emphasis.

### Deep Research
- Hid the sign-in lock message once logged in.
- Auto-generated session titles when missing using the email prefix and a random hash.
- Set Deep Research to be more local-first by default (web toggle unchecked).

### Files Updated
- `search-app/app/templates/index.html`
- `search-app/app/static/style.css`
