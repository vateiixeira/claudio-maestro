// Side-effect module: `main.ts` imports it first, so the old `vibing:*` keys are moved
// before any other module reads `maestro:*` while it loads (e.g. sidebarCollapse).
import { migrateLegacyStorage } from './legacyStorage'

migrateLegacyStorage()
