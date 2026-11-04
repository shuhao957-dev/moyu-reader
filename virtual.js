/* MIT. Bounded DOM renderer for Moyu Reader; original UI/CSS remain intact. */
let actualLineKey='', actualLineHeight=22.4;
getLineHeight=function(){
  const root=document.getElementById('text-content'),s=getComputedStyle(root);
  const key=[s.fontFamily,s.fontSize,s.lineHeight].join('|');
  if(key!==actualLineKey){
    const probe=document.createElement('div');probe.style.cssText='position:absolute;visibility:hidden;white-space:pre;pointer-events:none';probe.textContent='字\n字';root.append(probe);
    actualLineHeight=probe.getBoundingClientRect().height/2;probe.remove();actualLineKey=key;
  }
  return actualLineHeight;
};
const virtualBook = {
  blocks: [], starts: [], heights: [], sums: [0], measured: new Set(), key: '',
  first: -1, last: -1, base: 0, anchor: 0, widthLock: 0,
  init(text) {
    this.blocks=[]; this.starts=[]; this.heights=[]; this.measured.clear(); this.key='';
    // Split at real line boundaries: browser wrapping inside each paragraph is unchanged.
    let begin=0;
    for(let i=0;i<text.length;i++) {
      if(text[i]==='\n' && i+1-begin>=1800) {
        this.starts.push(begin); this.blocks.push(text.slice(begin,i+1));begin=i+1;
      }
    }
    if(begin<text.length || !this.blocks.length){this.starts.push(begin);this.blocks.push(text.slice(begin));}
    this.first=-1;this.last=-1;this.anchor=0;this.base=0;
    this.metrics();this.render();
  },
  metrics() {
    const display=document.getElementById('text-display');
    const width=this.widthLock || display.clientWidth;
    const style=getComputedStyle(document.getElementById('text-content'));
    const key=[width,style.fontFamily,style.fontSize,style.lineHeight].join('|');
    if(key===this.key)return false;
    this.key=key;this.width=width;this.lh=getLineHeight();this.measured.clear();
    const cols=Math.max(1,Math.floor(width/parseFloat(style.fontSize)));
    this.heights=this.blocks.map(t=>{
      const rows=t.split('\n');if(t.endsWith('\n'))rows.pop();
      return Math.max(1,rows.reduce((n,r)=>n+Math.max(1,Math.ceil(r.length/cols)),0))*this.lh;
    });
    this.reindex();this.first=-1;return true;
  },
  reindex(){this.sums=[0];for(const h of this.heights)this.sums.push(this.sums[this.sums.length-1]+h);},
  blockAt(y){let lo=0,hi=this.blocks.length-1;while(lo<hi){const mid=(lo+hi+1)>>1;if(this.sums[mid]<=y)lo=mid;else hi=mid-1;}return lo;},
  blockForOffset(offset){let lo=0,hi=this.starts.length-1;while(lo<hi){const mid=(lo+hi+1)>>1;if(this.starts[mid]<=offset)lo=mid;else hi=mid-1;}return lo;},
  node(i){const el=document.createElement('div');el.className='moyu-text-block';el.dataset.block=i;el.textContent=this.blocks[i] || '\n';return el;},
  mount(first,last){
    const root=document.getElementById('text-content');
    if(first!==this.first||last!==this.last){root.replaceChildren(...Array.from({length:last-first+1},(_,n)=>this.node(first+n)));this.first=first;this.last=last;}
    let changed=false;
    for(const el of root.children){const i=+el.dataset.block;const h=el.getBoundingClientRect().height;if(h>0 && Math.abs(this.heights[i]-h)>.01){this.heights[i]=h;changed=true;}this.measured.add(i);}
    if(changed)this.reindex();
    this.base=this.sums[first];
  },
  render(){
    if(!this.blocks.length)return;
    const changed=this.metrics();
    if(changed){this.seek(this.anchor);return;}
    const idx=this.blockAt(Math.max(0,currentPosition));const delta=currentPosition-this.sums[idx];
    let last=idx;while(last<this.blocks.length-1 && this.sums[last+1]<currentPosition+viewHeight()+this.lh*4)last++;
    this.mount(Math.max(0,idx-1),Math.min(this.blocks.length-1,last+1));
    currentPosition=this.sums[idx]+delta;
    const root=document.getElementById('text-content');
    root.style.transform=`translateY(${this.base-currentPosition}px)`;
    this.anchor=this.offsetAtTop();
  },
  offsetAtTop(){
    const root=document.getElementById('text-content'),display=document.getElementById('text-display');
    const bounds=display.getBoundingClientRect();
    // caret hit testing is unreliable when a settings overlay covers the text.
    // A binary search of a single visible block uses bounded Range queries instead.
    let idx=this.blockAt(Math.max(0,currentPosition));
    const el=root.querySelector('[data-block="'+idx+'"]');
    if(!el||!el.firstChild)return this.starts[idx]||0;
    const node=el.firstChild, range=document.createRange();let lo=0,hi=Math.max(0,node.length-1);
    const top=bounds.top+.5;
    while(lo<hi){const m=(lo+hi)>>1;range.setStart(node,m);range.setEnd(node,Math.min(node.length,m+1));const r=range.getBoundingClientRect();if(r.bottom<=top)lo=m+1;else hi=m;}
    // Save the first character on the row, not a pixel estimate.
    return (this.starts[idx]||0)+lo;
  },
  seek(offset){
    if(!this.blocks.length)return 0;
    this.metrics();offset=Math.max(0,Math.min(content.length-1,Math.floor(offset)||0));
    const idx=this.blockForOffset(offset);
    this.mount(Math.max(0,idx-1),Math.min(this.blocks.length-1,idx+1));
    const root=document.getElementById('text-content');root.style.transform='none';
    const el=root.querySelector('[data-block="'+idx+'"]'),node=el.firstChild;
    let local=Math.max(0,Math.min(node.length-1,offset-this.starts[idx]));
    if(local>0 && /[\uDC00-\uDFFF]/.test(node.data[local]))local--;
    const range=document.createRange();range.setStart(node,local);range.setEnd(node,Math.min(node.length,local+(/^[\uD800-\uDBFF]/.test(node.data[local])?2:1)));
    const rect=range.getClientRects()[0];
    // Inline glyph boxes have font-dependent vertical leading. Floor to the line grid.
    const localY=rect?Math.max(0,Math.floor((rect.top-el.getBoundingClientRect().top+1)/this.lh)*this.lh):0;
    currentPosition=this.sums[idx]+localY;
    root.style.transform=`translateY(${this.base-currentPosition}px)`;
    this.anchor=offset;this.render();return currentPosition;
  },
  snapshot(){return {version:2,offset:this.anchor};},
  lock(){if(!this.widthLock){this.widthLock=document.getElementById('text-display').clientWidth;document.getElementById('text-display').style.width=this.widthLock+'px';}},
  unlock(){this.widthLock=0;document.getElementById('text-display').style.width='';this.render();}
};

contentHeight = function(){return virtualBook.sums[virtualBook.sums.length-1]||0;};
updatePagePosition = function(){virtualBook.render();};
charOffsetToY = function(offset){return virtualBook.seek(offset)+getLineHeight();};
// Every virtual block ends at a real newline, so each block starts on the same line grid.
snapTopToRealRow = function(){if(content){currentPosition=lineFloor(currentPosition);virtualBook.render();}};
updateProgressBar = function(){if(content)document.getElementById('progress-fill').style.width=(100*virtualBook.anchor/Math.max(1,content.length-1))+'%';};
jumpToPercent = function(pct){if(!content)return;virtualBook.seek((Math.min(100,Math.max(0,Number(pct)))/100)*(content.length-1));updateProgressBar();saveProgress();};
jumpToProgress = function(event){const r=document.getElementById('progress-bar').getBoundingClientRect();jumpToPercent(100*(event.clientX-r.left)/r.width);};
saveProgress = function(){if(currentFilePath&&content)return pywebview.api.save_progress(currentFilePath,virtualBook.snapshot());return Promise.resolve();};
closeApp = async function(){if(autoSaveInterval)clearInterval(autoSaveInterval);try{await saveProgress();await pywebview.api.close();}catch(err){alert('保存或退出失败：'+err);}};

scroll = function(timestamp){
  scrollFrame=0;if(!lastTimestamp)lastTimestamp=timestamp;
  const delta=Math.min(100,timestamp-lastTimestamp);lastTimestamp=timestamp;
  if(!isPaused&&content&&isAutoMode){
    currentPosition+=scrollSpeed*delta/1000;
    if(currentPosition>contentHeight()+viewHeight())currentPosition=-viewHeight();
    virtualBook.render();
    if(!scroll._progressAt||timestamp-scroll._progressAt>200){updateProgressBar();scroll._progressAt=timestamp;}
    scrollFrame=requestAnimationFrame(scroll);
  }
};
const originalStartScroll=startScroll;
startScroll=function(){if(isAutoMode)originalStartScroll();};

let openFilePending=false;
openFile = async function(){
  if(openFilePending)return;openFilePending=true;
  const previousPaused=isPaused;if(!isPaused)togglePause();saveProgress();
  try {
    const result=await pywebview.api.open_file();
    if(!result.success){if(result.error!=='未选择文件')alert(result.error||'打开失败');if(!previousPaused&&isPaused)togglePause();return;}
    await closeToc();closeSearch();
    content=await unpackContent(result);currentFile=result.filename;currentFilePath=result.filepath;
    isAutoMode=result.auto_mode!==undefined?!!result.auto_mode:true;isPaused=true;
    cancelAnimationFrame(scrollFrame);scrollFrame=0;lastTimestamp=0;currentPosition=0;
    document.getElementById('pause-btn').textContent='继续';syncModeUi(false);
    searchMatches=[];searchIndex=-1;updateSearchCount();
    virtualBook.init(content);
    if(result.position&&result.position.version===2)virtualBook.seek(result.position.offset);
    else if(Number(result.position)>0){currentPosition=Number(result.position);virtualBook.render();}
    updateProgressBar();startAutoSave();
  }catch(err){alert('打开文件出错：'+err);}finally{openFilePending=false;}
};

const oldOpenSettings=openSettings,oldFinishSettings=finishSettings,oldOpenToc=openToc,oldCloseToc=closeToc;
openSettings=async function(){virtualBook.lock();await oldOpenSettings();if(!settingsOpen)virtualBook.unlock();};
finishSettings=async function(){await oldFinishSettings();virtualBook.unlock();};
openToc=async function(){virtualBook.lock();await oldOpenToc();if(!document.body.classList.contains('toc-open'))virtualBook.unlock();};
closeToc=async function(){const wasOpen=document.body.classList.contains('toc-open');await oldCloseToc();if(wasOpen&&!settingsOpen)virtualBook.unlock();};

// Keep the heading, current chapter and return button outside the scrolling list.
const tocHeader=document.createElement('div');
tocHeader.id='toc-header';
const tocCard=document.getElementById('toc-card');
tocCard.insertBefore(tocHeader,tocCard.firstChild);
tocHeader.append(document.getElementById('toc-close'),tocCard.querySelector('h1'));
const currentChapterLabel=document.createElement('div');
currentChapterLabel.id='toc-current-chapter';
currentChapterLabel.setAttribute('role','status');
tocHeader.append(currentChapterLabel);
const originalBuildTocList=buildTocList;
buildTocList=function(chapters){
  originalBuildTocList(chapters);
  const offset=virtualBook.anchor;
  let current=-1;
  for(let i=0;i<chapters.length;i++){
    if(chapters[i].offset<=offset && (current<0 || chapters[i].offset>=chapters[current].offset))current=i;
  }
  const title=current>=0?chapters[current].title:(chapters.length?'正文开头（目录前）':'暂无章节');
currentChapterLabel.textContent='当前：'+title;
  currentChapterLabel.title=title;
  const list=document.getElementById('toc-list');
  const active=current>=0?list.children[current]:null;
  if(active){
    active.classList.add('toc-current');
    active.setAttribute('aria-current','location');
    requestAnimationFrame(()=>{
      if(!document.body.classList.contains('toc-open') || !active.isConnected)return;
      const row=active.getBoundingClientRect(),bounds=list.getBoundingClientRect();
      list.scrollTop+=row.top-bounds.top-(list.clientHeight-row.height)/2;
    });
  }
};

// Wheel input adjusts the reading position without changing auto/manual or pause state.
let wheelSaveTimer=null;
document.getElementById('container').addEventListener('wheel',event=>{
  if(!isAutoMode || !content || settingsOpen || document.body.classList.contains('toc-open') || senseHidden)return;
  if(event.ctrlKey || event.target.closest('input,button,select,textarea'))return;
  if(!event.deltaY)return;
  event.preventDefault();
  const unit=event.deltaMode===1?getLineHeight():event.deltaMode===2?viewHeight():1;
  const limit=Math.max(getLineHeight()*3,viewHeight());
  const delta=Math.max(-limit,Math.min(limit,event.deltaY*unit));
  currentPosition=Math.max(0,Math.min(currentPosition+delta,Math.max(0,contentHeight()-viewHeight())));
  virtualBook.render();updateProgressBar();lastTimestamp=0;
  clearTimeout(wheelSaveTimer);
  wheelSaveTimer=setTimeout(()=>saveProgress().catch(()=>{}),250);
},{passive:false});

// Coalesce drag calls: at most one bridge call in flight, retain latest pointer coordinates.
// screen coordinates stay stable when the native window moves under the pointer.
const dragClickSlop=4;
const dragExcluded='button, input, select, textarea, #progress-bar, #search-bar, #toc-list';
let clickGesture=null,suppressDragClick=false;
function trackClickGesture(event){
  if(!clickGesture || clickGesture.id!==event.pointerId)return;
  if(Math.hypot(event.screenX-clickGesture.x,event.screenY-clickGesture.y)>dragClickSlop)clickGesture.moved=true;
}
document.addEventListener('pointerdown',event=>{
  if(!event.isPrimary || event.button!==0)return;
  suppressDragClick=false;
  clickGesture=event.target.closest(dragExcluded)?null:{id:event.pointerId,x:event.screenX,y:event.screenY,moved:false};
},true);
document.addEventListener('pointermove',trackClickGesture,true);
document.addEventListener('pointerup',event=>{
  if(!clickGesture || clickGesture.id!==event.pointerId)return;
  trackClickGesture(event);suppressDragClick=clickGesture.moved;clickGesture=null;
},true);
document.addEventListener('pointercancel',event=>{
  if(clickGesture && clickGesture.id===event.pointerId){suppressDragClick=true;clickGesture=null;}
},true);
document.addEventListener('click',event=>{
  // A keyboard/programmatic activation is not the synthetic mouse click after dragging.
  if(!suppressDragClick || event.detail===0)return;
  suppressDragClick=false;event.preventDefault();event.stopImmediatePropagation();
},true);
const originalDragApi=moyuDragApi;
let dragPending=null,dragBusy=false,dragReady=Promise.resolve(),dragOrigin=null,dragThresholdPassed=false;
moyuDragApi=function(name,...args){
  if(name==='drag_begin'){dragPending=null;dragOrigin=args;dragThresholdPassed=false;dragReady=pywebview.api.drag_begin(...args).catch(()=>{});return;}
  if(name==='drag_move'){
    if(!dragThresholdPassed){if(!dragOrigin || Math.hypot(args[0]-dragOrigin[0],args[1]-dragOrigin[1])<=dragClickSlop)return;dragThresholdPassed=true;}
    dragPending=args;if(!dragBusy){dragBusy=true;(async()=>{try{await dragReady;while(dragPending){const pos=dragPending;dragPending=null;await pywebview.api.drag_move(...pos);}}catch(e){}finally{dragBusy=false;}})();}return;}
  if(name==='drag_end'){dragPending=null;dragReady.then(()=>originalDragApi(name,...args));return;}
  originalDragApi(name,...args);
};
const virtualCSS=document.createElement('style');
virtualCSS.textContent=`
#text-content{transition:none!important}
.moyu-text-block{white-space:pre-wrap;word-break:break-all;margin:0;padding:0;border:0}
#toc-panel{overflow:hidden}
#toc-card{height:100%;max-height:100%;display:flex;flex-direction:column}
#toc-header{flex:none;position:relative;z-index:1;background:white;display:flex;align-items:center;gap:8px;padding-bottom:8px;border-bottom:1px solid #ececef}
#toc-header h1{order:0;flex:none;margin:0;white-space:nowrap}
#toc-current-chapter{order:1;flex:1;min-width:0;font-size:12px;line-height:1.6;color:#49764c;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#toc-header #toc-close{order:2;flex:none;float:none;margin:0;white-space:nowrap}
#toc-list{flex:1;min-height:0;overflow-y:auto;overscroll-behavior:contain}
.toc-item.toc-current{background:#e8f3e9;color:#276330;font-weight:600;box-shadow:inset 3px 0 #4b8754}
`;
document.head.appendChild(virtualCSS);
const oldApplyFontStyle=applyFontStyle;
applyFontStyle=function(...args){oldApplyFontStyle(...args);if(content)virtualBook.render();};
window.addEventListener('resize',()=>{if(content)virtualBook.render();});
window.addEventListener('pywebviewready',async()=>{if(await pywebview.api.has_startup_file())await openFile();});
// Diagnostic API is read-only except test loading; only exposed in a test browser, not a remote port.
window.moyuDiagnostics=()=>({characters:content.length,renderedCharacters:document.getElementById('text-content').textContent.length,blocks:virtualBook.blocks.length,visibleBlocks:document.getElementById('text-content').children.length,offset:virtualBook.anchor,position:currentPosition,totalHeight:contentHeight()});

// [integration] TOC / 搜索跳转改走 virtualBook.seek（按字符偏移精确定位，自带 emoji/代理对处理）。
// 原 reader.py 的 jumpToCharOffset 依赖旧分块变量 starts/lineStarts，virtualBook 不维护它们，必须覆盖。
jumpToCharOffset = function(offset, contextLines) {
    if (!content || !virtualBook.blocks.length) return;
    virtualBook.seek(offset);
    updateProgressBar();
    saveProgress();
};
