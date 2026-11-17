/**
 * Grid shared by the repository rows and the column header. It lives in a .ts file under src/
 * so Tailwind finds the classes; container queries keep it tied to the panel width, not the viewport.
 */
export const REPO_ROW_GRID = '@3xl:grid @3xl:grid-cols-[0.875rem_minmax(0,1fr)_14rem_11rem_10rem_2rem] @3xl:items-center @3xl:gap-x-3.5'
