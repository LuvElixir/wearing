"use strict";
// Preserve the identity of a user submission across a lost HTTP response.
// This journal never sends, retries, or schedules work by itself.
(() => {
  const prefix="wearing-chat-submission:v1:";
  function create(storage,onError=()=>{},makeId=()=>window.WearingIds.uuid()){
    const memory=new Map();
    const key=identity=>{
      if(typeof identity!=="string"||!identity||identity.length>64)throw Error("提交身份不完整。");
      return prefix+encodeURIComponent(identity);
    };
    function read(k){
      if(memory.has(k))return memory.get(k);
      try{const value=JSON.parse(storage().getItem(k)||"null");
        if(value&&typeof value.content==="string"&&value.content.length<=12000&&typeof value.id==="string"&&/^[a-zA-Z0-9_-]{16,80}$/.test(value.id))return value;
      }catch{onError();}
      return null;
    }
    function prepare(identity,content){
      if(typeof content!=="string"||!content.trim()||content.length>12000)throw Error("提交内容不完整。");
      const k=key(identity),previous=read(k);
      if(previous?.content===content)return previous.id;
      const value={id:makeId(),content};
      memory.set(k,value);
      try{storage().setItem(k,JSON.stringify(value));}catch{onError();}
      return value.id;
    }
    function acknowledge(identity,id){
      const k=key(identity);
      if(read(k)?.id!==id)return false;
      memory.set(k,null);
      try{
        // Another tab may have saved a later submission while this response travelled.
        const persisted=JSON.parse(storage().getItem(k)||"null");
        if(persisted?.id===id)storage().removeItem(k);
      }catch{onError();}
      return true;
    }
    return {prepare,acknowledge};
  }
  window.WearingSubmissions={create};
})();
