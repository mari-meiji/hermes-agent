import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { ToolsetConfig } from '@/types/hermes'

const getToolsetConfig = vi.fn()
const selectToolsetProvider = vi.fn()
const setEnvVar = vi.fn()
const deleteEnvVar = vi.fn()
const revealEnvVar = vi.fn()
const runToolsetPostSetup = vi.fn()
const getActionStatus = vi.fn()

vi.mock('@/hermes', () => ({
  getToolsetConfig: (name: string) => getToolsetConfig(name),
  selectToolsetProvider: (name: string, provider: string) => selectToolsetProvider(name, provider),
  setEnvVar: (key: string, value: string) => setEnvVar(key, value),
  deleteEnvVar: (key: string) => deleteEnvVar(key),
  revealEnvVar: (key: string) => revealEnvVar(key),
  runToolsetPostSetup: (name: string, key: string) => runToolsetPostSetup(name, key),
  getActionStatus: (name: string, lines?: number) => getActionStatus(name, lines)
}))

vi.mock('@/store/notifications', () => ({
  notify: vi.fn(),
  notifyError: vi.fn()
}))

vi.mock('@/store/activity', () => ({
  upsertDesktopActionTask: vi.fn()
}))

function config(overrides: Partial<ToolsetConfig> = {}): ToolsetConfig {
  return {
    name: 'tts',
    has_category: true,
    active_provider: null,
    providers: [
      {
        name: 'Microsoft Edge TTS',
        badge: 'free',
        tag: 'No API key needed',
        env_vars: [],
        post_setup: null,
        requires_nous_auth: false,
        is_active: false
      },
      {
        name: 'ElevenLabs',
        badge: 'paid',
        tag: 'Most natural voices',
        env_vars: [
          { key: 'ELEVENLABS_API_KEY', prompt: 'ElevenLabs API key', url: 'https://x', default: null, is_set: false }
        ],
        post_setup: null,
        requires_nous_auth: false,
        is_active: false
      }
    ],
    ...overrides
  }
}

beforeEach(() => {
  getToolsetConfig.mockResolvedValue(config())
  selectToolsetProvider.mockResolvedValue({ ok: true, name: 'tts', provider: 'ElevenLabs' })
  setEnvVar.mockResolvedValue({ ok: true })
  deleteEnvVar.mockResolvedValue({ ok: true })
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('ToolsetConfigPanel', () => {
  it('lists providers from the config endpoint', async () => {
    const { ToolsetConfigPanel } = await import('./toolset-config-panel')
    render(<ToolsetConfigPanel onConfiguredChange={vi.fn()} toolset="tts" />)

    expect(await screen.findByText('Microsoft Edge TTS')).toBeTruthy()
    expect(screen.getByText('ElevenLabs')).toBeTruthy()
    expect(getToolsetConfig).toHaveBeenCalledWith('tts')
  })

  it('selects a provider when clicked', async () => {
    const { ToolsetConfigPanel } = await import('./toolset-config-panel')
    render(<ToolsetConfigPanel onConfiguredChange={vi.fn()} toolset="tts" />)

    const elevenlabs = await screen.findByRole('button', { name: /ElevenLabs/ })
    fireEvent.click(elevenlabs)

    await waitFor(() => expect(selectToolsetProvider).toHaveBeenCalledWith('tts', 'ElevenLabs'))
  })

  it('saves an API key for a provider env var', async () => {
    const { ToolsetConfigPanel } = await import('./toolset-config-panel')
    render(<ToolsetConfigPanel onConfiguredChange={vi.fn()} toolset="tts" />)

    // Select the keyed provider so its env vars render.
    const elevenlabs = await screen.findByRole('button', { name: /ElevenLabs/ })
    fireEvent.click(elevenlabs)

    // Click "Set" to reveal the input for the unset key.
    fireEvent.click(await screen.findByRole('button', { name: 'Set' }))

    const input = await screen.findByPlaceholderText('ElevenLabs API key')
    fireEvent.change(input, { target: { value: 'sk-test-123' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(setEnvVar).toHaveBeenCalledWith('ELEVENLABS_API_KEY', 'sk-test-123'))
  })

  it('expands the active provider on load, not just the first configured one', async () => {
    // ElevenLabs is the active provider per config, even though the keyless
    // Edge TTS provider sorts first and is also "configured". The panel must
    // honor is_active and expand ElevenLabs (so its API-key field renders)
    // rather than defaulting to the first keyless provider. Regression test
    // for the GUI showing the wrong provider selected after relaunch.
    getToolsetConfig.mockResolvedValue(
      config({
        active_provider: 'ElevenLabs',
        providers: [
          {
            name: 'Microsoft Edge TTS',
            badge: 'free',
            tag: 'No API key needed',
            env_vars: [],
            post_setup: null,
            requires_nous_auth: false,
            is_active: false
          },
          {
            name: 'ElevenLabs',
            badge: 'paid',
            tag: 'Most natural voices',
            env_vars: [
              {
                key: 'ELEVENLABS_API_KEY',
                prompt: 'ElevenLabs API key',
                url: 'https://x',
                default: null,
                is_set: true
              }
            ],
            post_setup: null,
            requires_nous_auth: false,
            is_active: true
          }
        ]
      })
    )

    const { ToolsetConfigPanel } = await import('./toolset-config-panel')
    render(<ToolsetConfigPanel onConfiguredChange={vi.fn()} toolset="tts" />)

    // The active provider's env-var field only renders when it's the expanded
    // one — so finding it proves ElevenLabs (not Edge TTS) was auto-expanded.
    expect(await screen.findByText('ELEVENLABS_API_KEY')).toBeTruthy()
    // No provider selection was triggered — this is purely reflecting state.
    expect(selectToolsetProvider).not.toHaveBeenCalled()
  })

  it('runs a provider post-setup install hook and tails its log', async () => {
    // A browser-style toolset whose active provider declares a post_setup hook.
    getToolsetConfig.mockResolvedValue(
      config({
        name: 'browser',
        active_provider: 'Camofox',
        providers: [
          {
            name: 'Camofox',
            badge: 'local',
            tag: 'Stealth local browser',
            env_vars: [],
            post_setup: 'camofox',
            requires_nous_auth: false,
            is_active: true
          }
        ]
      })
    )
    runToolsetPostSetup.mockResolvedValue({ ok: true, pid: 4321, name: 'tools-post-setup', key: 'camofox' })
    // First poll: still running; second poll: finished cleanly.
    getActionStatus
      .mockResolvedValueOnce({
        exit_code: null,
        lines: ['Installing Camofox browser server...'],
        name: 'tools-post-setup',
        pid: 4321,
        running: true
      })
      .mockResolvedValue({
        exit_code: 0,
        lines: ['Installing Camofox browser server...', "Post-setup 'camofox' complete"],
        name: 'tools-post-setup',
        pid: 4321,
        running: false
      })

    const { ToolsetConfigPanel } = await import('./toolset-config-panel')
    render(<ToolsetConfigPanel onConfiguredChange={vi.fn()} toolset="browser" />)

    fireEvent.click(await screen.findByRole('button', { name: /Run setup/ }))

    await waitFor(() => expect(runToolsetPostSetup).toHaveBeenCalledWith('browser', 'camofox'))
    // The install log is tailed inline. The first poll fires after a 1200ms
    // delay (mirrors command-center's poll cadence), so allow >1200ms here.
    await waitFor(() => expect(getActionStatus).toHaveBeenCalledWith('tools-post-setup', 300), {
      timeout: 4000
    })
  })
})
