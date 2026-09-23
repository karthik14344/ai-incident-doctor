import React, { useState, useRef, useEffect } from 'react';
import { api } from '../services/api';
import { isRecordingSupported, startRecording } from '../utils/audioRecorder';
import {
  isBrowserRecognitionSupported,
  startBrowserRecognition
} from '../utils/browserSpeech';

/**
 * Microphone button that dictates the user's prompt into the chat box.
 *
 * Two engines, picked from what the backend reports:
 *  - "vexyl": record 16 kHz WAV locally, POST it to VEXYL-STT through the
 *    gateway, drop the returned transcript into the input.
 *  - "browser": the Web Speech API, streaming interim words as they are heard.
 *
 * If the server engine fails mid-session we switch to the browser engine and
 * stay there, so the user is never left with a dead mic button.
 */
export default function VoiceInput({
  capabilities,
  language = 'hi-IN',
  disabled = false,
  onTranscript,
  onInterim
}) {
  const [status, setStatus] = useState('idle'); // idle | recording | transcribing
  const [level, setLevel] = useState(0);
  const [error, setError] = useState(null);
  const [forcedBrowser, setForcedBrowser] = useState(false);

  const recorderRef = useRef(null);
  const recognitionRef = useRef(null);
  const interimRef = useRef('');

  const serverStt = !forcedBrowser && capabilities?.stt?.available === true;
  const engine = serverStt ? 'vexyl' : 'browser';

  const canRecord = serverStt ? isRecordingSupported() : isBrowserRecognitionSupported();

  // Release the microphone if the component unmounts mid-recording.
  useEffect(() => {
    return () => {
      recorderRef.current?.cancel();
      recognitionRef.current?.abort();
    };
  }, []);

  const showError = (message) => {
    setError(message);
    setTimeout(() => setError(null), 6000);
  };

  const startVexyl = async () => {
    try {
      recorderRef.current = await startRecording({ onLevel: setLevel });
      setStatus('recording');
    } catch (err) {
      showError(
        err.name === 'NotAllowedError'
          ? 'Microphone permission denied. Allow mic access and try again.'
          : `Could not open the microphone: ${err.message}`
      );
      setStatus('idle');
    }
  };

  const stopVexyl = async () => {
    const recorder = recorderRef.current;
    recorderRef.current = null;
    if (!recorder) return;

    setStatus('transcribing');
    setLevel(0);

    try {
      const recording = await recorder.stop();
      if (!recording || recording.durationSeconds < 0.3) {
        showError('That recording was too short. Hold the mic while you speak.');
        setStatus('idle');
        return;
      }

      const result = await api.transcribeAudio(recording.blob, language);
      const text = (result.text || '').trim();
      if (text) {
        onTranscript(text);
      } else {
        showError('No speech was detected in that recording.');
      }
    } catch (err) {
      if (err.canFallback && isBrowserRecognitionSupported()) {
        setForcedBrowser(true);
        showError(`${err.message} Switched to browser dictation.`);
      } else {
        showError(err.message);
      }
    } finally {
      setStatus('idle');
    }
  };

  const startBrowser = () => {
    interimRef.current = '';
    try {
      recognitionRef.current = startBrowserRecognition({
        lang: language,
        onResult: (text, isFinal) => {
          interimRef.current = text;
          if (isFinal) {
            onTranscript(text.trim());
            interimRef.current = '';
            if (onInterim) onInterim('');
          } else if (onInterim) {
            onInterim(text);
          }
        },
        onError: (code) => {
          const messages = {
            'not-allowed': 'Microphone permission denied. Allow mic access and try again.',
            'no-speech': 'No speech was detected. Try again.',
            'network': 'Browser dictation needs an internet connection.'
          };
          showError(messages[code] || `Dictation failed: ${code}`);
        },
        onEnd: () => {
          recognitionRef.current = null;
          setStatus('idle');
          // Commit whatever was heard if the engine ended without a final result.
          const pending = interimRef.current.trim();
          if (pending) {
            onTranscript(pending);
            interimRef.current = '';
            if (onInterim) onInterim('');
          }
        }
      });
      setStatus('recording');
    } catch (err) {
      showError(err.message);
      setStatus('idle');
    }
  };

  const stopBrowser = () => {
    recognitionRef.current?.stop();
    recognitionRef.current = null;
    setStatus('idle');
  };

  const handleClick = () => {
    setError(null);
    if (status === 'transcribing') return;

    if (status === 'recording') {
      if (engine === 'vexyl') stopVexyl();
      else stopBrowser();
      return;
    }

    if (engine === 'vexyl') startVexyl();
    else startBrowser();
  };

  if (!canRecord) {
    return (
      <div
        title="This browser cannot capture audio. Try Chrome or Edge."
        className="w-12 h-12 shrink-0 rounded-xl bg-slate-900 border border-slate-800 text-slate-600 flex items-center justify-center cursor-not-allowed"
      >
        <MicIcon muted />
      </div>
    );
  }

  const isRecording = status === 'recording';
  const isBusy = status === 'transcribing';

  const engineLabel =
    engine === 'vexyl'
      ? `VEXYL-STT · ${language}`
      : 'Browser dictation (VEXYL-STT offline)';

  return (
    <div className="relative shrink-0">
      <button
        type="button"
        onClick={handleClick}
        disabled={disabled || isBusy}
        title={engineLabel}
        aria-label={isRecording ? 'Stop recording' : 'Ask by voice'}
        className={`relative w-12 h-12 rounded-xl flex items-center justify-center transition-all border ${
          isRecording
            ? 'bg-rose-600 border-rose-500 text-white shadow-lg shadow-rose-600/30'
            : isBusy
            ? 'bg-slate-800 border-slate-700 text-indigo-400'
            : 'bg-slate-900 border-slate-800 text-slate-300 hover:text-indigo-400 hover:border-indigo-500/50 disabled:opacity-40 disabled:hover:text-slate-300'
        }`}
      >
        {isBusy ? (
          <span className="w-5 h-5 border-2 border-indigo-400 border-t-transparent rounded-full animate-spin" />
        ) : (
          <MicIcon />
        )}

        {isRecording && (
          <span
            className="absolute inset-0 rounded-xl border-2 border-rose-300/70 pointer-events-none"
            style={{ transform: `scale(${1 + level * 0.35})`, opacity: 0.35 + level * 0.5 }}
          />
        )}
      </button>

      {(isRecording || isBusy || error) && (
        <div
          className={`absolute bottom-full mb-2 right-0 whitespace-nowrap px-3 py-1.5 rounded-lg text-[11px] font-medium border shadow-lg z-30 ${
            error
              ? 'bg-rose-950 border-rose-800 text-rose-200 max-w-xs whitespace-normal'
              : 'bg-slate-900 border-slate-700 text-slate-200'
          }`}
        >
          {error
            ? error
            : isBusy
            ? 'Transcribing with VEXYL-STT...'
            : `● Listening — ${engineLabel}. Click to stop.`}
        </div>
      )}
    </div>
  );
}

function MicIcon({ muted = false }) {
  return (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="2"
        d="M19 11a7 7 0 01-14 0m7 7v3m0-3a7 7 0 007-7M12 1a3 3 0 013 3v7a3 3 0 01-6 0V4a3 3 0 013-3z"
      />
      {muted && (
        <path strokeLinecap="round" strokeWidth="2" d="M4 4l16 16" />
      )}
    </svg>
  );
}
