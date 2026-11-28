const assert = require('node:assert/strict')
const {test} = require('node:test')
const {inspectPhoto, fitPhoto} = require('../static/directory/photo_processing.js')

function png(width, height, animated = false) {
  const buffer = new ArrayBuffer(animated ? 57 : 45)
  const bytes = new Uint8Array(buffer)
  const view = new DataView(buffer)
  bytes.set([137, 80, 78, 71, 13, 10, 26, 10])
  view.setUint32(8, 13)
  bytes.set(Buffer.from('IHDR'), 12)
  view.setUint32(16, width)
  view.setUint32(20, height)
  bytes.set(Buffer.from(animated ? 'acTL' : 'IEND'), 37)
  return buffer
}

test('dimensões e redução respeitam limites sem ampliar fotos pequenas', () => {
  assert.deepEqual(inspectPhoto(png(2000, 1500)), {width: 2000, height: 1500})
  assert.deepEqual(fitPhoto(2000, 1500), {width: 1200, height: 900})
  assert.deepEqual(fitPhoto(400, 300), {width: 400, height: 300})
  assert.deepEqual(fitPhoto(1, 5000), {width: 1, height: 1200})
})

test('arquivos grandes, animações e conteúdo não suportado são recusados', () => {
  for (const data of [png(5001, 5000), png(20, 20, true), new ArrayBuffer(10 * 1024 * 1024 + 1), new ArrayBuffer(0)]) {
    assert.throws(() => inspectPhoto(data))
  }
  assert.throws(() => inspectPhoto(new TextEncoder().encode('<svg></svg>').buffer))
})

test('JPEG progressivo tem dimensões reconhecidas antes de decodificar', () => {
  const bytes = new Uint8Array([255, 216, 255, 194, 0, 11, 8, 0, 30, 0, 40, 1, 1, 17, 0, 255, 218, 0, 2])
  assert.deepEqual(inspectPhoto(bytes.buffer), {width: 40, height: 30})
})

test('WebP estendido e animação são distinguidos', () => {
  const bytes = new Uint8Array(30)
  bytes.set(Buffer.from('RIFF'), 0)
  bytes.set(Buffer.from('WEBPVP8X'), 8)
  new DataView(bytes.buffer).setUint32(16, 10, true)
  bytes[24] = 39
  bytes[27] = 29
  assert.deepEqual(inspectPhoto(bytes.buffer), {width: 40, height: 30})
  bytes[20] = 2
  assert.throws(() => inspectPhoto(bytes.buffer))
})
