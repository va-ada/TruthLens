import React, { useState, useEffect, useRef } from 'react';
import * as THREE from 'three';
import { Chart, registerables } from 'chart.js';
import { api, postJson, adminFetch, errorMessage } from './api.js';

Chart.register(...registerables);

// --- Clean Minimalist Icons ---
const Icon = ({ name, className = "w-4 h-4" }) => {
  switch (name) {
    case 'shield':
      return <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" /></svg>;
    case 'cube':
      return <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4" /></svg>;
    case 'search':
      return <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" /></svg>;
    case 'database':
      return <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4" /></svg>;
    case 'history':
      return <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>;
    case 'chart':
      return <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" /></svg>;
    case 'external':
      return <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" /></svg>;
    case 'check':
      return <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M5 13l4 4L19 7" /></svg>;
    case 'x':
      return <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" /></svg>;
    case 'upload':
      return <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" /></svg>;
    case 'trash':
      return <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" /></svg>;
    default:
      return null;
  }
};

// --- MONOCHROME 3D EARTH ORBITAL COMPONENT (BLACK & WHITE APOGEE SCHEME) ---
const Earth3DCanvas = () => {
  const mountRef = useRef(null);

  useEffect(() => {
    const container = mountRef.current;
    if (!container || typeof THREE === 'undefined') return;

    // Scene & Camera
    const scene = new THREE.Scene();
    const width = container.clientWidth || window.innerWidth;
    const height = container.clientHeight || window.innerHeight;
    
    // Position camera to display Earth majestically on the right side
    const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 1000);
    camera.position.set(2.2, 0.3, 6.2);

    // Renderer
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.35;
    container.appendChild(renderer.domElement);

    // Starfield Particles (Pure monochrome white/silver)
    const starGeo = new THREE.BufferGeometry();
    const starCount = 900;
    const starPositions = new Float32Array(starCount * 3);
    for (let i = 0; i < starCount * 3; i += 3) {
      starPositions[i] = (Math.random() - 0.5) * 60;
      starPositions[i+1] = (Math.random() - 0.5) * 60;
      starPositions[i+2] = (Math.random() - 0.5) * 40 - 15;
    }
    starGeo.setAttribute('position', new THREE.BufferAttribute(starPositions, 3));
    const starMat = new THREE.PointsMaterial({ color: 0xffffff, size: 0.07, transparent: true, opacity: 0.55 });
    const stars = new THREE.Points(starGeo, starMat);
    scene.add(stars);

    // Texture Loader
    const loader = new THREE.TextureLoader();
    loader.setCrossOrigin('anonymous');
    
    const earthTexture = loader.load(
      '/static/img/earth_atmos_2048.jpg'
    );
    const cloudTexture = loader.load(
      '/static/img/earth_clouds_1024.png'
    );

    // PURE BLACK & WHITE SHADER ON EARTH MESH
    const earthGeo = new THREE.SphereGeometry(2.35, 64, 64);
    const earthMat = new THREE.MeshStandardMaterial({
      map: earthTexture,
      roughness: 0.8,
      metalness: 0.1,
    });

    // Intercept fragment shader to enforce pure high-contrast black & white palette
    earthMat.onBeforeCompile = (shader) => {
      shader.fragmentShader = shader.fragmentShader.replace(
        '#include <map_fragment>',
        `
        #ifdef USE_MAP
          vec4 texColor = texture2D(map, vUv);
          // Calculate luminance: ITU-R BT.601
          float lum = dot(texColor.rgb, vec3(0.299, 0.587, 0.114));
          // High-contrast S-curve: deep pitch-black oceans, luminous silver land
          lum = pow(lum, 1.4) * 1.25;
          diffuseColor *= vec4(vec3(lum), texColor.a);
        #endif
        `
      );
    };

    const earth = new THREE.Mesh(earthGeo, earthMat);
    earth.rotation.z = 23.5 * Math.PI / 180; // 23.5 deg Earth axial tilt
    scene.add(earth);

    // Atmospheric Cloud Layer (Monochrome Pure White)
    const cloudGeo = new THREE.SphereGeometry(2.38, 64, 64);
    const cloudMat = new THREE.MeshStandardMaterial({
      map: cloudTexture,
      transparent: true,
      opacity: 0.45,
      blending: THREE.AdditiveBlending,
    });
    const clouds = new THREE.Mesh(cloudGeo, cloudMat);
    clouds.rotation.z = 23.5 * Math.PI / 180;
    scene.add(clouds);

    // Monochrome Silver-White Atmospheric Halo (Fresnel)
    const haloGeo = new THREE.SphereGeometry(2.43, 64, 64);
    const haloMat = new THREE.ShaderMaterial({
      vertexShader: `
        varying vec3 vNormal;
        void main() {
          vNormal = normalize(normalMatrix * normal);
          gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
        }
      `,
      fragmentShader: `
        varying vec3 vNormal;
        void main() {
          float intensity = pow(0.60 - dot(vNormal, vec3(0.0, 0.0, 1.0)), 2.6);
          gl_FragColor = vec4(1.0, 1.0, 1.0, 1.0) * intensity * 0.75;
        }
      `,
      blending: THREE.AdditiveBlending,
      side: THREE.BackSide,
      transparent: true
    });
    const halo = new THREE.Mesh(haloGeo, haloMat);
    scene.add(halo);

    // Lighting: Clean White Sun from top-left
    const sunLight = new THREE.DirectionalLight(0xffffff, 2.5);
    sunLight.position.set(-6, 3.5, 5);
    scene.add(sunLight);

    const spaceLight = new THREE.AmbientLight(0x0a0a0e, 0.4);
    scene.add(spaceLight);

    // Interactive Mouse Parallax & Scroll Track
    let mouseX = 0, mouseY = 0;
    const handleMouseMove = (e) => {
      mouseX = (e.clientX / window.innerWidth) * 2 - 1;
      mouseY = -(e.clientY / window.innerHeight) * 2 + 1;
    };
    window.addEventListener('mousemove', handleMouseMove);

    const handleResize = () => {
      if (!container) return;
      const w = container.clientWidth || window.innerWidth;
      const h = container.clientHeight || window.innerHeight;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    };
    window.addEventListener('resize', handleResize);

    // Render Loop
    let animId;
    const animate = () => {
      animId = requestAnimationFrame(animate);

      // Orbital rotation
      earth.rotation.y += 0.0012;
      clouds.rotation.y += 0.0017;
      stars.rotation.y -= 0.0001;

      // Parallax camera easing (Earth positioned on right side)
      const targetX = 2.2 + mouseX * 0.3;
      const targetY = 0.2 + mouseY * 0.2 - (window.scrollY * 0.0005);
      camera.position.x += (targetX - camera.position.x) * 0.04;
      camera.position.y += (targetY - camera.position.y) * 0.04;
      camera.lookAt(0.3, 0, 0);

      renderer.render(scene, camera);
    };
    animate();

    return () => {
      cancelAnimationFrame(animId);
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('resize', handleResize);
      if (renderer.domElement && container.contains(renderer.domElement)) {
        container.removeChild(renderer.domElement);
      }
      renderer.dispose();
    };
  }, []);

  return (
    <div 
      ref={mountRef} 
      className="fixed inset-0 pointer-events-none z-0 overflow-hidden opacity-85" 
    />
  );
};

// --- Verdicts: canonical names match the backend Verdict enum (backend/models/schemas.py) ---
const VERDICT_STYLES = {
  SUPPORTED: { label: 'Supported', badge: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/50', dot: 'bg-emerald-400', chart: '#10B981' },
  SUPPORTED_HISTORICALLY: { label: 'True in the past', badge: 'bg-blue-500/20 text-blue-300 border-blue-500/50', dot: 'bg-blue-400', chart: '#3B82F6' },
  OUTDATED: { label: 'Outdated', badge: 'bg-orange-500/20 text-orange-300 border-orange-500/50', dot: 'bg-orange-400', chart: '#F97316' },
  REFUTED: { label: 'Refuted', badge: 'bg-rose-500/20 text-rose-300 border-rose-500/50', dot: 'bg-rose-400', chart: '#F43F5E' },
  CONFLICTING: { label: 'Conflicting evidence', badge: 'bg-amber-500/20 text-amber-300 border-amber-500/50', dot: 'bg-amber-400', chart: '#F59E0B' },
  INSUFFICIENT_EVIDENCE: { label: 'Not enough evidence', badge: 'bg-zinc-800 text-zinc-300 border-zinc-700', dot: 'bg-zinc-400', chart: '#71717A' },
};
// Spellings used by older versions (still present in saved history rows)
const LEGACY_VERDICTS = {
  'SUPPORTED_CURRENT': 'SUPPORTED', 'VERIFIED': 'SUPPORTED', 'TRUE': 'SUPPORTED',
  'HISTORICAL SUPPORT ONLY': 'SUPPORTED_HISTORICALLY',
  'CONTRADICTED': 'REFUTED', 'FALSE': 'REFUTED',
  'CONFLICTING EVIDENCE': 'CONFLICTING', 'MISLEADING': 'CONFLICTING',
  'INSUFFICIENT EVIDENCE': 'INSUFFICIENT_EVIDENCE', 'AMBIGUOUS_TIME_CONTEXT': 'INSUFFICIENT_EVIDENCE',
  'AMBIGUOUS TIME CONTEXT': 'INSUFFICIENT_EVIDENCE', 'CURRENT STATUS UNVERIFIED': 'INSUFFICIENT_EVIDENCE',
  'AMBIGUOUS': 'INSUFFICIENT_EVIDENCE',
};
const canonicalVerdict = (v) => {
  const k = String(v || '').trim().toUpperCase().replace(/-/g, '_');
  if (VERDICT_STYLES[k]) return k;
  return LEGACY_VERDICTS[k] || LEGACY_VERDICTS[k.replace(/_/g, ' ')] || 'INSUFFICIENT_EVIDENCE';
};
const verdictStyle = (v) => {
  const key = canonicalVerdict(v);
  return { key, ...VERDICT_STYLES[key] };
};
// Percent formatting: unknown values render as an em dash, never as an invented number
const fmtPct = (v) => (v === null || v === undefined || v === '' || isNaN(Number(v))) ? '—' : `${Math.round(Number(v) * 10) / 10}%`;
const toPct = (v) => (v === null || v === undefined || isNaN(Number(v))) ? null : (Number(v) <= 1 ? Number(v) * 100 : Number(v));
const confidenceText = (result) => canonicalVerdict(result.verdict) === 'INSUFFICIENT_EVIDENCE' ? '—' : fmtPct(result.confidence_score);

// Label text is always shown, so colour is never the only signal
const VerdictBadge = ({ verdict, size = 'md' }) => {
  const st = verdictStyle(verdict);
  const sizing = size === 'sm' ? 'px-2.5 py-0.5 text-[10px] rounded-full' : 'px-4 py-2 sm:px-5 sm:py-2.5 text-xs sm:text-sm rounded-2xl';
  return (
    <span className={`${sizing} font-mono font-bold tracking-wider border inline-flex items-center gap-2 ${st.badge}`}>
      <span aria-hidden="true" className={`w-2 h-2 shrink-0 rounded-full ${st.dot}`} />
      <span className="break-words">{st.label}</span>
    </span>
  );
};

// --- Apogee 3D Evidence Card with Explicit Source Attribution ---
const EvidenceChunkCard = ({ chunk }) => {
  const isSupport = chunk.stance === 'SUPPORT' || chunk.stance === 'SUPPORTING';
  const isContradict = chunk.stance === 'CONTRADICT' || chunk.stance === 'CONTRADICTING';

  const sourceName = chunk.source || chunk.document_name || "Verified Knowledge Vault";
  const docName = chunk.document_name || "Document Dossier";
  const sourceUrl = chunk.url || null;

  return (
    <div className={`p-6 rounded-2xl apogee-card space-y-4 relative overflow-hidden group ${
      isSupport 
        ? 'border-emerald-500/35 hover:border-emerald-400/60' 
        : isContradict 
        ? 'border-rose-500/35 hover:border-rose-400/60' 
        : 'border-white/10 hover:border-white/25'
    }`}>
      {/* Subtle Ambient Glow */}
      <div className={`absolute top-0 right-0 w-32 h-32 blur-3xl pointer-events-none opacity-20 transition-opacity group-hover:opacity-40 ${
        isSupport ? 'bg-emerald-500' : isContradict ? 'bg-rose-500' : 'bg-white'
      }`} />

      {/* Stance Header */}
      <div className="flex items-center justify-between gap-3 text-xs font-mono">
        <span className={`px-3 py-1 rounded-full text-[11px] font-bold tracking-wider border flex items-center gap-1.5 ${
          isSupport 
            ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/40' 
            : isContradict 
            ? 'bg-rose-500/10 text-rose-400 border-rose-500/40' 
            : 'bg-zinc-800/80 text-zinc-300 border-zinc-700'
        }`}>
          <span className={`w-1.5 h-1.5 rounded-full ${isSupport ? 'bg-emerald-400' : isContradict ? 'bg-rose-400' : 'bg-zinc-400'}`} />
          {isSupport ? 'CORROBORATING EVIDENCE' : isContradict ? 'REFUTING EVIDENCE' : 'CONTEXTUAL EXCERPT'}
        </span>

        <span className="text-zinc-400 font-mono text-[11px] flex flex-wrap gap-x-3">
          {(isSupport || isContradict) && (
            <span>Stance strength: <strong className="text-white">{fmtPct(toPct(chunk.stance_score))}</strong></span>
          )}
          <span>Source credibility: <strong className="text-white">{fmtPct(toPct(chunk.credibility_score))}</strong></span>
        </span>
      </div>

      {/* Evidence Excerpt */}
      <p className="text-[15px] text-zinc-200 leading-relaxed font-sans font-normal border-l-2 border-white/20 pl-4 py-1">
        "{chunk.text}"
      </p>

      {/* Why the judge classified this passage the way it did */}
      {chunk.rationale && (
        <p className="text-xs text-zinc-400 font-mono leading-relaxed">
          <span className="text-zinc-500">Why: </span>{chunk.rationale}
        </p>
      )}
      {(chunk.publication_date || chunk.retrieval_date) && (
        <p className="text-[11px] text-zinc-500 font-mono">
          {chunk.publication_date && <span>Published/updated: {String(chunk.publication_date).slice(0, 10)} </span>}
          {chunk.retrieval_date && <span>· Retrieved: {String(chunk.retrieval_date).slice(0, 10)}</span>}
        </p>
      )}

      {/* PROMINENT SOURCE ATTRIBUTION BLOCK */}
      <div className="pt-3 border-t border-white/10 flex flex-wrap items-center justify-between gap-3 text-xs font-mono">
        <div className="flex items-center gap-2 text-zinc-300">
          <span className="text-zinc-500">Source:</span>
          <strong className="text-white font-semibold flex items-center gap-1.5">
            🏛️ {sourceName}
          </strong>
        </div>

        <div className="flex items-center gap-2">
          <span className="px-2.5 py-0.5 rounded-full bg-white/5 border border-white/10 text-[10px] text-zinc-400">
            {chunk.source_type || 'Unclassified source'}
          </span>

          {sourceUrl ? (
            <a 
              href={sourceUrl} 
              target="_blank" 
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 px-3 py-1 rounded-full bg-white text-black font-semibold hover:bg-zinc-200 transition-colors text-[11px]"
            >
              <span>Visit Source</span>
              <Icon name="external" className="w-3 h-3" />
            </a>
          ) : (
            <span className="text-zinc-500 text-[11px] truncate max-w-[200px]" title={docName}>
              📄 {docName}
            </span>
          )}
        </div>
      </div>
    </div>
  );
};

// --- Wrong-verdict report form (POST /api/feedback) ---
const REPORT_COMMENT_MAX = 1000;

const ReportModal = ({ result, sending, onCancel, onSubmit }) => {
  const [suggested, setSuggested] = useState('');
  const [comment, setComment] = useState('');
  const firstField = useRef(null);

  useEffect(() => {
    if (firstField.current) firstField.current.focus();
    const onKey = (e) => { if (e.key === 'Escape') onCancel(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm" onClick={onCancel}>
      <form
        role="dialog"
        aria-modal="true"
        aria-labelledby="report-title"
        onClick={(e) => e.stopPropagation()}
        onSubmit={(e) => { e.preventDefault(); onSubmit({ suggested_verdict: suggested || null, comment: comment.trim() }); }}
        className="w-full max-w-lg p-6 rounded-3xl apogee-card space-y-4 font-mono text-sm"
      >
        <h3 id="report-title" className="text-base font-bold text-white font-sans">Report wrong verdict</h3>
        <p className="text-xs text-zinc-400">
          Claim: <span className="text-zinc-200">"{result.claim}"</span><br />
          Verdict given: <span className="text-zinc-200">{verdictStyle(result.verdict).label}</span>
        </p>
        <label className="block space-y-1">
          <span className="text-xs text-zinc-400">What should the verdict be?</span>
          <select
            ref={firstField}
            value={suggested}
            onChange={(e) => setSuggested(e.target.value)}
            className="w-full bg-black/60 border border-white/20 rounded-xl px-3 py-2 text-white focus:outline-none focus:border-white/50"
          >
            <option value="">Not sure</option>
            {Object.keys(VERDICT_STYLES).map(v => (
              <option key={v} value={v}>{VERDICT_STYLES[v].label}</option>
            ))}
          </select>
        </label>
        <label className="block space-y-1">
          <span className="text-xs text-zinc-400">What is wrong? (optional)</span>
          <textarea
            rows={4}
            maxLength={REPORT_COMMENT_MAX}
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="e.g. the cited source is about a different person"
            className="w-full bg-black/60 border border-white/20 rounded-xl px-3 py-2 text-white placeholder-zinc-600 resize-none focus:outline-none focus:border-white/50 font-sans"
          />
          <span className="block text-right text-[10px] text-zinc-500">{comment.length}/{REPORT_COMMENT_MAX}</span>
        </label>
        <p className="text-[11px] text-zinc-500">Reports are reviewed by the maintainers. Don't include personal information.</p>
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onCancel} className="px-4 py-2 rounded-full border border-white/20 text-zinc-300 hover:text-white">Cancel</button>
          <button type="submit" disabled={sending} className="px-4 py-2 rounded-full bg-white text-black font-semibold hover:bg-zinc-200 disabled:opacity-50">
            {sending ? 'Sending…' : 'Send report'}
          </button>
        </div>
      </form>
    </div>
  );
};

// --- Main Application ---
export default function App() {
  const [activeTab, setActiveTab] = useState('verify');
  const [inputMode, setInputMode] = useState('text');
  const [claimInput, setClaimInput] = useState('');
  const [urlInput, setUrlInput] = useState('');
  const [forwardInput, setForwardInput] = useState('');
  
  const [verifying, setVerifying] = useState(false);
  const [extractingUrl, setExtractingUrl] = useState(false);
  const [cleaningForward, setCleaningForward] = useState(false);
  
  const [currentResult, setCurrentResult] = useState(null);
  const [health, setHealth] = useState(null);
  const [documents, setDocuments] = useState([]);
  const [history, setHistory] = useState([]);
  const [analytics, setAnalytics] = useState(null);
  const [newsStatus, setNewsStatus] = useState(null);
  const [toast, setToast] = useState(null);
  const [vaultTab, setVaultTab] = useState('news');
  const [newsSearchQuery, setNewsSearchQuery] = useState('');
  const [isSyncingNews, setIsSyncingNews] = useState(false);
  const [reportFor, setReportFor] = useState(null);
  const [sendingReport, setSendingReport] = useState(false);

  const chartRef = useRef(null);
  const chartInstance = useRef(null);

  const showToast = (msg, type = 'info') => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 4000);
  };

  useEffect(() => {
    loadHealth();
    loadDocuments();
    loadHistory();
    loadAnalytics();
    loadNewsStatus();
  }, []);

  const loadHealth = async () => {
    try {
      const res = await api(`/api/health?t=${Date.now()}`);
      const data = await res.json();
      setHealth(data);
    } catch (e) {
      console.error(e);
    }
  };

  const handleManualSyncNews = async () => {
    setIsSyncingNews(true);
    try {
      const res = await adminFetch('/api/news/sync', { method: 'POST' });
      if (!res.ok) throw new Error(await errorMessage(res, 'Failed to sync live news'));
      showToast('Live news synced successfully!', 'success');
      await loadNewsStatus();
    } catch (e) {
      showToast(e.message, 'error');
    } finally {
      setIsSyncingNews(false);
    }
  };

  const loadDocuments = async () => {
    try {
      const res = await api(`/api/documents?t=${Date.now()}`);
      const data = await res.json();
      if (Array.isArray(data)) setDocuments(data);
    } catch (e) {
      console.error(e);
    }
  };

  const loadHistory = async () => {
    try {
      const res = await api(`/api/history?limit=50&t=${Date.now()}`);
      const data = await res.json();
      if (Array.isArray(data)) setHistory(data);
    } catch (e) {
      console.error(e);
    }
  };

  const loadAnalytics = async () => {
    try {
      const res = await api(`/api/analytics?t=${Date.now()}`);
      const data = await res.json();
      setAnalytics(data);
    } catch (e) {
      console.error(e);
    }
  };

  const loadNewsStatus = async () => {
    try {
      const res = await api(`/api/news/status?t=${Date.now()}`);
      const data = await res.json();
      setNewsStatus(data);
    } catch (e) {
      console.error(e);
    }
  };

  const handleVerifyNewsArticle = (claimText) => {
    setClaimInput(claimText);
    setInputMode('text');
    setActiveTab('verify');
    handleVerify(claimText);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const handleVerify = async (textToVerify) => {
    const text = (textToVerify || claimInput).trim();
    if (!text) {
      showToast('Please enter a claim or statement to verify.', 'error');
      return;
    }

    setVerifying(true);
    setCurrentResult(null);

    try {
      const res = await postJson('/api/verify', { claim: text });
      if (!res.ok) throw new Error(await errorMessage(res, 'Verification failed'));

      const data = await res.json();
      setCurrentResult(data);
      
      // Instant sync into this browser's history without waiting for the reload below
      setHistory(prev => [data, ...prev.filter(h => h.id !== data.id)]);

      // Instant sync into analytics
      setAnalytics(prev => {
        if (!prev) return prev;
        const v = canonicalVerdict(data.verdict);
        const total = prev.total_claims_verified || 0;
        const curConf = prev.average_confidence || 0;
        
        return {
          ...prev,
          total_claims_verified: total + 1,
          verdict_counts: {
            ...prev.verdict_counts,
            [v]: (prev.verdict_counts?.[v] || 0) + 1
          },
          average_confidence: ((curConf * total) + data.confidence_score) / (total + 1)
        };
      });

      loadHealth();
      loadHistory();
      loadAnalytics();
      showToast(`Verdict: ${verdictStyle(data.verdict).label}`, 'success');
    } catch (err) {
      showToast(err.message, 'error');
    } finally {
      setVerifying(false);
    }
  };

  // "Report wrong verdict": opens a small form; submitted reports go to POST /api/feedback
  const handleReportWrongVerdict = (result) => {
    setReportFor(result);
  };

  const submitReport = async ({ suggested_verdict, comment }) => {
    if (!reportFor) return;
    setSendingReport(true);
    try {
      const res = await postJson('/api/feedback', {
        verification_id: reportFor.id,
        claim: reportFor.claim,
        verdict: reportFor.verdict,
        suggested_verdict: suggested_verdict || null,
        comment: comment || ''
      });
      if (res.status !== 201 && !res.ok) throw new Error(await errorMessage(res, 'Could not send the report'));
      setReportFor(null);
      showToast('Thanks — report received', 'success');
    } catch (err) {
      showToast(err.message, 'error');
    } finally {
      setSendingReport(false);
    }
  };

  const handleClearHistory = async () => {
    if (!window.confirm('Delete all checks stored for this browser? This cannot be undone.')) return;
    try {
      const res = await api('/api/history', { method: 'DELETE' });
      if (!res.ok) throw new Error(await errorMessage(res, 'Could not clear history'));
      setHistory([]);
      showToast('Your history was cleared.', 'success');
      loadHistory();
      loadAnalytics();
    } catch (err) {
      showToast(err.message, 'error');
    }
  };

  const handleExtractUrl = async () => {
    const u = urlInput.trim();
    if (!u) return showToast('Please enter a URL.', 'error');
    setExtractingUrl(true);
    try {
      const res = await postJson('/api/news/extract-url', { url: u });
      if (!res.ok) throw new Error(await errorMessage(res, 'Could not extract headline'));
      const data = await res.json();
      if (data.status === 'success' && data.extracted_claim) {
        setClaimInput(data.extracted_claim);
        setInputMode('text');
        showToast('Headline extracted! Ready to verify.', 'success');
      } else {
        showToast(data.message || 'Could not extract headline.', 'error');
      }
    } catch (err) {
      showToast(err.message, 'error');
    } finally {
      setExtractingUrl(false);
    }
  };

  const handleCleanForward = async () => {
    const f = forwardInput.trim();
    if (!f) return showToast('Please paste a forward message.', 'error');
    setCleaningForward(true);
    try {
      const res = await postJson('/api/news/clean-forward', { text: f });
      if (!res.ok) throw new Error(await errorMessage(res, 'Could not clean the message'));
      const data = await res.json();
      if (data.cleaned_claim) {
        setClaimInput(data.cleaned_claim);
        setInputMode('text');
        showToast('Viral message cleaned! Ready to verify.', 'success');
      }
    } catch (err) {
      showToast(err.message, 'error');
    } finally {
      setCleaningForward(false);
    }
  };

  const handleFileUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const formData = new FormData();
    formData.append('file', file);
    showToast('Uploading & vectorizing document...', 'info');
    try {
      const res = await adminFetch('/api/upload', { method: 'POST', body: formData });
      if (!res.ok) throw new Error(await errorMessage(res, 'Upload failed'));
      const data = await res.json();
      showToast(`Indexed: ${data.filename} (${data.chunks_indexed} chunks)`, 'success');
      loadDocuments();
      loadHealth();
    } catch (err) {
      showToast(err.message, 'error');
    }
  };

  const handleDeleteDoc = async (id, title) => {
    if (!confirm(`Delete ${title || 'document'} and its chunks?`)) return;
    try {
      const res = await adminFetch(`/api/documents/${id}`, { method: 'DELETE' });
      if (!res.ok) throw new Error(await errorMessage(res, 'Delete failed'));
      showToast('Document deleted.', 'success');
      loadDocuments();
      loadHealth();
    } catch (err) {
      showToast(err.message, 'error');
    }
  };

  // Chart.js initialization for Analytics tab
  useEffect(() => {
    if (activeTab === 'analytics' && analytics && chartRef.current) {
      if (chartInstance.current) chartInstance.current.destroy();
      const ctx = chartRef.current.getContext('2d');
      // Fold any legacy keys into the six canonical buckets
      const counts = {};
      Object.keys(VERDICT_STYLES).forEach(k => { counts[k] = 0; });
      Object.entries(analytics.verdict_counts || {}).forEach(([k, n]) => { counts[canonicalVerdict(k)] += Number(n) || 0; });
      const keys = Object.keys(VERDICT_STYLES);
      chartInstance.current = new Chart(ctx, {
        type: 'doughnut',
        data: {
          labels: keys.map(k => VERDICT_STYLES[k].label),
          datasets: [{
            data: keys.map(k => counts[k]),
            backgroundColor: keys.map(k => VERDICT_STYLES[k].chart),
            borderColor: '#030303',
            borderWidth: 3
          }]
        },
        options: {
          responsive: true,
          plugins: {
            legend: { position: 'bottom', labels: { color: '#D4D4D8', font: { family: 'JetBrains Mono' } } }
          }
        }
      });
    }
  }, [activeTab, analytics]);

  // Benchmark quick claims
  const benchmarkClaims = [
    "Is Narendra Modi PM of India",
    "Donald Trump is the Prime Minister of India.",
    "Renewable energy accounts for over 30 percent of global electricity.",
    "Antibiotics can cure viral infections like the flu.",
    "The moon is made of green cheese."
  ];

  return (
    <div className="flex flex-col min-h-screen font-sans relative bg-[#030303]">
      
      {/* MONOCHROME 3D EARTH ORBIT BACKGROUND (THREE.JS) */}
      <Earth3DCanvas />

      {/* Left-side Dark Vignette Scrim so text is 100% readable over space */}
      <div className="fixed inset-0 pointer-events-none z-0 hero-scrim" />

      {/* Wrong-verdict report form */}
      {reportFor && (
        <ReportModal
          result={reportFor}
          sending={sendingReport}
          onCancel={() => setReportFor(null)}
          onSubmit={submitReport}
        />
      )}

      {/* Toast */}
      {toast && (
        <div role="status" aria-live="polite" className="fixed bottom-6 right-6 left-6 sm:left-auto z-50 px-5 py-3 rounded-2xl sm:rounded-full border border-white/20 bg-black/90 text-white shadow-2xl flex items-center gap-3 backdrop-blur-xl text-xs font-mono">
          <span className={`w-2 h-2 rounded-full ${toast.type === 'error' ? 'bg-rose-500' : 'bg-emerald-400'}`} />
          <span>{toast.msg}</span>
        </div>
      )}

      {/* Top Marquee Radar Bar */}
      <div className="relative z-10 border-b border-white/10 bg-black/85 backdrop-blur-md text-[11px] font-mono py-2 px-4 text-zinc-400 overflow-hidden">
        <div className="max-w-7xl mx-auto flex items-center justify-between gap-4">
          <div className="flex items-center gap-2 shrink-0">
            <span className="w-2 h-2 rounded-full bg-white animate-pulse" />
            <span className="font-semibold text-white tracking-widest text-[10px]">RADAR 3D</span>
            <span className="text-zinc-600">|</span>
          </div>
          <div className="overflow-hidden flex-1">
            <div className="ticker-scroll text-zinc-400">
              <span>✦ EVIDENCE FROM THE LOCAL KNOWLEDGE VAULT + LIVE WIKIPEDIA ✦ PASSAGES RANKED BY AN MS-MARCO CROSS-ENCODER ✦ JUDGED BY A CLOUD LLM IF CONFIGURED, OTHERWISE AN OFFLINE DeBERTa-v3 NLI MODEL ✦ EVERY VERDICT LISTS ITS SOURCES ✦ </span>
              <span>✦ EVIDENCE FROM THE LOCAL KNOWLEDGE VAULT + LIVE WIKIPEDIA ✦ PASSAGES RANKED BY AN MS-MARCO CROSS-ENCODER ✦ JUDGED BY A CLOUD LLM IF CONFIGURED, OTHERWISE AN OFFLINE DeBERTa-v3 NLI MODEL ✦ EVERY VERDICT LISTS ITS SOURCES ✦ </span>
            </div>
          </div>
          <div className="hidden sm:flex items-center gap-2 shrink-0 text-xs">
            <span>Vault:</span>
            <strong className="text-white font-mono">{health ? health.indexed_chunks : '—'} Chunks</strong>
          </div>
        </div>
      </div>

      {/* Clean Header */}
      <header className="relative z-30 sticky top-0 w-full border-b border-white/10 bg-black/75 backdrop-blur-xl">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 min-h-[4rem] py-3 flex flex-wrap items-center justify-between gap-4">
          
          {/* Brand */}
          <div 
            onClick={() => setActiveTab('verify')}
            className="flex items-center gap-3 cursor-pointer group"
          >
            <div className="w-8 h-8 rounded-xl bg-white text-black flex items-center justify-center font-black shadow-[0_0_20px_rgba(255,255,255,0.4)] group-hover:scale-105 transition-transform">
              <Icon name="cube" className="w-4 h-4 text-black" />
            </div>
            <div className="flex items-center gap-2">
              <span className="font-bold text-xl tracking-tight text-white font-sans">
                Truth<span className="text-zinc-400">Lens</span>
              </span>
              <span className="text-[10px] font-mono font-semibold px-2 py-0.5 rounded-full border border-white/20 bg-white/5 text-zinc-300">
                V.o.2
              </span>
            </div>
          </div>

          {/* Navigation Tabs */}
          <nav className="flex items-center gap-1 border border-white/10 bg-white/[0.04] p-1 rounded-full text-xs font-mono">
            {[
              { id: 'verify', label: 'Verify', icon: 'search' },
              { id: 'knowledge', label: 'Knowledge Vault', icon: 'database' },
              { id: 'history', label: 'History', icon: 'history' },
              { id: 'analytics', label: 'Analytics', icon: 'chart' }
            ].map(tab => (
              <button
                key={tab.id}
                aria-label={tab.label}
                aria-current={activeTab === tab.id ? 'page' : undefined}
                onClick={() => setActiveTab(tab.id)}
                className={`px-3 py-1.5 sm:px-4 sm:py-1.5 rounded-full transition-all flex items-center gap-1.5 ${
                  activeTab === tab.id 
                    ? 'bg-white text-black font-semibold shadow-md' 
                    : 'text-zinc-400 hover:text-white hover:bg-white/5'
                }`}
              >
                <Icon name={tab.icon} className="w-3.5 h-3.5" />
                <span className="hidden sm:inline">{tab.label}</span>
              </button>
            ))}
          </nav>

        </div>
      </header>

      {/* Main Content Area */}
      <main className="relative z-10 flex-1 max-w-6xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-10">
        
        {/* ======================================================== */}
        {/* TAB 1: VERIFY (CLEAN BLACK & WHITE HERO + 3D MONO EARTH) */}
        {/* ======================================================== */}
        {activeTab === 'verify' && (
          <div className="space-y-10">
            
            {/* Hero Section (Left-aligned or centered with high-contrast text) */}
            <div className="text-center max-w-3xl mx-auto space-y-3 pt-4">
              <div className="inline-flex items-center gap-2 px-3.5 py-1 rounded-full border border-white/20 bg-black/60 text-zinc-300 text-xs font-mono backdrop-blur-md">
                <span className="w-1.5 h-1.5 rounded-full bg-white" />
                <span>Retrieval-augmented, evidence-first fact checking</span>
              </div>
              <h1 className="text-4xl sm:text-5xl font-extrabold tracking-tight text-white leading-tight drop-shadow-lg">
                Verify claims with verifiable, source-grounded evidence.
              </h1>
              <p className="text-zinc-300 text-sm sm:text-base leading-relaxed drop-shadow-md">
                Every verdict shows the passages it is based on, which sources support or contradict the claim, and how strong that evidence is. Verdicts are AI-assisted and can be wrong, so check the sources.
              </p>
            </div>

            {/* Omnibox 3D Container */}
            <div className="max-w-4xl mx-auto apogee-card-3d">
              <div className="omnibox-3d rounded-3xl p-6 sm:p-8">
                
                {/* Input Mode Selector */}
                <div className="flex items-center gap-2 mb-4 border-b border-white/10 pb-4 text-xs font-mono">
                  {[
                    { id: 'text', label: 'Claim / Statement' },
                    { id: 'url', label: 'News Article URL' },
                    { id: 'forward', label: 'Viral WhatsApp Message' }
                  ].map(mode => (
                    <button
                      key={mode.id}
                      onClick={() => setInputMode(mode.id)}
                      className={`px-3.5 py-1.5 rounded-full transition-all ${
                        inputMode === mode.id 
                          ? 'bg-white text-black font-semibold' 
                          : 'text-zinc-400 hover:text-white'
                      }`}
                    >
                      {mode.label}
                    </button>
                  ))}
                </div>

                {/* Mode: TEXT */}
                {inputMode === 'text' && (
                  <div className="space-y-4">
                    <textarea
                      rows={3}
                      value={claimInput}
                      onChange={(e) => setClaimInput(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                          handleVerify();
                        }
                      }}
                      aria-label="Claim to verify"
                      placeholder="What claim shall we verify today? (e.g., Is Narendra Modi PM of India)"
                      className="w-full bg-transparent text-lg text-white placeholder-zinc-500 resize-none focus:outline-none font-sans"
                    />
                    <div className="flex items-center justify-between pt-2 border-t border-white/5">
                      <span className="text-xs text-zinc-500 font-mono hidden sm:inline">
                        Press <kbd className="px-1.5 py-0.5 rounded bg-white/10 text-zinc-300">Ctrl</kbd> + <kbd className="px-1.5 py-0.5 rounded bg-white/10 text-zinc-300">Enter</kbd> to verify
                      </span>
                      <button
                        onClick={() => handleVerify()}
                        disabled={verifying || !claimInput.trim()}
                        className="ml-auto px-6 py-2.5 rounded-full bg-white text-black font-bold text-sm hover:bg-zinc-200 transition-all disabled:opacity-40 disabled:cursor-not-allowed shadow-[0_0_20px_rgba(255,255,255,0.2)]"
                      >
                        {verifying ? 'Auditing Claim...' : 'Verify Claim →'}
                      </button>
                    </div>
                    <p className="text-[11px] text-zinc-500 font-mono">Your checks are stored for 30 days, visible only in this browser. Don't paste personal information.</p>
                  </div>
                )}

                {/* Mode: URL */}
                {inputMode === 'url' && (
                  <div className="space-y-4">
                    <input
                      type="url"
                      value={urlInput}
                      onChange={(e) => setUrlInput(e.target.value)}
                      aria-label="News article URL"
                      placeholder="Paste news article link (e.g., https://reuters.com/world/...)"
                      className="w-full bg-transparent text-base text-white placeholder-zinc-500 focus:outline-none font-mono py-2"
                    />
                    <div className="flex justify-end pt-2 border-t border-white/5">
                      <button
                        onClick={handleExtractUrl}
                        disabled={extractingUrl || !urlInput.trim()}
                        className="px-6 py-2.5 rounded-full bg-white text-black font-bold text-sm hover:bg-zinc-200 transition-all disabled:opacity-40"
                      >
                        {extractingUrl ? 'Extracting Headline...' : 'Extract & Inspect Claim →'}
                      </button>
                    </div>
                  </div>
                )}

                {/* Mode: FORWARD */}
                {inputMode === 'forward' && (
                  <div className="space-y-4">
                    <textarea
                      rows={4}
                      value={forwardInput}
                      onChange={(e) => setForwardInput(e.target.value)}
                      aria-label="Forwarded message text"
                      placeholder="Paste forwarded viral WhatsApp or Telegram message..."
                      className="w-full bg-transparent text-sm text-white placeholder-zinc-500 resize-none focus:outline-none font-sans"
                    />
                    <div className="flex justify-end pt-2 border-t border-white/5">
                      <button
                        onClick={handleCleanForward}
                        disabled={cleaningForward || !forwardInput.trim()}
                        className="px-6 py-2.5 rounded-full bg-white text-black font-bold text-sm hover:bg-zinc-200 transition-all disabled:opacity-40"
                      >
                        {cleaningForward ? 'Stripping Boilerplate...' : 'Clean & Extract Claim →'}
                      </button>
                    </div>
                  </div>
                )}

              </div>

              {/* Benchmark Suggestion Chips */}
              <div className="flex flex-wrap items-center gap-2 mt-4 px-2">
                <span className="text-xs font-mono text-zinc-500">Quick benchmarks:</span>
                {benchmarkClaims.map((b, i) => (
                  <button
                    key={i}
                    onClick={() => {
                      setClaimInput(b);
                      setInputMode('text');
                      handleVerify(b);
                    }}
                    className="px-3 py-1 rounded-full border border-white/10 bg-black/60 text-xs text-zinc-300 hover:text-white hover:border-white/30 transition-all font-mono backdrop-blur-md"
                  >
                    "{b}"
                  </button>
                ))}
              </div>
            </div>

            {/* Progress: one honest state (the backend does not stream stage updates) */}
            {verifying && (
              <div className="max-w-4xl mx-auto p-6 rounded-2xl apogee-card space-y-4" role="status" aria-live="polite">
                <div className="flex items-center gap-3 text-xs font-mono text-zinc-300">
                  <span aria-hidden="true" className="w-4 h-4 rounded-full border-2 border-white/30 border-t-white animate-spin" />
                  <span>Retrieving evidence and judging… this can take several seconds.</span>
                </div>
                <div className="h-1.5 w-full bg-white/10 rounded-full overflow-hidden">
                  <div className="h-full w-1/3 bg-white/70 rounded-full animate-pulse" />
                </div>
              </div>
            )}

            {/* VERDICT & EVIDENCE DISPLAY */}
            {currentResult && !verifying && (
              <div className="max-w-4xl mx-auto space-y-8 pt-4">
                
                {/* Main Verdict Card */}
                <div className="p-8 rounded-3xl apogee-card space-y-6 relative overflow-hidden">
                  <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
                    <div className="space-y-1">
                      <span className="text-xs font-mono uppercase tracking-widest text-zinc-400">Verifying Assertion</span>
                      <h2 className="text-2xl font-bold text-white font-sans">
                        "{currentResult.claim}"
                      </h2>
                    </div>

                    {/* Verdict badge (label text + colour) */}
                    <div className="flex flex-col items-start sm:items-end gap-2">
                      <VerdictBadge verdict={currentResult.verdict} />
                      {currentResult.cached && (
                        <span className="px-2.5 py-0.5 rounded-full border border-sky-400/40 bg-sky-500/10 text-sky-300 text-[10px] font-mono tracking-wider"
                              title="This exact claim was checked recently; the stored result is shown instead of re-running the check.">
                          Cached result
                        </span>
                      )}
                    </div>
                  </div>

                  {/* 4.7: every verdict is labelled as AI-assisted, with a way to flag it */}
                  <div className="flex flex-wrap items-center justify-between gap-3 text-xs font-mono">
                    <span className="text-amber-300/90">AI-assisted verdict — check the sources below before sharing.</span>
                    <button
                      onClick={() => handleReportWrongVerdict(currentResult)}
                      className="px-3 py-1 rounded-full border border-white/20 text-zinc-300 hover:text-white hover:border-white/40 transition-colors"
                    >
                      Report wrong verdict
                    </button>
                  </div>

                  {currentResult.similar_claim_found && (
                    <div className="p-3 rounded-xl bg-white/[0.03] border border-white/10 text-xs font-mono text-zinc-400">
                      A similar claim was checked before: "{currentResult.similar_claim_found.claim}" → {verdictStyle(currentResult.similar_claim_found.verdict).label} ({fmtPct(currentResult.similar_claim_found.similarity_score)} word overlap)
                    </div>
                  )}

                  {/* Stat Metrics Grid: all values come from the API; unknown shows a dash */}
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 sm:gap-4 pt-4 border-t border-white/10 font-mono text-center">
                    <div className="p-3 sm:p-4 rounded-xl bg-white/[0.03] border border-white/10">
                      <div className="text-xs text-zinc-400">Confidence</div>
                      <div className="text-xl sm:text-2xl font-bold text-white mt-1">{confidenceText(currentResult)}</div>
                    </div>
                    <div className="p-3 sm:p-4 rounded-xl bg-white/[0.03] border border-white/10">
                      <div className="text-xs text-zinc-400">Source agreement</div>
                      <div className="text-xl sm:text-2xl font-bold text-white mt-1">{canonicalVerdict(currentResult.verdict) === 'INSUFFICIENT_EVIDENCE' ? '—' : fmtPct(currentResult.evidence_agreement_score)}</div>
                    </div>
                    <div className="p-3 sm:p-4 rounded-xl bg-white/[0.03] border border-white/10">
                      <div className="text-xs text-zinc-400">Avg. source credibility</div>
                      <div className="text-xl sm:text-2xl font-bold text-white mt-1">{fmtPct(currentResult.source_credibility_score)}</div>
                    </div>
                    <div className="p-3 sm:p-4 rounded-xl bg-white/[0.03] border border-white/10">
                      <div className="text-xs text-zinc-400">Evidence strength</div>
                      <div className="text-xl sm:text-2xl font-bold text-white mt-1">{currentResult.verification_strength || '—'}</div>
                    </div>
                  </div>
                  <div className="text-[11px] font-mono text-zinc-500 flex flex-wrap gap-x-4 gap-y-1">
                    {currentResult.agreement_analysis && <span>{currentResult.agreement_analysis}</span>}
                    <span>Judged by: {currentResult.llm_provider_used || '—'}</span>
                    {currentResult.claim_type && <span>Claim type: {currentResult.claim_type.replace(/_/g, ' ').toLowerCase()}</span>}
                  </div>

                  {/* Executive Explanation */}
                  <div className="p-5 rounded-2xl bg-white/[0.03] border border-white/10 space-y-2">
                    <div className="text-xs font-mono text-zinc-400 uppercase tracking-wider">Why this verdict</div>
                    <p className="text-base text-zinc-200 leading-relaxed font-sans">
                      {currentResult.explanation}
                    </p>
                    {currentResult.key_reasoning && (
                      <ul className="text-xs text-zinc-400 font-mono pt-2 border-t border-white/5 space-y-1 list-disc pl-4">
                        {String(currentResult.key_reasoning).split(/\s\|\s|\n+/).filter(Boolean).map((line, i) => (
                          <li key={i}>{line.replace(/^[-•*]\s*/, '')}</li>
                        ))}
                      </ul>
                    )}
                  </div>

                  {/* Entity & time checks the backend ran */}
                  {(currentResult.entity_analysis || currentResult.temporal_analysis) && (
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs font-mono">
                      <div className="p-4 rounded-xl bg-white/[0.03] border border-white/10 space-y-1">
                        <div className="text-zinc-400 uppercase tracking-wider mb-1">Entity check</div>
                        <div><span className="text-zinc-500">Subject:</span> <span className="text-zinc-200">{currentResult.entity_analysis?.subject || '—'}</span></div>
                        {currentResult.entity_analysis?.role && <div><span className="text-zinc-500">Role:</span> <span className="text-zinc-200">{currentResult.entity_analysis.role}</span></div>}
                        <div><span className="text-zinc-500">Evidence names the subject:</span> <span className="text-zinc-200">{currentResult.entity_analysis?.entity_match || currentResult.entity_match || '—'}</span></div>
                      </div>
                      <div className="p-4 rounded-xl bg-white/[0.03] border border-white/10 space-y-1">
                        <div className="text-zinc-400 uppercase tracking-wider mb-1">Time check</div>
                        <div><span className="text-zinc-500">Time in claim:</span> <span className="text-zinc-200">{currentResult.temporal_analysis?.time_expression || 'none stated'}</span></div>
                        <div><span className="text-zinc-500">Needs current evidence:</span> <span className="text-zinc-200">{currentResult.temporal_analysis?.requires_current_evidence ? 'yes' : 'no'}</span></div>
                        <div><span className="text-zinc-500">About the past:</span> <span className="text-zinc-200">{currentResult.temporal_analysis?.historical_claim ? 'yes' : 'no'}</span></div>
                        <div><span className="text-zinc-500">Temporal match:</span> <span className="text-zinc-200">{currentResult.temporal_analysis?.temporal_match || currentResult.temporal_match || '—'}</span></div>
                      </div>
                    </div>
                  )}

                  {/* Limitations the backend reported for this verdict */}
                  {currentResult.limitations && currentResult.limitations.length > 0 && (
                    <div className="p-4 rounded-xl border border-amber-500/20 bg-amber-500/[0.04] text-xs font-mono space-y-1">
                      <div className="text-amber-300/90 uppercase tracking-wider">Limitations</div>
                      <ul className="list-disc pl-4 text-zinc-300 space-y-1">
                        {currentResult.limitations.map((l, i) => <li key={i}>{l}</li>)}
                      </ul>
                    </div>
                  )}

                  {/* PROMINENT VERIFIED SOURCES BANNER */}
                  {currentResult.retrieved_sources && currentResult.retrieved_sources.length > 0 && (
                    <div className="pt-2 border-t border-white/10 space-y-3">
                      <div className="text-xs font-mono text-zinc-400 uppercase tracking-wider flex items-center justify-between">
                        <span>Sources retrieved ({currentResult.retrieved_sources.length})</span>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {currentResult.retrieved_sources.map((src, idx) => {
                          const Content = () => (
                            <>
                              <span className="text-[10px] tracking-widest text-emerald-400 uppercase mr-1 border-r border-white/20 pr-1.5">{src.source_type || 'News'}</span>
                              <span>{src.source || src.document_name}</span>
                              <span className="text-zinc-500 font-sans ml-1 text-[10px]">({fmtPct(src.credibility_score)} credibility)</span>
                              {src.url && <span className="ml-1 opacity-50 group-hover:opacity-100 transition-opacity">↗</span>}
                            </>
                          );
                          
                          const baseClasses = "group px-3 py-1.5 rounded border bg-zinc-900/50 text-xs font-mono text-zinc-200 flex items-center transition-all duration-200";
                          
                          if (src.url) {
                            return (
                              <a 
                                key={idx}
                                href={src.url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className={`${baseClasses} border-emerald-500/20 hover:border-emerald-500/50 hover:bg-emerald-500/5`}
                              >
                                <Content />
                              </a>
                            );
                          }
                          
                          return (
                            <span key={idx} className={`${baseClasses} border-white/10`}>
                              <Content />
                            </span>
                          );
                        })}
                      </div>
                    </div>
                  )}

                </div>

                {/* How to check this yourself (verification_recommendation) */}
                {currentResult.verification_recommendation && (
                  <div className="p-6 rounded-3xl apogee-card space-y-3 text-sm">
                    <h3 className="text-sm font-mono uppercase tracking-wider text-zinc-300">How to check this yourself</h3>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs font-mono">
                      <div><span className="text-zinc-500">Best source type:</span> <span className="text-zinc-200">{currentResult.verification_recommendation.source_type}</span></div>
                      <div><span className="text-zinc-500">Where to look:</span> <span className="text-zinc-200">{currentResult.verification_recommendation.target_domain}</span></div>
                    </div>
                    <p className="text-zinc-300 font-sans">{currentResult.verification_recommendation.what_to_check}</p>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs font-sans">
                      <div className="p-3 rounded-xl border border-emerald-500/20 bg-emerald-500/[0.04]"><span className="font-mono text-emerald-300">Confirms it: </span><span className="text-zinc-300">{currentResult.verification_recommendation.what_confirms}</span></div>
                      <div className="p-3 rounded-xl border border-rose-500/20 bg-rose-500/[0.04]"><span className="font-mono text-rose-300">Refutes it: </span><span className="text-zinc-300">{currentResult.verification_recommendation.what_refutes}</span></div>
                    </div>
                    {currentResult.verification_recommendation.queries && currentResult.verification_recommendation.queries.length > 0 && (
                      <div className="flex flex-wrap items-center gap-2 text-xs font-mono">
                        <span className="text-zinc-500">Try searching:</span>
                        {currentResult.verification_recommendation.queries.map((q, i) => (
                          <a key={i} href={`https://www.google.com/search?q=${encodeURIComponent(q)}`} target="_blank" rel="noopener noreferrer"
                             className="px-2.5 py-1 rounded-full border border-white/15 text-zinc-300 hover:text-white hover:border-white/40">
                            {q} ↗
                          </a>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {/* Corroborating Evidence Cards */}
                {currentResult.supporting_evidence && currentResult.supporting_evidence.length > 0 && (
                  <div className="space-y-4">
                    <h3 className="text-sm font-mono uppercase tracking-wider text-emerald-400 flex items-center gap-2">
                      <span>✓ Corroborating Evidence ({currentResult.supporting_evidence.length})</span>
                    </h3>
                    <div className="space-y-4">
                      {currentResult.supporting_evidence.map((chunk, i) => (
                        <EvidenceChunkCard key={i} chunk={chunk} />
                      ))}
                    </div>
                  </div>
                )}

                {/* Refuting Evidence Cards */}
                {currentResult.contradicting_evidence && currentResult.contradicting_evidence.length > 0 && (
                  <div className="space-y-4">
                    <h3 className="text-sm font-mono uppercase tracking-wider text-rose-400 flex items-center gap-2">
                      <span>✗ Refuting Evidence ({currentResult.contradicting_evidence.length})</span>
                    </h3>
                    <div className="space-y-4">
                      {currentResult.contradicting_evidence.map((chunk, i) => (
                        <EvidenceChunkCard key={i} chunk={chunk} />
                      ))}
                    </div>
                  </div>
                )}

                {/* Neutral Excerpts */}
                {currentResult.neutral_evidence && currentResult.neutral_evidence.length > 0 && (
                  <div className="space-y-4">
                    <h3 className="text-sm font-mono uppercase tracking-wider text-zinc-400 flex items-center gap-2">
                      <span>ℹ Contextual Excerpts ({currentResult.neutral_evidence.length})</span>
                    </h3>
                    <div className="space-y-4">
                      {currentResult.neutral_evidence.map((chunk, i) => (
                        <EvidenceChunkCard key={i} chunk={chunk} />
                      ))}
                    </div>
                  </div>
                )}

              </div>
            )}

          </div>
        )}

        {/* ======================================================== */}
        {/* TAB 2: KNOWLEDGE VAULT                                   */}
        {/* ======================================================== */}
        {activeTab === 'knowledge' && (
          <div className="space-y-8">
            
            <div>
              <h2 className="text-3xl font-bold text-white tracking-tight">Knowledge Vault & News Engine</h2>
              <p className="text-zinc-400 text-sm mt-1">The passages TruthLens searches: bundled reference files, uploaded documents and synced news headlines.</p>
            </div>

            {/* News Stats */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 font-mono text-xs">
              <div className="p-5 rounded-2xl apogee-card">
                <div className="text-zinc-400">Total Chunks</div>
                <div className="text-2xl font-bold text-white mt-1">
                  {health ? health.indexed_chunks : '—'}
                </div>
              </div>
              <div className="p-5 rounded-2xl apogee-card">
                <div className="text-zinc-400">Live Articles</div>
                <div className="text-2xl font-bold text-white mt-1">
                  {newsStatus ? newsStatus.total_live_articles : '—'}
                </div>
              </div>
              <div className="p-5 rounded-2xl apogee-card">
                <div className="text-zinc-400">Active RSS Feeds</div>
                <div className="text-2xl font-bold text-white mt-1">
                  {newsStatus?.active_feeds ? newsStatus.active_feeds.length : '—'}
                </div>
              </div>
              <div className="p-5 rounded-2xl apogee-card">
                <div className="text-zinc-400">Last Synced</div>
                <div className="text-xs font-semibold text-zinc-300 mt-2 truncate">
                  {newsStatus?.last_sync_time || '—'}
                </div>
              </div>
            </div>

            {/* Sub-navigation Switcher */}
            <div className="flex items-center gap-2 border-b border-white/10 pb-4">
              <button
                onClick={() => setVaultTab('news')}
                className={`px-4 py-2 rounded-xl text-xs font-mono font-semibold transition-all ${
                  vaultTab === 'news'
                    ? 'bg-white text-black shadow-lg shadow-white/10'
                    : 'bg-white/5 text-zinc-400 hover:text-white hover:bg-white/10'
                }`}
              >
                Live News Stream ({(newsStatus?.recent_articles || []).length})
              </button>
              <button
                onClick={() => setVaultTab('dossiers')}
                className={`px-4 py-2 rounded-xl text-xs font-mono font-semibold transition-all ${
                  vaultTab === 'dossiers'
                    ? 'bg-white text-black shadow-lg shadow-white/10'
                    : 'bg-white/5 text-zinc-400 hover:text-white hover:bg-white/10'
                }`}
              >
                Custom Reference Dossiers ({documents.length})
              </button>
            </div>

            {/* VIEW 1: LIVE NEWS INTELLIGENCE STREAM */}
            {vaultTab === 'news' && (
              <div className="p-6 rounded-3xl apogee-card space-y-4">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                  <div>
                    <h3 className="text-base font-bold text-white">
                      Indexed Live News Feed ({
                        (newsStatus?.recent_articles || []).filter(item => {
                          if (!newsSearchQuery) return true;
                          const q = newsSearchQuery.toLowerCase();
                          return (item.title || '').toLowerCase().includes(q) || (item.source || '').toLowerCase().includes(q) || (item.category || '').toLowerCase().includes(q);
                        }).length
                      })
                    </h3>
                    <p className="text-xs text-zinc-400 mt-0.5">Headlines pulled from the configured RSS feeds{newsStatus?.active_feeds ? ` (${newsStatus.active_feeds.join(', ')})` : ''}, ready to verify.</p>
                  </div>
                  <div className="relative flex items-center gap-2">
                    <button
                      onClick={handleManualSyncNews}
                      disabled={isSyncingNews}
                      className="px-4 py-1.5 bg-white text-black hover:bg-zinc-200 disabled:opacity-50 text-xs font-semibold rounded-xl transition-colors shadow-sm"
                    >
                      {isSyncingNews ? 'Syncing...' : 'Sync Now'}
                    </button>
                    <input
                      type="text"
                      aria-label="Filter news"
                      placeholder="Filter news..."
                      value={newsSearchQuery}
                      onChange={(e) => setNewsSearchQuery(e.target.value)}
                      className="bg-white/5 border border-white/10 rounded-xl px-3 py-1.5 text-xs text-white placeholder-zinc-500 focus:outline-none focus:border-white/40 font-mono w-40 sm:w-56"
                    />
                  </div>
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs sm:text-sm font-mono">
                    <thead className="border-b border-white/10 text-zinc-500">
                      <tr>
                        <th className="pb-3 px-3 font-semibold">Headline / News Story</th>
                        <th className="pb-3 px-3 font-semibold">Source</th>
                        <th className="pb-3 px-3 font-semibold">Category</th>
                        <th className="pb-3 px-3 font-semibold">Ingested</th>
                        <th className="pb-3 px-3 text-right font-semibold">Action</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-white/5 text-zinc-300">
                      {((newsStatus?.recent_articles || []).filter(item => {
                        if (!newsSearchQuery) return true;
                        const q = newsSearchQuery.toLowerCase();
                        return (item.title || '').toLowerCase().includes(q) || (item.source || '').toLowerCase().includes(q) || (item.category || '').toLowerCase().includes(q);
                      })).map((item, idx) => {
                        const title = item.title || item.headline || "News Story";
                        const source = item.source_name || item.source || "Trusted Feed";
                        const cat = item.category || "GENERAL";
                        const date = (item.ingested_at || item.published_at || "Recent").slice(0, 10);
                        return (
                          <tr key={item.id || idx} className="hover:bg-white/[0.03] transition-colors">
                            <td className="py-3.5 px-3 font-semibold text-white font-sans max-w-md truncate">
                              {title}
                            </td>
                            <td className="py-3.5 px-3">
                              <span className="px-2.5 py-1 rounded-full bg-white/5 border border-white/10 text-[11px] text-zinc-300 whitespace-nowrap">
                                {source}
                              </span>
                            </td>
                            <td className="py-3.5 px-3">
                              <span className="text-[11px] text-zinc-400 uppercase tracking-wider">
                                {cat}
                              </span>
                            </td>
                            <td className="py-3.5 px-3 text-zinc-500 whitespace-nowrap">
                              {date}
                            </td>
                            <td className="py-3.5 px-3 text-right whitespace-nowrap space-x-2">
                              {(item.url || item.link) && (
                                <a
                                  href={item.url || item.link}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="inline-block px-3 py-1 bg-white/10 text-zinc-300 hover:text-white hover:bg-white/20 text-xs font-semibold rounded-lg transition-colors shadow-sm border border-white/10"
                                  title="Read Original Article"
                                >
                                  Redirect ↗
                                </a>
                              )}
                              <button
                                onClick={() => handleVerifyNewsArticle(title)}
                                className="px-3 py-1 bg-white text-black hover:bg-zinc-200 text-xs font-semibold rounded-lg transition-colors shadow-sm"
                              >
                                Verify Claim
                              </button>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* VIEW 2: CUSTOM DOSSIER UPLOAD */}
            {vaultTab === 'dossiers' && (
              <div className="space-y-6">
                {/* Upload Dossier */}
                <div className="p-6 rounded-3xl apogee-card space-y-4">
                  <div className="flex items-center justify-between">
                    <h3 className="text-base font-bold text-white">Upload New Reference Dossier</h3>

                  </div>
                  <div className="p-3 bg-white/[0.02] border border-white/10 rounded-xl text-xs text-zinc-400">
                    Uploaded files are split into passages and added to the local knowledge vault, where they are searched alongside live Wikipedia results. On a serverless deployment the vault is temporary and resets.
                  </div>
                  <label className="border-2 border-dashed border-white/20 hover:border-white/50 rounded-2xl p-8 text-center cursor-pointer transition-all flex flex-col items-center justify-center gap-2 bg-white/[0.02]">
                    <Icon name="upload" className="w-8 h-8 text-zinc-400" />
                    <span className="text-sm font-semibold text-white">Click to upload document or drag and drop</span>
                    <span className="text-xs text-zinc-500 font-mono">PDF, TXT, MD (Max 10MB)</span>
                    <input type="file" accept=".pdf,.txt,.md" className="hidden" aria-label="Upload reference document" onChange={handleFileUpload} />
                  </label>
                </div>

                {/* Indexed Documents Table */}
                <div className="p-6 rounded-3xl apogee-card space-y-4">
                  <div className="flex items-center justify-between">
                    <h3 className="text-base font-bold text-white">
                      Indexed Reference Dossiers ({documents.length})
                    </h3>
                    <span className="text-xs font-mono text-zinc-400">
                      {documents.reduce((acc, d) => acc + (d.number_of_chunks || d.chunks_count || 0), 0)} total chunks
                    </span>
                  </div>

                  {documents.length === 0 ? (
                    <div className="py-8 text-center text-zinc-500 text-xs font-mono border border-dashed border-white/10 rounded-2xl">
                      No documents uploaded yet. Claims are checked against the bundled reference files, synced news and live Wikipedia.
                    </div>
                  ) : (
                    <div className="overflow-x-auto">
                      <table className="w-full text-left text-xs sm:text-sm font-mono">
                        <thead className="border-b border-white/10 text-zinc-500">
                          <tr>
                            <th className="pb-3 px-3 font-semibold">Document Title</th>
                            <th className="pb-3 px-3 font-semibold">Category / Type</th>
                            <th className="pb-3 px-3 font-semibold">Chunks</th>
                            <th className="pb-3 px-3 font-semibold">Indexed On</th>
                            <th className="pb-3 px-3 text-right font-semibold">Actions</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-white/5 text-zinc-300">
                          {documents.map((doc) => {
                            const title = doc.source || doc.filename || doc.title || "Untitled Dossier";
                            const chunks = doc.number_of_chunks ?? doc.chunks_count ?? 0;
                            const date = (doc.upload_date || doc.created_at || "Recent").slice(0, 10);

                            return (
                              <tr key={doc.id} className="hover:bg-white/[0.03] transition-colors">
                                <td className="py-3.5 px-3 font-semibold text-white font-sans">
                                  {title}
                                </td>
                                <td className="py-3.5 px-3">
                                  <span className="px-2.5 py-1 rounded-full bg-white/5 border border-white/10 text-[11px] text-zinc-300">
                                    {doc.source_type || 'General'}
                                  </span>
                                </td>
                                <td className="py-3.5 px-3 font-bold text-white">
                                  {chunks}
                                </td>
                                <td className="py-3.5 px-3 text-zinc-500">
                                  {date}
                                </td>
                                <td className="py-3.5 px-3 text-right">
                                  <button
                                    onClick={() => handleDeleteDoc(doc.id, title)}
                                    className="p-1.5 rounded-lg hover:bg-white/10 text-zinc-500 hover:text-white transition-colors"
                                    title="Delete document"
                                    aria-label={`Delete ${title}`}
                                  >
                                    <Icon name="trash" className="w-4 h-4" />
                                  </button>
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              </div>
            )}

          </div>
        )}

        {/* ======================================================== */}
        {/* TAB 3: AUDIT HISTORY                                     */}
        {/* ======================================================== */}
        {activeTab === 'history' && (
          <div className="space-y-6">
            <div>
              <div className="flex flex-wrap items-end justify-between gap-3">
                <div>
                  <h2 className="text-3xl font-bold text-white tracking-tight">Your Fact-Check History</h2>
                  <p className="text-zinc-400 text-sm mt-1">Claims checked from this browser. Select a row to check it again.</p>
                </div>
                <button
                  onClick={handleClearHistory}
                  disabled={history.length === 0}
                  className="px-4 py-1.5 rounded-xl border border-white/20 text-xs font-mono text-zinc-300 hover:text-white hover:border-white/40 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  Clear my history
                </button>
              </div>
              <p className="text-[11px] text-zinc-500 font-mono mt-2">Your checks are stored for 30 days, visible only in this browser. Don't paste personal information.</p>
            </div>

            <div className="p-6 rounded-3xl apogee-card">
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs sm:text-sm font-mono">
                  <thead className="border-b border-white/10 text-zinc-500">
                    <tr>
                      <th className="pb-3 px-3 font-semibold">Claim</th>
                      <th className="pb-3 px-3 font-semibold">Verdict</th>
                      <th className="pb-3 px-3 font-semibold">Confidence</th>
                      <th className="pb-3 px-3 font-semibold">Date</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/5 text-zinc-300">
                    {history.length === 0 && (
                      <tr><td colSpan={4} className="py-6 text-center text-zinc-500">No claims checked yet.</td></tr>
                    )}
                    {history.map((h) => (
                      <tr
                        key={h.id}
                        className="hover:bg-white/[0.03] transition-colors cursor-pointer focus:outline-none focus:bg-white/[0.06]"
                        tabIndex={0}
                        aria-label={`Check again: ${h.claim}`}
                        onClick={() => { setClaimInput(h.claim); setActiveTab('verify'); handleVerify(h.claim); }}
                        onKeyDown={(e) => { if (e.key === 'Enter') { setClaimInput(h.claim); setActiveTab('verify'); handleVerify(h.claim); } }}
                      >
                        <td className="py-3.5 px-3 font-semibold text-white font-sans max-w-xs truncate">
                          "{h.claim}"
                        </td>
                        <td className="py-3.5 px-3">
                          <VerdictBadge verdict={h.verdict} size="sm" />
                        </td>
                        <td className="py-3.5 px-3 font-bold text-white">
                          {confidenceText(h)}
                        </td>
                        <td className="py-3.5 px-3 text-zinc-500">
                          {h.timestamp}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}

        {/* ======================================================== */}
        {/* TAB 4: ANALYTICS                                         */}
        {/* ======================================================== */}
        {activeTab === 'analytics' && (
          <div className="space-y-6">
            <div>
              <h2 className="text-3xl font-bold text-white tracking-tight">Verification Engine Analytics</h2>
              <p className="text-zinc-400 text-sm mt-1">Verdicts given on this server so far. This is not an accuracy measure.</p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div className="p-6 rounded-3xl apogee-card space-y-4">
                <h3 className="text-base font-bold text-white">Verdict Distribution</h3>
                <div className="max-w-xs mx-auto">
                  <canvas ref={chartRef} role="img" aria-label={`Verdict distribution: ${Object.entries(analytics?.verdict_counts || {}).map(([k, n]) => `${verdictStyle(k).label} ${n}`).join(', ')}`} />
                </div>
              </div>

              <div className="p-6 rounded-3xl apogee-card space-y-4 font-mono text-sm">
                <h3 className="text-base font-bold text-white">Engine</h3>
                <div className="space-y-3">
                  <div className="flex justify-between border-b border-white/5 pb-2">
                    <span className="text-zinc-400">Claims checked:</span>
                    <strong className="text-white">{analytics ? analytics.total_claims_verified : '—'}</strong>
                  </div>
                  <div className="flex justify-between border-b border-white/5 pb-2">
                    <span className="text-zinc-400">Average confidence:</span>
                    <strong className="text-white">{analytics ? fmtPct(analytics.average_confidence) : '—'}</strong>
                  </div>
                  <div className="flex justify-between border-b border-white/5 pb-2">
                    <span className="text-zinc-400">Indexed passages:</span>
                    <strong className="text-white">{health ? health.indexed_chunks : '—'}</strong>
                  </div>
                  <div className="flex justify-between border-b border-white/5 pb-2">
                    <span className="text-zinc-400">Documents:</span>
                    <strong className="text-white">{analytics ? analytics.total_documents : '—'}</strong>
                  </div>
                  <div className="flex justify-between gap-4">
                    <span className="text-zinc-400 shrink-0">Judge (latest verdict):</span>
                    <strong className="text-white text-right">{currentResult?.llm_provider_used || '—'}</strong>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

      </main>

      {/* Footer */}
      <footer className="relative z-10 border-t border-white/10 bg-black/85 py-8 text-xs font-mono text-zinc-500 mt-16 backdrop-blur-md">
        <div className="max-w-7xl mx-auto px-4 flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <span className="font-bold text-white">TruthLens</span>
            <span>— Explainable Neural Fact Verification</span>
          </div>
          <div>
            <span>Truth is not a narrative. It is a verifiable state.</span>
          </div>
        </div>
      </footer>

    </div>
  );
}

