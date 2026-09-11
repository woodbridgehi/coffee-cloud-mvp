import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

test('menu refresh unlocks after collection, removes stale READY and preserves selection on unchanged snapshots', async()=>{
  let collected=false,writes=0,html='',menuCalls=0,fail=false;
  const store=new Map([['coffee_active_order:machine',JSON.stringify({orderId:'a',token:'private-a',status:'READY',updatedAt:Date.now()})]]);
  const elements=new Map([['app',{set innerHTML(value){html=value;writes++;},get innerHTML(){return html;}}]]);
  const context=vm.createContext({URLSearchParams,AbortController,location:{search:'?device_id=machine',pathname:'/order',hash:''},
    document:{hidden:false,getElementById(id){if(!elements.has(id))elements.set(id,{});return elements.get(id);},querySelectorAll(){return [];}},
    localStorage:{getItem:k=>store.get(k),setItem:(k,v)=>store.set(k,v),removeItem:k=>store.delete(k)},
    sessionStorage:{getItem(){return null;},setItem(){},removeItem(){}},setTimeout:()=>1,clearTimeout(){},clearInterval(){},
    fetch:async url=>{
      if(fail)throw Error('network down');
      if(url.endsWith('/menu')){menuCalls++;return {ok:true,json:async()=>({deviceId:'machine',serverTime:menuCalls,online:true,salesEnabled:collected,paymentMode:'ONLINE',products:[{recipeId:'latte',name:'Latte',available:collected,priceMinor:1800,remainingServings:10}]})};}
      return {ok:true,json:async()=>({orderId:'a',status:'READY',collectedAt:collected?'collected':null})};
    }});
  for(const file of ['shared/i18n.js','locales/common/zh-CN.js','locales/common/en-US.js','locales/order/zh-CN.js','locales/order/en-US.js','order.js'])vm.runInContext(fs.readFileSync(new URL('../public/'+file,import.meta.url),'utf8'),context);
  await context.loadMenu();assert.match(html,/active-order-banner/);
  collected=true;await context.loadMenu({background:true});assert.doesNotMatch(html,/active-order-banner/);assert.equal(store.has('coffee_active_order:machine'),false);
  context.selectDrink('latte');const before=writes;
  await context.loadMenu({background:true});assert.equal(writes,before);assert.match(html,/aria-pressed="true"/);
  fail=true;await context.loadMenu({background:true});assert.equal(writes,before);
});
