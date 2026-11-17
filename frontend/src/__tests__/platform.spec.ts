import { afterEach, describe, expect, it, vi } from 'vitest'
import { isMacPlatform } from '../platform'

afterEach(() => vi.restoreAllMocks())

describe('isMacPlatform', () => {
  it.each([
    ['MacIntel', true],
    ['iPhone', true],
    ['Linux x86_64', false],
    ['Win32', false],
    ['', false],
  ])('plataforma "%s"', (platform, expected) => {
    vi.spyOn(navigator, 'platform', 'get').mockReturnValue(platform)
    expect(isMacPlatform()).toBe(expected)
  })
})
