import { effectScope, ref } from 'vue'
import { beforeEach, expect, it, vi } from 'vitest'
import { useRepoExpansion } from '../repoExpansion'

beforeEach(() => localStorage.clear())

it('isola escolhas por projeto, repositório e seção e restaura recolhimento', () => {
  const scope = effectScope()
  scope.run(() => {
    useRepoExpansion(() => 1, () => '/repo', 'scm', () => true).value = false
    expect(useRepoExpansion(() => 1, () => '/repo', 'scm', () => true).value).toBe(false)
    expect(useRepoExpansion(() => 2, () => '/repo', 'scm', () => true).value).toBe(true)
    expect(useRepoExpansion(() => 1, () => '/other', 'scm', () => true).value).toBe(true)
    expect(useRepoExpansion(() => 1, () => '/repo', 'commits', () => true).value).toBe(true)
  })
  scope.stop()
})

it('mantém escolha manual mesmo sem storage e com mudança do padrão', () => {
  const read = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw Error('blocked') })
  const write = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw Error('blocked') })
  const scope = effectScope()
  scope.run(() => {
    const initial = ref(false)
    const open = useRepoExpansion(() => 1, () => '/repo', 'commits', () => initial.value)
    open.value = true
    open.value = false
    initial.value = true
    expect(open.value).toBe(false)
  })
  scope.stop()
  read.mockRestore()
  write.mockRestore()
})
