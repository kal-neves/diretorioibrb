document.querySelectorAll('[data-directory-region]').forEach((region) => {
  let controller
  const kind = region.dataset.directoryRegion
  const keys = kind === 'listing' ? ['q', 'category', 'page'] : ['month']
  const error = document.querySelector('[data-directory-error]')

  async function update(parameters) {
    controller?.abort()
    const current = new AbortController()
    controller = current
    const url = new URL(region.dataset.fragmentUrl, window.location.origin)
    for (const key of keys) {
      if (parameters.has(key)) url.searchParams.set(key, parameters.get(key))
    }
    region.setAttribute('aria-busy', 'true')
    error.hidden = true
    try {
      const response = await fetch(url, {
        headers: {'X-Requested-With': 'XMLHttpRequest'},
        credentials: 'same-origin', cache: 'no-store', signal: current.signal
      })
      if (current !== controller) return
      const destination = response.headers.get('X-Access-Redirect')
      if ([401, 403].includes(response.status) && destination) {
        const target = new URL(destination, window.location.origin)
        if (target.origin !== window.location.origin) throw new Error('Destino inválido')
        window.location.assign(target.href)
        return
      }
      if (!response.ok || response.redirected || response.headers.get('X-Directory-Fragment') !== kind
          || !response.headers.get('Content-Type')?.startsWith('text/html')) {
        throw new Error('Resposta inválida')
      }
      const html = await response.text()
      if (current !== controller) return
      region.innerHTML = html
      const location = new URL(window.location.href)
      for (const key of keys) {
        location.searchParams.delete(key)
        if (parameters.has(key)) location.searchParams.set(key, parameters.get(key))
      }
      window.history.replaceState(null, '', location)
      synchronizeNavigation(location.searchParams)
      const heading = region.querySelector('h2')
      heading.tabIndex = -1
      heading.focus()
    } catch (failure) {
      if (failure.name !== 'AbortError' && current === controller) {
        error.textContent = 'Não foi possível atualizar esta seção. Tente novamente.'
        error.hidden = false
      }
    } finally {
      if (current === controller) region.removeAttribute('aria-busy')
    }
  }

  region.addEventListener('submit', (event) => {
    if (!(event.target instanceof HTMLFormElement)) return
    event.preventDefault()
    update(new URLSearchParams(new FormData(event.target)))
  })
  region.addEventListener('change', (event) => {
    if (event.target.matches('select')) event.target.form.requestSubmit()
  })
  region.addEventListener('click', (event) => {
    const link = event.target.closest('nav[aria-label="Páginas do diretório"] a')
    if (!link || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return
    event.preventDefault()
    update(new URL(link.href).searchParams)
  })
})

function synchronizeNavigation(parameters) {
  document.querySelectorAll('[data-directory-region] form').forEach((form) => {
    const birthday = form.closest('[data-directory-region]').dataset.directoryRegion === 'birthdays'
    const keys = birthday ? ['q', 'category', 'page'] : ['month']
    for (const key of keys) {
      let input = form.querySelector(`input[name="${key}"]`)
      if (!input) {
        input = document.createElement('input')
        input.type = 'hidden'
        input.name = key
        form.append(input)
      }
      input.value = parameters.get(key) || ''
    }
  })
  document.querySelectorAll('[data-directory-region="listing"] nav a').forEach((link) => {
    const url = new URL(link.href)
    url.searchParams.delete('month')
    if (parameters.has('month')) url.searchParams.set('month', parameters.get('month'))
    link.href = url.href
  })
}
