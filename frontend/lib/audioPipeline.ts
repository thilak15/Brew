"use client";

/**
 * Capture microphone at 16 kHz mono, 16-bit PCM, and send chunks via callback.
 * Browser typically gives 44.1k or 48k; we downsample to 16k and convert float to int16.
 */
const TARGET_SAMPLE_RATE = 16000;
const CHUNK_MS = 80;

export async function startMicCapture(
  onChunk: (buffer: ArrayBuffer) => void
): Promise<() => void> {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const ctx = new AudioContext({ sampleRate: 48000 });
  const source = ctx.createMediaStreamSource(stream);
  const rate = ctx.sampleRate;

  // createScriptProcessor requires buffer size to be a power of 2 in [256, 16384]
  const desired = Math.floor((rate * CHUNK_MS) / 1000);
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
  if (playbackQueue.length === 0) prepareAudioPlayback();
  playbackQueue.push(int16Data);
  playNextInQueue();
}
