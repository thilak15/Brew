"use client";

/**
 * Capture microphone at 16 kHz mono, 16-bit PCM, and send chunks via callback.
 * Uses AudioWorklet (modern, off-main-thread) with a ScriptProcessor fallback.
 */
import hark from 'hark';

const TARGET_SAMPLE_RATE = 16000;

export let isUserSpeaking = false;

export async function startMicCapture(
  onChunk: (buffer: ArrayBuffer) => void,
  onSpeechEnd?: () => void
): Promise<() => void> {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const ctx = new AudioContext({ sampleRate: 48000 });
  const source = ctx.createMediaStreamSource(stream);

  // Set up hark for VAD
  const speechEvents = hark(stream, { interval: 100, threshold: -35, play: false });
  speechEvents.on('speaking', () => {
    isUserSpeaking = true;
    // Immediately cut off local playback when user starts talking (barge-in latency fix)
    interruptAudioPlayback();
  });
  speechEvents.on('stopped_speaking', () => {
    isUserSpeaking = false;
    onSpeechEnd?.();
  });

  // Try AudioWorklet first, fall back to ScriptProcessor
  if (ctx.audioWorklet) {
    try {
      await ctx.audioWorklet.addModule('/audio-processor.js');
      const workletNode = new AudioWorkletNode(ctx, 'pcm-capture-processor');
      workletNode.port.onmessage = (e: MessageEvent) => {
        onChunk(e.data as ArrayBuffer);
      };
      source.connect(workletNode);
      workletNode.connect(ctx.destination);

      return () => {
        speechEvents.stop();
        workletNode.port.close();
        workletNode.disconnect();
        source.disconnect();
        stream.getTracks().forEach((t) => t.stop());
        ctx.close();
      };
    } catch (err) {
      console.warn('AudioWorklet failed, falling back to ScriptProcessor:', err);
    }
  }

  // Fallback: deprecated ScriptProcessor for older browsers
  const rate = ctx.sampleRate;
  const desired = Math.floor((rate * 80) / 1000);
  const bufferSize = Math.min(
    16384,
    Math.max(256, Math.pow(2, Math.round(Math.log2(desired))))
  );
  const scriptNode = ctx.createScriptProcessor(bufferSize, 1, 1);
  let targetSamplesAcc = 0;
  const ratio = TARGET_SAMPLE_RATE / rate;

  scriptNode.onaudioprocess = (e) => {
    const input = e.inputBuffer.getChannelData(0);
    const output: number[] = [];
    for (let i = 0; i < input.length; i++) {
      targetSamplesAcc += ratio;
      while (targetSamplesAcc >= 1) {
        output.push(input[i] ?? 0);
        targetSamplesAcc -= 1;
      }
    }
    if (output.length === 0) return;
    const buf = new ArrayBuffer(output.length * 2);
    const view = new DataView(buf);
    for (let i = 0; i < output.length; i++) {
      const s = Math.max(-1, Math.min(1, output[i]));
      view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    }
    onChunk(buf);
  };
  source.connect(scriptNode);
  scriptNode.connect(ctx.destination);

  return () => {
    speechEvents.stop();
    scriptNode.disconnect();
    source.disconnect();
    stream.getTracks().forEach((t) => t.stop());
    ctx.close();
  };
}

/**
 * Play 24 kHz 16-bit PCM mono chunks via AudioContext.
 * Chunks are queued and played in order so agent speech is not overlapping.
 */
const PLAYBACK_RATE = 24000;
let playbackContext: AudioContext | null = null;
const playbackQueue: ArrayBuffer[] = [];
let isPlaying = false;
let discardStaleAudio = false;
let interruptedAtMs = 0;
const STALE_AUDIO_WINDOW_MS = 200;

function getPlaybackContext(): AudioContext {
  if (!playbackContext) {
    playbackContext = new AudioContext({ sampleRate: PLAYBACK_RATE });
  }
  return playbackContext;
}

let activeNode: AudioBufferSourceNode | null = null;

function playNextInQueue(): void {
  if (isPlaying || playbackQueue.length === 0) return;
  const int16Data = playbackQueue.shift()!;
  isPlaying = true;
  const ctx = getPlaybackContext();
  if (ctx.state === "suspended") ctx.resume();

  const view = new DataView(int16Data);
  const len = view.byteLength / 2;
  const buffer = ctx.createBuffer(1, len, PLAYBACK_RATE);
  const channel = buffer.getChannelData(0);
  for (let i = 0; i < len; i++) {
    channel[i] = view.getInt16(i * 2, true) / 0x8000;
  }
  const node = ctx.createBufferSource();
  activeNode = node;
  node.buffer = buffer;
  node.connect(ctx.destination);
  node.onended = () => {
    activeNode = null;
    isPlaying = false;
    playNextInQueue();
  };
  node.start();
}

/** Stop current playback and clear the queue (used when the user interrupts the AI). */
export function interruptAudioPlayback(): void {
  discardStaleAudio = true;
  interruptedAtMs = performance.now();
  playbackQueue.length = 0;
  if (activeNode) {
    activeNode.onended = null;
    try {
      activeNode.stop();
    } catch {
      // ignore if already stopped
    }
    activeNode = null;
  }
  isPlaying = false;
}

/** Call on user gesture (e.g. Start mic) so playback is allowed when agent audio arrives. */
export function prepareAudioPlayback(): void {
  const ctx = getPlaybackContext();
  if (ctx.state === "suspended") ctx.resume();
}

export function playAudioChunk(int16Data: ArrayBuffer): void {
  if (isUserSpeaking) return;

  if (discardStaleAudio) {
    if (performance.now() - interruptedAtMs < STALE_AUDIO_WINDOW_MS) return;
    discardStaleAudio = false;
  }

  if (playbackQueue.length === 0) prepareAudioPlayback();
  playbackQueue.push(int16Data);
  playNextInQueue();
}
