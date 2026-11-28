const assert = require('node:assert/strict')
const {readFileSync} = require('node:fs')
const {join} = require('node:path')
const {test} = require('node:test')
const vm = require('node:vm')

const source = readFileSync(join(__dirname, '../static/directory/directory.js'), 'utf8')
const tick = () => new Promise((resolve) => setImmediate(resolve))

function setup() {
  const requests = []
  const redirects = []
  const error = {hidden: true}
  class Form {
    constructor(values) { this.values = values }
  }
  const regions = ['listing', 'birthdays'].map((kind) => ({
    dataset: {directoryRegion: kind, fragmentUrl: `/diretorio/${kind}/`},
    innerHTML: 'original', handlers: {}, busy: false,
    addEventListener(event, handler) { this.handlers[event] = handler },
    setAttribute() { this.busy = true },
    removeAttribute() { this.busy = false },
    querySelector() { return {focus() {}} }
  }))
  const location = {
    href: 'https://ibrb.example/diretorio/?q=Ana&category=MEMBER&page=2&month=2',
    origin: 'https://ibrb.example', assign(url) { redirects.push(url) }
  }
  vm.runInNewContext(source, {
    URL, URLSearchParams, AbortController, HTMLFormElement: Form,
    FormData: class { constructor(form) { return new Map(Object.entries(form.values)) } },
    window: {location, history: {replaceState(state, title, url) { location.href = url.href }}},
    document: {
      querySelector() { return error },
      querySelectorAll(selector) { return selector === '[data-directory-region]' ? regions : [] }
    },
    fetch(url, options) {
      return new Promise((resolve) => requests.push({url, options, resolve}))
    }
  })
  const submit = (region, values) => region.handlers.submit({target: new Form(values), preventDefault() {}})
  const respond = (index, kind, html, status = 200, headers = {}) => requests[index].resolve({
    status, ok: status === 200, redirected: false,
    headers: new Map(Object.entries({'X-Directory-Fragment': kind, 'Content-Type': 'text/html', ...headers})),
    text: async () => html
  })
  return {regions, requests, redirects, location, error, submit, respond}
}

test('a resposta antiga não substitui a busca mais recente', async () => {
  const app = setup()
  app.submit(app.regions[0], {q: 'Ana', category: ''})
  app.submit(app.regions[0], {q: 'Maria', category: 'MEMBER'})
  assert.equal(app.requests[0].options.signal.aborted, true)
  app.respond(1, 'listing', 'Maria')
  await tick()
  app.respond(0, 'listing', 'Ana')
  await tick()
  assert.equal(app.regions[0].innerHTML, 'Maria')
  assert.equal(app.regions[1].innerHTML, 'original')
  assert.equal(new URL(app.location.href).searchParams.get('month'), '2')
  assert.equal(new URL(app.location.href).searchParams.has('page'), false)
  assert.equal(app.requests[1].options.headers['X-Requested-With'], 'XMLHttpRequest')
  assert.equal(app.requests[1].options.cache, 'no-store')
})

test('lista e mês concorrentes preservam o estado um do outro', async () => {
  const app = setup()
  app.submit(app.regions[0], {q: 'João', category: 'PASTOR'})
  app.submit(app.regions[1], {month: '3', q: 'Ana', page: '2'})
  app.respond(1, 'birthdays', 'Março')
  await tick()
  app.respond(0, 'listing', 'João')
  await tick()
  const parameters = new URL(app.location.href).searchParams
  assert.equal(parameters.get('month'), '3')
  assert.equal(parameters.get('q'), 'João')
  assert.equal(parameters.get('category'), 'PASTOR')
  assert.equal(parameters.has('page'), false)
  assert.equal(app.regions[1].innerHTML, 'Março')
})

test('sessão encerrada navega sem inserir login na seção', async () => {
  const app = setup()
  app.submit(app.regions[0], {q: 'Ana'})
  app.respond(0, null, '<html>login</html>', 401, {'X-Access-Redirect': '/login/'})
  await tick()
  assert.deepEqual(app.redirects, ['https://ibrb.example/login/'])
  assert.equal(app.regions[0].innerHTML, 'original')
})

test('falhas e fragmentos incorretos conservam conteúdo e permitem tentar novamente', async () => {
  const app = setup()
  app.submit(app.regions[0], {q: 'Ana'})
  app.respond(0, 'listing', 'falha', 503)
  await tick()
  assert.equal(app.error.hidden, false)
  assert.equal(app.regions[0].innerHTML, 'original')
  assert.equal(app.regions[0].busy, false)
  app.submit(app.regions[0], {q: 'Ana'})
  app.respond(1, 'birthdays', 'seção errada')
  await tick()
  assert.equal(app.regions[0].innerHTML, 'original')
  app.submit(app.regions[0], {q: 'Ana'})
  app.respond(2, 'listing', 'resultado')
  await tick()
  assert.equal(app.regions[0].innerHTML, 'resultado')
  assert.equal(app.error.hidden, true)
})
