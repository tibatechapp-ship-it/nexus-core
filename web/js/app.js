// app logic — extracted from unified_ui.html

"use strict";
/* ============================ i18n ============================ */
const I18N={
  ar:{newChat:"محادثة جديدة",settings:"الإعدادات",language:"اللغة",online:"متصل",offline:"غير متصل",
    placeholder:"اكتب رسالتك…",enterSend:"للإرسال",shiftNewline:"سطر جديد",curAgent:"الوكيل الحالي",
    tools:"الأدوات المتاحة",stats:"إحصائيات",msgCount:"عدد الرسائل",lastUpdate:"آخر تحديث",conn:"حالة الاتصال",
    quick:"إعدادات سريعة",streaming:"البث المباشر",showInfo:"إظهار لوحة المعلومات",searchTitle:"بحث في المحادثات",
    confirmClear:"حذف كل المحادثات",close:"إغلاق",copy:"نسخ",copied:"تم النسخ ✅",del:"تم الحذف 🗑️",
    err:"خطأ في الاتصال ❌",you:"أنت",assistant:"NovaMind",regen:"إعادة",edit:"تعديل",save:"حفظ",cancel:"إلغاء",
    empty:"ابدأ محادثة جديدة ✨",deleteQ:"حذف هذه المحادثة؟",confirmClearQ:"حذف كل المحادثات نهائياً؟",
    stopped:"تم الإيقاف",thinking:"يكتب…",agentDefault:"الوكيل التلقائي",
    timeMachine:"🔭 آلة الزمن",clearTraces:"مسح السجل",clearTracesQ:"مسح كل سجل الطلبات؟",
    noTraces:"لا توجد طلبات مسجّلة بعد",replay:"إعادة التشغيل",export:"تصدير",
    request:"الطلب",response:"الرد",latency:"الزمن",status:"الحالة",replayDone:"تمت الإعادة — أُضيف طلب جديد",
    pin:"تثبيت",pinned:"تم التثبيت 📌",unpinned:"أُلغي التثبيت",
    exportAll:"تصدير كل المحادثات",importConvs:"استيراد محادثات",imported:"تم الاستيراد",
    council:"⚖️ المجلس الحيّ",history:"السجل",councilTopicPh:"ما الموضوع الذي يناقشه المجلس؟",
    rounds:"الجولات",startDebate:"ابدأ النقاش",verdict:"الحكم النهائي",consensus:"الإجماع",
    round:"الجولة",councilOpening:"انعقد المجلس…",councilNeedTopic:"اكتب الموضوع أولاً",
    noCouncil:"لا جلسات بعد",councilDone:"انتهى المجلس ⚖️",influence:"التأثير",
    genome:"🧬 جينوم الوكلاء",genomeHint:"مكانة كل وكيل تتطوّر حسب نتائجه في المجلس.",
    standings:"المكانة",runs:"التشغيلات",successRate:"نسبة النجاح",avgLatency:"متوسط الزمن",
    generation:"الجيل",persona:"الشخصية",retrain:"إعادة تدريب",retrainQ:"إعادة تدريب هذا الوكيل؟ (تُصفَّر إحصاءاته)",
    noAgents:"لا يوجد وكلاء بعد",agentSaved:"تم الحفظ ✅",genomeImported:"تم استيراد الجينوم",
    academy:"🎓 الأكاديمية",academyHint:"دروس الوكلاء ولياقاتهم ومراحل تدريبهم.",
    refresh:"تحديث",stages:"المراحل",lessons:"الدروس",fitness:"اللياقات",
    acaNoLessons:"لا توجد دروس بعد — درّب وكيلاً أولاً.",acaNoFitness:"لا توجد لياقات بعد.",
    acaNoStages:"لا توجد مراحل لهذا الوكيل.",acaHint:"درّب وكيلاً (POST /api/training/run) لتظهر بياناته هنا.",
    evolveDone:"تمت جولة تطوير",evolveNone:"لا يوجد ما يُطوَّر الآن",confidence:"الثقة",
    observations:"المشاهدات",agreements:"موافقات",dissent:"مخالفات",action:"الإجراء",
    judgements:"أحكام",tasks:"مهام",acaEvidence:"الدليل",acaAvgTime:"متوسط الزمن",
    acaNoTasks:"بلا مهام",acaLastTask:"آخر مهمة",
    acaEvolved:"وكلاء تطوروا",acaMutations:"طفرات",acaTicks:"دورات",acaAbsorbed:"دروس مضافة",
    module:"وحدة",weight:"الوزن",hours:"الساعات",source:"المصدر",score:"الدرجة",pass:"ناجح",fail:"راسب",
    apexAction_observe:"مراقبة",apexAction_promote:"ترقية",apexAction_keep:"إبقاء",
    apexAction_retrain:"إعادة تدريب",apexAction_revise:"مراجعة",apexAction_unknown:"غير معروف",
    fitnessStatus_elite:"نخبة",fitnessStatus_stable:"مستقر",fitnessStatus_probationary:"تحت المراقبة",
    import:"استيراد",timeline:"الخط الزمني",
    offlineQueued:"لا اتصال — ستُرسل عند العودة",synced:"تمت المزامنة ☁",installApp:"تثبيت التطبيق",queued:"قيد الانتظار"},
  en:{newChat:"New chat",settings:"Settings",language:"Language",online:"Online",offline:"Offline",
    placeholder:"Type your message…",enterSend:"to send",shiftNewline:"new line",curAgent:"Current agent",
    tools:"Available tools",stats:"Stats",msgCount:"Messages",lastUpdate:"Last update",conn:"Connection",
    quick:"Quick settings",streaming:"Live streaming",showInfo:"Show info panel",searchTitle:"Search chats",
    confirmClear:"Delete all conversations",close:"Close",copy:"Copy",copied:"Copied ✅",del:"Deleted 🗑️",
    err:"Connection error ❌",you:"You",assistant:"NovaMind",regen:"Regenerate",edit:"Edit",save:"Save",cancel:"Cancel",
    empty:"Start a new chat ✨",deleteQ:"Delete this conversation?",confirmClearQ:"Delete ALL conversations?",
    stopped:"Stopped",thinking:"Typing…",agentDefault:"Auto agent",
    timeMachine:"🔭 Time Machine",clearTraces:"Clear log",clearTracesQ:"Clear the whole request log?",
    noTraces:"No requests logged yet",replay:"Replay",export:"Export",
    request:"Request",response:"Response",latency:"Latency",status:"Status",replayDone:"Replayed — new request logged",
    pin:"Pin",pinned:"Pinned 📌",unpinned:"Unpinned",
    exportAll:"Export all conversations",importConvs:"Import conversations",imported:"Imported",
    council:"⚖️ The Living Council",history:"History",councilTopicPh:"What should the council debate?",
    rounds:"Rounds",startDebate:"Start debate",verdict:"Final verdict",consensus:"Consensus",
    round:"Round",councilOpening:"Council convened…",councilNeedTopic:"Enter a topic first",
    noCouncil:"No sessions yet",councilDone:"Council concluded ⚖️",influence:"Influence",
    genome:"🧬 Agent Genome",genomeHint:"Each agent's standing evolves from its council results.",
    standings:"Standing",runs:"Runs",successRate:"Success",avgLatency:"Avg latency",
    generation:"Generation",persona:"Persona",retrain:"Retrain",retrainQ:"Retrain this agent? (stats reset)",
    noAgents:"No agents yet",agentSaved:"Saved ✅",genomeImported:"Genome imported",
    academy:"🎓 Agent Academy",academyHint:"Agent lessons, fitness and training stages.",
    refresh:"Refresh",stages:"Stages",lessons:"Lessons",fitness:"Fitness",
    acaNoLessons:"No lessons yet — train an agent first.",acaNoFitness:"No fitness yet.",
    acaNoStages:"No stages for this agent.",acaHint:"Train an agent (POST /api/training/run) to fill this in.",
    evolveDone:"Evolution pass done",evolveNone:"Nothing to evolve right now",confidence:"Confidence",
    observations:"Observations",agreements:"Agreements",dissent:"Dissents",action:"Action",
    judgements:"Judgements",tasks:"Tasks",acaEvidence:"Evidence",acaAvgTime:"Avg time",
    acaNoTasks:"no tasks",acaLastTask:"Last task",
    acaEvolved:"agents evolved",acaMutations:"mutations",acaTicks:"ticks",acaAbsorbed:"lessons absorbed",
    module:"Module",weight:"Weight",hours:"Hours",source:"Source",score:"Score",pass:"pass",fail:"fail",
    apexAction_observe:"observe",apexAction_promote:"promote",apexAction_keep:"keep",
    apexAction_retrain:"retrain",apexAction_revise:"revise",apexAction_unknown:"unknown",
    fitnessStatus_elite:"elite",fitnessStatus_stable:"stable",fitnessStatus_probationary:"probationary",
    import:"Import",timeline:"Timeline",
    offlineQueued:"Offline — will send later",synced:"Synced ☁",installApp:"Install app",queued:"queued"}
};
const API={chat:"/api/chat",agents:"/api/agents",convs:"/api/conversations",traces:"/api/traces",council:"/api/council",genome:"/api/genome",training:"/api/training"};
const LS={conv:"nm_convs",cur:"nm_cur",lang:"nm_lang",migrated:"nm_migrated"};
const MAX_CONV=200;
let useDB=true;              // false = localStorage fallback (API unreachable)
let codes=[];               // highlighted code blocks (per render, kept for copy)

/* ============================ state ============================ */
let state={convs:[],cur:null,lang:"ar",agents:[],agent:"",streaming:false,ctrl:null,stream:true,curTrace:null};
const $=id=>document.getElementById(id);
const t=k=>(I18N[state.lang]||I18N.ar)[k]||k;

/* ============================ storage ============================ */
/* ============================ storage (DB-first) ============================ */
async function apiGet(p){const r=await fetch(p);if(!r.ok)throw new Error("HTTP "+r.status);return r.json();}
async function apiSend(method,p,body){
  try{const r=await fetch(p,{method,headers:{"Content-Type":"application/json"},
    body:body?JSON.stringify(body):undefined});
    return r.ok?await r.json():null;}catch(e){return null;}
}
// push the whole thread to SQLite (client-authoritative sync). Never wipes messages
// that aren't loaded yet.
function saveConv(c){
  if(!useDB||!c)return;
  const body={title:c.title,agent:c.agent||"",meta:c.meta||{}};
  if(c.messages)body.messages=c.messages.map(m=>({role:m.role,content:m.content,ts:m.ts||Date.now()}));
  apiSend("PUT",API.convs+"/"+c.id,body);
}
function saveCache(){  // localStorage mirror → offline fallback
  try{localStorage.setItem(LS.conv,JSON.stringify(state.convs.slice(0,MAX_CONV)));}catch(e){}
  localStorage.setItem(LS.cur,state.cur||"");
  localStorage.setItem(LS.lang,state.lang);
}
function save(){saveCache();const c=curConv();if(c)saveConv(c);}
async function load(){
  state.lang=localStorage.getItem(LS.lang)||"ar";
  let cached=[];try{cached=JSON.parse(localStorage.getItem(LS.conv)||"[]")}catch(e){cached=[]}
  try{
    let j=await apiGet(API.convs);state.convs=j.conversations||[];useDB=true;
    if(!localStorage.getItem(LS.migrated)){
      if(Array.isArray(cached)&&cached.length){
        await apiSend("POST",API.convs+"/migrate",{conversations:cached});
        j=await apiGet(API.convs);state.convs=j.conversations||[];
      }
      localStorage.setItem(LS.migrated,"1");
    }
  }catch(e){
    useDB=false;state.convs=Array.isArray(cached)?cached:[];
  }
  state.cur=localStorage.getItem(LS.cur)||null;
  if(!Array.isArray(state.convs))state.convs=[];
}
// list endpoint omits messages → hydrate the selected conversation on demand
async function ensureMessages(c){
  if(!c||c.messages)return;
  if(!useDB){c.messages=c.messages||[];return;}
  try{const d=await apiGet(API.convs+"/"+c.id);c.messages=d.messages||[];c.message_count=(d.messages||[]).length;}
  catch(e){c.messages=c.messages||[];}
}
const curConv=()=>state.convs.find(c=>c.id===state.cur);
async function newChat(){
  const c={id:"c"+Date.now().toString(36)+Math.random().toString(36).slice(2,6),
    title:t("empty"),messages:[],agent:state.agent,date:Date.now(),message_count:0};
  state.convs.unshift(c);state.cur=c.id;saveConv(c);saveCache();
  renderSidebar();await renderMessages();renderInfo();closeAll();
  $("input").focus();return c;
}

/* ============================ time / helpers ============================ */
function fmt(ts){const d=new Date(ts);
  return d.toLocaleDateString(state.lang==="ar"?"ar-EG":"en-US",{month:"short",day:"numeric"})+", "+
    d.toLocaleTimeString(state.lang==="ar"?"ar-EG":"en-US",{hour:"2-digit",minute:"2-digit"});}

/* ============================ markdown ============================ */
function esc(s){return s.replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
function inline(s){
  s=s.replace(/`([^`]+)`/g,"<code class=\"ic\">$1</code>");
  s=s.replace(/!\[([^\]]*)\]\((https?:[^)\s]+)\)/g,'<img src="$2" alt="$1" loading="lazy">');
  s=s.replace(/\*\*([^*\n]+)\*\*/g,"<strong>$1</strong>");
  s=s.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g,"$1<em>$2</em>");
  s=s.replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g,'<a href="$2" target="_blank" rel="noopener">$1</a>');
  return s;
}
function md(src){
  src=String(src==null?"":src);
  const lines=src.split("\n");const out=[];let i=0;
  codes=[];
  const isBlank=l=>/^\s*$/.test(l);
  const isTableStart=k=>k<lines.length&&lines[k].includes("|")&&k+1<lines.length
    &&/^[\s|:-]+$/.test(lines[k+1])&&lines[k+1].includes("-");
  const tCells=h=>h.replace(/^\s*\|/,"").replace(/\|\s*$/,"").split("|").map(x=>x.trim());
  while(i<lines.length){
    const line=lines[i];
    let m;
    if(m=line.match(/^\s*```(\w+)?\s*$/)){
      const lang=m[1]||"";i++;const buf=[];
      while(i<lines.length&&!/^\s*```\s*$/.test(lines[i])){buf.push(lines[i]);i++;}
      i++;const raw=buf.join("\n");const idx=codes.push({lang,raw})-1;
      out.push("@@C"+idx+"@@");continue;
    }
    if(isBlank(line)){i++;continue;}
    if(m=line.match(/^(#{1,6})\s+(.*)$/)){const n=m[1].length;out.push("<h"+n+">"+inline(esc(m[2]))+"</h"+n+">");i++;continue;}
    if(/^\s*[-*+]\s+/.test(line)){out.push("<ul>");
      while(i<lines.length&&/^\s*[-*+]\s+/.test(lines[i])){out.push("<li>"+inline(esc(lines[i].replace(/^\s*[-*+]\s+/,"")))+"</li>");i++;}out.push("</ul>");continue;}
    if(/^\s*\d+[.)]\s+/.test(line)){out.push("<ol>");
      while(i<lines.length&&/^\s*\d+[.)]\s+/.test(lines[i])){out.push("<li>"+inline(esc(lines[i].replace(/^\s*\d+[.)]\s+/,"")))+"</li>");i++;}out.push("</ol>");continue;}
    if(/^\s*>\s?/.test(line)){out.push("<blockquote>"+inline(esc(line.replace(/^\s*>\s?/,"")))+"</blockquote>");i++;continue;}
    if(/^\s*---+\s*$/.test(line)){out.push("<hr>");i++;continue;}
    if(isTableStart(i)){
      const head=tCells(lines[i]);i+=2;const rows=[];
      while(i<lines.length&&lines[i].includes("|")&&!isBlank(lines[i])){rows.push(tCells(lines[i]));i++;}
      out.push("<table><thead><tr>"+head.map(h=>"<th>"+inline(esc(h))+"</th>").join("")+"</tr></thead><tbody>"+
        rows.map(r=>"<tr>"+r.map(c=>"<td>"+inline(esc(c))+"</td>").join("")+"</tr>").join("")+"</tbody></table>");
      continue;
    }
    const p=[];
    while(i<lines.length&&!isBlank(lines[i])&&!/^\s*```/.test(lines[i])&&!/^#{1,6}\s/.test(lines[i])
      &&!/^\s*[-*+]\s+/.test(lines[i])&&!/^\s*\d+[.)]\s+/.test(lines[i])&&!/^\s*>/.test(lines[i])
      &&!/^\s*---+\s*$/.test(lines[i])&&!isTableStart(i)){
      p.push(lines[i]);i++;}
    out.push("<p>"+inline(esc(p.join("\n"))).replace(/\n/g,"<br>")+"</p>");
  }
  return out.join("\n").replace(/@@C(\d+)@@/g,(_,k)=>{
    const c=codes[+k];
    return '<div class="code"><div class="code-head"><span>'+(c.lang||"code")+
      '</span><button class="code-copy" data-idx="'+k+'">'+t("copy")+'</button></div>'+
      '<pre><code class="hljs'+(c.lang?" language-"+c.lang:"")+'">'+esc(c.raw)+'</code></pre></div>';
  });
}

/* ============================ render: sidebar ============================ */
function renderSidebar(){
  const box=$("convList");box.innerHTML="";
  if(!state.convs.length){box.innerHTML='<div style="color:var(--faint);text-align:center;padding:24px 8px;font-size:13px">'+t("empty")+'</div>';return;}
  const sorted=state.convs.slice().sort((a,b)=>{
    const pa=(a.meta&&a.meta.pinned)?1:0,pb=(b.meta&&b.meta.pinned)?1:0;
    return pb-pa||(b.date||0)-(a.date||0);});
  sorted.forEach(c=>{
    const el=document.createElement("div");
    el.className="conv"+(c.id===state.cur?" active":"");
    el.dataset.id=c.id;
    el.innerHTML='<div class="meta"><div class="title"></div><div class="date"></div></div>'+
      '<button class="pin'+(c.meta&&c.meta.pinned?" on":"")+'" title="'+t("pin")+'">📌</button>'+
      '<button class="del" title="'+t("del")+'"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14"/></svg></button>';
    el.querySelector(".title").textContent=(c.meta&&c.meta.pinned?"📌 ":"")+(c.title||t("empty"));
    el.querySelector(".date").textContent=fmt(c.date||Date.now());
    el.onclick=e=>{if(e.target.closest(".del")||e.target.closest(".pin"))return;state.cur=c.id;save();
      renderSidebar();renderMessages();renderInfo();closeAll();};
    el.querySelector(".title").ondblclick=e=>{e.stopPropagation();renameConv(c);};
    el.querySelector(".pin").onclick=e=>{e.stopPropagation();
      c.meta=c.meta||{};c.meta.pinned=!c.meta.pinned;saveConv(c);saveCache();renderSidebar();
      toast(c.meta.pinned?"📌 "+t("pinned"):t("unpinned"));};
    el.querySelector(".del").onclick=()=>{if(confirm(t("deleteQ"))){
      if(useDB)apiSend("DELETE",API.convs+"/"+c.id);
      state.convs=state.convs.filter(x=>x.id!==c.id);
      if(state.cur===c.id)state.cur=state.convs[0]?state.convs[0].id:null;
      saveCache();renderSidebar();renderMessages();renderInfo();toast(t("del"));}};
    box.appendChild(el);
  });
}
function renameConv(c){
  const el=document.querySelector('#convList .conv[data-id="'+c.id+'"]');
  if(!el)return;
  const titleEl=el.querySelector(".title");
  const inp=document.createElement("input");
  inp.className="rename";inp.value=c.title||"";
  titleEl.replaceWith(inp);inp.focus();inp.select();
  let done=false;
  const commit=()=>{if(done)return;done=true;const v=inp.value.trim();if(v)c.title=v;saveConv(c);saveCache();renderSidebar();};
  inp.onclick=e=>e.stopPropagation();
  inp.onblur=commit;
  inp.onkeydown=e=>{if(e.key==="Enter"){e.preventDefault();commit();}
    else if(e.key==="Escape"){e.preventDefault();done=true;renderSidebar();}};
}

/* ============================ render: messages ============================ */
function bubbleHTML(role,content,streaming){
  if(role==="assistant")return streaming?esc(content):md(content);
  return esc(content).replace(/\n/g,"<br>");
}
function msgNode(m,idx){
  const row=document.createElement("div");
  row.className="msg "+(m.role==="user"?"user":"assistant");
  const av=document.createElement("div");
  av.className="av "+(m.role==="user"?"me":"ai");
  av.textContent=m.role==="user"?"أ":"N";
  const wrap=document.createElement("div");wrap.className="bubble-wrap";
  const b=document.createElement("div");b.className="bubble"+(m.streaming?" streaming":"");
  b.innerHTML=bubbleHTML(m.role,m.content,m.streaming);
  wrap.appendChild(b);
  // actions
  const acts=document.createElement("div");acts.className="msg-actions";
  if(m.role==="user"){
    acts.innerHTML=btn("copy","<path d='M9 9h10v10H9z'/><path d='M5 15V5h10'/>")+
                   btn("edit","<path d='M12 20h9'/><path d='M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z'/>");
  }else{
    acts.innerHTML=btn("copy","<path d='M9 9h10v10H9z'/><path d='M5 15V5h10'/>")+
                   btn("regen","<path d='M23 4v6h-6M1 20v-6h6'/><path d='M3.5 9a9 9 0 0 1 14.9-3.4L23 10M1 14l4.6 4.4A9 9 0 0 0 20.5 15'/>");
  }
  acts.querySelectorAll("button").forEach(btnEl=>{
    btnEl.onclick=()=>handleAction(btnEl.dataset.k,idx);
  });
  wrap.appendChild(acts);
  row.appendChild(av);row.appendChild(wrap);
  return row;
}
function btn(k,path){return '<button class="act" data-k="'+k+'" title="'+t(k)+'"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">'+path+'</svg></button>';}
async function renderMessages(){
  const box=$("messages");box.innerHTML="";codes=[];
  const c=curConv();
  if(c)await ensureMessages(c);
  if(!c||!(c.messages||[]).length){
    box.innerHTML='<div style="max-width:820px;margin:14vh auto;text-align:center;color:var(--faint)">'+
      '<div style="font-size:44px;margin-bottom:12px">✨</div>'+t("empty")+'</div>';return;
  }
  c.messages.forEach((m,idx)=>box.appendChild(msgNode(m,idx)));
  highlightAll();scrollDown(true);
}
function highlightAll(){
  if(!window.hljs)return;
  $("messages").querySelectorAll("pre code").forEach(el=>{try{hljs.highlightElement(el)}catch(e){}});
}
function scrollDown(force){
  const box=$("messages");
  const near=box.scrollHeight-box.scrollTop-box.clientHeight<120;
  if(force||near)box.scrollTop=box.scrollHeight;
}

/* ============================ actions ============================ */
function handleAction(k,idx){
  const c=curConv();if(!c)return;
  const m=c.messages[idx];
  if(k==="copy"){navigator.clipboard.writeText(m.content).then(()=>toast(t("copied"))).catch(()=>toast(t("err"),1));}
  else if(k==="regen"){regenerate(idx);}
  else if(k==="edit"){editMessage(idx);}
}
function editMessage(idx){
  const c=curConv();const m=c.messages[idx];
  const row=$("messages").children[idx];const b=row.querySelector(".bubble");
  b.classList.add("edit");
  b.innerHTML='<textarea>'+esc(m.content)+'</textarea><div class="edit-row">'+
    '<button class="pill ghost" data-c>'+t("cancel")+'</button><button class="pill" data-s>'+t("save")+'</button></div>';
  const ta=b.querySelector("textarea");ta.focus();
  b.querySelector("[data-c]").onclick=()=>renderMessages();
  b.querySelector("[data-s]").onclick=()=>{
    const v=ta.value.trim();if(!v)return;
    c.messages=c.messages.slice(0,idx+1);c.messages[idx].content=v;
    if(idx===0)c.title=v.slice(0,42);
    save();renderMessages();renderSidebar();streamReply(c);
  };
}
function regenerate(idx){
  const c=curConv();
  let ui=idx;while(ui>=0&&c.messages[ui].role!=="user")ui--;
  if(ui<0)return;
  const text=c.messages[ui].content;
  c.messages=c.messages.slice(0,ui+1);
  save();renderMessages();streamReply(c,text);
}

/* ============================ send ============================ */
function pushUser(c,text){
  c.messages.push({role:"user",content:text,ts:Date.now()});
  if(!c.title||c.title===t("empty")||c.title==="محادثة جديدة"||c.title==="New chat")c.title=text.slice(0,42);
  c.date=Date.now();save();
}
function send(){
  if(state.streaming)return;
  const box=$("input");const text=box.value.trim();if(!text)return;
  let c=curConv();if(!c)c=newChat();
  box.value="";autoGrow();$("charCount").textContent="0";
  pushUser(c,text);renderSidebar();renderMessages();
  if(!navigator.onLine){qAdd({conv:c.id,text,ts:Date.now()});toast(t("offlineQueued"),1);return;}
  streamReply(c,text);
}
async function streamReply(c,text){
  const last=text||(c.messages.filter(m=>m.role==="user").slice(-1)[0]||{}).content||"";
  const am={role:"assistant",content:"",streaming:true};
  c.messages.push(am);state.streaming=true;renderMessages();setBusy(true);
  // typing indicator
  const box=$("messages");
  const typing=document.createElement("div");typing.className="msg assistant";
  typing.innerHTML='<div class="av ai">N</div><div class="bubble-wrap"><div class="typing"><i></i><i></i><i></i></div></div>';
  box.appendChild(typing);scrollDown(true);
  const done=()=>{am.streaming=false;state.streaming=false;setBusy(false);typing.remove();
    c.date=Date.now();save();renderMessages();renderInfo();setTimeout(scrollDown,30);};
  let acc="";
  try{
    state.ctrl=new AbortController();
    const res=await fetch(API.chat,{method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({message:last,thread_id:c.id,conversation_id:c.id,agent:state.agent}),
      signal:state.ctrl.signal});
    if(!res.ok)throw new Error("HTTP "+res.status);
    if(!res.body||!state.stream){                 // no stream support → text
      am.content=await res.text();am.streaming=false;renderMessages();done();return;
    }
    const reader=res.body.getReader();const dec=new TextDecoder();let buf="";
    while(true){
      const r=await reader.read();if(r.done)break;
      buf+=dec.decode(r.value,{stream:true});
      let sep;
      while((sep=buf.indexOf("\n\n"))>=0){
        const raw=buf.slice(0,sep);buf=buf.slice(sep+2);
        const ev=raw.split("\n").find(l=>l.startsWith("data:"));
        if(!ev)continue;
        const data=ev.slice(5).trim();
        if(data==="[DONE]")continue;
        let o;try{o=JSON.parse(data)}catch(e){continue;}
        if(o.type==="chunk"){acc+=o.content;
          const rows=box.querySelectorAll(".msg");const mine=rows[rows.length-1];
          const bb=mine&&mine.querySelector(".bubble");if(bb)bb.textContent=acc;
          if(!typing.parentNode){/*already removed*/} else typing.remove?0:0;
          if(typing.isConnected===false){}
          scrollDown(false);
        }else if(o.type==="plan"){/* shown via plan chip below */ am.plan=o.content;
        }else if(o.type==="error"){am.error=true;acc+=o.content;}
      }
    }
  }catch(err){
    if(err&&err.name==="AbortError"){am.content=acc||t("stopped");}
    else if(!navigator.onLine){qAdd({conv:c.id,text:last,ts:Date.now()});
      am.error=true;am.content=acc||("⏳ "+t("offlineQueued"));toast(t("offlineQueued"),1);}
    else{am.error=true;am.content=acc||("⚠️ "+t("err")+" ("+err.message+")");toast(t("err"),1);}
  }finally{
    if(am.content!==""||acc)am.content=acc;
    done();
  }
}
function setBusy(b){
  const s=$("btnSend");
  s.disabled=!b&&$("input").value.trim()==="";
  s.classList.toggle("stop",b);
  s.innerHTML=b?'<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>'
    :'<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 2 11 13M22 2l-7 20-4-9-9-4 20-7z"/></svg>';
}

/* ============================ info panel ============================ */
function renderInfo(){
  const c=curConv();
  const a=state.agents.find(x=>x.name===state.agent)||{name:t("agentDefault"),description:""};
  $("infoAgent").textContent=a.name||"—";
  $("infoAgentDesc").textContent=a.description||t("agentDefault");
  $("stMsg").textContent=c?((c.messages||[]).length||c.message_count||0):0;
  $("stTime").textContent=c?fmt(c.date||Date.now()):"—";
  $("stConn").textContent=navigator.onLine?t("online"):t("offline");
  const tools=$("infoTools");tools.innerHTML="";
  state.agents.slice(0,40).forEach(x=>{const s=document.createElement("span");s.className="tool";s.textContent=x.name;tools.appendChild(s);});
  if(state.agents.length>40){const s=document.createElement("span");s.className="tool";s.textContent="+"+(state.agents.length-40);tools.appendChild(s);}
}
function renderAgents(){
  const sel=$("agentSelect");sel.innerHTML="";
  const def=document.createElement("option");def.value="";def.textContent=t("agentDefault");sel.appendChild(def);
  state.agents.forEach(a=>{const o=document.createElement("option");o.value=a.name;o.textContent=a.name;sel.appendChild(o);});
  sel.value=state.agent||"";
  sel.onchange=()=>{state.agent=sel.value;renderInfo();};
}

/* ============================ overlays ============================ */
function closeAll(){$("sidebar").classList.remove("open");$("info").classList.remove("open");
  $("backdrop").classList.remove("show");$("searchModal").classList.remove("show");$("settingsModal").classList.remove("show");
  $("tracesModal").classList.remove("show");$("councilModal").classList.remove("show");$("genomeModal").classList.remove("show");
  $("academyModal").classList.remove("show");}
function openSearch(){closeAll();$("searchModal").classList.add("show");$("backdrop").classList.add("show");
  const inp=$("searchInput");inp.value="";searchRender("");inp.focus();}
async function searchRender(q){
  q=q.trim();const box=$("searchResults");box.innerHTML="";
  let list;
  if(useDB&&q){try{list=(await apiGet(API.convs+"?q="+encodeURIComponent(q))).conversations;}catch(e){list=[];}}
  else{const ql=q.toLowerCase();list=state.convs.filter(c=>!ql||(c.title||"").toLowerCase().includes(ql)||
    (c.messages||[]).some(m=>(m.content||"").toLowerCase().includes(ql)));}
  if(!list.length){box.innerHTML='<div style="color:var(--faint);padding:14px;text-align:center">—</div>';return;}
  list.forEach(c=>{const el=document.createElement("div");el.className="result";
    el.innerHTML='<div></div><div class="d"></div>';
    el.children[0].textContent=c.title||t("empty");
    el.children[1].textContent=fmt(c.date||c.updated_at||Date.now())+" · "+(c.message_count!=null?c.message_count:(c.messages||[]).length);
    el.onclick=async()=>{state.cur=c.id;if(!state.convs.find(x=>x.id===c.id))state.convs.unshift(c);
      saveCache();renderSidebar();await renderMessages();renderInfo();closeAll();};
    box.appendChild(el);});
}
/* ============================ time machine ============================ */
async function openTraces(){
  closeAll();
  $("tracesModal").classList.add("show");$("backdrop").classList.add("show");
  state.curTrace=null;
  const det=$("traceDetail");det.classList.remove("show");det.innerHTML="";
  const inp=$("traceSearch");inp.value="";
  inp.oninput=()=>renderTraces(inp.value);
  await renderTraces("");
  inp.focus();
}
async function renderTraces(q){
  const box=$("traceList");box.innerHTML="";
  let list;
  try{
    const url=q?API.traces+"?q="+encodeURIComponent(q):API.traces+"?limit=200";
    list=(await apiGet(url)).traces||[];
  }catch(e){list=[];}
  if(!list.length){box.innerHTML='<div style="color:var(--faint);padding:14px;text-align:center">'+t("noTraces")+'</div>';return;}
  list.forEach(tr=>{
    const el=document.createElement("div");
    el.className="trace-item"+(state.curTrace===tr.id?" sel":"");
    el.innerHTML='<div class="t"></div><div class="d"></div>';
    el.children[0].textContent=(tr.message||"").slice(0,80)||"—";
    el.children[1].textContent=fmt(tr.ts)+" · "+tr.latency_ms+"ms · "+tr.status+" · "+(tr.agent||t("agentDefault"));
    el.onclick=()=>openTraceDetail(tr.id);
    box.appendChild(el);
  });
}
async function openTraceDetail(tid){
  state.curTrace=tid;
  let tr;try{tr=await apiGet(API.traces+"/"+tid);}catch(e){toast(t("err"),1);return;}
  const d=$("traceDetail");d.classList.add("show");
  d.innerHTML='<h4>'+t("request")+'</h4><pre class="req"></pre>'+
    '<h4>'+t("response")+'</h4><pre class="res"></pre>'+
    '<div class="trace-detail-actions"></div>'+
    '<div class="trace-meta"></div>';
  d.querySelector(".req").textContent=tr.message||"—";
  d.querySelector(".res").textContent=tr.response||"—";
  d.querySelector(".trace-meta").textContent=
    fmt(tr.ts)+" · "+t("latency")+": "+tr.latency_ms+"ms · "+t("status")+": "+tr.status;
  const acts=d.querySelector(".trace-detail-actions");
  const bR=document.createElement("button");bR.className="pill";bR.textContent="↻ "+t("replay");
  const bJ=document.createElement("button");bJ.className="pill ghost";bJ.textContent="⬇ "+t("export")+" JSON";
  const bM=document.createElement("button");bM.className="pill ghost";bM.textContent="⬇ "+t("export")+" MD";
  acts.append(bR,bJ,bM);
  bR.onclick=()=>replayTrace(tid);
  bJ.onclick=()=>window.open(API.traces+"/"+tid+"/export?format=json","_blank");
  bM.onclick=()=>window.open(API.traces+"/"+tid+"/export?format=markdown","_blank");
  renderTraces($("traceSearch").value);
}
async function replayTrace(tid){
  const r=await apiSend("POST",API.traces+"/"+tid+"/replay",{});
  if(!r||!r.trace){toast(t("err"),1);return;}
  state.curTrace=r.trace.id;
  toast(t("replayDone"));
  await renderTraces($("traceSearch").value);
  openTraceDetail(r.trace.id);
}
/* ============================ living council ============================ */
function openCouncil(){
  closeAll();
  $("councilModal").classList.add("show");$("backdrop").classList.add("show");
  $("councilHistoryList").style.display="none";$("councilHistoryList").innerHTML="";
  $("councilTopic").focus();
}
async function startCouncil(){
  const topic=($("councilTopic").value||"").trim();
  if(!topic){toast(t("councilNeedTopic"),1);return;}
  const rounds=Math.max(1,Math.min(5,parseInt($("councilRounds").value||"3",10)||3));
  const btn=$("councilStart");btn.disabled=true;
  const stream=$("councilStream");stream.innerHTML="";
  $("councilMembers").innerHTML="";
  const verdict=$("councilVerdict");verdict.classList.remove("show");verdict.innerHTML="";
  $("councilHistoryList").style.display="none";
  try{
    const r=await fetch(API.council+"/stream",{method:"POST",
      headers:{"Content-Type":"application/json"},body:JSON.stringify({topic,rounds})});
    if(!r.ok||!r.body){toast(t("err"),1);btn.disabled=false;return;}
    const reader=r.body.getReader();const dec=new TextDecoder();let buf="";
    while(true){
      const {value,done}=await reader.read();if(done)break;
      buf+=dec.decode(value,{stream:true});
      const parts=buf.split("\n\n");buf=parts.pop();
      for(const p of parts){const line=p.trim();if(!line.startsWith("data:"))continue;
        const data=line.slice(5).trim();if(data==="[DONE]")continue;
        try{councilEvent(JSON.parse(data));}catch(e){}}
    }
    toast(t("councilDone"));
  }catch(e){toast(t("err"),1);}
  btn.disabled=false;
}
function councilEvent(ev){
  const stream=$("councilStream");
  if(ev.type==="session"){
    const m=$("councilMembers");m.innerHTML="";
    (ev.members||[]).forEach(mm=>{const c=document.createElement("span");
      c.className="council-chip";c.id="chip-"+mm.id;
      c.textContent=(mm.emoji||"")+" "+(mm.name||mm.id);m.appendChild(c);});
    const note=document.createElement("div");note.className="council-round";
    note.textContent=t("councilOpening");stream.appendChild(note);
  }else if(ev.type==="round"){
    const d=document.createElement("div");d.className="council-round";
    d.textContent="— "+t("round")+" "+ev.round+" / "+ev.total+" —";stream.appendChild(d);
  }else if(ev.type==="member_start"){
    const c=$("chip-"+ev.agent);if(c)c.classList.add("speaking");
  }else if(ev.type==="member_message"){
    const c=$("chip-"+ev.agent);if(c)c.classList.remove("speaking");
    const el=document.createElement("div");el.className="council-msg";
    el.innerHTML='<div class="cm-head"><span class="cm-name"></span><span class="cm-meta"></span></div><div class="cm-body"></div>';
    el.querySelector(".cm-name").textContent=(ev.emoji||"")+" "+(ev.name||ev.agent);
    el.querySelector(".cm-meta").textContent=(ev.provider||"")+(ev.elapsed?(" · "+Math.round(ev.elapsed*1000)+"ms"):"");
    el.querySelector(".cm-body").textContent=ev.content||"";
    stream.appendChild(el);stream.scrollTop=stream.scrollHeight;
  }else if(ev.type==="consensus"){
    const el=document.createElement("div");el.className="council-consensus";
    el.innerHTML='<span></span><div class="bar"><i></i></div>';
    el.children[0].textContent=t("consensus")+" "+Math.round((ev.score||0)*100)+"%";
    stream.appendChild(el);stream.scrollTop=stream.scrollHeight;
    requestAnimationFrame(()=>{el.querySelector("i").style.width=Math.round((ev.score||0)*100)+"%";});
  }else if(ev.type==="verdict"){
    const v=$("councilVerdict");v.classList.add("show");
    v.innerHTML='<h4></h4><div class="v-body"></div><div class="v-inf"></div>';
    v.querySelector("h4").textContent="⚖️ "+t("verdict")+" · "+t("consensus")+" "+Math.round((ev.consensus||0)*100)+"%";
    v.querySelector(".v-body").textContent=ev.verdict||"";
    const inf=ev.influence||{},box=v.querySelector(".v-inf");
    Object.keys(inf).forEach(k=>{const d=inf[k]||{};const up=d.standing_delta>0;
      const s=document.createElement("span");s.className="inf "+(up?"up":"down");
      s.textContent=k+" "+(up?"▲":"▼")+" "+Math.round((d.alignment||0)*100)+"%";box.appendChild(s);});
    v.scrollIntoView({behavior:"smooth",block:"nearest"});
  }else if(ev.type==="error"){toast(ev.message||t("err"),1);}
}
async function toggleCouncilHistory(){
  const box=$("councilHistoryList");
  if(box.style.display!=="none"){box.style.display="none";return;}
  box.style.display="block";box.innerHTML='<div style="color:var(--faint);padding:10px;text-align:center">…</div>';
  let list=[];try{list=(await apiGet(API.council+"/sessions")).sessions||[];}catch(e){list=[];}
  box.innerHTML="";
  if(!list.length){box.innerHTML='<div style="color:var(--faint);padding:10px;text-align:center">'+t("noCouncil")+'</div>';return;}
  list.forEach(s=>{const el=document.createElement("div");el.className="trace-item";
    el.innerHTML='<div class="t"></div><div class="d"></div>';
    el.children[0].textContent=(s.topic||"").slice(0,90)||"—";
    el.children[1].textContent=fmt(s.created_at)+" · "+Math.round((s.consensus||0)*100)+"% · "+t("rounds")+" "+(s.rounds||0);
    el.onclick=()=>loadCouncilSession(s.id);box.appendChild(el);});
}
async function loadCouncilSession(sid){
  let s;try{s=await apiGet(API.council+"/sessions/"+sid);}catch(e){toast(t("err"),1);return;}
  $("councilStream").innerHTML="";$("councilVerdict").classList.remove("show");$("councilVerdict").innerHTML="";
  const info={};const meta=(s.meta&&s.meta.members)||[];
  const m=$("councilMembers");m.innerHTML="";
  meta.forEach(mm=>{
    const id=(typeof mm==="object")?(mm.id||""):mm;
    const nm=(typeof mm==="object")?(mm.name||id):id;
    const em=(typeof mm==="object")?(mm.emoji||""):"";
    if(id)info[id]={name:nm,emoji:em};
    const c=document.createElement("span");c.className="council-chip";c.textContent=em+" "+nm;m.appendChild(c);
  });
  $("councilTopic").value=s.topic||"";
  const stream=$("councilStream");let curRound=0;
  (s.messages||[]).forEach(msg=>{
    if(msg.round!==curRound){curRound=msg.round;
      const d=document.createElement("div");d.className="council-round";
      d.textContent="— "+t("round")+" "+curRound+" —";stream.appendChild(d);}
    const inf=info[msg.agent]||{name:msg.agent,emoji:""};
    const el=document.createElement("div");el.className="council-msg";
    el.innerHTML='<div class="cm-head"><span class="cm-name"></span><span class="cm-meta"></span></div><div class="cm-body"></div>';
    el.querySelector(".cm-name").textContent=inf.emoji+" "+inf.name;
    el.querySelector(".cm-meta").textContent=(msg.meta&&msg.meta.provider)||"";
    el.querySelector(".cm-body").textContent=msg.content||"";
    stream.appendChild(el);
  });
  if(s.verdict){const v=$("councilVerdict");v.classList.add("show");
    v.innerHTML='<h4></h4><div class="v-body"></div>';
    v.querySelector("h4").textContent="⚖️ "+t("verdict")+" · "+t("consensus")+" "+Math.round((s.consensus||0)*100)+"%";
    v.querySelector(".v-body").textContent=s.verdict;}
  $("councilHistoryList").style.display="none";stream.scrollTop=0;
}
/* ============================ agent genome ============================ */
async function openGenome(){
  closeAll();
  $("genomeModal").classList.add("show");$("backdrop").classList.add("show");
  $("genomeDetail").classList.remove("show");$("genomeDetail").innerHTML="";
  await renderGenome();
}
function standClass(s){return s>=0.7?"promoted":(s<0.4?"probation":"active");}
function rankBadge(i){return i===0?"🥇":(i===1?"🥈":(i===2?"🥉":""));}
async function renderGenome(){
  const box=$("genomeList");box.innerHTML='<div style="color:var(--faint);padding:14px;text-align:center">…</div>';
  let list=[];try{list=(await apiGet(API.genome)).agents||[];}catch(e){list=[];}
  box.innerHTML="";
  if(!list.length){box.innerHTML='<div style="color:var(--faint);padding:14px;text-align:center">'+t("noAgents")+'</div>';return;}
  list.forEach((a,i)=>{
    const st=Math.round((a.standing||0)*100);
    const el=document.createElement("div");el.className="genome-row";el.dataset.id=a.agent_id;
    el.innerHTML='<span class="g-emoji"></span><div class="g-main"><div class="g-name"></div><div class="g-sub"></div></div>'+
      '<div class="g-stand"><span class="pct"></span><div class="bar"><i></i></div></div>';
    el.querySelector(".g-emoji").textContent=(a.meta&&a.meta.emoji)||"🤖";
    const nm=el.querySelector(".g-name");
    nm.textContent=(rankBadge(i)?rankBadge(i)+" ":"")+(a.name||a.agent_id);
    const pill=document.createElement("span");pill.className="pill stat "+standClass(a.standing);pill.textContent=a.status;nm.appendChild(pill);
    el.querySelector(".g-sub").textContent=t("runs")+" "+(a.runs||0)+" · "+t("generation")+" "+(a.generation||1);
    el.querySelector(".pct").textContent=st+"%";
    el.onclick=()=>openAgent(a.agent_id);
    box.appendChild(el);
    requestAnimationFrame(()=>{el.querySelector(".bar i").style.width=st+"%";});
  });
}
async function openAgent(id){
  let a;try{a=await apiGet(API.genome+"/"+id);}catch(e){toast(t("err"),1);return;}
  document.querySelectorAll(".genome-row").forEach(r=>r.classList.toggle("sel",r.dataset.id===id));
  const sr=a.runs?Math.round((a.successes/(a.runs||1))*100):0;
  const lat=a.runs?Math.round(a.latency_sum_ms/a.runs):0;
  const d=$("genomeDetail");d.classList.add("show");
  d.innerHTML='<h4></h4><div class="g-stats"></div><label id="gPersonaLabel" style="font-size:12px;color:var(--faint)"></label>'+
    '<textarea id="gPersona"></textarea><div class="g-actions"></div>'+
    '<div id="gTimelineLabel" style="font-size:12px;color:var(--faint);margin-top:14px"></div><div class="genome-timeline"></div>';
  d.querySelector("h4").textContent=(a.name||a.agent_id)+" · "+a.status;
  d.querySelector("#gPersonaLabel").textContent=t("persona");
  d.querySelector("#gPersona").value=a.persona||"";
  d.querySelector("#gTimelineLabel").textContent=t("timeline");
  const stats=d.querySelector(".g-stats");
  stats.innerHTML='<span>'+t("standings")+': <b>'+Math.round((a.standing||0)*100)+'%</b></span>'+
    '<span>'+t("runs")+': <b>'+(a.runs||0)+'</b></span>'+
    '<span>'+t("successRate")+': <b>'+sr+'%</b></span>'+
    '<span>'+t("avgLatency")+': <b>'+lat+'ms</b></span>'+
    '<span>'+t("generation")+': <b>'+(a.generation||1)+'</b></span>';
  const acts=d.querySelector(".g-actions");
  const bS=document.createElement("button");bS.className="pill";bS.textContent=t("save");
  const bR=document.createElement("button");bR.className="pill ghost";bR.textContent="♻ "+t("retrain");
  acts.append(bS,bR);
  bS.onclick=()=>saveAgent(id);
  bR.onclick=()=>resetAgent(id);
  const tl=d.querySelector(".genome-timeline");
  (a.timeline||[]).forEach(ev=>{
    const row=document.createElement("div");row.className="genome-ev "+(ev.kind||"");
    row.innerHTML='<div class="k"></div><div class="b"></div>';
    row.querySelector(".k").textContent=(ev.kind||"")+" · "+fmt(ev.ts);
    row.querySelector(".b").textContent=evSummary(ev);
    tl.appendChild(row);
  });
}
function evSummary(ev){
  const d=ev.detail||{};
  if(ev.kind==="outcome"||ev.kind==="council"){
    return (d.success?"✅":"❌")+(d.latency_ms?(" · "+d.latency_ms+"ms"):"")+
      (d.consensus!=null?(" · "+t("consensus")+" "+Math.round((d.consensus||0)*100)+"%"):"")+
      (d.standing!=null?(" · "+Math.round(d.standing*100)+"%"):"");
  }
  if(ev.kind==="reset")return "→ "+t("generation")+" "+(d.generation||"");
  if(ev.kind==="born")return d.name||"";
  return "";
}
async function saveAgent(id){
  const persona=$("gPersona").value;
  const r=await apiSend("PATCH",API.genome+"/"+id,{persona});
  if(!r){toast(t("err"),1);return;}
  toast(t("agentSaved"));renderGenome();
}
async function resetAgent(id){
  if(!confirm(t("retrainQ")))return;
  const r=await apiSend("POST",API.genome+"/"+id+"/reset",{});
  if(!r){toast(t("err"),1);return;}
  toast("♻ "+t("retrain"));await renderGenome();openAgent(id);
}
function exportGenome(){window.open(API.genome+"/export","_blank");}
async function importGenomeFile(file){
  try{
    const j=JSON.parse(await file.text());
    const r=await apiSend("POST",API.genome+"/import",j);
    toast(t("genomeImported")+(r&&r.imported!=null?(": "+r.imported):""));
    renderGenome();
  }catch(e){toast(t("err"),1);}
}
/* ============================ agent academy (🎓 training) ============================ */
/* Backend: GET  /api/training/{status,agents,plan/<id>,lessons,fitness}
             POST /api/training/evolve  (one evolution pass) */
let acaTab="stages",acaAgent="";
function acaPanel(){return $("aca"+acaTab.charAt(0).toUpperCase()+acaTab.slice(1));}
function acaSelectTab(tab){
  acaTab=tab;["Stages","Lessons","Fitness"].forEach(n=>{
    const on=n.toLowerCase()===tab;$("acaTab"+n).classList.toggle("on",on);
    $("aca"+n).classList.toggle("on",on);});
  acaRender();
}
function acaRow(){const el=document.createElement("div");el.className="aca-row";return el;}
function acaSet(el,title,sub,pills){
  el.innerHTML='<div class="t"></div><div class="s"></div>';
  el.querySelector(".t").textContent=title;
  el.querySelector(".s").innerHTML=sub||"";
  (pills||[]).forEach(p=>{
    const s=document.createElement("span");s.className="aca-pill "+(p.k||"");
    s.textContent=p.v;el.querySelector(".t").appendChild(s);});
  return el;
}
function acaBar(el,value,cls){
  const b=document.createElement("div");b.className="aca-bar "+(cls||"");
  b.innerHTML="<i></i>";el.appendChild(b);
  requestAnimationFrame(()=>{b.querySelector("i").style.width=Math.round(Math.max(0,Math.min(1,value))*100)+"%";});
  return b;
}
function acaEmpty(box,key){box.innerHTML='<div class="aca-empty">'+t(key)+'</div>';}
function acaFitnessPill(f){
  const s=(f.status||"").toLowerCase();
  const k=s==="elite"?"ok":(s==="probationary"?"bad":(s? "warn":""));
  return {v:t("fitnessStatus_"+s)||s,k:k};
}
function acaActionWord(a){return t("apexAction_"+(a||"unknown"))||a||"";}
async function openAcademy(){
  closeAll();
  $("academyModal").classList.add("show");$("backdrop").classList.add("show");
  await acaLoadAgents();
  acaRender();
}
async function acaLoadAgents(){
  const sel=$("acaAgent");
  let list=[];try{list=(await apiGet(API.training+"/agents?roster=1")).agents||[];}catch(e){list=[];}
  if(!list.length){try{list=(await apiGet(API.agents)).tools||[];}catch(e){list=[];}}
  const ids=list.map(a=>a.agent_id||a.name).filter(Boolean);
  const prev=sel.value||acaAgent;
  sel.innerHTML="";
  if(!ids.length){const o=document.createElement("option");o.value="";o.textContent=t("noAgents");sel.appendChild(o);}
  ids.forEach(id=>{const o=document.createElement("option");o.value=id;o.textContent=id;sel.appendChild(o);});
  acaAgent=ids.includes(prev)?prev:(ids[0]||"");
  sel.value=acaAgent;
  sel.onchange=()=>{acaAgent=sel.value;acaRender();};
  return ids;
}
async function acaRender(){
  const box=acaPanel();
  box.innerHTML='<div class="aca-empty">…</div>';
  if(acaTab==="stages")await acaRenderStages(box);
  else if(acaTab==="lessons")await acaRenderLessons(box);
  else await acaRenderFitness(box);
  acaRenderSummary();
}
async function acaRenderSummary(){
  const el=$("acaSummary");
  try{
    const s=await apiGet(API.training+"/status");
    const f=s.field||{};
    el.textContent=(s.agents!=null?s.agents+" "+(state.lang==="ar"?"وكيل":"agents")+" · ":"")+
      (f.ticks||0)+" "+t("acaTicks")+" · "+(f.absorbed||0)+" "+t("acaAbsorbed")+
      " · "+(f.mutations||0)+" "+t("acaMutations");
  }catch(e){el.textContent=t("academyHint");}
}
async function acaRenderStages(box){
  if(!acaAgent){acaEmpty(box,"acaNoStages");return;}
  let p;try{p=await apiGet(API.training+"/plan/"+encodeURIComponent(acaAgent));}catch(e){acaEmpty(box,"acaNoStages");return;}
  const mods=p.modules||p.phases||[];
  if(!mods.length){acaEmpty(box,"acaNoStages");return;}
  box.innerHTML="";
  const run=(p.last_run||p.run||null);
  const done={};(run&&run.phases?run.phases:[]).forEach(x=>{done[x.skill]=x;});
  mods.forEach((m,i)=>{
    const name=m.name||m.module||m.skill||("module "+i);
    const seen=done[name]||done[m.skill]||null;
    const ok=seen?(seen.score>=0.5):null;
    const el=acaRow();
    const pills=[{v:(m.weight!=null?t("weight")+": "+m.weight:t("hours")+": "+(m.hours!=null?m.hours:"?")),k:"info"}];
    if(seen)pills.push({v:String(Math.round((seen.score||0)*100))+"%",k:ok?"ok":"bad"});
    acaSet(el,(i+1)+". "+name,
      (m.min_score!=null?"<b>"+t("score")+"</b> ≥ "+m.min_score+" · ":"")+
      "<b>"+t("source")+"</b> "+(m.source||m.kind||"-")+
      (seen?(" · "+(seen.passed?t("pass"):t("fail"))):" · "+t("acaNoStages")),
      pills);
    const val=seen?Math.max(0,Math.min(1,seen.score||0)):(m.min_score||0.7);
    acaBar(el,val,seen?(ok?"":"low"):"mid");
    box.appendChild(el);
  });
}
async function acaRenderLessons(box){
  let list=[];
  try{list=(await apiGet(API.training+"/lessons"+(acaAgent?("?agent_id="+encodeURIComponent(acaAgent)):""))).lessons||[];}catch(e){list=[];}
  if(!list.length){acaEmpty(box,"acaNoLessons");return;}
  box.innerHTML="";
  list.forEach(l=>{
    const el=acaRow();
    acaSet(el,l.principle||"",(l.context||"")+
      '<br><b>'+t("confidence")+'</b> '+Math.round((l.confidence||0)*100)+'%'+
      ' · <b>'+t("source")+'</b> '+(l.source_outcome||"-")+
      ' · <b>'+(l.agent_role||"-")+'</b>'+(l.created_at?(" · "+fmt(l.created_at)):""),
      [{v:(l.source_outcome||""),k:(l.source_outcome==="success"?"ok":(l.source_outcome==="failure"?"bad":"warn"))}]);
    acaBar(el,l.confidence||0,(l.confidence>=0.75?"":(l.confidence<0.55?"low":"mid")));
    box.appendChild(el);
  });
}
function acaScore(v){return (v==null||isNaN(v))?0:Number(v);}
/* line 1 = the judgement channel (council verdicts) + total evidence */
function acaJudgeLine(f){
  return '<b>'+t("judgements")+'</b> '+acaScore(f.observations)+
    ' · <b>'+t("agreements")+'</b> '+acaScore(f.agreements)+
    ' · <b>'+t("dissent")+'</b> '+acaScore(f.dissent)+
    ' · <b>'+t("acaEvidence")+'</b> '+acaScore(f.evidence);
}
/* line 2 = the task channel (real /api/chat runs), honestly "no tasks" */
function acaTaskLine(f){
  const n=acaScore(f.task_observations);
  if(!n)return '<b>'+t("tasks")+'</b> <span class="aca-pill">'+t("acaNoTasks")+'</span>';
  const rate=Math.round(acaScore(f.task_rate)*100);
  const bits=[n+' · '+acaScore(f.task_successes)+' ✓ · '+rate+'%'];
  if(typeof f.task_duration_avg==="number"&&isFinite(f.task_duration_avg))
    bits.push(t("acaAvgTime")+' '+f.task_duration_avg.toFixed(2)+'s');
  if(f.task_last_ok!=null)
    bits.push(t("acaLastTask")+' '+(f.task_last_ok?'<span class="aca-pill ok">✓</span>':'<span class="aca-pill bad">✗</span>'));
  return '<b>'+t("tasks")+'</b> '+bits.join(' · ');
}
async function acaRenderFitness(box){
  let list=[];
  try{list=(await apiGet(API.training+"/fitness")).agents||[];}catch(e){list=[];}
  if(!list.length){acaEmpty(box,"acaNoFitness");return;}
  box.innerHTML="";
  list.forEach((f,i)=>{
    const el=acaRow();
    const pills=[acaFitnessPill(f),{v:"↳ "+acaActionWord(f.action),k:(f.action==="retrain"?"bad":"info")}];
    if(i<3)pills.unshift({v:rankBadge(i),k:"ok"});
    if(f.retired)pills.push({v:"retired",k:"warn"});
    acaSet(el,(f.agent_id||"")+" · "+Math.round((f.fitness||0)*100)+"%",
      acaJudgeLine(f)+'<br>'+acaTaskLine(f)+
      ' · <b>'+t("action")+'</b> '+acaActionWord(f.action)+
      (f.reason?(" — "+f.reason):""),
      pills);
    acaBar(el,f.fitness||0,(f.fitness>=0.75?"":(f.fitness<0.55?"low":"mid")));
    box.appendChild(el);
  });
}
async function acaEvolve(){
  const btn=$("acaEvolve");const label=btn.textContent;btn.disabled=true;
  try{
    const r=await apiSend("POST",API.training+"/evolve",{});
    if(!r){toast(t("err"),1);}
    else{
      const mutated=(r.mutated||[]).length;
      const evolved=(r.evolved||[]).filter(a=>a.action!=="keep").length;
      toast("♻ "+(mutated?t("acaEvolved")+": "+mutated:(evolved?t("evolveDone"):t("evolveNone"))));
    }
    await acaRender();
  }finally{btn.disabled=false;btn.textContent=label;}
}
function toast(msg,isErr){
  const el=document.createElement("div");el.className="toast"+(isErr?" err":"");el.textContent=msg;
  $("toasts").appendChild(el);setTimeout(()=>{el.style.opacity="0";el.style.transition="opacity .3s";setTimeout(()=>el.remove(),300)},2200);
}

/* ============================ offline queue ============================ */
let qdb=null,deferredInstall=null;
function qOpen(){return new Promise(res=>{
  if(typeof indexedDB==="undefined")return res(null);
  if(qdb)return res(qdb);
  const r=indexedDB.open("nexus_queue",1);
  r.onupgradeneeded=()=>{r.result.createObjectStore("q",{keyPath:"id",autoIncrement:true});};
  r.onsuccess=()=>{qdb=r.result;res(qdb);};
  r.onerror=()=>res(null);
});}
async function qAdd(item){const db=await qOpen();if(!db)return;
  await new Promise(res=>{const t=db.transaction("q","readwrite");t.objectStore("q").add(item);
    t.oncomplete=res;t.onerror=res;});await qRefresh();}
async function qAll(){const db=await qOpen();if(!db)return[];
  return await new Promise(res=>{const t=db.transaction("q","readonly");
    const rq=t.objectStore("q").getAll();rq.onsuccess=()=>res(rq.result||[]);rq.onerror=()=>res([]);});}
async function qClear(){const db=await qOpen();if(!db)return;
  await new Promise(res=>{const t=db.transaction("q","readwrite");t.objectStore("q").clear();
    t.oncomplete=res;t.onerror=res;});}
async function qRefresh(){const n=(await qAll()).length;
  const el=$("qBadge");if(el){el.textContent=n?("⏳ "+n):"";el.style.display=n?"inline":"none";}}
async function flushQueue(){
  if(!navigator.onLine)return;
  const items=await qAll();if(!items.length)return;
  await qClear();await qRefresh();
  for(const it of items){
    let c=state.convs.find(x=>x.id===it.conv);
    if(!c){c={id:it.conv,title:(it.text||"").slice(0,40),messages:[],date:Date.now()};
      state.convs.unshift(c);pushUser(c,it.text);}
    state.cur=c.id;renderSidebar();
    await streamReply(c,it.text);
  }
  toast(t("synced"));
}
function registerSW(){
  if("serviceWorker" in navigator){
    navigator.serviceWorker.register("/sw.js").catch(()=>{});
    window.addEventListener("beforeinstallprompt",e=>{
      e.preventDefault();deferredInstall=e;
      const row=$("installRow");if(row)row.style.display="flex";
    });
    window.addEventListener("appinstalled",()=>{
      const row=$("installRow");if(row)row.style.display="none";toast("✅");
    });
  }
}

/* ============================ input ============================ */
function autoGrow(){const el=$("input");el.style.height="auto";el.style.height=Math.min(el.scrollHeight,200)+"px";}

/* ============================ language ============================ */
function applyLang(){
  document.documentElement.lang=state.lang;
  document.documentElement.dir=state.lang==="ar"?"rtl":"ltr";
  document.querySelectorAll("[data-i18n]").forEach(el=>el.textContent=t(el.dataset.i18n));
  document.querySelectorAll("[data-i18n-ph]").forEach(el=>el.placeholder=t(el.dataset.i18nPh));
  $("langTag").textContent=state.lang.toUpperCase();
  renderSidebar();renderMessages();renderInfo();
}

/* ============================ init ============================ */
function bind(){
  $("btnNew").onclick=()=>newChat();
  $("btnTopNew").onclick=()=>newChat();
  $("btnMenu").onclick=()=>{$("sidebar").classList.add("open");$("backdrop").classList.add("show");};
  $("btnInfo").onclick=()=>{$("info").classList.toggle("open");
    if(window.innerWidth>900){$("app").classList.toggle("no-info");state.stream=state.stream;}
    $("backdrop").classList.toggle("show",$("info").classList.contains("open")&&window.innerWidth<=900);};
  $("btnSearch").onclick=openSearch;
  $("btnTraces").onclick=openTraces;
  $("btnCouncil").onclick=openCouncil;
  $("councilStart").onclick=startCouncil;
  $("councilHistory").onclick=toggleCouncilHistory;
  $("btnGenome").onclick=openGenome;
  $("btnAcademy").onclick=openAcademy;
  $("acaRefresh").onclick=()=>acaRender();
  $("acaEvolve").onclick=acaEvolve;
  $("acaTabStages").onclick=()=>acaSelectTab("stages");
  $("acaTabLessons").onclick=()=>acaSelectTab("lessons");
  $("acaTabFitness").onclick=()=>acaSelectTab("fitness");
  $("genomeExport").onclick=exportGenome;
  $("genomeImportBtn").onclick=()=>$("genomeFile").click();
  $("genomeFile").onchange=e=>{const f=e.target.files&&e.target.files[0];if(f)importGenomeFile(f);e.target.value="";};
  $("councilTopic").addEventListener("keydown",e=>{if(e.key==="Enter"){e.preventDefault();startCouncil();}});
  $("traceClear").onclick=()=>{if(confirm(t("clearTracesQ"))){apiSend("DELETE",API.traces);
    state.curTrace=null;const det=$("traceDetail");det.classList.remove("show");det.innerHTML="";
    renderTraces("");toast(t("del"));}};
  $("backdrop").onclick=closeAll;
  $("btnSettings").onclick=()=>{closeAll();$("settingsModal").classList.add("show");$("backdrop").classList.add("show");
    $("setInfo").classList.toggle("on",!$("app").classList.contains("no-info"));};
  $("setClose").onclick=closeAll;
  $("setLang").onclick=()=>{state.lang=state.lang==="ar"?"en":"ar";save();applyLang();toast("🌐 "+state.lang.toUpperCase());};
  $("btnLang").onclick=$("setLang").onclick;
  $("setExport").onclick=()=>{const a=document.createElement("a");
    a.href="/api/export/conversations?format=json";a.download="nexus-conversations.json";
    document.body.appendChild(a);a.click();a.remove();};
  $("setImport").onclick=()=>$("importFile").click();
  $("importFile").onchange=async e=>{
    const f=e.target.files&&e.target.files[0];if(!f)return;
    try{
      const j=JSON.parse(await f.text());
      const convs=j.conversations||(Array.isArray(j)?j:[]);
      const r=await apiSend("POST",API.convs+"/migrate",{conversations:convs});
      localStorage.setItem(LS.migrated,"1");
      await load();renderSidebar();await renderMessages();renderInfo();
      toast(t("imported")+": "+(r&&r.imported!=null?r.imported:convs.length));
    }catch(err){toast(t("err"),1);}
    e.target.value="";
  };
  $("setClear").onclick=()=>{if(confirm(t("confirmClearQ"))){if(useDB)apiSend("DELETE",API.convs);
    state.convs=[];state.cur=null;saveCache();
    renderSidebar();renderMessages();renderInfo();closeAll();toast(t("del"));}};
  $("setInstall").onclick=async()=>{if(deferredInstall){deferredInstall.prompt();await deferredInstall.userChoice;
      deferredInstall=null;const row=$("installRow");if(row)row.style.display="none";}};
  $("setInfo").onclick=()=>{$("app").classList.toggle("no-info");renderInfo();};
  $("tglInfo").onclick=()=>{$("app").classList.toggle("no-info");};
  $("tglStream").onclick=()=>{state.stream=!state.stream;$("tglStream").classList.toggle("on",state.stream);};
  $("searchInput").oninput=e=>searchRender(e.target.value);
  $("btnSend").onclick=()=>{if(state.streaming){state.ctrl&&state.ctrl.abort();}else send();};
  const inp=$("input");
  inp.addEventListener("input",()=>{autoGrow();$("charCount").textContent=inp.value.length;
    $("btnSend").disabled=!state.streaming&&!inp.value.trim();});
  inp.addEventListener("keydown",e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();send();}});
  document.addEventListener("keydown",e=>{
    if(e.ctrlKey&&e.key.toLowerCase()==="k"){e.preventDefault();openSearch();}
    else if(e.ctrlKey&&e.shiftKey&&e.key.toLowerCase()==="o"){e.preventDefault();newChat();}
    else if(e.ctrlKey&&e.shiftKey&&e.key.toLowerCase()==="t"){e.preventDefault();openTraces();}
    else if(e.key==="Escape")closeAll();
  });
  document.addEventListener("click",e=>{const cp=e.target.closest(".code-copy");
    if(cp){const c=codes[+cp.dataset.idx];if(c){navigator.clipboard.writeText(c.raw).then(()=>toast(t("copied"))).catch(()=>toast(t("err"),1));}}});
  window.addEventListener("online",()=>{renderInfo();toast("🟢 "+t("online"));flushQueue();});
  window.addEventListener("offline",()=>{renderInfo();toast("🔴 "+t("offline"),1);});
  const dot=$("statusDot");
  const sync=()=>{const on=navigator.onLine;dot.classList.toggle("off",!on);$("statusText").textContent=on?t("online"):t("offline");};
  window.addEventListener("online",sync);window.addEventListener("offline",sync);
}
async function boot(){
  bind();registerSW();qRefresh();await load();applyLang();sync();
  if(!state.convs.length)await newChat();
  else{state.cur=state.cur||state.convs[0].id;renderSidebar();await renderMessages();renderInfo();}
  try{
    const r=await fetch(API.agents);const j=await r.json();
    state.agents=(j.tools||[]).map(x=>({name:x.name,description:x.description}));
    renderAgents();renderInfo();
  }catch(e){toast(t("err"),1);}
}
function sync(){const on=navigator.onLine;$("statusDot").classList.toggle("off",!on);
  $("statusText").textContent=on?t("online"):t("offline");}
boot();
