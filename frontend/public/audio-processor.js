/**
 * AudioWorklet processor: downsample incoming audio to 16 kHz mono,
 * convert float32 → int16 PCM, and post back to the main thread.
 */
const TARGET_SAMPLE_RATE = 16000;

class PcmCaptureProcessor extends AudioWorkletProcessor {
    constructor() {
        super();
        this._accumulator = 0;
    }

    process(inputs) {
        const input = inputs[0];
        if (!input || !input[0] || input[0].length === 0) return true;

        const channelData = input[0]; // mono channel 0
        const ratio = TARGET_SAMPLE_RATE / sampleRate;
        const output = [];

        for (let i = 0; i < channelData.length; i++) {
            this._accumulator += ratio;
            while (this._accumulator >= 1) {
                output.push(channelData[i]);
                this._accumulator -= 1;
            }
        }

        if (output.length > 0) {
            const buf = new ArrayBuffer(output.length * 2);
            const view = new DataView(buf);
            for (let i = 0; i < output.length; i++) {
                const s = Math.max(-1, Math.min(1, output[i]));
                view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
            }
            this.port.postMessage(buf, [buf]);
        }

        return true;
    }
}

registerProcessor("pcm-capture-processor", PcmCaptureProcessor);
