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
  it('mostra o slug de cada etiqueta, com a cor e o texto legível', () => {
    const w = mountBadges({ ids: [1, 2] })
    const badges = w.findAll('[data-test="label-badge"]')
    expect(badges.map((b) => b.text())).toEqual(['urgente', 'revisao'])
    expect(badges[0].attributes('style')).toContain('background-color: rgb(239, 68, 68)')
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
})
