import { describe, expect, it } from 'vitest'
import { activityText, isActiveToday, shortPath, staleDays } from '../projectsList'

// 2026-11-17 10:40 local, in seconds.
const now = Math.floor(new Date(2026, 10, 17, 10, 40).getTime() / 1000)
const DAY = 86400

describe('shortPath', () => {
  it('troca a pasta do usuário por ~', () => {
    expect(shortPath('/home/ana/dev/loja-online')).toBe('~/dev/loja-online')
    expect(shortPath('/Users/ana/x')).toBe('~/x')
    expect(shortPath('/home/ana')).toBe('~')
  })
  it('mantém o que está fora da pasta do usuário', () => {
    expect(shortPath('/opt/app')).toBe('/opt/app')
    expect(shortPath('/homework/ana/x')).toBe('/homework/ana/x')
  })
})

describe('isActiveToday', () => {
  it('vale com atividade hoje ou com conversa aberta', () => {
    expect(isActiveToday(now - 60, 0, now)).toBe(true)
    expect(isActiveToday(now - 5 * DAY, 1, now)).toBe(true)
    expect(isActiveToday(now - 5 * DAY, 0, now)).toBe(false)
    expect(isActiveToday(0, 0, now)).toBe(false)
  })
  it('hoje começa à meia-noite local', () => {
    const midnight = Math.floor(new Date(2026, 10, 17).getTime() / 1000)
    expect(isActiveToday(midnight, 0, now)).toBe(true)
    expect(isActiveToday(midnight - 1, 0, now)).toBe(false)
  })
})

describe('staleDays', () => {
  it('conta os dias só com alterações e atividade acima de 2 dias', () => {
    expect(staleDays(11, now - 18 * DAY, now)).toBe(18)
    expect(staleDays(11, now - 2 * DAY, now)).toBeNull()
    expect(staleDays(11, now - 2 * DAY - 1, now)).toBe(2)
    expect(staleDays(0, now - 18 * DAY, now)).toBeNull()
    expect(staleDays(3, 0, now)).toBeNull()
  })
})

describe('activityText', () => {
  it('é relativa perto de agora, data em outro dia e "sem uso" sem atividade', () => {
    expect(activityText(now - 30, now)).toBe('agora')
    expect(activityText(now - 15 * 60, now)).toBe('há 15 min')
    expect(activityText(now - 3600 - 5, now)).toBe('há 1 h')
    expect(activityText(Math.floor(new Date(2026, 10, 12, 9).getTime() / 1000), now)).toBe('12 nov')
    expect(activityText(Math.floor(new Date(2026, 10, 16, 23).getTime() / 1000), now)).toBe('16 nov')
    expect(activityText(Math.floor(new Date(2025, 11, 30, 9).getTime() / 1000), now)).toBe('30 dez 2025')
    expect(activityText(0, now)).toBe('sem uso')
  })
})
