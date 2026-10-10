"use strict";
const invoke=window.__TAURI__?.core.invoke;
const $=id=>document.getElementById(id);
const status=$("status"),join=$("join"),login=$("login");
let ready=false,connecting=false,development=false;
function controls(disabled){for(const button of [join,login,$("connect")])if(button)button.disabled=disabled;}
async function connect(intent,persist=true){
  if(!invoke||!ready||connecting)return;
  if(intent==="development"&&!development)return;
  connecting=true;controls(true);status.classList.remove("is-error");status.textContent="正在打开 Pajio…";
  try{
    if(intent==="development")await invoke("connect_server",{value:$("server").value,persist});
    else await invoke("open_account",{intent});
    status.textContent="已打开 Pajio。";
  }catch(error){status.textContent=typeof error==="string"?error:"暂时没能打开，请再试一次。";status.classList.add("is-error");}
  finally{connecting=false;controls(false);}
}
join.addEventListener("click",()=>connect("join"));
login.addEventListener("click",()=>connect("login"));
(async()=>{
  if(!invoke){status.textContent="请从 Pajio 桌面应用打开这个入口。";return;}
  try{
    const settings=await invoke("connection_info");
    development=settings.development_endpoints===true;
    if(development){
      $("development-host").append($("development-template").content.cloneNode(true));
      $("server").value=settings.url;
      $("connection-form").addEventListener("submit",event=>{event.preventDefault();void connect("development");});
    }
    $("shortcut").textContent=settings.shortcut_ready?`随时记一下：${settings.shortcut_label}`:"快捷键暂时被占用，可以使用菜单里的「记一下」。";
    ready=true;controls(false);
    if(settings.warning){status.textContent=settings.warning;status.classList.add("is-error");}
    else if(settings.auto_connect===true)await connect(development?"development":"continue",false);
  }catch{status.textContent="账号入口暂时没准备好，请重新打开客户端。";status.classList.add("is-error");}
})();
