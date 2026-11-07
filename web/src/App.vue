<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { api, post } from './api'

const WORDS = ref([])
const STATE = ref({})
const SM = ref(null)
const view = ref('home')
const cat = ref('')
const gi = ref(0)
const queue = ref([])
const qi = ref(0)
const li = ref(0)
const results = ref([])
const wrong = ref([])
const answered = ref(false)
const picked = ref('')
const okFlag = ref(false)
const nextDue = ref(0)
const source = ref('')
const t0 = ref(0)
const answerText = ref('')
const feedback = ref('')
const toastMsg = ref('')
let toastTimer = null

const SET = ref({ mode: 'write', chunk: 10 })
try { const raw = localStorage.getItem('fk_set'); if (raw) SET.value = Object.assign({ mode: 'write', chunk: 10 }, JSON.parse(raw)) } catch (e) {}
function saveSet() { try { localStorage.setItem('fk_set', JSON.stringify(SET.value)) } catch (e) {} }

const letters = computed(() => Array.from(new Set(WORDS.value.map(w => w.cat || 'A'))).sort())
function wordsOf(c) { return WORDS.value.filter(w => (w.cat || 'A') === c) }
function groupsOf(list) { const n = Math.max(1, Number(SET.value.chunk) || 10); const out = []; for (let i = 0; i < list.length; i += n) out.push(list.slice(i, i + n)); return out }
function shuffle(a) { const x = a.slice(); for (let i = x.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [x[i], x[j]] = [x[j], x[i]] } return x }
function esc(s) { return String(s == null ? '' : s) }

function toast(t) { toastMsg.value = t; clearTimeout(toastTimer); toastTimer = setTimeout(() => { toastMsg.value = '' }, 1400) }

async function getWords() {
  try {
    const raw = localStorage.getItem('fk_words_cache')
    const at = Number(localStorage.getItem('fk_words_at') || 0)
    if (raw && Date.now() - at < 7 * 864e5) return JSON.parse(raw)
  } catch (e) {}
  const w = await api('/api/words')
  try { localStorage.setItem('fk_words_cache', JSON.stringify(w)); localStorage.setItem('fk_words_at', String(Date.now())) } catch (e) {}
  return w
}
async function load() {
  const [w, boot] = await Promise.all([getWords(), api('/api/bootstrap')])
  WORDS.value = w
  const map = {}; (boot.state || []).forEach(x => { map[x.word] = x }); STATE.value = map
  SM.value = boot.summary
}

function openCat(c) { cat.value = c; view.value = 'list' }
function backHome() { view.value = 'home'; cat.value = ''; api('/api/summary').then(x => SM.value = x) }

function startQueue(items, src, g) {
  if (!items.length) return
  queue.value = items.slice(); source.value = src; gi.value = g == null ? 0 : g
  li.value = 0; qi.value = 0; results.value = []; wrong.value = []; answered.value = false
  picked.value = ''; okFlag.value = false; nextDue.value = 0; answerText.value = ''; feedback.value = ''
  view.value = 'learn'
}
function openGroup(i) { const c = cat.value || 'A'; startQueue(shuffle(groupsOf(wordsOf(c))[i]), '第 ' + (i + 1) + ' 组', i) }
async function todayReview() {
  let rec = []
  try { rec = await api('/api/recommend?limit=200') } catch (e) {}
  if (!rec.length) { toast('今天没有要复习的'); return }
  startQueue(rec, '今日复习', -1)
}
function nextLearn() { if (li.value < queue.value.length - 1) li.value++ }
function prevLearn() { if (li.value > 0) li.value-- }

const cur = computed(() => queue.value[li.value] || {})

async function record(word, ok, ms) {
  const r = await post('/api/review', { word, ok, ms })
  if (r && r.item) { STATE.value = Object.assign({}, STATE.value, { [word]: r.item }); if (r.summary) SM.value = r.summary }
  return r
}

function startQuiz() {
  if (SET.value.mode === 'off') { finishGroup(); return }
  queue.value = shuffle(queue.value); qi.value = 0; results.value = []; wrong.value = []
  answered.value = false; picked.value = ''; t0.value = Date.now()
  view.value = SET.value.mode === 'choice' ? 'choice' : 'write'
  if (SET.value.mode === 'choice') buildOptions(queue.value[0])
}
async function finishGroup() {
  toast('记录中…')
  for (const it of queue.value) { try { await post('/api/review', { word: it.word, skip: true, ok: false, ms: 0 }) } catch (e) {} }
  backHome(); toast('已记录，明天复习')
}

const qItem = computed(() => queue.value[qi.value] || {})
const options = ref([])
function buildOptions(it) {
  if (!it || !it.word) { options.value = []; return }
  let pool = WORDS.value.filter(w => w.word !== it.word && (w.cat || 'A') === (it.cat || 'A'))
  if (pool.length < 3) pool = WORDS.value.filter(w => w.word !== it.word)
  options.value = shuffle(shuffle(pool).slice(0, 3).map(w => w.word).concat([it.word]))
}
watch([view, qi], () => {
  if (view.value === 'choice' && !answered.value && options.value.length < 2) buildOptions(qItem.value)
})
async function answerChoice(w) {
  if (answered.value) return
  const it = qItem.value
  okFlag.value = w === it.word
  picked.value = w
  answered.value = true
  results.value.push(okFlag.value)
  if (!okFlag.value) wrong.value.push({ word: it.word, def: it.def, pinyin: it.pinyin })
  await record(it.word, okFlag.value, Date.now() - (t0.value || Date.now()))
  if (okFlag.value) setTimeout(nextQuestion, 500)
}
function pickedInfo() { return WORDS.value.find(w => w.word === picked.value) || { word: picked.value, gloss: '', def: '' } }

async function submitWrite() {
  if (answered.value) return
  const it = qItem.value
  const val = answerText.value.trim()
  okFlag.value = !!val && val === it.word
  answered.value = true
  results.value.push(okFlag.value)
  if (!okFlag.value) wrong.value.push({ word: it.word, def: it.def, pinyin: it.pinyin })
  feedback.value = okFlag.value ? '答对了' : '正确答案：' + it.word
  await record(it.word, okFlag.value, Date.now() - (t0.value || Date.now()))
}
function nextQuestion() {
  if (qi.value < queue.value.length - 1) {
    qi.value++; answered.value = false; picked.value = ''; answerText.value = ''; feedback.value = ''; okFlag.value = false; t0.value = Date.now()
    if (SET.value.mode === 'choice') buildOptions(qItem.value)
  } else {
    view.value = 'result'
    api('/api/summary').then(x => SM.value = x)
  }
}
function retryWrong() {
  if (!wrong.value.length) return
  queue.value = shuffle(wrong.value.map(w => WORDS.value.find(x => x.word === w.word) || w))
  qi.value = 0; results.value = []; wrong.value = []; answered.value = false; picked.value = ''; okFlag.value = false; t0.value = Date.now()
  view.value = 'choice'
  buildOptions(queue.value[0])
}

const lettersCards = computed(() => letters.value.map(c => {
  const list = wordsOf(c); const m = STATE.value
  const seen = list.filter(w => m[w.word] && m[w.word].seen > 0).length
  const mast = list.filter(w => m[w.word] && m[w.word].interval >= 7).length
  const gs = groupsOf(list)
  const doneG = gs.filter(g => g.every(w => m[w.word] && m[w.word].seen > 0)).length
  return { c, n: list.length, seen, mast, groups: gs.length, doneG }
}))
const groupsView = computed(() => groupsOf(wordsOf(cat.value)).map((g, i) => {
  const m = STATE.value
  const seen = g.filter(w => m[w.word] && m[w.word].seen > 0).length
  return { i, n: g.length, seen, all: seen === g.length }
}))
const accuracy = computed(() => { const tot = results.value.length || 1; return Math.round(results.value.filter(Boolean).length / tot * 100) })

function onKey(e) {
  if (view.value === 'learn') {
    if (e.key === 'ArrowRight' || e.key === 'Enter') { e.preventDefault(); li.value < queue.value.length - 1 ? nextLearn() : (SET.value.mode === 'off' ? finishGroup() : startQuiz()) }
    if (e.key === 'ArrowLeft') { e.preventDefault(); prevLearn() }
  }
  if (view.value === 'write' && e.key === 'Enter') { e.preventDefault(); answered.value ? nextQuestion() : submitWrite() }
  if (view.value === 'choice' && e.key === 'Enter' && answered.value) { e.preventDefault(); nextQuestion() }
}
onMounted(() => { load(); window.addEventListener('keydown', onKey) })
onUnmounted(() => window.removeEventListener('keydown', onKey))
</script>

<template>
<div class="screen">
  <!-- HOME -->
  <template v-if="view === 'home'">
    <header>
      <div class="brand">习语</div>
      <div class="sub">{{ SM ? SM.seen + '/' + SM.total + ' 已学' : '' }} · <span style="text-decoration:underline" @click="view = 'settings'">设置</span></div>
    </header>
    <div class="scroll">
      <div class="cta" @click="todayReview">
        <div>
          <div class="ctaTitle">今日复习</div>
          <div class="ctaSub">{{ SM && SM.due ? SM.due + ' 个待复习' : '暂无待复习' }}</div>
        </div>
        <div class="ctaArrow">›</div>
      </div>
      <div class="todayRow"><span>今日新学 <b>{{ SM ? SM.todayNew : 0 }}</b></span><span>今日复习 <b>{{ SM ? SM.todayReview : 0 }}</b></span></div>
      <div class="groups">
        <div class="gitem" v-for="x in lettersCards" :key="x.c" @click="openCat(x.c)">
          <div class="gmain">
            <div class="gname">首字母 {{ x.c }}<span class="done" v-if="x.doneG === x.groups">全部学完</span></div>
            <div class="gbar"><i class="m" :style="{width: (x.mast / x.n * 100) + '%'}"></i><i class="s" :style="{width: ((x.seen - x.mast) / x.n * 100) + '%'}"></i></div>
            <div class="gmeta">{{ x.n }} 词 · {{ x.groups }} 组 · 已学 {{ x.seen }} · 熟练 {{ x.mast }}</div>
          </div>
          <div class="gmeta">›</div>
        </div>
      </div>
    </div>
  </template>

  <!-- LIST -->
  <template v-else-if="view === 'list'">
    <header>
      <button class="back" @click="backHome">‹</button>
      <div class="brand">首字母 {{ cat }}</div>
      <div class="sub">{{ wordsOf(cat).length }} 词</div>
    </header>
    <div class="scroll">
      <div class="groups">
        <div class="gitem" v-for="g in groupsView" :key="g.i" @click="openGroup(g.i)">
          <div class="gmain">
            <div class="gname">第 {{ g.i + 1 }} 组<span class="done" v-if="g.all">已学完</span></div>
            <div class="gmeta">已学 {{ g.seen }} / {{ g.n }}</div>
          </div>
          <div class="gmeta">›</div>
        </div>
      </div>
    </div>
  </template>

  <!-- LEARN -->
  <template v-else-if="view === 'learn'">
    <header>
      <button class="back" @click="backHome">‹</button>
      <div class="brand">{{ source }} · 学习</div>
      <div class="sub">{{ li + 1 }} / {{ queue.length }}</div>
    </header>
    <div class="bar"><i :style="{width: ((li + 1) / queue.length * 100) + '%'}"></i></div>
    <div class="scroll">
      <div class="card center">
        <div class="word">{{ cur.word }}</div>
        <div class="pinyin">{{ cur.pinyin }}</div>
        <div class="gloss" v-if="cur.gloss">{{ cur.gloss }}</div>
        <div class="def">{{ cur.def }}</div>
        <div class="src" v-if="cur.quote">{{ cur.quote }}</div>
        <div class="extra" v-if="cur.example || (cur.similar && cur.similar.length) || (cur.opposite && cur.opposite.length) || cur.usage">
          <div v-if="cur.example"><b>例句</b>{{ cur.example }}</div>
          <div v-if="cur.similar && cur.similar.length"><b>近义</b>{{ cur.similar.join(' / ') }}</div>
          <div v-if="cur.opposite && cur.opposite.length"><b>反义</b>{{ cur.opposite.join(' / ') }}</div>
          <div v-if="cur.usage"><b>用法</b>{{ cur.usage }}</div>
        </div>
        <div class="meta">{{ cur.word.length }} 字<span v-if="STATE[cur.word] && STATE[cur.word].seen"> · 学过 {{ STATE[cur.word].seen }} 次</span><span v-else> · 新词</span></div>
      </div>
    </div>
    <div class="row">
      <button class="ghost" :disabled="li === 0" @click="prevLearn">上一个</button>
      <button class="primary" v-if="li < queue.length - 1" @click="nextLearn">下一个</button>
      <button class="primary" v-else @click="SET.mode === 'off' ? finishGroup() : startQuiz()">{{ SET.mode === 'off' ? '完成本组' : (SET.mode === 'choice' ? '开始选择' : '开始默写') }}</button>
    </div>
  </template>

  <!-- CHOICE -->
  <template v-else-if="view === 'choice'">
    <header>
      <button class="back" @click="backHome">‹</button>
      <div class="brand">{{ source }} · 选词</div>
      <div class="sub">{{ qi + 1 }} / {{ queue.length }}</div>
    </header>
    <div class="bar"><i :style="{width: ((qi + 1) / queue.length * 100) + '%'}"></i></div>
    <div class="scroll">
      <div class="card center"><div class="def quiz">{{ qItem.def }}</div></div>
      <div class="opts">
        <div v-for="w in options" :key="w" class="opt"
             :class="{right: answered && w === qItem.word, wrong: answered && w === picked && w !== qItem.word, dim: answered && w !== qItem.word && w !== picked}"
             @click="answerChoice(w)">{{ w }}</div>
      </div>
      <div class="cmp" v-if="answered && !okFlag">
        <div class="cmpRow bad">
          <b>你选的：{{ pickedInfo().word }}</b>
          <div class="cmpGloss" v-if="pickedInfo().gloss">{{ pickedInfo().gloss }}</div>
          <div class="cmpDef">{{ pickedInfo().def }}</div>
        </div>
        <div class="cmpRow good">
          <b>正确答案：{{ qItem.word }}</b>
          <div class="cmpGloss" v-if="qItem.gloss">{{ qItem.gloss }}</div>
          <div class="cmpDef">{{ qItem.def }}</div>
        </div>
        <button class="primary" style="width:100%;margin-top:6px" @click="nextQuestion">下一个</button>
      </div>
    </div>
  </template>

  <!-- WRITE -->
  <template v-else-if="view === 'write'">
    <header>
      <button class="back" @click="backHome">‹</button>
      <div class="brand">{{ source }} · 默写</div>
      <div class="sub">{{ qi + 1 }} / {{ queue.length }}</div>
    </header>
    <div class="bar"><i :style="{width: ((qi + 1) / queue.length * 100) + '%'}"></i></div>
    <div class="scroll noscroll">
      <div class="card center"><div class="def quiz">{{ qItem.def }}</div><div class="meta" v-if="answered">{{ feedback }}</div></div>
    </div>
    <input class="answer" v-model="answerText" :disabled="answered" autocapitalize="off" autocomplete="off"
           autocorrect="off" spellcheck="false" enterkeyhint="done" placeholder="输入成语">
    <div class="row">
      <button class="ghost" v-if="!answered" @click="answerText = ''; submitWrite()">不会</button>
      <button class="primary" v-if="!answered" @click="submitWrite">提交</button>
      <button class="primary" v-else @click="nextQuestion">下一个</button>
    </div>
  </template>

  <!-- RESULT -->
  <template v-else-if="view === 'result'">
    <header><button class="back" @click="backHome">‹</button><div class="brand">完成</div><div class="sub">{{ results.length }} 题</div></header>
    <div class="scroll">
      <div class="card center">
        <div class="word" style="font-size:44px">{{ accuracy }}%</div>
        <div class="meta">答对 {{ results.filter(Boolean).length }} / {{ results.length }}</div>
      </div>
      <div class="card" v-if="wrong.length">
        <div class="gname" style="margin-bottom:8px">错题</div>
        <div class="wrongItem" v-for="w in wrong" :key="w.word"><em>{{ w.word }}</em><span>{{ w.pinyin }}<br>{{ w.def }}</span></div>
      </div>
    </div>
    <div class="row">
      <button class="ghost" v-if="wrong.length" @click="retryWrong">再练错题</button>
      <button class="primary" @click="backHome">回主页</button>
    </div>
  </template>

  <!-- SETTINGS -->
  <template v-else-if="view === 'settings'">
    <header><button class="back" @click="backHome">‹</button><div class="brand">设置</div><div class="sub">学习后做什么</div></header>
    <div class="scroll">
      <div class="groups">
        <div class="gitem" v-for="o in [['write','默写','看释义，手写成语'],['choice','选词','看释义，四选一'],['off','关闭','只看卡片，不做题']]" :key="o[0]"
             @click="SET.mode = o[0]; saveSet()">
          <div class="gmain">
            <div class="gname">{{ o[1] }}<span class="done" v-if="SET.mode === o[0]">当前</span></div>
            <div class="gmeta">{{ o[2] }}</div>
          </div>
        </div>
      </div>
      <div class="gname" style="margin:18px 4px 8px">每组成语数</div>
      <div class="groups">
        <div class="gitem" v-for="n in [5, 10, 15, 20]" :key="n" @click="SET.chunk = n; saveSet()">
          <div class="gmain">
            <div class="gname">{{ n }} 个<span class="done" v-if="Number(SET.chunk) === n">当前</span></div>
            <div class="gmeta">每组 {{ n }} 个成语</div>
          </div>
        </div>
      </div>
      <div class="gmeta" style="text-align:center;margin-top:18px">构建版本 v3 · Vue</div>
    </div>
  </template>

  <div class="toast" :class="{on: toastMsg}">{{ toastMsg }}</div>
</div>
</template>
