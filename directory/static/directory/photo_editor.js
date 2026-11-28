document.querySelectorAll('[data-photo-editor]').forEach((editor) => {
  const form = editor.closest('form')
  const original = editor.querySelector('[data-original]')
  const upload = form.querySelector('[name="photo"]')
  const remove = form.querySelector('[name="remove_photo"]')
  const dialog = editor.querySelector('dialog')
  const canvas = editor.querySelector('canvas')
  const status = editor.querySelector('[data-photo-status]')
  const preview = editor.querySelector('[data-photo-preview]')
  const controls = [...editor.querySelectorAll('[data-crop]')]
  let bitmap, crop, start, previewUrl, busy = false, sequence = 0
  function draw() {
    if (!bitmap) return
    const context = canvas.getContext('2d')
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height)
    context.strokeStyle = '#ff0000'
    context.lineWidth = 2
    context.strokeRect(crop.x * canvas.width / bitmap.width, crop.y * canvas.height / bitmap.height,
      crop.width * canvas.width / bitmap.width, crop.height * canvas.height / bitmap.height)
    for (const control of controls) {
      const key = control.dataset.crop
      control.max = key === 'x' ? bitmap.width - crop.width : key === 'y' ? bitmap.height - crop.height : key === 'width' ? bitmap.width - crop.x : bitmap.height - crop.y
      control.value = crop[key]
    }
  }
  function cancel() {
    sequence++
    bitmap?.close()
    bitmap = null
    start = null
    busy = false
    original.value = ''
    dialog.close()
    original.focus()
  }
  original.addEventListener('change', async () => {
    const current = ++sequence
    busy = true
    status.textContent = 'Processando foto…'
    try {
      const file = original.files[0]
      if (!file || file.size > 10 * 1024 * 1024) throw new Error('Use um arquivo de até 10 MiB.')
      inspectPhoto(await file.arrayBuffer())
      const decoded = await createImageBitmap(file, {imageOrientation: 'from-image'})
      if (current !== sequence) { decoded.close(); return }
      bitmap?.close()
      bitmap = decoded
      if (bitmap.width * bitmap.height > 25000000) throw new Error('A imagem excede 25 milhões de pixels.')
      const scale = Math.min(1, 600 / Math.max(bitmap.width, bitmap.height))
      canvas.width = Math.max(1, Math.round(bitmap.width * scale))
      canvas.height = Math.max(1, Math.round(bitmap.height * scale))
      crop = {x: 0, y: 0, width: bitmap.width, height: bitmap.height}
      draw()
      dialog.showModal()
      status.textContent = 'Confirme o recorte antes de salvar.'
    } catch (error) {
      if (current === sequence) {
        status.textContent = error instanceof RangeError ? 'Arquivo de imagem incompleto ou inválido.' : error.message || 'Não foi possível ler a foto.'
        cancel()
      }
    }
  })
  controls.forEach((control) => control.addEventListener('input', () => {
    crop[control.dataset.crop] = Number(control.value)
    draw()
  }))
  const point = (event) => {
    const rect = canvas.getBoundingClientRect()
    return {x: Math.max(0, Math.min(bitmap.width - 1, Math.round((event.clientX - rect.left) / rect.width * bitmap.width))),
      y: Math.max(0, Math.min(bitmap.height - 1, Math.round((event.clientY - rect.top) / rect.height * bitmap.height)))}
  }
  canvas.addEventListener('pointerdown', (event) => { start = point(event); canvas.setPointerCapture(event.pointerId) })
  canvas.addEventListener('pointermove', (event) => {
    if (!start) return
    const end = point(event)
    crop = {x: Math.min(start.x, end.x), y: Math.min(start.y, end.y), width: Math.max(1, Math.abs(start.x - end.x)), height: Math.max(1, Math.abs(start.y - end.y))}
    draw()
  })
  canvas.addEventListener('pointerup', () => { start = null })
  canvas.addEventListener('pointercancel', () => { start = null })
  dialog.addEventListener('cancel', (event) => { event.preventDefault(); cancel() })
  editor.querySelector('[data-cancel-crop]').addEventListener('click', cancel)
  editor.querySelector('[data-use-crop]').addEventListener('click', async () => {
    const current = sequence
    const output = document.createElement('canvas')
    Object.assign(output, fitPhoto(crop.width, crop.height))
    const context = output.getContext('2d')
    context.fillStyle = 'white'
    context.fillRect(0, 0, output.width, output.height)
    context.drawImage(bitmap, crop.x, crop.y, crop.width, crop.height, 0, 0, output.width, output.height)
    let blob
    for (const quality of [0.85, 0.75, 0.65, 0.5]) {
      blob = await new Promise((resolve) => output.toBlob(resolve, 'image/jpeg', quality))
      if (blob && blob.size <= 1024 * 1024) break
    }
    if (current !== sequence) return
    if (!blob || blob.size > 1024 * 1024) { status.textContent = 'Reduza o recorte para até 1 MiB.'; return }
    const transfer = new DataTransfer()
    transfer.items.add(new File([blob], 'foto.jpg', {type: 'image/jpeg'}))
    upload.files = transfer.files
    remove.checked = false
    if (previewUrl) URL.revokeObjectURL(previewUrl)
    previewUrl = URL.createObjectURL(blob)
    preview.src = previewUrl
    preview.hidden = false
    status.textContent = `Recorte pronto: ${output.width} × ${output.height}. Salve a entrada para confirmar.`
    cancel()
  })
  remove.addEventListener('change', () => {
    if (remove.checked) { upload.value = ''; preview.hidden = true; status.textContent = 'A foto será removida ao salvar.' }
  })
  form.addEventListener('submit', (event) => {
    if (busy) {
      event.preventDefault()
      event.stopImmediatePropagation()
      status.textContent = 'Confirme ou cancele o recorte antes de salvar.'
    }
  }, true)
  window.addEventListener('pagehide', () => { bitmap?.close(); if (previewUrl) URL.revokeObjectURL(previewUrl) })
})
