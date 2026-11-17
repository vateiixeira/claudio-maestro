import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import LabelBadges from '../LabelBadges.vue'
import { useLabelsStore } from '../../../stores/labels'
import { makeLabel } from '../../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia
beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  useLabelsStore().labels = [
    makeLabel({ id: 1, slug: 'urgente', color: '#ef4444' }),
    makeLabel({ id: 2, slug: 'revisao', color: '#facc15' }),
    makeLabel({ id: 3, slug: 'backend', color: '#1d4ed8' }),
    makeLabel({ id: 4, slug: 'infra', color: '#000000' }),
  ]
})

const mountBadges = (props: Record<string, unknown>) => mount(LabelBadges, { props, global: { plugins: [pinia] } })

describe('badges de etiquetas', () => {
  it('mostra o slug de cada etiqueta, com fundo tingido, ponto de cor e texto legível', () => {
    const w = mountBadges({ ids: [1, 2] })
    const badges = w.findAll('[data-test="label-badge"]')
    expect(badges.map((b) => b.text())).toEqual(['urgente', 'revisao'])
    expect(badges[0].attributes('style')).toContain('color-mix(in srgb, #ef4444 24%, var(--color-elevated))')
    expect(badges[0].attributes('style')).toContain('--label-dot: #ef4444')
    expect(badges[0].find('[data-test="label-dot"]').exists()).toBe(true)
    expect(badges[1].attributes('data-slug')).toBe('revisao')
    expect(badges[0].attributes('title')).toBe('urgente')
  })

  it('não mostra nada sem etiquetas', () => {
    expect(mountBadges({ ids: [] }).find('[data-test="label-badges"]').exists()).toBe(false)
    expect(mountBadges({ ids: null }).find('[data-test="label-badges"]').exists()).toBe(false)
    expect(mountBadges({}).find('[data-test="label-badges"]').exists()).toBe(false)
  })

  it('ignora o id que o catálogo ainda não conhece', () => {
    const w = mountBadges({ ids: [99, 1] })
    expect(w.findAll('[data-test="label-badge"]').map((b) => b.text())).toEqual(['urgente'])
    expect(mountBadges({ ids: [99] }).find('[data-test="label-badges"]').exists()).toBe(false)
  })

  it('o excesso vira "+N" e o título lista as escondidas', () => {
    const w = mountBadges({ ids: [1, 2, 3, 4], max: 2 })
    expect(w.findAll('[data-test="label-badge"]')).toHaveLength(2)
    const more = w.find('[data-test="label-more"]')
    expect(more.text()).toBe('+2')
    expect(more.attributes('title')).toBe('backend, infra')
  })

  it('o modo compacto mostra uma só e resume o resto', () => {
    const w = mountBadges({ ids: [1, 2, 3], compact: true })
    expect(w.findAll('[data-test="label-badge"]')).toHaveLength(1)
    expect(w.find('[data-test="label-more"]').text()).toBe('+2')
  })

  it('o contêiner encolhe e corta o excesso em vez de empurrar a linha', () => {
    const classes = mountBadges({ ids: [1, 2, 3] }).get('[data-test="label-badges"]').classes()
    expect(classes).toEqual(expect.arrayContaining(['min-w-0', 'shrink', 'overflow-hidden']))
    expect(classes).not.toContain('shrink-0')
  })

  it('o modo "wrap" mostra o nome inteiro e quebra a linha em vez de cortar', () => {
    useLabelsStore().labels.push(makeLabel({ id: 5, slug: 'subir-e-acompanhar-deploy-em-producao', color: '#000000' }))
    const w = mountBadges({ ids: [5, 1, 2, 3, 4], compact: true, wrap: true })
    const container = w.get('[data-test="label-badges"]').classes()
    expect(container).toContain('flex-wrap')
    expect(container).not.toContain('overflow-hidden')
    const badges = w.findAll('[data-test="label-badge"]')
    // Every label shows, none summed up as "+N".
    expect(badges.map((b) => b.text())).toEqual(['subir-e-acompanhar-deploy-em-producao', 'urgente', 'revisao', 'backend', 'infra'])
    expect(w.find('[data-test="label-more"]').exists()).toBe(false)
    const long = badges[0].classes()
    expect(long).not.toContain('truncate')
    expect(long).not.toContain('max-w-20')
    expect(long).toContain('max-w-full')
  })

  it('sem "wrap" o badge compacto continua cortado', () => {
    const badge = mountBadges({ ids: [1], compact: true }).get('[data-test="label-badge"]').classes()
    expect(badge).toEqual(expect.arrayContaining(['truncate', 'max-w-20']))
  })
})
