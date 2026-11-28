function inspectPhoto(buffer) {
  const bytes = new Uint8Array(buffer)
  const view = new DataView(buffer)
  const text = (start, length) => String.fromCharCode(...bytes.slice(start, start + length))
  const check = (width, height) => {
    if (!width || !height || width * height > 25000000) throw new Error('A imagem excede 25 milhões de pixels.')
    return {width, height}
  }
  if (!bytes.length || bytes.length > 10 * 1024 * 1024) throw new Error('Use um arquivo de até 10 MiB.')
  if (text(1, 3) === 'PNG' && bytes[0] === 137) {
    let offset = 8
    while (offset + 12 <= bytes.length) {
      const size = view.getUint32(offset)
      if (text(offset + 4, 4) === 'acTL') throw new Error('Fotos animadas não são aceitas.')
      offset += size + 12
    }
    return check(view.getUint32(16), view.getUint32(20))
  }
  if (text(0, 4) === 'RIFF' && text(8, 4) === 'WEBP') {
    let dimensions
    for (let offset = 12; offset + 8 <= bytes.length;) {
      const kind = text(offset, 4)
      const size = view.getUint32(offset + 4, true)
      const start = offset + 8
      if (start + size > bytes.length) throw new Error('Arquivo incompleto.')
      if (kind === 'ANIM' || (kind === 'VP8X' && bytes[start] & 2)) throw new Error('Fotos animadas não são aceitas.')
      if (kind === 'VP8X') dimensions = check(1 + bytes[start + 4] + (bytes[start + 5] << 8) + (bytes[start + 6] << 16), 1 + bytes[start + 7] + (bytes[start + 8] << 8) + (bytes[start + 9] << 16))
      if (kind === 'VP8 ' && !dimensions) dimensions = check(view.getUint16(start + 6, true) & 16383, view.getUint16(start + 8, true) & 16383)
      if (kind === 'VP8L' && !dimensions) {
        const bits = view.getUint32(start + 1, true)
        dimensions = check((bits & 16383) + 1, ((bits >>> 14) & 16383) + 1)
      }
      offset = start + size + (size % 2)
    }
    if (dimensions) return dimensions
  }
  if (bytes[0] === 255 && bytes[1] === 216) {
    let dimensions
    for (let offset = 2; offset + 4 <= bytes.length;) {
      if (bytes[offset++] !== 255) throw new Error('JPEG inválido.')
      while (bytes[offset] === 255) offset++
      const marker = bytes[offset++]
      if (marker === 218 || marker === 217) break
      const size = view.getUint16(offset)
      if (size < 2 || offset + size > bytes.length) throw new Error('Arquivo incompleto.')
      if (marker === 226 && text(offset + 2, 4) === 'MPF\0') throw new Error('Use uma imagem estática.')
      if ([192, 193, 194].includes(marker)) dimensions = check(view.getUint16(offset + 5), view.getUint16(offset + 3))
      offset += size
    }
    if (dimensions) return dimensions
  }
  throw new Error('Use JPEG, PNG ou WebP estático.')
}

function fitPhoto(width, height) {
  const scale = Math.min(1, 1200 / Math.max(width, height))
  return {width: Math.max(1, Math.round(width * scale)), height: Math.max(1, Math.round(height * scale))}
}

if (typeof module !== 'undefined') module.exports = {inspectPhoto, fitPhoto}
