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

### Upload Flow
- Updated the upload dropzone with rounded corners, gradients, and press states.
- Refined progress list styling with elevated cards and iOS-like separators.

### Auth & Account
- Refactored auth cards with larger radii, gradient surface, and full-width CTAs.
- Added pressed states for buttons and cards.

### Micro-Interactions & Motion
- Added press/hover transitions on buttons, tabs, and cards.
- Added subtle fade/slide transitions for search results, image cards, and answer panels.
- Added active tab states for the bottom navigation to mirror iOS tab selection.

### Files Updated
- `search-app/app/templates/index.html`
- `search-app/app/static/style.css`
