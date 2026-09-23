/**
 * Web Speech API wrappers used as the fallback path.
 *
 * When the VEXYL-STT / Hindi-TTS servers are not running, voice input and
 * output still work through the browser's own engines. Quality is lower and
 * Chrome's recognizer needs an internet connection, but the feature never
 * hard-fails just because the local models are not set up yet.
 */

function getRecognitionClass() {
  if (typeof window === 'undefined') return null;
  return window.SpeechRecognition || window.webkitSpeechRecognition || null;
}

export function isBrowserRecognitionSupported() {
  return getRecognitionClass() !== null;
}

export function isBrowserSynthesisSupported() {
  return typeof window !== 'undefined' && 'speechSynthesis' in window;
}

/**
 * Starts browser dictation. Returns a handle with `stop()` and `abort()`.
 * `onResult` fires with (text, isFinal) as the interim transcript firms up.
 */
export function startBrowserRecognition({ lang = 'hi-IN', onResult, onError, onEnd }) {
  const RecognitionClass = getRecognitionClass();
  if (!RecognitionClass) {
    throw new Error('This browser has no speech recognition support.');
  }

  const recognition = new RecognitionClass();
  recognition.lang = lang;
  recognition.interimResults = true;
  recognition.continuous = false;
  recognition.maxAlternatives = 1;

  recognition.onresult = (event) => {
    let transcript = '';
    let isFinal = false;
    for (let i = event.resultIndex; i < event.results.length; i++) {
      transcript += event.results[i][0].transcript;
      if (event.results[i].isFinal) isFinal = true;
    }
    if (onResult) onResult(transcript, isFinal);
  };

  recognition.onerror = (event) => {
    if (onError) onError(event.error || 'Speech recognition failed.');
  };

  recognition.onend = () => {
    if (onEnd) onEnd();
  };

  recognition.start();

  return {
    stop: () => { try { recognition.stop(); } catch { /* already stopped */ } },
    abort: () => { try { recognition.abort(); } catch { /* already stopped */ } }
  };
}

/** Speaks text with the browser's built-in synthesizer. Resolves when done. */
export function speakWithBrowser(text, lang = 'hi-IN') {
  return new Promise((resolve, reject) => {
    if (!isBrowserSynthesisSupported()) {
      reject(new Error('This browser has no speech synthesis support.'));
      return;
    }

    window.speechSynthesis.cancel();

    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = lang;
    utterance.rate = 1;
    utterance.pitch = 1;

    // Prefer a voice that actually matches the language; otherwise the default
    // voice reads Devanagari with an English phoneme set and it is unlistenable.
    const voices = window.speechSynthesis.getVoices();
    const base = lang.split('-')[0];
    const match =
      voices.find((v) => v.lang === lang) ||
      voices.find((v) => v.lang && v.lang.startsWith(base));
    if (match) utterance.voice = match;

    utterance.onend = () => resolve();
    utterance.onerror = (event) => reject(new Error(event.error || 'Speech synthesis failed.'));

    window.speechSynthesis.speak(utterance);
  });
}

export function cancelBrowserSpeech() {
  if (isBrowserSynthesisSupported()) window.speechSynthesis.cancel();
}
