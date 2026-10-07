import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js/lib/core'
import bash from 'highlight.js/lib/languages/bash'
import css from 'highlight.js/lib/languages/css'
import diff from 'highlight.js/lib/languages/diff'
import javascript from 'highlight.js/lib/languages/javascript'
import json from 'highlight.js/lib/languages/json'
import markdown from 'highlight.js/lib/languages/markdown'
import python from 'highlight.js/lib/languages/python'
import sql from 'highlight.js/lib/languages/sql'
import typescript from 'highlight.js/lib/languages/typescript'
import xml from 'highlight.js/lib/languages/xml'
import yaml from 'highlight.js/lib/languages/yaml'

// Only a few common languages, to keep the bundle small.
const languages = { bash, css, diff, javascript, json, markdown, python, sql, typescript, xml, yaml }
for (const [name, lang] of Object.entries(languages)) hljs.registerLanguage(name, lang)
hljs.registerAliases(['sh', 'shell', 'zsh', 'console'], { languageName: 'bash' })
hljs.registerAliases(['js', 'jsx', 'mjs'], { languageName: 'javascript' })
hljs.registerAliases(['ts', 'tsx', 'vue'], { languageName: 'typescript' })
hljs.registerAliases(['py'], { languageName: 'python' })
hljs.registerAliases(['html', 'svg'], { languageName: 'xml' })
hljs.registerAliases(['yml'], { languageName: 'yaml' })
hljs.registerAliases(['md'], { languageName: 'markdown' })

// `html: false` is required: the text comes from the model and from command output.
function escapeHtml(text: string): string {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

const md = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: false,
  highlight(code, lang) {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return `<pre class="hljs"><code>${hljs.highlight(code, { language: lang, ignoreIllegals: true }).value}</code></pre>`
      } catch {
        // falls through to plain escaped code
      }
    }
    return `<pre class="hljs"><code>${escapeHtml(code)}</code></pre>`
  },
})

export interface MarkdownRef { path: string; anchor: string | null }
export interface RenderOptions {
  /** Conversation whose folder relative paths start from; without it nothing links to the reader. */
  sessionId?: string
  /** Folder of the document being read: relative links inside it start here. */
  baseDir?: string
  /** On the reader page: headings get ids and reader links stay in the same tab. */
  reader?: boolean
}
interface Env extends RenderOptions { slugs?: Map<string, number> }

// Only real schemes: `plano.md:12` must not look like the scheme `plano.md:`.
const SCHEME = /^(?:[a-z][a-z0-9+.-]*:\/\/|mailto:|javascript:|vbscript:|data:|file:)/i
const MD_REF = /^(\S+?\.md)(?:#(\S*))?(?::\d+(?:-\d+)?)?$/i

/** The `.md` file a piece of text points at, with its `#anchor`; `:line` is dropped. */
export function parseMarkdownRef(text: string): MarkdownRef | null {
  const value = text.trim()
  if (!value || SCHEME.test(value)) return null
  const match = MD_REF.exec(value)
  if (!match) return null
  return { path: match[1]!, anchor: match[2] ? match[2] : null }
}

/**
 * The `.md` file a tool's `file_path` points at. A tool path is always a path, never free text,
 * so spaces are fine: only the extension and the lack of a URL scheme are checked.
 */
export function markdownFileRef(path: string): MarkdownRef | null {
  const value = path.trim()
  if (!value || SCHEME.test(value) || !/\.md$/i.test(value)) return null
  return { path: value, anchor: null }
}

export function markdownViewHref(sessionId: string, ref: MarkdownRef): string {
  const hash = ref.anchor ? `#${encodeURIComponent(ref.anchor)}` : ''
  return `/sessions/${encodeURIComponent(sessionId)}/ver?caminho=${encodeURIComponent(ref.path)}${hash}`
}

export function dirname(path: string): string {
  const at = path.lastIndexOf('/')
  return at <= 0 ? '/' : path.slice(0, at)
}

/** `relative` read from `baseDir`, with `.` and `..` folded; absolute and `~` paths stay as they are. */
export function joinPath(baseDir: string, relative: string): string {
  if (relative.startsWith('/') || relative.startsWith('~')) return relative
  const parts: string[] = []
  for (const part of `${baseDir}/${relative}`.split('/')) {
    if (!part || part === '.') continue
    if (part === '..') parts.pop()
    else parts.push(part)
  }
  return `/${parts.join('/')}`
}

export function slugify(text: string): string {
  return text
    .toLowerCase()
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
}

function safeDecode(text: string): string {
  try {
    return decodeURIComponent(text)
  } catch {
    return text
  }
}

/**
 * Reader address for a path, or null when it is not a `.md` or there is no conversation.
 * `encoded` is for markdown link hrefs, whose spaces and accents arrive percent-encoded: the text
 * is parsed first (it has no spaces) and only the path and anchor are decoded afterwards.
 */
function viewHref(raw: string, env: Env, encoded = false): string | null {
  if (!env.sessionId) return null
  const ref = parseMarkdownRef(raw)
  if (!ref) return null
  const found = encoded ? { path: safeDecode(ref.path), anchor: ref.anchor && safeDecode(ref.anchor) } : ref
  const path = env.baseDir ? joinPath(env.baseDir, found.path) : found.path
  return markdownViewHref(env.sessionId, { path, anchor: found.anchor })
}

function newTab(token: { attrSet(name: string, value: string): void }) {
  token.attrSet('target', '_blank')
  token.attrSet('rel', 'noopener noreferrer')
}

// Links open outside the app, except links to the reader (and `#anchors` on the reader page).
type Rule = NonNullable<typeof md.renderer.rules.link_open>
const defaultLinkOpen: Rule =
  md.renderer.rules.link_open ?? ((tokens, idx, options, _env, self) => self.renderToken(tokens, idx, options))
md.renderer.rules.link_open = (...args: Parameters<Rule>) => {
  const [tokens, idx, , env] = args
  const token = tokens[idx]!
  const href = String(token.attrGet('href') ?? '')
  const view = viewHref(href, env as Env, true)
  if (view) {
    token.attrSet('href', view)
    token.attrSet('data-md-view', '')
    if (!(env as Env).reader) newTab(token)
  } else if (!((env as Env).reader && href.startsWith('#'))) {
    newTab(token)
  }
  return defaultLinkOpen(...args)
}

function insideLink(tokens: { type: string }[], idx: number): boolean {
  for (let i = idx - 1; i >= 0; i--) {
    if (tokens[i]!.type === 'link_close') return false
    if (tokens[i]!.type === 'link_open') return true
  }
  return false
}

// Inline code naming a `.md` links to the reader.
const defaultCodeInline = md.renderer.rules.code_inline!
md.renderer.rules.code_inline = (tokens, idx, options, env, self) => {
  const code = defaultCodeInline(tokens, idx, options, env, self)
  if (insideLink(tokens, idx)) return code
  const view = viewHref(tokens[idx]!.content, env as Env)
  if (!view) return code
  const target = (env as Env).reader ? '' : ' target="_blank" rel="noopener noreferrer"'
  return `<a href="${escapeHtml(view)}" class="md-view-link" data-md-view${target}>${code}</a>`
}

/** Prefix of heading ids on the reader page, so none collides with the app's own ids (`#app`). */
export const HEADING_ID_PREFIX = 'md-'

// Reader page: headings get ids, so `#anchor` links can scroll to them.
const defaultHeadingOpen: Rule =
  md.renderer.rules.heading_open ?? ((tokens, idx, options, _env, self) => self.renderToken(tokens, idx, options))
md.renderer.rules.heading_open = (...args: Parameters<Rule>) => {
  const [tokens, idx, , env] = args
  const e = env as Env
  if (e.reader) {
    const slug = slugify(tokens[idx + 1]?.content ?? '') || 'secao'
    e.slugs ??= new Map()
    const seen = (e.slugs.get(slug) ?? 0) + 1
    e.slugs.set(slug, seen)
    tokens[idx]!.attrSet('id', `${HEADING_ID_PREFIX}${seen === 1 ? slug : `${slug}-${seen}`}`)
  }
  return defaultHeadingOpen(...args)
}

// `- [ ]` and `- [x]` items show a disabled box. After text_join, so `[ ] a` is one text token.
md.core.ruler.push('task_checkbox', (state) => {
  const tokens = state.tokens
  for (let i = 2; i < tokens.length; i++) {
    const inline = tokens[i]!
    if (inline.type !== 'inline' || tokens[i - 1]!.type !== 'paragraph_open' || tokens[i - 2]!.type !== 'list_item_open') continue
    const first = inline.children?.[0]
    const match = first?.type === 'text' ? /^\[([ xX])\]\s+/.exec(first.content) : null
    if (!first || !match) continue
    first.content = first.content.slice(match[0].length)
    const box = new state.Token('task_checkbox', '', 0)
    box.meta = { checked: match[1] !== ' ' }
    inline.children!.unshift(box)
    tokens[i - 2]!.attrJoin('class', 'task-item')
  }
})
md.renderer.rules.task_checkbox = (tokens, idx) =>
  `<input type="checkbox" class="task-checkbox" disabled${tokens[idx]!.meta?.checked ? ' checked' : ''}> `

// Fenced blocks get a copy button (handled by `onCodeCopyClick`). The wrapper is added here and
// not in `highlight`, because markdown-it only skips its own <pre> wrapper when the result starts with `<pre`.
const defaultFence = md.renderer.rules.fence!
md.renderer.rules.fence = (tokens, idx, options, env, self) =>
  `<div class="code-block"><button type="button" class="code-copy" data-code-copy aria-label="Copiar código">Copiar</button>${defaultFence(tokens, idx, options, env, self)}</div>`

export function renderMarkdown(text: string, options: RenderOptions = {}): string {
  const env: Env = { ...options }
  return md.render(text, env as Record<string, unknown>)
}
