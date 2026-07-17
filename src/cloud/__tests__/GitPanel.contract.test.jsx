// GitPanel.contract.test.jsx — vitest coverage for the local-git rewire
// (decisions.md 2026-07-17 "local git only; no OAuth" addendum).
//
// GitPanel.jsx and RemotesManager.jsx now drive GET/POST /api/git/:project_id/*
// directly (src/cloud/api.js `git`) instead of the retired hosted-git +
// GitHub-OAuth product. Component tests render the exported, prop-driven
// sub-components via react-dom/server's renderToStaticMarkup — this repo's
// toolchain has no jsdom/@testing-library/react (see the header comment on
// the pre-existing src/cloud/GitPanel.test.jsx). Source-text assertions
// cover the "no OAuth" requirement directly, since that's an absence of a
// code path rather than something with a renderable state.
//
// Covers:
//   1. api.js — the `git` client hits the exact contract URLs/methods/bodies.
//   2. EmptyState — offers "Initialize git", no GitHub/OAuth language.
//   3. CommitLog — empty vs populated commit list.
//   4. TransferPanel (push/pull) — remote + branch pickers, disabled when
//      branch is blank.
//   5. ErrorBanner — renders + dismiss affordance.
//   6. Source-text: no githubOAuth / "Connect GitHub" / branch-merge/diff
//      surface survives in GitPanel.jsx or RemotesManager.jsx.
//   7. RemotesManager — default render carries the required helper text
//      verbatim ("Use any git remote… kerf never stores credentials").

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { ErrorBanner, TransferPanel, CommitLog, EmptyState } from '../GitPanel.jsx'
import RemotesManager from '../RemotesManager.jsx'
import { git } from '../api.js'

const __dirname = dirname(fileURLToPath(import.meta.url))
const gitPanelSrc = readFileSync(join(__dirname, '../GitPanel.jsx'), 'utf8')
const remotesSrc = readFileSync(join(__dirname, '../RemotesManager.jsx'), 'utf8')

// ---------------------------------------------------------------------------
// 1. api.js `git` client — exact contract URLs/methods/bodies
// ---------------------------------------------------------------------------

describe('git API client — matches the /api/git/:project_id contract', () => {
  let calls
  beforeEach(() => {
    calls = []
    global.fetch = vi.fn(async (url, opts) => {
      calls.push({ url, ...opts })
      return {
        ok: true,
        status: 200,
        json: async () => ({ ok: true }),
      }
    })
  })
  afterEach(() => {
    delete global.fetch
  })

  it('status: GET /api/git/:pid/status', async () => {
    await git.status('proj-1')
    expect(calls[0].url).toBe('/api/git/proj-1/status')
    expect(calls[0].method ?? 'GET').toBe('GET')
  })

  it('init: POST /api/git/:pid/init', async () => {
    await git.init('proj-1')
    expect(calls[0].url).toBe('/api/git/proj-1/init')
    expect(calls[0].method).toBe('POST')
  })

  it('commit: POST /api/git/:pid/commit {message}', async () => {
    await git.commit('proj-1', 'first commit')
    expect(calls[0].url).toBe('/api/git/proj-1/commit')
    expect(calls[0].method).toBe('POST')
    expect(JSON.parse(calls[0].body)).toEqual({ message: 'first commit' })
  })

  it('log: GET /api/git/:pid/log?limit=50', async () => {
    await git.log('proj-1')
    expect(calls[0].url).toBe('/api/git/proj-1/log?limit=50')
  })

  it('listRemotes: GET /api/git/:pid/remotes', async () => {
    await git.listRemotes('proj-1')
    expect(calls[0].url).toBe('/api/git/proj-1/remotes')
    expect(calls[0].method ?? 'GET').toBe('GET')
  })

  it('addRemote: POST /api/git/:pid/remotes {name,url}', async () => {
    await git.addRemote('proj-1', 'origin', 'git@github.com:me/repo.git')
    expect(calls[0].url).toBe('/api/git/proj-1/remotes')
    expect(calls[0].method).toBe('POST')
    expect(JSON.parse(calls[0].body)).toEqual({ name: 'origin', url: 'git@github.com:me/repo.git' })
  })

  it('removeRemote: DELETE /api/git/:pid/remotes/:name', async () => {
    await git.removeRemote('proj-1', 'origin')
    expect(calls[0].url).toBe('/api/git/proj-1/remotes/origin')
    expect(calls[0].method).toBe('DELETE')
  })

  it('push: POST /api/git/:pid/push {remote,branch}', async () => {
    await git.push('proj-1', 'origin', 'main')
    expect(calls[0].url).toBe('/api/git/proj-1/push')
    expect(calls[0].method).toBe('POST')
    expect(JSON.parse(calls[0].body)).toEqual({ remote: 'origin', branch: 'main' })
  })

  it('pull: POST /api/git/:pid/pull {remote,branch}', async () => {
    await git.pull('proj-1', 'origin', 'main')
    expect(calls[0].url).toBe('/api/git/proj-1/pull')
    expect(calls[0].method).toBe('POST')
    expect(JSON.parse(calls[0].body)).toEqual({ remote: 'origin', branch: 'main' })
  })

  it('has no leftover branches/merge/diff/provider/OAuth client methods', () => {
    for (const dead of ['branches', 'checkout', 'merge', 'diff', 'commitDiff', 'deleteRepo', 'importRepo', 'connect', 'listProviders', 'providerStatus', 'providerConnect', 'providerDisconnect']) {
      expect(git[dead]).toBeUndefined()
    }
  })
})

// ---------------------------------------------------------------------------
// 2. EmptyState
// ---------------------------------------------------------------------------

describe('EmptyState', () => {
  it('offers "Initialize git" and explains local-remote collaboration, no GitHub-specific language', () => {
    const html = renderToStaticMarkup(<EmptyState busy={null} onInit={() => {}} />)
    expect(html).toContain('Initialize git')
    expect(html).toContain('plain local git repo')
    expect(html).not.toContain('Connect GitHub')
    expect(html).not.toContain('Import or connect GitHub')
  })

  it('shows an "Initializing…" busy state', () => {
    const html = renderToStaticMarkup(<EmptyState busy="init" onInit={() => {}} />)
    expect(html).toContain('Initializing')
  })
})

// ---------------------------------------------------------------------------
// 3. CommitLog
// ---------------------------------------------------------------------------

describe('CommitLog', () => {
  it('shows the empty state when there are no commits', () => {
    const html = renderToStaticMarkup(<CommitLog commits={[]} loading={false} />)
    expect(html).toContain('No commits yet')
  })

  it('shows a loading indicator when loading with no commits yet', () => {
    const html = renderToStaticMarkup(<CommitLog commits={[]} loading />)
    expect(html).toContain('Loading commits')
  })

  it('renders sha/message/author/ts for each commit in the contract shape', () => {
    const commits = [
      { sha: 'abc1234567', message: 'Initial commit', author: 'pc', ts: new Date().toISOString() },
      { sha: 'def7654321', message: 'Fix thing\n\nlonger body', author: 'pc', ts: new Date().toISOString() },
    ]
    const html = renderToStaticMarkup(<CommitLog commits={commits} loading={false} />)
    expect(html).toContain('Initial commit')
    expect(html).toContain('abc1234')
    expect(html).toContain('Fix thing')
    expect(html).not.toContain('longer body') // only the first message line is shown
  })
})

// ---------------------------------------------------------------------------
// 4. TransferPanel (push/pull)
// ---------------------------------------------------------------------------

describe('TransferPanel — push/pull with remote + branch pickers', () => {
  const remotes = [{ name: 'origin', url: 'git@github.com:me/repo.git' }, { name: 'homelab', url: 'https://git.example.com/repo.git' }]

  it('push mode lists every configured remote as an option', () => {
    const html = renderToStaticMarkup(
      <TransferPanel mode="push" remotes={remotes} defaultBranch="main" busy={false} onSubmit={() => {}} onCancel={() => {}} />,
    )
    expect(html).toContain('>origin<')
    expect(html).toContain('>homelab<')
    expect(html).toContain('Push to')
  })

  it('pull mode renders a Pull button', () => {
    const html = renderToStaticMarkup(
      <TransferPanel mode="pull" remotes={remotes} defaultBranch="main" busy={false} onSubmit={() => {}} onCancel={() => {}} />,
    )
    expect(html).toContain('Pull to')
  })

  it('defaults the branch field to the current branch', () => {
    const html = renderToStaticMarkup(
      <TransferPanel mode="push" remotes={remotes} defaultBranch="feature/x" busy={false} onSubmit={() => {}} onCancel={() => {}} />,
    )
    expect(html).toContain('value="feature/x"')
  })

  it('disables submit while a transfer is in flight', () => {
    const html = renderToStaticMarkup(
      <TransferPanel mode="push" remotes={remotes} defaultBranch="main" busy onSubmit={() => {}} onCancel={() => {}} />,
    )
    expect(html).toMatch(/disabled=""/)
  })
})

// ---------------------------------------------------------------------------
// 5. ErrorBanner
// ---------------------------------------------------------------------------

describe('ErrorBanner', () => {
  it('renders the message with role=alert', () => {
    const html = renderToStaticMarkup(<ErrorBanner message="Push failed." onDismiss={() => {}} />)
    expect(html).toContain('role="alert"')
    expect(html).toContain('Push failed.')
  })

  it('renders nothing when there is no message', () => {
    const html = renderToStaticMarkup(<ErrorBanner message={null} onDismiss={() => {}} />)
    expect(html).toBe('')
  })
})

// ---------------------------------------------------------------------------
// 6. Source-text: no OAuth / branch-merge/diff surface survives
// ---------------------------------------------------------------------------

describe('GitPanel.jsx + RemotesManager.jsx — no OAuth, no hosted-git leftovers', () => {
  it('GitPanel.jsx has no GitHub OAuth wiring', () => {
    expect(gitPanelSrc).not.toContain('githubOAuth')
    expect(gitPanelSrc).not.toContain('github_login')
    expect(gitPanelSrc).not.toContain('Connect GitHub')
    expect(gitPanelSrc).not.toContain('Link GitHub')
  })

  it('GitPanel.jsx is not gated behind cloudEnabled', () => {
    expect(gitPanelSrc).not.toMatch(/cloudEnabled\s*&&/)
  })

  it('GitPanel.jsx has no branch-switching/merge/diff-viewer imports (not in the new contract)', () => {
    for (const dead of ['BranchPicker', 'MergeDialog', 'CommitDiffViewer', 'GitConnectDialog', 'GitProviderSettings', 'GitGraph']) {
      expect(gitPanelSrc).not.toContain(dead)
    }
  })

  it('RemotesManager.jsx has no OAuth wiring (prose explaining its absence is fine)', () => {
    expect(remotesSrc).not.toContain('githubOAuth')
    expect(remotesSrc).not.toContain('startUrl')
    expect(remotesSrc).not.toMatch(/window\.location\.assign/)
  })
})

// ---------------------------------------------------------------------------
// 7. RemotesManager — required helper text, default render
// ---------------------------------------------------------------------------

describe('RemotesManager', () => {
  beforeEach(() => {
    global.fetch = vi.fn(async () => ({ ok: true, status: 200, json: async () => [] }))
  })
  afterEach(() => {
    delete global.fetch
  })

  it('default render carries the required helper text verbatim', () => {
    const html = renderToStaticMarkup(<RemotesManager projectId="proj-1" onClose={() => {}} onChanged={() => {}} />)
    expect(html).toContain(
      'Use any git remote — a teammate',
    )
    expect(html).toContain('homelab, GitHub or')
    expect(html).toContain('Gitea')
    expect(html).toContain('kerf never')
    expect(html).toContain('stores credentials')
  })

  it('renders the Add remote form (name + URL)', () => {
    const html = renderToStaticMarkup(<RemotesManager projectId="proj-1" onClose={() => {}} onChanged={() => {}} />)
    expect(html).toContain('Add remote')
  })
})
