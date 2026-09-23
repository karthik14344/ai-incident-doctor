/**
 * Microphone capture that produces 16 kHz, 16-bit, mono WAV.
 *
 * MediaRecorder is deliberately not used: Chrome only emits WebM/Opus, which
 * the VEXYL-STT batch API does not accept. Capturing raw PCM through the Web
 * Audio API instead lets us hand the server the exact format the underlying
 * indic-conformer model wants, with no transcoding anywhere in the chain.
 */

const TARGET_SAMPLE_RATE = 16000;
const BUFFER_SIZE = 4096;

export function isRecordingSupported() {
  return (
    typeof navigator !== 'undefined' &&
    !!navigator.mediaDevices &&
    typeof navigator.mediaDevices.getUserMedia === 'function' &&
    !!(window.AudioContext || window.webkitAudioContext)
  );
}

function mergeBuffers(chunks, totalLength) {
  const merged = new Float32Array(totalLength);
  let offset = 0;
  for (const chunk of chunks) {
    merged.set(chunk, offset);
    offset += chunk.length;
  }
  return merged;
}

function resample(samples, fromRate, toRate) {
  if (fromRate === toRate || samples.length === 0) return samples;

  const ratio = fromRate / toRate;

  if (ratio > 1) {
    // Downsampling: average each source window rather than picking one sample.
    // The averaging doubles as a crude low-pass, which keeps high frequencies
    // from aliasing down into the speech band and confusing the model.
    const length = Math.floor(samples.length / ratio);
    const result = new Float32Array(length);
    for (let i = 0; i < length; i++) {
      const start = Math.floor(i * ratio);
      const end = Math.min(Math.floor((i + 1) * ratio), samples.length);
      let sum = 0;
      let count = 0;
      for (let j = start; j < end; j++) {
        sum += samples[j];
        count += 1;
      }
      result[i] = count > 0 ? sum / count : 0;
    }
    return result;
  }

  // Upsampling (only if a device ever reports below 16 kHz): linear interpolation.
  const length = Math.round(samples.length / ratio);
  const result = new Float32Array(length);
  for (let i = 0; i < length; i++) {
    const position = i * ratio;
    const left = Math.floor(position);
    const right = Math.min(left + 1, samples.length - 1);
    const weight = position - left;
    result[i] = samples[left] * (1 - weight) + samples[right] * weight;
  }
  return result;
}

function encodeWav(samples, sampleRate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);

  const writeString = (offset, text) => {
    for (let i = 0; i < text.length; i++) {
      view.setUint8(offset + i, text.charCodeAt(i));
    }
  };

  writeString(0, 'RIFF');
  view.setUint32(4, 36 + samples.length * 2, true);
  writeString(8, 'WAVE');
  writeString(12, 'fmt ');
  view.setUint32(16, 16, true); // PCM header size
  view.setUint16(20, 1, true); // format: PCM
  view.setUint16(22, 1, true); // channels: mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true); // byte rate
  view.setUint16(32, 2, true); // block align
  view.setUint16(34, 16, true); // bits per sample
  writeString(36, 'data');
  view.setUint32(40, samples.length * 2, true);

  let offset = 44;
  for (let i = 0; i < samples.length; i++, offset += 2) {
    const clamped = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(offset, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true);
  }

  return new Blob([view], { type: 'audio/wav' });
}

/**
 * Opens the microphone and starts capturing.
 *
 * Returns a handle with `stop()` (resolves to a WAV Blob plus metadata) and
 * `cancel()` (releases the mic and discards everything). `onLevel` receives a
 * 0..1 loudness value per audio frame so the UI can show the mic is live.
 */
export async function startRecording({ onLevel } = {}) {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: {
      channelCount: 1,
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true
    }
  });

  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  const context = new AudioContextClass();
  const source = context.createMediaStreamSource(stream);
  const processor = context.createScriptProcessor(BUFFER_SIZE, 1, 1);

  // ScriptProcessorNode only runs while connected to the destination, so route
  // it through a muted gain node instead of letting the mic loop to speakers.
  const mute = context.createGain();
  mute.gain.value = 0;

  const chunks = [];
  let totalLength = 0;
  let finished = false;

  processor.onaudioprocess = (event) => {
    if (finished) return;
    const input = event.inputBuffer.getChannelData(0);
    chunks.push(new Float32Array(input));
    totalLength += input.length;

    if (onLevel) {
      let peak = 0;
      for (let i = 0; i < input.length; i += 32) {
        const amplitude = Math.abs(input[i]);
        if (amplitude > peak) peak = amplitude;
      }
      onLevel(Math.min(1, peak));
    }
  };

  source.connect(processor);
  processor.connect(mute);
  mute.connect(context.destination);

  const teardown = () => {
    finished = true;
    processor.onaudioprocess = null;
    try { source.disconnect(); } catch { /* already torn down */ }
    try { processor.disconnect(); } catch { /* already torn down */ }
    try { mute.disconnect(); } catch { /* already torn down */ }
    stream.getTracks().forEach((track) => track.stop());
    if (context.state !== 'closed') context.close();
  };

  return {
    async stop() {
      if (finished) return null;
      const sampleRate = context.sampleRate;
      const captured = mergeBuffers(chunks, totalLength);
      teardown();

      const resampled = resample(captured, sampleRate, TARGET_SAMPLE_RATE);
      return {
        blob: encodeWav(resampled, TARGET_SAMPLE_RATE),
        durationSeconds: resampled.length / TARGET_SAMPLE_RATE,
        sampleRate: TARGET_SAMPLE_RATE
      };
    },
    cancel() {
      if (!finished) teardown();
    }
  };
}
