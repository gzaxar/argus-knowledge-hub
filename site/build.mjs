import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import MarkdownIt from 'markdown-it';

const here = path.dirname(fileURLToPath(import.meta.url));
const guide = path.resolve(here, '../backend/app/help/guide');
const out = path.join(here, 'dist');
const base = '/argus-knowledge-hub/';
const webApp = 'https://argus-hub.90.147.174.30.myip.cloud.infn.it/';
const playApp = 'https://play.google.com/store/apps/details?id=it.infn.argus.field';
const project = 'https://infn-argus.github.io/argus-project-site/';
const md = new MarkdownIt({ html: false, linkify: true, typographer: true });

const ui = {
  en: {
    home: 'Home', platform: 'Platform', stories: 'Use cases', start: 'Getting started', manuals: 'Manuals', launch: 'Open the Hub',
    eyebrow: 'ARGUS KNOWLEDGE HUB · BY INFN', hero: 'Make every intervention part of what your team knows.',
    heroBody: 'One connected home for assets, documents, tickets and projects. Find the context behind an issue, capture the work, and make the next answer easier to discover.',
    explore: 'Explore the platform', heroStart: 'Get started', signal: 'From scattered facts to connected knowledge',
    intro: 'Know what you have. Understand what happened. Move forward together.',
    introBody: 'ARGUS connects the physical world of equipment and facilities with the work and knowledge around them. Each record becomes a useful part of a larger story.',
    assets: 'Assets & places', assetsBody: 'Follow equipment from a site map or floor plan to its technical record, related work and documentation.',
    work: 'Tickets & activities', workBody: 'Coordinate incidents, requests, planned work and recurring checks, with a traceable history.',
    docs: 'Documents', docsBody: 'Keep procedures, reports, drawings and minutes linked to what they describe and the people who use them.',
    ai: 'AI with context and review', aiBody: 'Ask questions across connected records and draft structured documents from raw text. People review proposed changes before they become trusted knowledge.',
    graph: 'Knowledge graph', graphBody: 'See relationships and dependencies across assets, work and documents, including connections that may have been missed.',
    field: 'From control room to field', fieldBody: 'Use the web hub for the full picture and ARGUS Field on Android to capture facts where work happens.',
    storyTitle: 'Built for complex environments. Useful every day.', storyBody: 'A fault, an inspection, a new installation or a handover: ARGUS keeps the evidence and the next action together.',
    story1: 'Investigate an equipment fault', story1Body: 'Start from an asset, review earlier tickets, locate the relevant procedure, and record the resolution.',
    story2: 'Plan and carry out work', story2Body: 'See activities across a workspace, schedule checks, and connect the outcome to the affected equipment.',
    story3: 'Turn raw notes into a usable record', story3Body: 'Use a document template and AI assistance to turn notes into a draft; review dates, sources and wording before publishing.',
    story4: 'Navigate a facility', story4Body: 'Place buildings, rooms and equipment on maps or floor plans, then move from location to record.',
    startTitle: 'Your first fifteen minutes in ARGUS', startBody: 'A short route through the product. Your workspace administrator can help with access and the local rules for your team.',
    steps: [
      ['01', 'Sign in', 'Open the Hub and sign in with the account your administrator has granted access to. Your email identifies you in ARGUS.'],
      ['02', 'Choose a workspace', 'Select the machine, facility or team you work in. Check the workspace name before creating records.'],
      ['03', 'Find an asset', 'Use global search or Assets to open an equipment record. Inspect its location, tickets and documents.'],
      ['04', 'Record work', 'Create a ticket for an issue or an activity for planned or completed work. Link the relevant asset and keep the outcome in the record.'],
      ['05', 'Explore the knowledge', 'Open a related document, follow the knowledge graph, or ask ARGUS a question. Review AI suggestions before applying them.']
    ],
    manualHeading: 'Product manuals', manualBody: 'These chapters are generated from the help shipped with ARGUS Knowledge Hub. Search a topic, then open the full guide.',
    search: 'Search manuals…', all: 'All chapters', noResults: 'No chapters match your search.', source: 'Current source: in-app help', languageNote: 'The detailed manual is currently available in English.',
    more: 'Read the manuals', ctaTitle: 'Ready to connect your work?', ctaBody: 'Enter the Hub, or start with the guide and build confidence step by step.',
    android: 'ARGUS Field for Android', androidNote: 'The Android app is in a restricted test. Ask andrea.michelotti@infn.it for access.',
    project: 'About the ARGUS project', footer: 'An INFN Group 5 project · Built for knowledge that survives handovers.',
    prev: 'Previous chapter', next: 'Next chapter', back: 'All manuals'
  },
  it: {
    home: 'Home', platform: 'Piattaforma', stories: 'Casi d’uso', start: 'Per iniziare', manuals: 'Manuali', launch: 'Apri l’Hub',
    eyebrow: 'ARGUS KNOWLEDGE HUB · INFN', hero: 'Ogni intervento diventa conoscenza per il tuo gruppo.',
    heroBody: 'Un luogo connesso per asset, documenti, ticket e progetti. Trova il contesto di un problema, registra il lavoro e rendi più facile trovare la prossima risposta.',
    explore: 'Scopri la piattaforma', heroStart: 'Inizia ora', signal: 'Da informazioni sparse a conoscenza connessa',
    intro: 'Sai cosa hai. Capisci cosa è successo. Vai avanti insieme agli altri.',
    introBody: 'ARGUS collega il mondo fisico di apparati e infrastrutture con il lavoro e la conoscenza che li riguardano. Ogni record diventa parte utile di una storia più ampia.',
    assets: 'Asset e luoghi', assetsBody: 'Passa dalla mappa o dalla planimetria alla scheda tecnica, agli interventi e ai documenti collegati.',
    work: 'Ticket e attività', workBody: 'Coordina guasti, richieste, lavori programmati e verifiche ricorrenti, conservando la storia degli interventi.',
    docs: 'Documenti', docsBody: 'Tieni procedure, rapporti, disegni e minute collegati a ciò che descrivono e alle persone che li usano.',
    ai: 'AI con contesto e verifica', aiBody: 'Fai domande sui record collegati e crea bozze strutturate da testi grezzi. Le persone verificano le proposte prima che diventino conoscenza affidabile.',
    graph: 'Grafo della conoscenza', graphBody: 'Esplora relazioni e dipendenze fra asset, interventi e documenti, anche quando un collegamento esplicito manca.',
    field: 'Dalla sala controllo al campo', fieldBody: 'Usa l’Hub sul web per la visione completa e ARGUS Field su Android per registrare i fatti dove si svolge il lavoro.',
    storyTitle: 'Pensato per sistemi complessi. Utile ogni giorno.', storyBody: 'Un guasto, un’ispezione, una nuova installazione o un passaggio di consegne: ARGUS tiene insieme le evidenze e il passo successivo.',
    story1: 'Indaga un guasto', story1Body: 'Parti dall’asset, controlla i ticket precedenti, trova la procedura pertinente e registra la soluzione.',
    story2: 'Pianifica ed esegui il lavoro', story2Body: 'Consulta le attività del workspace, programma le verifiche e collega l’esito agli apparati interessati.',
    story3: 'Trasforma appunti grezzi in un documento', story3Body: 'Usa un modello e l’aiuto dell’AI per creare una bozza; verifica date, fonti e testo prima della pubblicazione.',
    story4: 'Esplora un’infrastruttura', story4Body: 'Colloca edifici, stanze e apparati su mappe o planimetrie, poi passa dalla posizione alla scheda.',
    startTitle: 'I primi quindici minuti con ARGUS', startBody: 'Un percorso breve nella piattaforma. L’amministratore del workspace può aiutarti con l’accesso e con le regole del tuo gruppo.',
    steps: [
      ['01', 'Accedi', 'Apri l’Hub e usa l’account a cui l’amministratore ha dato accesso. In ARGUS la tua email ti identifica.'],
      ['02', 'Scegli un workspace', 'Seleziona la macchina, l’infrastruttura o il gruppo in cui lavori. Controlla il nome prima di creare record.'],
      ['03', 'Trova un asset', 'Usa la ricerca globale o Asset per aprire una scheda. Guarda posizione, ticket e documenti collegati.'],
      ['04', 'Registra il lavoro', 'Crea un ticket per un problema o un’attività per un lavoro previsto o concluso. Collega l’asset e documenta l’esito.'],
      ['05', 'Esplora la conoscenza', 'Apri un documento, segui il grafo o fai una domanda ad ARGUS. Verifica le proposte dell’AI prima di applicarle.']
    ],
    manualHeading: 'Manuali del prodotto', manualBody: 'Questi capitoli sono generati dalla guida inclusa in ARGUS Knowledge Hub. Cerca un argomento e apri la guida completa.',
    search: 'Cerca nei manuali…', all: 'Tutti i capitoli', noResults: 'Nessun capitolo corrisponde alla ricerca.', source: 'Fonte aggiornata: guida nell’app', languageNote: 'Il manuale dettagliato è attualmente disponibile in inglese.',
    more: 'Leggi i manuali', ctaTitle: 'Pronto a collegare il tuo lavoro?', ctaBody: 'Entra nell’Hub oppure inizia dalla guida e procedi un passo alla volta.',
    android: 'ARGUS Field per Android', androidNote: 'L’app Android è in test riservato. Chiedi l’accesso a andrea.michelotti@infn.it.',
    project: 'Il progetto ARGUS', footer: 'Un progetto INFN del Gruppo 5 · La conoscenza che resta, anche quando cambiano le persone.',
    prev: 'Capitolo precedente', next: 'Capitolo successivo', back: 'Tutti i manuali'
  }
};

const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const href = (lang, section = '') => `${base}${lang}/${section}`;
const nav = (lang, active) => {
  const t = ui[lang];
  return [['',t.home],['platform/',t.platform],['use-cases/',t.stories],['getting-started/',t.start],['manuals/',t.manuals]]
    .map(([p,label]) => `<a href="${href(lang,p)}" ${active===p?'aria-current="page"':''}>${label}</a>`).join('');
};
const shell = (lang, active, title, description, body) => {
  const t = ui[lang];
  const alternate = lang === 'en' ? 'it' : 'en';
  const current = `${href(lang,active)}`;
  const other = `${href(alternate,active)}`;
  return `<!doctype html><html lang="${lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#0d1930"><title>${esc(title)} · ARGUS Knowledge Hub</title><meta name="description" content="${esc(description)}"><link rel="canonical" href="https://infn-argus.github.io${current}"><link rel="alternate" hreflang="${alternate}" href="https://infn-argus.github.io${other}"><link rel="icon" href="${base}assets/argus-icon.png"><link rel="stylesheet" href="${base}assets/styles.css"></head><body><a class="skip" href="#main">Skip to content</a><header class="site-header"><div class="header-inner"><a class="brand" href="${href(lang)}" aria-label="ARGUS Knowledge Hub home"><img src="${base}assets/argus-icon.png" alt=""><span><strong>ARGUS</strong><small>KNOWLEDGE HUB</small></span></a><nav class="desktop-nav" aria-label="Main navigation">${nav(lang,active)}</nav><div class="header-actions"><a class="language" href="${other}" aria-label="${alternate==='en'?'English':'Italiano'}">${alternate.toUpperCase()}</a><a class="button button-small button-dark" href="${webApp}" target="_blank" rel="noopener">${t.launch} <span aria-hidden="true">↗</span></a><button class="menu-button" aria-label="Menu" aria-expanded="false" type="button">☰</button></div></div><nav class="mobile-nav" aria-label="Mobile navigation">${nav(lang,active)}</nav></header><main id="main">${body}</main><footer class="footer"><div class="footer-inner"><div><a class="footer-brand" href="${href(lang)}">ARGUS <span>Knowledge Hub</span></a><p>${t.footer}</p></div><div class="footer-links"><a href="${href(lang,'getting-started/')}">${t.start}</a><a href="${href(lang,'manuals/')}">${t.manuals}</a><a href="${project}?lang=${lang}">${t.project}</a><a href="mailto:andrea.michelotti@infn.it">Contact</a></div></div></footer><script src="${base}assets/site.js" defer></script></body></html>`;
};
const write = (relative, content) => { const target = path.join(out,relative); fs.mkdirSync(path.dirname(target),{recursive:true}); fs.writeFileSync(target,content); };
const card = (n,title,body) => `<article class="feature-card"><span class="feature-num">${n}</span><h3>${title}</h3><p>${body}</p></article>`;
const cta = lang => { const t=ui[lang]; return `<section class="cta"><div class="container cta-grid"><div><span class="eyebrow light">ARGUS KNOWLEDGE HUB</span><h2>${t.ctaTitle}</h2><p>${t.ctaBody}</p><div class="action-row"><a class="button button-light" href="${webApp}">${t.launch} ↗</a><a class="text-link light-link" href="${href(lang,'getting-started/')}">${t.start} →</a></div></div><div class="qr-box"><img src="${base}assets/qr-web-app.png" alt="QR code for ARGUS web app"><span>${t.launch}</span></div></div></section>`; };

const sourceFiles = fs.readdirSync(guide).filter(f=>/^\d+-.+\.md$/.test(f)).sort();
const chapters = sourceFiles.map(file=>{
  const raw = fs.readFileSync(path.join(guide,file),'utf8');
  const match = raw.match(/^---\n([\s\S]*?)\n---\n/);
  if (!match) throw new Error(`Missing front matter: ${file}`);
  const meta = Object.fromEntries(match[1].split('\n').map(line=>{const at=line.indexOf(':');return at<0?[]:[line.slice(0,at),line.slice(at+1).trim()];}).filter(x=>x.length));
  const body = raw.slice(match[0].length);
  return {slug:file.replace(/^\d+-/,'').replace(/\.md$/,''),title:meta.title,summary:meta.summary,keywords:meta.keywords||'',body,html:md.render(body),order:Number(meta.order)};
}).sort((a,b)=>a.order-b.order);

fs.rmSync(out,{recursive:true,force:true});
fs.mkdirSync(out,{recursive:true});
fs.cpSync(path.join(here,'assets'),path.join(out,'assets'),{recursive:true});
write('.nojekyll','');
write('index.html',`<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ARGUS Knowledge Hub</title><script>location.replace((navigator.language||'en').toLowerCase().startsWith('it')?'${base}it/':'${base}en/')</script><a href="${base}en/">English</a> · <a href="${base}it/">Italiano</a>`);
for (const lang of ['en','it']) {
  const t=ui[lang];
  const hero=`<section class="hero"><div class="hero-glow"></div><div class="container hero-inner"><div class="hero-copy"><span class="eyebrow">${t.eyebrow}</span><h1>${t.hero}</h1><p>${t.heroBody}</p><div class="action-row"><a class="button button-coral" href="${href(lang,'getting-started/')}">${t.heroStart} <span>↗</span></a><a class="text-link" href="${href(lang,'platform/')}">${t.explore} →</a></div></div><div class="hero-art" aria-label="Connected ARGUS records"><div class="orbit orbit-a"></div><div class="orbit orbit-b"></div><div class="hub-mark"><img src="${base}assets/argus-icon.png" alt=""><span>ARGUS</span></div><div class="node node-a"><i>◈</i><span>${t.assets}</span></div><div class="node node-b"><i>◇</i><span>${t.work}</span></div><div class="node node-c"><i>▤</i><span>${t.docs}</span></div><div class="node node-d"><i>✦</i><span>AI</span></div></div></div><div class="hero-bottom"><div class="container"><span class="pulse-dot"></span>${t.signal}</div></div></section>`;
  const home=`${hero}<section class="intro-section container"><span class="eyebrow dark">A CONNECTED OPERATING PICTURE</span><h2>${t.intro}</h2><p class="lead">${t.introBody}</p><div class="feature-grid">${card('01',t.assets,t.assetsBody)}${card('02',t.work,t.workBody)}${card('03',t.docs,t.docsBody)}</div></section><section class="split-section"><div class="container split-grid"><div class="diagram"><div class="diagram-main">Asset <span>↔</span> Ticket <span>↔</span> Document</div><div class="diagram-lines"><span>Location</span><span>Activity</span><span>Knowledge</span></div></div><div><span class="eyebrow dark">HUMAN KNOWLEDGE, AMPLIFIED</span><h2>${t.ai}</h2><p>${t.aiBody}</p><a class="text-link dark-link" href="${href(lang,'platform/')}">${t.explore} →</a></div></div></section><section class="container story-preview"><div class="section-heading"><div><span class="eyebrow dark">REAL WORKFLOWS</span><h2>${t.storyTitle}</h2></div><a class="text-link dark-link" href="${href(lang,'use-cases/')}">${t.stories} →</a></div><div class="story-grid"><article><span>01 / OPERATE</span><h3>${t.story1}</h3><p>${t.story1Body}</p></article><article><span>02 / REMEMBER</span><h3>${t.story3}</h3><p>${t.story3Body}</p></article></div></section>${cta(lang)}`;
  write(`${lang}/index.html`,shell(lang,'', 'Connected knowledge for complex operations',t.heroBody,home));
  const platform=`<section class="page-hero container"><span class="eyebrow dark">THE PLATFORM</span><h1>${t.intro}</h1><p>${t.introBody}</p></section><section class="container platform-grid">${card('01',t.assets,t.assetsBody)}${card('02',t.work,t.workBody)}${card('03',t.docs,t.docsBody)}${card('04',t.graph,t.graphBody)}${card('05',t.ai,t.aiBody)}${card('06',t.field,t.fieldBody)}</section><section class="container platform-bottom"><div class="callout"><strong>WEB</strong><h2>${t.launch}</h2><p>${t.ctaBody}</p><a class="button button-dark" href="${webApp}">${t.launch} ↗</a></div><div class="callout"><strong>ANDROID</strong><h2>${t.android}</h2><p>${t.androidNote}</p><a class="button button-outline" href="${playApp}">Google Play ↗</a></div></section>${cta(lang)}`;
  write(`${lang}/platform/index.html`,shell(lang,'platform/',t.platform,t.introBody,platform));
  const stories=`<section class="page-hero container"><span class="eyebrow dark">ARGUS IN PRACTICE</span><h1>${t.storyTitle}</h1><p>${t.storyBody}</p></section><section class="container case-grid">${[[t.story1,t.story1Body,'01','INCIDENT → RESOLUTION'],[t.story2,t.story2Body,'02','PLAN → PERFORM'],[t.story3,t.story3Body,'03','RAW TEXT → REVIEW'],[t.story4,t.story4Body,'04','MAP → EQUIPMENT']].map(([title,body,n,flow])=>`<article class="case-card"><div class="case-top"><span>${n}</span><small>${flow}</small></div><h2>${title}</h2><p>${body}</p></article>`).join('')}</section>${cta(lang)}`;
  write(`${lang}/use-cases/index.html`,shell(lang,'use-cases/',t.stories,t.storyBody,stories));
  const steps=`<section class="page-hero container"><span class="eyebrow dark">YOUR FIRST STEPS</span><h1>${t.startTitle}</h1><p>${t.startBody}</p></section><section class="container getting-grid"><div class="steps">${t.steps.map(([n,title,body])=>`<article class="step"><span class="step-number">${n}</span><div><h2>${title}</h2><p>${body}</p></div></article>`).join('')}</div><aside class="start-aside"><div class="aside-panel"><span class="eyebrow dark">START HERE</span><h3>${t.launch}</h3><img src="${base}assets/qr-web-app.png" alt="QR code for ARGUS web app"><a class="button button-dark" href="${webApp}">${t.launch} ↗</a></div><div class="aside-panel subtle"><h3>${t.more}</h3><p>${t.languageNote}</p><a class="text-link dark-link" href="${href(lang,'manuals/')}">${t.manuals} →</a></div></aside></section>${cta(lang)}`;
  write(`${lang}/getting-started/index.html`,shell(lang,'getting-started/',t.start,t.startBody,steps));
  const list=`<section class="page-hero container compact"><span class="eyebrow dark">ARGUS HELP</span><h1>${t.manualHeading}</h1><p>${t.manualBody}</p><div class="manual-search"><label for="manual-query" class="sr-only">${t.search}</label><input id="manual-query" type="search" placeholder="${t.search}" autocomplete="off"><span>⌕</span></div><p class="manual-note">${t.source} · ${t.languageNote}</p></section><section class="container manuals-list" id="manual-list">${chapters.map((c,i)=>`<a class="manual-row" href="${href(lang,`manuals/${c.slug}/`)}" data-search="${esc(`${c.title} ${c.summary} ${c.keywords} ${c.body}`.toLowerCase())}"><span class="manual-index">${String(i+1).padStart(2,'0')}</span><span><strong>${esc(c.title)}</strong><small>${esc(c.summary)}</small></span><span class="manual-arrow">↗</span></a>`).join('')}<p class="no-results" hidden>${t.noResults}</p></section>`;
  write(`${lang}/manuals/index.html`,shell(lang,'manuals/',t.manuals,t.manualBody,list));
  chapters.forEach((c,i)=>{
    const active=`manuals/${c.slug}/`;
    const before=chapters[i-1], after=chapters[i+1];
    const sidebar=chapters.map((x,j)=>`<a href="${href(lang,`manuals/${x.slug}/`)}" ${x.slug===c.slug?'aria-current="page"':''}><span>${String(j+1).padStart(2,'0')}</span>${esc(x.title)}</a>`).join('');
    const body=`<section class="manual-shell container"><aside class="manual-sidebar"><a class="back-link" href="${href(lang,'manuals/')}">← ${t.back}</a><div class="chapter-list">${sidebar}</div></aside><article class="manual-article"><div class="manual-breadcrumb"><a href="${href(lang,'manuals/')}">${t.manuals}</a><span>›</span>${esc(c.title)}</div><span class="eyebrow dark">CHAPTER ${String(i+1).padStart(2,'0')} / ${chapters.length}</span><h1>${esc(c.title)}</h1><p class="article-summary">${esc(c.summary)}</p><p class="manual-note">${t.languageNote}</p><div class="prose">${c.html}</div><nav class="chapter-pager">${before?`<a href="${href(lang,`manuals/${before.slug}/`)}"><small>← ${t.prev}</small><strong>${esc(before.title)}</strong></a>`:'<span></span>'}${after?`<a href="${href(lang,`manuals/${after.slug}/`)}"><small>${t.next} →</small><strong>${esc(after.title)}</strong></a>`:'<span></span>'}</nav></article></section>`;
    write(`${lang}/${active}index.html`,shell(lang,active,c.title,c.summary,body));
  });
}
write('search-index.json',JSON.stringify(chapters.map(({slug,title,summary,keywords,body})=>({slug,title,summary,keywords,body})),null,2));
console.log(`Built ${chapters.length} chapters × 2 languages into ${out}`);
