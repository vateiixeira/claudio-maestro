import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import RepoName from '../RepoName.vue'

describe('nome do repositório', () => {
  it('worktree: nome curto e pasta pai na mesma linha', () => {
    const wrapper = mount(RepoName, { props: { name: '.claude/worktrees/chat' } })
    expect(wrapper.get('[data-test="repo-short-name"]').text()).toBe('chat')
    expect(wrapper.get('[data-test="repo-parent-name"]').text()).toBe('.claude/worktrees')
    expect(wrapper.classes()).toContain('flex-row')
    expect(wrapper.classes()).toContain('items-baseline')
    expect(wrapper.classes()).not.toContain('flex-col')
  })

  it('sem pasta pai, só o nome', () => {
    const wrapper = mount(RepoName, { props: { name: 'app' } })
    expect(wrapper.get('[data-test="repo-short-name"]').text()).toBe('app')
    expect(wrapper.find('[data-test="repo-parent-name"]').exists()).toBe(false)
  })

  it('quiet deixa o nome em text-fg-muted e sem negrito', () => {
    const loud = mount(RepoName, { props: { name: 'app' } })
    expect(loud.get('[data-test="repo-short-name"]').classes()).toEqual(expect.arrayContaining(['text-fg', 'font-semibold']))
    const quiet = mount(RepoName, { props: { name: 'app', quiet: true } })
    const classes = quiet.get('[data-test="repo-short-name"]').classes()
    expect(classes).toContain('text-fg-muted')
    expect(classes).not.toContain('text-fg')
    expect(classes).not.toContain('font-semibold')
  })
})
