"use strict";
const invoke=window.__TAURI__?.core.invoke;
const form=document.getElementById("connection-form"),button=document.getElementById("connect"),server=document.getElementById("server"),status=document.getElementById("status");
async function connect(persist){
  if(!invoke){status.textContent="请从 Pajio 桌面应用打开这个入口。";return;}
  button.disabled=true;button.textContent="正在连接…";status.classList.remove("is-error");status.textContent="正在找 Pajio，记录仍留在原来的地方。";
  try{await invoke("connect_server",{value:server.value,persist});status.textContent="已连接。";}
  catch(error){status.textContent=typeof error==="string"?error:"连接暂时没有完成，请再试一次。";status.classList.add("is-error");}
  finally{button.disabled=false;button.textContent="连接 Pajio";}
}
form.addEventListener("submit",event=>{event.preventDefault();connect(true);});
(async()=>{
  if(!invoke){status.textContent="请从 Pajio 桌面应用打开这个入口。";return;}
  try{
    const settings=await invoke("connection_info");server.value=settings.url;
    document.getElementById("shortcut").textContent=settings.shortcut_ready?`随时记一下：${settings.shortcut_label}`:"快捷键暂时被占用，可以使用菜单里的「记一下」。";
    if(settings.warning){status.textContent=settings.warning;status.classList.add("is-error");}
    else if(settings.auto_connect)await connect(false);
  }catch{status.textContent="连接信息暂时没打开，可以再试一次。";status.classList.add("is-error");}
})();
