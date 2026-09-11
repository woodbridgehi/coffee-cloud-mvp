/* Shared event presentation only. No business state is inferred from audio. */
(function (root) {
  'use strict';
  class StatusSound {
    constructor({ contextFactory, storage } = {}) {
      this.factory = contextFactory || (() => {
        const Context = root.AudioContext || root.webkitAudioContext;
        return Context ? new Context() : null;
      });
      this.storage = storage;
      this.context = null;
      this.enabled = false;
      this.volume = 0.2;
      this.nodes = new Set();
      this.processNodes = new Set(); this.loop = null; this.noise = null; this.voice = false; this.surface = 'customer';
      this.seen = new Set();
      try {
        const saved = JSON.parse(storage?.getItem('coffee-sound:recent') || '[]');
        if (Array.isArray(saved)) this.seen = new Set(saved.filter(key => typeof key === 'string').slice(-256));
      } catch (_) {}
      this.previous = null;
      this.generation = 0;
    }
    async enable() {
      const generation = ++this.generation;
      try {
        this.context ||= this.factory();
        if (!this.context) return false;
        await this.context.resume();
        if (generation !== this.generation) return false;
        this.enabled = this.context.state === 'running';
        if(this.enabled)this.prepareAudio();
      } catch (_) { this.enabled = false; }
      this.notify();
      return this.enabled;
    }
    notify() { if (root.CustomEvent) root.dispatchEvent?.(new root.CustomEvent('coffee-sound-change')); }
    mute() { this.generation++; this.enabled = false; this.stop(); this.notify(); }
    stop() {
      this.stopProcess();
      root.speechSynthesis?.cancel();
      for (const { oscillator, gain } of this.nodes) {
        try { oscillator.stop(); } catch (_) {}
        oscillator.disconnect(); gain.disconnect();
      }
      this.nodes.clear();
    }
    disconnect() { this.stop(); this.previous = null; }
    close() {
      this.mute(); this.previous = null;
      if (this.context) { const context = this.context; this.context = null; this.noise = null; Promise.resolve(context.close()).catch(() => {}); }
    }
    setVolume(value) {
      const volume = Number(value);
      if (Number.isFinite(volume)) this.volume = Math.min(1, Math.max(0, volume));
      if (!this.volume) this.stop();
      for (const node of this.processNodes) node.gain.gain.setValueAtTime(this.volume * node.level, this.context.currentTime);
    }
    mark(key) {
      if (this.seen.has(key)) return false;
      this.seen.add(key);
      if (this.seen.size > 256) this.seen.delete(this.seen.values().next().value);
      try { this.storage?.setItem('coffee-sound:recent', JSON.stringify([...this.seen])); } catch (_) {}
      return true;
    }
    update({ id, status, revision = 0, collected = false, surface }) {
      if (surface) this.surface = surface;
      if (!id) { this.stop(); this.previous = { id: null }; return; }
      const previous = this.previous;
      if (previous?.id === id && revision && previous.revision && revision < previous.revision) return;
      this.previous = { id, status, revision };
      const kind = ({ ACCEPTED: 'accepted', ACKNOWLEDGED: 'accepted', READY: 'ready', SUCCEEDED: 'ready', HOLD: 'alert', FAILED: 'alert' })[status];
      if (['PAUSED', 'RETRY_WAIT', 'HOLD', 'FAILED', 'CANCELLED', 'EXPIRED', 'REFUNDED'].includes(status) || collected) this.stop();
      if (!kind) return;
      // Baseline snapshots, reconnects and silent events are consumed, never replayed later.
      const fresh = this.mark(`${id}:${kind}`);
      if (!fresh || !previous || (previous.id !== id && kind !== 'accepted') || (previous.id === id && previous.status === status) || collected) return;
      if (this.enabled && this.volume > 0 && this.context?.state === 'running') this.play(kind);
    }
    prepareAudio() {
      const c=this.context;if(this.noise || !c?.createBuffer)return;
      this.noise=c.createBuffer(1,c.sampleRate*2,c.sampleRate);
      const data=this.noise.getChannelData(0);let seed=719;
      for(let i=0;i<data.length;i++){seed=(Math.imul(seed,1664525)+1013904223)>>>0;data[i]=(seed/4294967296*2-1)*.45;}
    }
    stopProcess() {
      for (const node of [...this.processNodes]) node.dispose();
      this.loop = null;
    }
    setProcessLoop(key,kind) {
      if (!key || !this.enabled || !this.volume || this.context?.state !== 'running') {
        if (this.loop) this.loop.node.dispose();
        this.loop=null; return;
      }
      if (this.loop?.key === key) return;
      if (this.loop) this.loop.node.dispose();
      const node=this.processTone(kind,true);
      this.loop=node?{key,node}:null;
    }
    playAction(kind) {
      if (this.enabled && this.volume>0 && this.context?.state==='running') this.processTone(kind,false);
    }
    processTone(kind,loop) {
      const profiles={brew:[95,400,.12,.2],water:[0,1800,.09,.2],milk:[0,850,.065,.2],syrup:[0,600,.055,.2],
        grip:[170,1100,.11,.10],place:[640,1600,.10,.16],ice:[0,3400,.17,.24],lid:[110,700,.15,.12]};
      const p=profiles[kind];if(!p)return null;
      try {
        const c=this.context,t=c.currentTime,gain=c.createGain(),sources=[],filters=[];
        gain.gain.setValueAtTime(.0001,t);gain.gain.linearRampToValueAtTime(this.volume*p[2],t+.02);
        if(!loop)gain.gain.exponentialRampToValueAtTime(.0001,t+p[3]);
        gain.connect(c.destination);
        if(c.createBuffer && c.createBufferSource) {
          this.prepareAudio();
          const source=c.createBufferSource();source.buffer=this.noise;source.loop=loop;
          const filter=c.createBiquadFilter();filter.type='lowpass';filter.frequency.value=p[1];filter.Q.value=.5;
          source.connect(filter);filter.connect(gain);filters.push(filter);sources.push(source);
        }
        if(p[0] || !sources.length) {
          const source=c.createOscillator();source.type=kind==='place'?'sine':'triangle';
          source.frequency.setValueAtTime(p[0] || 180,t);
          if(!loop)source.frequency.exponentialRampToValueAtTime((p[0] || 180)*.55,t+p[3]);
          source.connect(gain);sources.push(source);
        }
        const node={gain,level:p[2],dispose:()=>{
          if(!this.processNodes.delete(node))return;
          for(const source of sources){source.onended=null;try{source.stop();}catch(_){}source.disconnect();}
          filters.forEach(f=>f.disconnect());gain.disconnect();
        }};
        if(this.processNodes.size>=8) [...this.processNodes].find(n=>n!==this.loop?.node)?.dispose();
        this.processNodes.add(node);
        sources[0].onended=node.dispose;
        for(const source of sources){source.start(t);if(!loop)source.stop(t+p[3]+.02);}
        return node;
      }catch(_){this.stopProcess();return null;}
    }
    play(kind) {
      this.stop();
      try {
        const context = this.context, now = context.currentTime;
        const oscillator = context.createOscillator(), gain = context.createGain();
        const node = { oscillator, gain };
        this.nodes.add(node);
        oscillator.type = 'sine';
        oscillator.frequency.setValueAtTime(kind === 'alert' ? (this.surface==='terminal'?440:330) : 587.33, now);
        oscillator.frequency.exponentialRampToValueAtTime(kind === 'ready' ? 880 : kind === 'alert' ? 220 : 660, now + 0.12);
        gain.gain.setValueAtTime(0.0001, now);
        gain.gain.linearRampToValueAtTime(this.volume * 0.12, now + 0.015);
        gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.4);
        oscillator.connect(gain); gain.connect(context.destination);
        oscillator.onended = () => { oscillator.disconnect(); gain.disconnect(); this.nodes.delete(node); };
        oscillator.start(now); oscillator.stop(now + 0.42);
        if(kind==='ready' && this.voice && root.speechSynthesis && root.SpeechSynthesisUtterance) {
          const en=root.document?.documentElement.lang.startsWith('en');
          const speech=new root.SpeechSynthesisUtterance(en?'Your coffee is ready. Please collect your drink.':'咖啡制作完成，请取杯。');
          speech.lang=en?'en-US':'zh-CN';speech.volume=this.volume;speech.rate=1;
          root.speechSynthesis.speak(speech);
        }
      } catch (_) { this.stop(); }
    }
  }
  root.CoffeeStatusSound = StatusSound;
  if (!root.document?.addEventListener) return;
  let storage;
  try { storage = root.sessionStorage; } catch (_) {}
  const sound = new StatusSound({ storage });
  root.CoffeeSound = sound;
  const controls = root.document.getElementById('sound-controls');
  if (controls) {
    const button = root.document.createElement('button');
    button.type = 'button';
    const volume = root.document.createElement('input');
    volume.type = 'range'; volume.min = '0'; volume.max = '100'; volume.value = '20';
    const label = () => {
      const en = root.document.documentElement.lang.startsWith('en');
      button.textContent = sound.enabled ? (en ? 'Mute' : '静音') : (en ? 'Enable sound' : '开启声音');
      button.setAttribute('aria-pressed', String(sound.enabled));
      volume.setAttribute('aria-label', en ? 'Sound volume' : '声音音量');
    };
    button.onclick = async () => { if (sound.enabled) sound.mute(); else await sound.enable(); label(); };
    volume.oninput = () => sound.setVolume(Number(volume.value) / 100);
    const voiceLabel=root.document.createElement('label'), voice=root.document.createElement('input'), voiceText=root.document.createElement('span');
    voice.type='checkbox'; voice.onchange=()=>{sound.voice=voice.checked;if(!sound.voice)root.speechSynthesis?.cancel();};
    voiceLabel.append(voice,voiceText);
    controls.append(button, volume, voiceLabel); label();
    const voiceLabelText=()=>{voiceText.textContent=root.document.documentElement.lang.startsWith('en')?'Ready announcement':'完成语音';};
    voiceLabelText(); new MutationObserver(voiceLabelText).observe(root.document.documentElement,{attributes:true,attributeFilter:['lang']});
    root.addEventListener('coffee-sound-change',label);
    new MutationObserver(label).observe(root.document.documentElement, { attributes: true, attributeFilter: ['lang'] });
    root.document.addEventListener('visibilitychange', () => {
      if (root.document.visibilityState !== 'visible') { sound.mute(); sound.disconnect(); label(); }
    });
    root.addEventListener('pagehide', () => { sound.close(); label(); });
  }
})(globalThis);
