// workshopGallery.test.js
//
// Tests for the pin-as-primary gallery logic. These are pure-JS unit tests
// that mirror the optimistic state transitions in WorkshopImageGallery.jsx and
// the thumbnail URL resolution logic shared with the backend.
//
// No DOM / React rendering required — we test the state transforms in isolation.

import { describe, it, expect } from 'vitest'

// ---------------------------------------------------------------------------
// Mirror the optimistic state update from WorkshopImageGallery.onSetPrimary.
// ---------------------------------------------------------------------------

function applySetPrimaryOptimistic(images, targetImage) {
  const wasPrimary = targetImage.is_primary
  return images.map((x) => ({
    ...x,
    is_primary: x.id === targetImage.id ? !wasPrimary : false,
  }))
}

function applySetPrimaryServerResponse(images, updatedRow) {
  return images.map((x) =>
    x.id === updatedRow.id
      ? { ...x, is_primary: updatedRow.is_primary }
      : { ...x, is_primary: false },
  )
}

function makeImages(n) {
  return Array.from({ length: n }, (_, i) => ({
    id: `img-${i}`,
    sort_order: i,
    is_primary: false,
    caption: null,
    url: `/api/projects/proj/workshop-images/img-${i}/file`,
  }))
}

// ---------------------------------------------------------------------------
// Thumbnail URL resolution (mirrors _project_to_workshop_row in routes.py)
// ---------------------------------------------------------------------------

function resolveThumbnailUrl(projectId, primaryImageId, thumbnailStorageKey) {
  if (primaryImageId) {
    return `/api/projects/${projectId}/workshop-images/${primaryImageId}/file`
  }
  if (thumbnailStorageKey) {
    return `/api/projects/${projectId}/thumbnail`
  }
  return null
}

// ---------------------------------------------------------------------------
// Tests: pin image as primary
// ---------------------------------------------------------------------------

describe('workshopGallery pin-as-primary', () => {
  it('pinning a non-primary image marks it as primary and clears others', () => {
    const images = makeImages(3)
    const result = applySetPrimaryOptimistic(images, images[1])
    expect(result[0].is_primary).toBe(false)
    expect(result[1].is_primary).toBe(true)
    expect(result[2].is_primary).toBe(false)
  })

  it('at most one primary after pin', () => {
    const images = makeImages(4)
    images[0].is_primary = true

    const result = applySetPrimaryOptimistic(images, images[2])
    const primaries = result.filter((x) => x.is_primary)
    expect(primaries).toHaveLength(1)
    expect(primaries[0].id).toBe('img-2')
  })

  it('pin another image — first one is automatically unpinned (optimistic)', () => {
    const images = makeImages(3)
    images[0].is_primary = true  // img-0 currently primary

    const result = applySetPrimaryOptimistic(images, images[2])
    expect(result[0].is_primary).toBe(false)
    expect(result[2].is_primary).toBe(true)
  })

  it('server response is authoritative — syncs the targeted row and clears others', () => {
    const images = makeImages(3)
    images[0].is_primary = true  // stale optimistic state

    const serverRow = { id: 'img-2', is_primary: true }
    const result = applySetPrimaryServerResponse(images, serverRow)
    expect(result[0].is_primary).toBe(false)
    expect(result[2].is_primary).toBe(true)
  })
})

// ---------------------------------------------------------------------------
// Tests: unpin (toggle off already-primary image)
// ---------------------------------------------------------------------------

describe('workshopGallery unpin', () => {
  it('calling set-primary on the already-primary image unpins it', () => {
    const images = makeImages(3)
    images[1].is_primary = true

    const result = applySetPrimaryOptimistic(images, images[1])
    const primaries = result.filter((x) => x.is_primary)
    expect(primaries).toHaveLength(0)
    expect(result[1].is_primary).toBe(false)
  })

  it('after unpin no image is primary — falls back to auto-thumbnail', () => {
    const images = makeImages(2)
    images[0].is_primary = true

    // Server confirms unpin by returning is_primary: false.
    const serverRow = { id: 'img-0', is_primary: false }
    const result = applySetPrimaryServerResponse(images, serverRow)
    const primaries = result.filter((x) => x.is_primary)
    expect(primaries).toHaveLength(0)
  })
})

// ---------------------------------------------------------------------------
// Tests: thumbnail URL resolution
// ---------------------------------------------------------------------------

describe('workshopGallery thumbnail URL resolution', () => {
  it('pinned primary gallery image beats auto-captured thumbnail', () => {
    const url = resolveThumbnailUrl('proj-1', 'img-abc', 'storage/thumb.jpg')
    expect(url).toContain('workshop-images/img-abc/file')
  })

  it('falls back to auto-captured thumbnail when no gallery primary', () => {
    const url = resolveThumbnailUrl('proj-1', null, 'storage/thumb.jpg')
    expect(url).toBe('/api/projects/proj-1/thumbnail')
  })

  it('returns null when neither gallery primary nor auto-thumbnail exists', () => {
    const url = resolveThumbnailUrl('proj-1', null, null)
    expect(url).toBeNull()
  })

  it('list returns is_primary: true on the pinned image', () => {
    const images = makeImages(3)
    const pinResult = applySetPrimaryOptimistic(images, images[1])
    const pinned = pinResult.find((x) => x.id === 'img-1')
    expect(pinned?.is_primary).toBe(true)
  })
})
