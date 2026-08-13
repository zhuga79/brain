"""Скрипты страницы дашборда.

Девять независимых блоков: фильтры, живое обновление (SSE), операции над
задачами, запуск агента, импорт workspace, поиск, переключение вида, опрос
статуса и вкладки. Каждый самодостаточен и вставляется в страницу как есть.
"""

FILTER_SCRIPT = (
    '<script>\n'
    'window.addEventListener("DOMContentLoaded",function(){'
    'document.querySelectorAll(".task-filters").forEach(function(box){'
    'var scope=box.closest("section")||document;'
    'function apply(){'
    'var q=(box.querySelector(".task-filter-text")||{}).value||"";q=q.toLowerCase();'
    'var fields=["priority","role","mode","client"];'
    'var shown=0;'
    'scope.querySelectorAll("[data-filter-row=task]").forEach(function(row){'
    'var ok=true;'
    'fields.forEach(function(f){var el=box.querySelector(".task-filter-"+f);'
    'var v=el?el.value:"";if(v&&row.getAttribute("data-"+f)!==v){ok=false;}});'
    'if(q&&String(row.getAttribute("data-text")||"").indexOf(q)===-1){ok=false;}'
    'row.style.display=ok?"":"none";if(ok){shown++;}'
    '});'
    'var count=box.querySelector(".task-filter-count");if(count){count.textContent=shown;}'
    '}'
    'box.querySelectorAll("input,select").forEach(function(el){el.addEventListener("input",apply);el.addEventListener("change",apply);});'
    'var reset=box.querySelector(".task-filter-reset");if(reset){reset.addEventListener("click",function(){'
    'box.querySelectorAll("input").forEach(function(el){el.value="";});'
    'box.querySelectorAll("select").forEach(function(el){el.value="";});'
    'apply();});}'
    'apply();'
    '});'
    '});\n'
    '</script>\n'
)


SSE_SCRIPT = (
    '<script>\n'
    'if(window.EventSource){'
    'var _params=new URLSearchParams(window.location.search);'
    'var _tok=_params.get("token")||localStorage.getItem("brainDashboardToken")||"";'
    'if(_params.get("token")){'
    'localStorage.setItem("brainDashboardToken",_params.get("token"));'
    '_params.delete("token");'
    'var _clean=window.location.pathname+(_params.toString()?"?"+_params.toString():"")+window.location.hash;'
    'history.replaceState(null,"",_clean);'
    '}else if(_tok){localStorage.setItem("brainDashboardToken",_tok);}'
    'var _events="/events";'
    'if(_tok){_events+="?token="+encodeURIComponent(_tok);}'
    'var _src=new EventSource(_events);'
    '_src.onmessage=function(e){'
    'try{'
    'window.__brainDashLastEventTs=Date.now();'
    'var d=JSON.parse(e.data);'
    'var set=function(id,v){var el=document.getElementById(id);if(el)el.textContent=v;};'
    'var t=d.tasks||{};var l=d.locks||{};var c=d.council||{};'
    'var tok=d.tokens||{};var ta=tok.aggregate||{};'
    'var idx=d.index||{};'
    'set("sse-tasks-active",t.active_count!=null?t.active_count:"");'
    'set("sse-tasks-done",t.done_count!=null?t.done_count:"");'
    'set("sse-locks-count",l.count!=null?l.count:"");'
    'set("sse-council-count",c.count!=null?c.count:"");'
    'set("token-commands",ta.commands!=null?ta.commands:"0");'
    'set("token-raw-tokens",ta.raw_tokens_est!=null?ta.raw_tokens_est:"0");'
    'set("token-compact-tokens",ta.compact_tokens_est!=null?ta.compact_tokens_est:"0");'
    'set("token-savings",(ta.savings_percent!=null?ta.savings_percent:"0")+"%");'
    'set("token-status",tok.available?"live":"waiting for first compacted command");'
    'if(tok.path){set("token-source",tok.path);}'
    'set("release-active-count",t.active_count!=null?t.active_count:"0");'
    'set("release-stale-locks",l.stale_count!=null?l.stale_count:"0");'
    'set("release-index-health",idx.health||"unknown");'
    'if(d.ts){var m=document.getElementById("sse-meta");if(m)m.textContent=d.ts;}'
    'var rg=document.getElementById("release-gates-status");'
    'if(rg){var ok=(t.active_count===0 && l.stale_count===0 && idx.health==="ok");'
    'rg.textContent=ok?"ready":"blocked";'
    'rg.className="badge "+(ok?"state-done":"state-blocked");}'
    '}catch(_){}'
    '};'
    '}\n'
    'window.addEventListener("DOMContentLoaded",function(){'
    'var agent=localStorage.getItem("brainAgentId")||"dashboard-user";'
    'var token=localStorage.getItem("brainDashboardToken")||"";'
    'var activeOut=null;'
    'function outFor(btn){var panel=btn&&btn.closest?btn.closest(".tab-panel"):null;return (panel&&panel.querySelector(".task-action-output"))||document.getElementById("task-action-output");}'
    'function showActionResult(text){var out=activeOut||document.getElementById("task-action-output");if(out){out.textContent=text;out.scrollIntoView({behavior:"smooth",block:"center"});}}'
    'function reloadAfterFeedback(){setTimeout(function(){window.location.reload();},700);}'
    'function actionSuccessMessage(action,task){var labels={take:"Задача взята",release:"Задача возвращена",complete:"Задача завершена",block:"Задача заблокирована"};return (labels[action]||"Действие выполнено")+" · "+task;}'
    'document.querySelectorAll("button[data-action]").forEach(function(btn){'
    'btn.addEventListener("click",function(){'
    'activeOut=outFor(btn);'
    'var action=btn.getAttribute("data-action");'
    'var task=btn.getAttribute("data-task")||"";'
    'btn.disabled=true;'
    'var headers={"X-Brain-Confirm":"1"};'
    'if(token){headers["X-Brain-Token"]=token;}'
    'if(action==="probe"){'
    'showActionResult("provider probe...");'
    'fetch("/api/providers/probe",{method:"POST",headers:headers}).then(function(r){return r.json();}).then(function(d){'
    'if(!d.ok){showActionResult(d.error||"Probe failed");alert(d.error||"Probe failed");btn.disabled=false;return;}'
    'showActionResult(d.output||"Provider probe completed");'
    'reloadAfterFeedback();'
    '}).catch(function(e){showActionResult(String(e));alert(String(e));btn.disabled=false;});'
    'return;'
    '}'
    'if(!task){showActionResult("task id is required");alert("task id is required");btn.disabled=false;return;}'
    'var url="/api/tasks/"+encodeURIComponent(task)+"?as="+encodeURIComponent(agent)+"&action="+encodeURIComponent(action);'
    'if(action==="block"){var reason=prompt("Block reason","blocked via dashboard");if(reason===null){btn.disabled=false;return;}url+="&reason="+encodeURIComponent(reason);}'
    'showActionResult(action+" "+task+"...");'
    'fetch(url,{method:"POST",headers:headers}).then(function(r){return r.json();}).then(function(d){'
    'if(!d.ok){showActionResult(d.error||"Action failed");alert(d.error||"Action failed");btn.disabled=false;return;}'
    'showActionResult(d.output||d.error||actionSuccessMessage(action,task));'
    'reloadAfterFeedback();'
    '}).catch(function(e){showActionResult(String(e));alert(String(e));btn.disabled=false;});'
    '});'
    '  });'
    '});\n'
    '</script>\n'
)


TASK_OPS_SCRIPT = (
"""<script>
window.addEventListener("DOMContentLoaded", function(){
  var active = null;
  function outFor(btn){
    var panel = btn && btn.closest ? btn.closest(".tab-panel") : null;
    return (panel && panel.querySelector(".task-action-output")) || document.getElementById("task-action-output");
  }
  function show(t){ var out = active || document.getElementById("task-action-output"); if(out){ out.textContent = t; out.scrollIntoView({behavior:"smooth", block:"center"}); } }
  function authHeaders(){
    var token = localStorage.getItem("brainDashboardToken") || "";
    var hd = {"X-Brain-Confirm":"1"};
    if(token){ hd["X-Brain-Token"] = token; }
    return hd;
  }
  function post(url){ return fetch(url, {method:"POST", headers: authHeaders()}).then(function(r){ return r.json(); }); }
  document.querySelectorAll("select.task-client").forEach(function(sel){
    var key = "taskClient:" + (sel.getAttribute("data-client-key") || "");
    var stored = localStorage.getItem(key);
    if(stored){ sel.value = stored; }
    sel.addEventListener("change", function(){ localStorage.setItem(key, sel.value); });
  });
  document.querySelectorAll("select.task-mode").forEach(function(sel){
    var key = "taskMode:" + (sel.getAttribute("data-mode-key") || "");
    var stored = localStorage.getItem(key);
    if(stored){ sel.value = stored; }
    sel.addEventListener("change", function(){ localStorage.setItem(key, sel.value); });
  });
  function clientFor(btn){
    var card = btn.closest ? btn.closest(".task-card") : null;
    var sel = card ? card.querySelector("select.task-client") : null;
    return (sel && sel.value) || btn.getAttribute("data-kb-client") || "";
  }
  function modeFor(btn){
    var card = btn.closest ? btn.closest(".task-card") : null;
    var sel = card ? card.querySelector("select.task-mode") : null;
    return (sel && sel.value) || "";
  }
  function handle(btn){
    var action = btn.getAttribute("data-kb-action") || "";
    var task = btn.getAttribute("data-kb-task") || "";
    var role = btn.getAttribute("data-kb-role") || "";
    var ws = btn.getAttribute("data-kb-workspace") || "";
    var proposal = btn.getAttribute("data-kb-proposal") || "";
    if(action === "cycle-status"){
      show(btn.getAttribute("data-kb-unit") + " — следующий запуск: " + (btn.getAttribute("data-kb-next") || "?"));
      return;
    }
    if(action === "cycle-run"){
      var unit = btn.getAttribute("data-kb-unit") || "";
      if(!confirm("Запустить цикл " + unit + " прямо сейчас?")){ return; }
      btn.disabled = true; show("запуск цикла " + unit + "...");
      post("/api/cycle/" + encodeURIComponent(unit) + "?action=run")
        .then(function(d){ show(d.ok ? ("Цикл запущен: " + unit) : (d.error || "Не удалось")); if(!d.ok){ alert(d.error || "Не удалось"); } btn.disabled = false; })
        .catch(function(e){ show(String(e)); btn.disabled = false; });
      return;
    }
    if(action === "status"){
      show("статус " + task + "...");
      fetch("/api/audit?task=" + encodeURIComponent(task)).then(function(r){ return r.json(); }).then(function(d){
        var items = (d && (d.entries || d.items || d.audit)) || [];
        if(!items.length){ show("по задаче " + task + " событий пока нет"); return; }
        show(items.slice(-8).map(function(e){ return (e.ts||e.timestamp||"") + "  " + (e.op||e.action||e.kind||"") + "  " + (e.agent||""); }).join("  |  "));
      }).catch(function(e){ show(String(e)); });
      return;
    }
    if(action === "launch" || action === "dry-run"){
      var dry = action === "dry-run";
      var client = clientFor(btn);
      var mode = modeFor(btn);
      if(!dry && !confirm("Запустить задачу " + task + (mode === "background" ? " в фоне?" : " в интерактивном режиме?"))){ return; }
      btn.disabled = true; show((dry ? "проверка " : "запуск ") + task + "...");
      var url;
      if(proposal){
        url = "/api/queue-proposals/" + encodeURIComponent(proposal) + "/launch?dry_run=" + (dry ? "1" : "0");
        if(client){ url += "&client=" + encodeURIComponent(client); }
      } else {
        url = "/api/launch?workspace=" + encodeURIComponent(ws) + "&task=" + encodeURIComponent(task) + "&role=" + encodeURIComponent(role) + "&client=" + encodeURIComponent(client) + "&dry_run=" + (dry ? "1" : "0");
      }
      if(mode){ url += "&mode=" + encodeURIComponent(mode); }
      post(url)
        .then(function(d){ show(d.output || d.error || JSON.stringify(d)); if(!d.ok){ alert(d.error || "Запуск не удался"); } btn.disabled = false; })
        .catch(function(e){ show(String(e)); btn.disabled = false; });
      return;
    }
  }
  document.querySelectorAll("[data-kb-action]").forEach(function(btn){
    btn.addEventListener("click", function(){ active = outFor(btn); handle(btn); });
  });
});
</script>
"""
)


LAUNCH_SCRIPT = (
    '<script>\n'
    'window.addEventListener("DOMContentLoaded",function(){'
    'function loadModels(form){'
    'var clientEl=form.querySelector(".launch-client");'
    'var sel=form.querySelector("select.launch-model");'
    'if(!clientEl||!sel){return;}'
    'var client=clientEl.value||"";'
    'if(!client){return;}'
    'var out=form.querySelector(".launch-output");'
    'if(out){out.textContent="проверяю "+client+"...";}'
    'fetch("/api/models?client="+encodeURIComponent(client)).then(function(r){return r.json();}).then(function(d){'
    'if(!d.ok){if(out){out.textContent=d.error||"не удалось проверить "+client;}return;}'
    'var current=sel.value;'
    'while(sel.firstChild){sel.removeChild(sel.firstChild);}'
    'var auto=document.createElement("option");auto.value="";auto.textContent="авто (по роли)";sel.appendChild(auto);'
    'var models=d.models||[];'
    'models.forEach(function(m){var o=document.createElement("option");o.value=m;o.textContent=m;sel.appendChild(o);});'
    'if(current&&models.indexOf(current)>=0){sel.value=current;}'
    'if(out){'
    'var status=d.available?("✓ доступен"+(d.version?(" · "+d.version):" · не ответил на --version — возможно, требуется логин; запускайте в интерактивном режиме")):"✗ CLI не найден";'
    'out.textContent=client+": "+status+"\\nмодели ("+(d.source||"")+"): "+(models.join(", ")||"нет данных");'
    '}'
    '}).catch(function(e){if(out){out.textContent=String(e);}});'
    '}'
    'function bindForm(form){'
    'function q(cls){return form.querySelector(cls);}'
    'function launchRequest(forceDry){'
    'var workspace=((q(".launch-workspace")||{}).value||"").trim();'
    'var task=((q(".launch-task")||{}).value||"").trim();'
    'var role=((q(".launch-role")||{}).value||"").trim();'
    'var client=(q(".launch-client")||{}).value||"";'
    'var model=((q(".launch-model")||{}).value||"").trim();'
    'var effort=((q(".launch-effort")||{}).value||"").trim();'
    'var mode=(q(".launch-mode")||{}).value||"";'
    'var dryEl=q(".launch-dry-run");'
    'var dry=(forceDry||!!(dryEl&&dryEl.checked))?"1":"0";'
    'var out=q(".launch-output");'
    'if(!workspace||!task||!role){alert("workspace, task and role are required");return Promise.resolve({ok:false});}'
    'var url="/api/launch?workspace="+encodeURIComponent(workspace)+"&task="+encodeURIComponent(task)+"&role="+encodeURIComponent(role)+"&client="+encodeURIComponent(client)+"&model="+encodeURIComponent(model)+"&effort="+encodeURIComponent(effort)+"&dry_run="+dry;'
    'if(mode){url+="&mode="+encodeURIComponent(mode);}'
    'var token=localStorage.getItem("brainDashboardToken")||"";'
    'var headers={"X-Brain-Confirm":"1"};'
    'if(token){headers["X-Brain-Token"]=token;}'
    'if(out)out.textContent=(dry==="1")?"launching (dry-run)...":"launching...";'
    'return fetch(url,{method:"POST",headers:headers}).then(function(r){return r.json();}).then(function(d){'
    'if(out)out.textContent=(d.output||d.error||JSON.stringify(d));'
    'return d;'
    '});'
    '}'
    'var btn=q(".launch-btn");'
    'if(!btn)return;'
    'btn.addEventListener("click",function(){'
    'var out=q(".launch-output");'
    'var dryEl=q(".launch-dry-run");'
    'btn.disabled=true;'
    'launchRequest(false).then(function(d){'
    'if(d&&d.ok){btn.disabled=false;return;}'
    'if(d&&d.sandbox_blocked&&!((dryEl&&dryEl.checked))){'
    'if(dryEl){dryEl.checked=true;}'
    'if(out){out.textContent=(out.textContent||"")+"\\nSandbox blocked live launch. Retrying in dry-run...";}'
    'return launchRequest(true).then(function(d2){if(!d2.ok){alert(d2.error||"Launch failed");}btn.disabled=false;});'
    '}'
    'alert((d&&d.error)||"Launch failed");'
    'btn.disabled=false;'
    '}).catch(function(e){if(out)out.textContent=String(e);alert(String(e));btn.disabled=false;});'
    '});'
    'var clientSel=q(".launch-client");'
    'if(clientSel){clientSel.addEventListener("change",function(){loadModels(form);});}'
    '}'
    'document.querySelectorAll("details.manual-launch").forEach(bindForm);'
    'document.querySelectorAll("[data-launch-fill-task]").forEach(function(fill){'
    'fill.addEventListener("click",function(){'
    'var task=fill.getAttribute("data-launch-fill-task")||"";'
    'var role=fill.getAttribute("data-launch-fill-role")||"";'
    'var client=fill.getAttribute("data-launch-fill-client")||"";'
    'var workspace=fill.getAttribute("data-launch-fill-workspace")||"";'
    'var panel=fill.closest?fill.closest(".tab-panel"):null;'
    'var manual=(panel&&panel.querySelector("details.manual-launch"))||document.querySelector("details.manual-launch");'
    'if(!manual){return;}'
    'function set(cls,v){var el=manual.querySelector(cls);if(el&&v){el.value=v;}}'
    'var taskEl=manual.querySelector(".launch-task");if(taskEl)taskEl.value=task;'
    'set(".launch-role",role);'
    'set(".launch-client",client);'
    'set(".launch-workspace",workspace);'
    'set(".launch-mode","interactive");'
    'manual.open=true;'
    'var out=manual.querySelector(".launch-output");if(out)out.textContent="поля заполнены: "+task;'
    'loadModels(manual);'
    'manual.scrollIntoView({behavior:"smooth",block:"center"});'
    '});'
    '});'
    '});\n'
    '</script>\n'
)


WORKSPACE_IMPORT_SCRIPT = r"""<script>
window.addEventListener("DOMContentLoaded", function(){
  var btn = document.getElementById("ws-import-btn");
  if(!btn){ return; }
  var out = document.getElementById("ws-import-out");
  function show(t){ if(out){ out.textContent = t; out.scrollIntoView({behavior:"smooth", block:"center"}); } }
  btn.addEventListener("click", function(){
    var el = document.getElementById("ws-import-desc");
    var targetEl = document.getElementById("ws-import-target");
    var desc = (el && el.value ? el.value : "").trim();
    var target = (targetEl && targetEl.value ? targetEl.value : "").trim();
    if(!desc){ alert("Укажи путь или ссылку"); return; }
    var token = localStorage.getItem("brainDashboardToken") || "";
    var headers = {"X-Brain-Confirm":"1"};
    if(token){ headers["X-Brain-Token"] = token; }
    btn.disabled = true; show("Импорт: " + desc + " …");
    fetch("/api/workspace/import?descriptor=" + encodeURIComponent(desc) + "&target=" + encodeURIComponent(target), {method:"POST", headers:headers})
      .then(function(r){ return r.json(); })
      .then(function(d){
        if(d.ok){
          var tasks = (d.tasks||[]).length;
          var roles = (d.roles||[]).join(", ");
          var applied = d.workspace ? ("\nWorkspace: " + d.workspace + "\nСоздано задач: " + (d.created_tasks||0)) : "";
          show("✅ Прочитано: " + d.name + "\nЦель: " + (d.goal||"—") + "\nЗадач: " + tasks + "  ·  Роли: " + (roles||"—") + applied);
        } else {
          show("❌ " + (d.error || "Не удалось"));
        }
        btn.disabled = false;
      })
      .catch(function(e){ show("❌ " + String(e)); btn.disabled = false; });
  });
});
</script>
"""


SEARCH_SCRIPT = (
    '<script>\n'
    'function runSearch() {'
    'var q = document.getElementById("search-q").value;'
    'var mode = document.getElementById("search-mode").value;'
    'if (!q) return;'
    'var resDiv = document.getElementById("search-results");'
    'var progress = document.getElementById("search-progress");'
    'resDiv.textContent = "";'
    'if(progress) progress.style.display = "inline";'
    'var url = "/api/search?q=" + encodeURIComponent(q) + "&mode=" + encodeURIComponent(mode);'
    'fetch(url).then(r => r.json()).then(d => {'
    'if(progress) progress.style.display = "none";'
    'if (d.timed_out) {'
    'resDiv.textContent = "";'
    'var timeoutSpan = document.createElement("span");'
    'timeoutSpan.classList.add("error");'
    'timeoutSpan.textContent = "Поиск занял слишком долго";'
    'resDiv.appendChild(timeoutSpan);'
    'return;'
    '}'
    'if (!d.results || d.results.length === 0) {'
    'resDiv.textContent = "No results found.";'
    'return;'
    '}'
    'var table = document.createElement("table");'
    'var headerRow = table.insertRow();'
    '["Score", "Path", "Title"].forEach(function(headerText) {'
    'var th = document.createElement("th");'
    'th.textContent = headerText;'
    'headerRow.appendChild(th);'
    '});'
    'd.results.forEach(r => {'
    'var tr = table.insertRow();'
    'var scoreTd = tr.insertCell();'
    'var score = r.hybrid_score || r.score;'
    'var label = r.hybrid_score ? "hybrid" : (d.mode || "bm25");'
    'scoreTd.style.whiteSpace = "nowrap";'
    'scoreTd.textContent = score.toFixed(4) + " (" + label + ")";'
    'var pathTd = tr.insertCell();'
    'pathTd.classList.add("mono");'
    'pathTd.textContent = r.path;'
    'var titleTd = tr.insertCell();'
    'var strong = document.createElement("strong");'
    'strong.textContent = r.title;'
    'titleTd.appendChild(strong);'
    'var br = document.createElement("br");'
    'titleTd.appendChild(br);'
    'var span = document.createElement("span");'
    'span.classList.add("small");'
    'span.textContent = r.snippet || "";'
    'titleTd.appendChild(span);'
    '});'
    'resDiv.appendChild(table);'
    '}).catch(e => {'
    'if(progress) progress.style.display = "none";'
    'resDiv.textContent = "";'
    'var errorSpan = document.createElement("span");'
    'errorSpan.classList.add("error");'
    'errorSpan.textContent = "Error: " + e;'
    'resDiv.appendChild(errorSpan);'
    '});'
    '}'
    'window.addEventListener("DOMContentLoaded", function() {'
    'var qInput = document.getElementById("search-q");'
    'if (qInput) {'
    'qInput.addEventListener("keypress", function(e) {'
    'if (e.key === "Enter") runSearch();'
    '});'
    '}'
    'var btn = document.getElementById("search-btn");'
    'if (btn) btn.addEventListener("click", runSearch);'
    '});\n'
    '</script>\n'
)


VIEW_SCRIPT = (
    '<script>\n'
    'window.addEventListener("DOMContentLoaded",function(){'
    'var prefs={compact:"brainDashboardCompact",diagnostics:"brainDashboardDiagnostics"};'
    'function setMode(name,on){'
    'if(name==="compact"){document.body.classList.toggle("compact",on);}'
    'if(name==="diagnostics"){document.body.classList.toggle("hide-diagnostics",!on);}'
    'var btn=document.querySelector("[data-view-toggle="+name+"]");'
    'if(btn){btn.classList.toggle("button-primary",on);btn.setAttribute("aria-pressed",on?"true":"false");}'
    '}'
    'var compact=localStorage.getItem(prefs.compact)==="1";'
    'var diagnostics=localStorage.getItem(prefs.diagnostics)!=="0";'
    'setMode("compact",compact);setMode("diagnostics",diagnostics);'
    'document.querySelectorAll("[data-view-toggle]").forEach(function(btn){'
    'btn.addEventListener("click",function(){'
    'var name=btn.getAttribute("data-view-toggle");'
    'if(name==="compact"){compact=!compact;localStorage.setItem(prefs.compact,compact?"1":"0");setMode(name,compact);}'
    'if(name==="diagnostics"){diagnostics=!diagnostics;localStorage.setItem(prefs.diagnostics,diagnostics?"1":"0");setMode(name,diagnostics);}'
    '});'
    '});'
    '});\n'
    '</script>\n'
)


STATUS_POLL_SCRIPT = (
    '<script>\n'
    'window.addEventListener("DOMContentLoaded",function(){'
    'var token=localStorage.getItem("brainDashboardToken")||"";'
    'var sentAt=Date.now();'
    'window.__brainDashLastEventTs=sentAt;'
    'var sigMeta=document.querySelector("meta[name=\\"state-sig\\"]");'
    'var curSig=sigMeta?sigMeta.getAttribute("content"):"";'
    'var pollSec=Number(localStorage.getItem("brainDashboardPollSec")||"20");'
    'if(!Number.isFinite(pollSec)||pollSec<10){pollSec=20;}'
    'function _busy(){var a=document.activeElement;return (a&&/^(INPUT|SELECT|TEXTAREA)$/.test(a.tagName))||document.hidden;}'
    'function refreshCheck(){'
    'var headers={};'
    'if(token){headers["X-Brain-Token"]=token;}'
    'fetch("/api/status",{headers:headers}).then(function(r){return r.ok?r.json():null;}).then(function(d){'
    'if(!d){return;}'
    'var nextSig=String(d.signature||"");'
    'if(nextSig&&curSig&&nextSig!==curSig&&!_busy()){window.location.reload();}'
    '}).catch(function(){});'
    '}'
    'setInterval(refreshCheck,pollSec*1000);'
    '});\n'
    '</script>\n'
)


TAB_SCRIPT = (
    "<script>\n"
    "(function(){\n"
    "function activate(tab){\n"
    "document.querySelectorAll('.tab-btn').forEach(function(b){b.classList.toggle('active', b.getAttribute('data-tab-target')===tab);});\n"
    "document.querySelectorAll('.tab-panel').forEach(function(p){p.classList.toggle('active', p.getAttribute('data-tab')===tab);});\n"
    "try{history.replaceState(null,'','#tab='+tab);}catch(e){}\n"
    "}\n"
    "document.addEventListener('click',function(e){\n"
    "var b=e.target.closest?e.target.closest('.tab-btn'):null;\n"
    "if(b){e.preventDefault();activate(b.getAttribute('data-tab-target'));}\n"
    "});\n"
    "var m=(location.hash||'').match(/tab=([\\w-]+)/);\n"
    "if(m){activate(m[1]);}\n"
    "})();\n"
    "</script>\n"
)
