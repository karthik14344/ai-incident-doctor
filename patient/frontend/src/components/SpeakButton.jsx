import React, { useState, useRef, useEffect } from 'react';
import { api } from '../services/api';
import {
  isBrowserSynthesisSupported,
  speakWithBrowser,
  cancelBrowserSpeech
} from '../utils/browserSpeech';

/**
 * Reads an assistant answer aloud.
 *
 * Prefers the Futurix-AI Hindi-TTS model (24 kHz WAV returned by the voice
 * service) and falls back to the browser synthesizer when that model is not
 * set up, so the button is never dead.
 */
export default function SpeakButton({
  capabilities,
  text,
  language = 'hi-IN',
  autoPlay = false
}) {
  const [state, setState] = useState('idle'); // idle | loading | playing
  const [error, setError] = useState(null);

  const audioRef = useRef(null);
  const urlRef = useRef(null);
  const cancelledRef = useRef(false);

  const serverTts = capabilities?.tts?.available === true;
  const supported = serverTts || isBrowserSynthesisSupported();

  const cleanupAudio = () => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
    }
    if (urlRef.current) {
      URL.revokeObjectURL(urlRef.current);
      urlRef.current = null;
    }
  };

  useEffect(() => {
    return () => {
      cancelledRef.current = true;
      cleanupAudio();
      cancelBrowserSpeech();
    };
  }, []);

  const showError = (message) => {
    setError(message);
    setTimeout(() => setError(null), 5000);
  };

  const stop = () => {
    cancelledRef.current = true;
    cleanupAudio();
    cancelBrowserSpeech();
    setState('idle');
  };

  const speakViaBrowser = async () => {
    if (!isBrowserSynthesisSupported()) {
      showError('This browser cannot speak text.');
      setState('idle');
      return;
    }
    setState('playing');
    try {
      await speakWithBrowser(text, language);
    } catch (err) {
      if (!cancelledRef.current) showError(err.message);
    } finally {
      if (!cancelledRef.current) setState('idle');
    }
  };

  const play = async () => {
    cancelledRef.current = false;
    setError(null);

    if (!serverTts) {
      await speakViaBrowser();
      return;
    }

    setState('loading');
    try {
      const blob = await api.synthesizeSpeech(text, language.split('-')[0]);
      if (cancelledRef.current) return;

      const url = URL.createObjectURL(blob);
      urlRef.current = url;

      const audio = new Audio(url);
      audioRef.current = audio;
      audio.onended = () => {
        cleanupAudio();
        setState('idle');
      };
      audio.onerror = () => {
        cleanupAudio();
        showError('Could not play the generated audio.');
        setState('idle');
      };

      await audio.play();
      setState('playing');
    } catch (err) {
      if (cancelledRef.current) return;
      if (err.canFallback) {
        await speakViaBrowser();
      } else {
        showError(err.message);
        setState('idle');
      }
    }
  };

  // "Speak answers automatically" in Settings: play once when this message
  // first appears, never on re-render or when the user scrolls back.
  const autoPlayedRef = useRef(false);
  useEffect(() => {
    if (autoPlay && !autoPlayedRef.current && text?.trim()) {
      autoPlayedRef.current = true;
      play();
    }
  }, [autoPlay, text]);

  if (!supported || !text?.trim()) return null;

  const engineLabel = serverTts
    ? 'Futurix-AI Hindi-TTS'
    : 'Browser voice (Hindi-TTS offline)';

  return (
    <span className="relative inline-flex">
      <button
        type="button"
        onClick={state === 'idle' ? play : stop}
        title={error || `Read aloud — ${engineLabel}`}
        aria-label={state === 'idle' ? 'Read answer aloud' : 'Stop reading'}
        className={`inline-flex items-center gap-1.5 px-2 py-1 rounded-md text-[11px] font-medium border transition-all ${
          state === 'idle'
            ? 'bg-slate-950/60 border-slate-800 text-slate-400 hover:text-indigo-300 hover:border-indigo-500/40'
            : 'bg-indigo-600/20 border-indigo-500/40 text-indigo-300'
        }`}
      >
        {state === 'loading' ? (
          <span className="w-3 h-3 border-2 border-indigo-400 border-t-transparent rounded-full animate-spin" />
        ) : state === 'playing' ? (
          <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 24 24">
            <rect x="6" y="5" width="4" height="14" rx="1" />
            <rect x="14" y="5" width="4" height="14" rx="1" />
          </svg>
        ) : (
          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth="2"
              d="M11 5L6 9H2v6h4l5 4V5zM15.5 8.5a5 5 0 010 7M18.5 5.5a9 9 0 010 13"
            />
          </svg>
        )}
        <span>
          {state === 'loading' ? 'Synthesizing' : state === 'playing' ? 'Stop' : 'Listen'}
        </span>
      </button>

      {error && (
        <span className="absolute bottom-full mb-1 left-0 z-30 px-2 py-1 rounded bg-rose-950 border border-rose-800 text-rose-200 text-[10px] w-56">
          {error}
        </span>
      )}
    </span>
  );
}
